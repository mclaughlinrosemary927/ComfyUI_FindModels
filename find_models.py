from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web

import folder_paths
from server import PromptServer

from .model_finder import MODEL_EXTENSIONS, analyze, basename, normalized_stem
from .node_installer import (
    COMFY_MANAGER_NODE_MAP_URL,
    TE_MARKET_URL,
    install_market_plugin,
    market_candidates,
    missing_node_types,
)


TIMEOUT = aiohttp.ClientTimeout(total=30)
SOURCE_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=20, sock_read=30)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=30, sock_read=600)
ALLOWED_DOWNLOAD_HOSTS = {
    "civitai.com",
    "huggingface.co",
    "cdn-lfs.hf.co",
    "cdn-lfs-us-1.hf.co",
    "cdn-lfs-eu-1.hf.co",
    "cas-bridge.xethub.hf.co",
}
QUARK_MODEL_LIBRARIES = (
    {"name": "夸克模型库 1", "share_id": "fb913d649b18", "url": "https://pan.quark.cn/s/fb913d649b18"},
    {"name": "夸克模型库 2", "share_id": "4680ac8665162", "url": "https://pan.quark.cn/s/4680ac8665162"},
)
QUARK_API = "https://drive-pc.quark.cn/1/clouddrive"
QUARK_CATEGORY_FOLDERS = {
    "checkpoints": {"checkpoints"},
    "loras": {"loras", "lora"},
    "vae": {"vae"},
    "controlnet": {"controlnet"},
    "clip_vision": {"clip_vision"},
    "text_encoders": {"text_encoders", "clip"},
    "diffusion_models": {"diffusion_models", "unet"},
    "upscale_models": {"upscale_models"},
    "embeddings": {"embeddings"},
}
DOWNLOAD_CATEGORY_ALIASES = {
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "vae": ("vae",),
    "controlnet": ("controlnet",),
    "clip_vision": ("clip_vision",),
    "text_encoders": ("text_encoders", "clip"),
    "diffusion_models": ("diffusion_models", "unet"),
    "upscale_models": ("upscale_models",),
    "embeddings": ("embeddings",),
}
KNOWN_MODEL_SOURCES = {
    "fantasytalking_fp16.safetensors": {
        "provider": "Hugging Face · Kijai/WanVideo_comfy",
        "name": "fantasytalking_fp16.safetensors",
        "url": "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/fantasytalking_fp16.safetensors",
        "size": 1684038568,
        "confidence": 1.0,
    },
}
DOWNLOAD_JOBS: dict[str, dict[str, Any]] = {}
DOWNLOAD_TASKS: dict[str, asyncio.Task[Any]] = {}


def _safe_query(name: str) -> str:
    return re.sub(r"[_\-.]+", " ", basename(name).rsplit(".", 1)[0]).strip()


def _exact_model_name(wanted: str, candidate: str) -> bool:
    return basename(wanted).lower() == basename(candidate).lower()


def _is_https_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _allowed_download_url(value: Any) -> bool:
    if not _is_https_url(value):
        return False
    host = (urlparse(value).hostname or "").lower()
    return (
        host in ALLOWED_DOWNLOAD_HOSTS
        or host.endswith(".civitai.com")
        or host.endswith(".hf.co")
        or host.endswith(".xethub.hf.co")
    )


def _allowed_quark_download_url(value: Any) -> bool:
    if not _is_https_url(value):
        return False
    host = (urlparse(value).hostname or "").lower()
    return host.endswith((".quark.cn", ".uc.cn", ".alicdn.com", ".aliyuncs.com"))


def _safe_filename(value: str) -> str:
    name = basename(value).strip()
    if not name or not name.lower().endswith(tuple(MODEL_EXTENSIONS)):
        raise web.HTTPBadRequest(text="Invalid model filename")
    return name


def _size_value(value: Any, multiplier: int = 1) -> int | None:
    try:
        size = int(float(value) * multiplier)
        return size if size > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _is_model_payload(path: Path) -> bool:
    if path.stat().st_size < 1024:
        return False
    with path.open("rb") as file:
        prefix = file.read(256).lower()
    return b"git-lfs.github.com/spec" not in prefix and not prefix.lstrip().startswith((b"<html", b"<!doctype", b"{\"error"))


def _target_directory(category: str) -> Path:
    aliases = DOWNLOAD_CATEGORY_ALIASES.get(category)
    if not aliases:
        raise web.HTTPBadRequest(text=f"无法确定模型对应的 ComfyUI 文件夹: {category}")
    for candidate in aliases:
        try:
            paths = folder_paths.get_folder_paths(candidate)
        except Exception:
            continue
        if paths:
            target = Path(paths[0]).resolve()
            target.mkdir(parents=True, exist_ok=True)
            return target
    raise web.HTTPBadRequest(text=f"No configured model folder for category: {category}")


def _clear_filename_cache(category: str) -> None:
    cache = getattr(folder_paths, "filename_list_cache", None)
    if isinstance(cache, dict):
        for candidate in DOWNLOAD_CATEGORY_ALIASES.get(category, (category,)):
            cache.pop(candidate, None)


async def _get_json(session: aiohttp.ClientSession, url: str) -> Any:
    try:
        async with session.get(url, headers={"User-Agent": "ComfyUI_FindModels/1.0"}) as response:
            if response.status == 200:
                return await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        pass
    return None


async def _remote_size(session: aiohttp.ClientSession, candidate: dict[str, Any]) -> None:
    url = candidate.get("url")
    if candidate.get("size") or not _allowed_download_url(url):
        return
    try:
        async with session.head(url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 ComfyUI_FindModels/1.4.0"}) as response:
            size = _size_value(
                response.headers.get("X-Linked-Size")
                or response.headers.get("X-File-Size")
                or response.headers.get("Content-Length")
            )
            candidate["size"] = size if size and size >= 1024 else None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        pass


async def _validate_web_candidate(session: aiohttp.ClientSession, candidate: dict[str, Any]) -> dict[str, Any] | None:
    url = candidate.get("url")
    if not _allowed_download_url(url):
        return None
    try:
        async with session.head(
            url,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 ComfyUI_FindModels/1.5.0"},
        ) as response:
            if response.status != 200 or not _allowed_download_url(str(response.url)):
                return None
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                return None
            await _remote_size(session, candidate)
            return candidate
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None


async def _civitai_candidates(session: aiohttp.ClientSession, name: str) -> list[dict[str, Any]]:
    query = quote(_safe_query(name))
    data = await _get_json(session, f"https://civitai.com/api/v1/models?query={query}&limit=4")
    candidates = []
    for model in (data or {}).get("items", []):
        for version in model.get("modelVersions", [])[:2]:
            for file in version.get("files", []):
                file_name = file.get("name", "")
                download_url = file.get("downloadUrl")
                if _is_https_url(download_url) and file_name:
                    candidates.append(
                        {
                            "provider": "Civitai",
                            "model": model.get("name"),
                            "name": file_name,
                            "url": download_url,
                            "size": _size_value(file.get("sizeKB"), 1024),
                            "confidence": round(
                                SequenceMatcher(None, normalized_stem(name), normalized_stem(file_name)).ratio(),
                                3,
                            ),
                        }
                    )
    return candidates


async def _huggingface_candidates(session: aiohttp.ClientSession, name: str) -> list[dict[str, Any]]:
    query = quote(_safe_query(name))
    models = await _get_json(session, f"https://huggingface.co/api/models?search={query}&limit=4&full=true")
    candidates = []
    for model in models or []:
        repo_id = model.get("id")
        if not repo_id:
            continue
        for sibling in model.get("siblings", []):
            file_name = sibling.get("rfilename", "")
            if not file_name or "." + file_name.rsplit(".", 1)[-1].lower() not in MODEL_EXTENSIONS:
                continue
            confidence = SequenceMatcher(None, normalized_stem(name), normalized_stem(file_name)).ratio()
            if confidence >= 0.45:
                candidates.append(
                    {
                        "provider": "Hugging Face",
                        "model": repo_id,
                        "name": basename(file_name),
                        "url": f"https://huggingface.co/{repo_id}/resolve/main/{quote(file_name)}",
                        "size": _size_value(sibling.get("size") or (sibling.get("lfs") or {}).get("size")),
                        "confidence": round(confidence, 3),
                    }
                )
    return candidates


async def _quark_json(
    session: aiohttp.ClientSession, method: str, path: str, *, share_id: str, data: Any = None
) -> Any:
    headers = {"User-Agent": "Mozilla/5.0 ComfyUI_FindModels/1.3.0", "Referer": f"https://pan.quark.cn/s/{share_id}"}
    url = f"{QUARK_API}{path}"
    try:
        async with session.request(method, url, json=data, headers=headers) as response:
            return await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        pass
    return None


async def _quark_candidates(
    session: aiohttp.ClientSession, name: str, category: str, library: dict[str, str]
) -> list[dict[str, Any]]:
    share_id = library["share_id"]
    token_data = await _quark_json(
        session,
        "POST",
        "/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=",
        share_id=share_id,
        data={"pwd_id": share_id, "passcode": ""},
    )
    stoken = ((token_data or {}).get("data") or {}).get("stoken")
    if not stoken:
        return []

    queue = ["0"]
    visited = set()
    candidates = []
    wanted = normalized_stem(name)
    preferred_folders = QUARK_CATEGORY_FOLDERS.get(category, {category})
    while queue and len(visited) < 80 and len(candidates) < 8:
        directory = queue.pop(0)
        if directory in visited:
            continue
        visited.add(directory)
        query = (
            f"/share/sharepage/detail?pr=ucpro&fr=pc&pwd_id={quote(share_id)}"
            f"&stoken={quote(stoken, safe='')}&pdir_fid={quote(directory)}&force=0"
            "&_page=1&_size=200&_sort=file_type:asc,file_name:asc"
        )
        detail = await _quark_json(session, "GET", query, share_id=share_id)
        for item in ((detail or {}).get("data") or {}).get("list", []):
            item_name = str(item.get("file_name", ""))
            if item.get("dir"):
                if item_name.lower() in preferred_folders:
                    queue = [item["fid"]]
                else:
                    queue.append(item["fid"])
                continue
            if not item_name.lower().endswith(tuple(MODEL_EXTENSIONS)):
                continue
            confidence = SequenceMatcher(None, wanted, normalized_stem(item_name)).ratio()
            if confidence >= 0.62:
                candidates.append(
                    {
                        "provider": library["name"],
                        "name": item_name,
                        "confidence": round(confidence, 3),
                        "size": _size_value(item.get("size")),
                        "quark": {
                            "share_id": share_id,
                            "fid": item.get("fid"),
                            "fid_token": item.get("share_fid_token"),
                        },
                    }
                )
    return candidates


@PromptServer.instance.routes.post("/findmodels/scan")
async def scan_models(request: web.Request) -> web.Response:
    payload = await request.json()
    result = analyze(payload, folder_paths.get_filename_list)
    try:
        import nodes

        registered = nodes.NODE_CLASS_MAPPINGS.keys()
    except (ImportError, AttributeError):
        registered = ()
    result["missing_nodes"] = missing_node_types(
        [node.get("type") for node in payload.get("nodes", []) if isinstance(node, dict)],
        registered,
    )
    result["missing_node_candidates"] = {}
    if result["missing_nodes"]:
        async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
            entries, node_map = await asyncio.gather(_te_market_entries(session), _official_node_map(session))
        result["missing_node_candidates"] = {
            node_type: market_candidates(entries, node_type, node_map)[:8]
            for node_type in result["missing_nodes"]
        }
    return web.json_response(result)


async def _te_market_entries(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    data = await _get_json(session, TE_MARKET_URL)
    return (data or {}).get("custom_nodes", [])


async def _official_node_map(session: aiohttp.ClientSession) -> dict[str, Any]:
    data = await _get_json(session, COMFY_MANAGER_NODE_MAP_URL)
    return data if isinstance(data, dict) else {}


@PromptServer.instance.routes.post("/findnodes/candidates")
async def find_node_candidates(request: web.Request) -> web.Response:
    payload = await request.json()
    node_type = str(payload.get("node_type", "")).strip()
    if not node_type:
        raise web.HTTPBadRequest(text="Missing node type")
    async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
        entries, node_map = await asyncio.gather(_te_market_entries(session), _official_node_map(session))
        candidates = market_candidates(entries, node_type, node_map)
    return web.json_response(
        {
            "node_type": node_type,
            "candidates": candidates[:8],
            "github_search_url": f"https://github.com/search?q={quote(f'{node_type} ComfyUI')}&type=repositories",
        }
    )


@PromptServer.instance.routes.post("/findnodes/install")
async def install_node_plugin(request: web.Request) -> web.Response:
    payload = await request.json()
    node_type = str(payload.get("node_type", "")).strip()
    plugin_id = str(payload.get("plugin_id", "")).strip()
    if not node_type or not plugin_id:
        raise web.HTTPBadRequest(text="Missing node type or plugin id")
    async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
        entries, node_map = await asyncio.gather(_te_market_entries(session), _official_node_map(session))
        candidates = market_candidates(entries, node_type, node_map)
    candidate = next((item for item in candidates if item["id"] == plugin_id), None)
    if not candidate:
        raise web.HTTPBadRequest(text="插件不在 TE 官方市场的精确节点匹配结果中")
    try:
        result = await asyncio.to_thread(install_market_plugin, folder_paths, candidate)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(result)


@PromptServer.instance.routes.post("/findmodels/sources")
async def find_sources(request: web.Request) -> web.Response:
    payload = await request.json()
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "unknown")).strip()
    if not name:
        raise web.HTTPBadRequest(text="Missing model name")
    async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
        results = await asyncio.gather(
            _civitai_candidates(session, name),
            _huggingface_candidates(session, name),
            *(_quark_candidates(session, name, category, library) for library in QUARK_MODEL_LIBRARIES),
            return_exceptions=True,
        )
    civitai = results[0] if isinstance(results[0], list) else []
    huggingface = results[1] if isinstance(results[1], list) else []
    quark_results = [result for result in results[2:] if isinstance(result, list)]
    quark = [candidate for result in quark_results for candidate in result]
    exact_web = [candidate for candidate in civitai + huggingface if _exact_model_name(name, candidate["name"])]
    known = KNOWN_MODEL_SOURCES.get(basename(name).lower())
    verified_known = [dict(known)] if known else []
    exact_quark = [candidate for candidate in quark if _exact_model_name(name, candidate["name"])]
    checked_web = await asyncio.gather(
        *(_validate_web_candidate(session, candidate) for candidate in exact_web),
        return_exceptions=True,
    )
    candidates = [
        candidate for candidate in [*verified_known, *checked_web, *exact_quark] if isinstance(candidate, dict)
    ]
    return web.json_response({"name": name, "candidates": candidates[:12]})


async def _quark_download_url(session: aiohttp.ClientSession, payload: dict[str, Any]) -> str:
    share_id = str(payload.get("share_id", ""))
    token_data = await _quark_json(
        session,
        "POST",
        "/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=",
        share_id=share_id,
        data={"pwd_id": share_id, "passcode": ""},
    )
    stoken = ((token_data or {}).get("data") or {}).get("stoken")
    request_data = {
        "fids": [payload.get("fid")],
        "pwd_id": share_id,
        "stoken": stoken,
        "fids_token": [payload.get("fid_token")],
    }
    errors = []
    for endpoint in ("/file/download?pr=ucpro&fr=pc", "/file/share/download?pr=ucpro&fr=pc"):
        download = await _quark_json(session, "POST", endpoint, share_id=share_id, data=request_data)
        if download and download.get("message"):
            errors.append(str(download["message"]))
        entries = (download or {}).get("data") or []
        url = entries[0].get("download_url") if entries else None
        if _allowed_quark_download_url(url):
            return url
    detail = errors[0] if errors else "需要登录或文件超过公开下载大小限制"
    raise web.HTTPBadGateway(text=f"夸克拒绝直链下载：{detail}")


async def _download_model_payload(payload: dict[str, Any], progress: dict[str, Any] | None = None) -> dict[str, Any]:
    url = str(payload.get("url", "")).strip()
    quark = payload.get("quark")
    category = str(payload.get("category", "")).strip()
    filename = _safe_filename(str(payload.get("filename", "")))
    expected_size = _size_value(payload.get("size"))
    if not quark and not _allowed_download_url(url):
        raise web.HTTPBadRequest(text="Only approved HTTPS model providers are allowed")

    target_dir = _target_directory(category)
    target = (target_dir / filename).resolve()
    if target.parent != target_dir:
        raise web.HTTPBadRequest(text="Invalid target path")
    if target.exists():
        raise web.HTTPConflict(text=f"Model already exists: {target}")

    temp_path: Path | None = None
    try:
        if progress is not None:
            progress.update(
                status="downloading",
                filename=filename,
                category=category,
                downloaded=0,
                total=expected_size,
                updated_at=time.time(),
            )
        fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".part", dir=target_dir)
        os.close(fd)
        temp_path = Path(temp_name)
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT, trust_env=True) as session:
            if isinstance(quark, dict):
                url = await _quark_download_url(session, quark)
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 ComfyUI_FindModels/1.4.0", "Referer": url},
                allow_redirects=True,
            ) as response:
                allowed = _allowed_download_url(str(response.url)) or _allowed_quark_download_url(str(response.url))
                if response.status != 200 or not allowed:
                    raise web.HTTPBadGateway(text=f"Download failed with HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    raise web.HTTPBadGateway(text="下载地址返回了网页或错误信息，而不是模型文件")
                response_size = _size_value(
                    response.headers.get("X-Linked-Size")
                    or response.headers.get("X-File-Size")
                    or response.headers.get("Content-Length")
                )
                total = expected_size or response_size
                downloaded = 0
                if progress is not None:
                    progress.update(total=total, updated_at=time.time())
                with temp_path.open("wb") as output:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            progress.update(downloaded=downloaded, total=total, updated_at=time.time())
        if not _is_model_payload(temp_path):
            raise web.HTTPBadGateway(text="下载结果不是有效模型文件，可能是登录页面、错误信息或 Git LFS 指针")
        temp_path.replace(target)
        tolerance = max(1024 * 1024, int(expected_size * 0.001)) if expected_size else 0
        if expected_size and abs(target.stat().st_size - expected_size) > tolerance:
            target.unlink()
            raise web.HTTPBadGateway(text="下载文件大小与来源不一致，已删除不完整文件")
        _clear_filename_cache(category)
    except web.HTTPException:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
        raise web.HTTPBadGateway(text=f"Download failed: {error}") from error
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()

    return {
        "downloaded": True,
        "filename": filename,
        "relative_name": filename,
        "category": category,
        "path": str(target),
        "size": target.stat().st_size,
    }


async def _run_download_job(job_id: str, payload: dict[str, Any]) -> None:
    progress = DOWNLOAD_JOBS[job_id]
    try:
        result = await _download_model_payload(payload, progress)
        progress.update(status="completed", result=result, downloaded=result["size"], total=result["size"])
    except Exception as error:
        progress.update(status="failed", error=getattr(error, "text", None) or str(error))
    finally:
        progress["updated_at"] = time.time()
        DOWNLOAD_TASKS.pop(job_id, None)


def _purge_download_jobs() -> None:
    cutoff = time.time() - 3600
    for job_id, job in list(DOWNLOAD_JOBS.items()):
        if job.get("status") in {"completed", "failed"} and job.get("updated_at", 0) < cutoff:
            DOWNLOAD_JOBS.pop(job_id, None)


@PromptServer.instance.routes.post("/findmodels/download/start")
async def start_download_model(request: web.Request) -> web.Response:
    payload = await request.json()
    _safe_filename(str(payload.get("filename", "")))
    category = str(payload.get("category", "")).strip()
    _target_directory(category)
    if not payload.get("quark") and not _allowed_download_url(str(payload.get("url", "")).strip()):
        raise web.HTTPBadRequest(text="Only approved HTTPS model providers are allowed")
    _purge_download_jobs()
    filename = basename(str(payload.get("filename", "")))
    existing = next(
        (
            job
            for job in DOWNLOAD_JOBS.values()
            if job.get("filename", "").lower() == filename.lower()
            and job.get("category") == category
            and job.get("status") in {"queued", "downloading"}
        ),
        None,
    )
    if existing:
        return web.json_response(existing)
    job_id = uuid.uuid4().hex
    DOWNLOAD_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "filename": filename,
        "category": category,
        "original": str(payload.get("original", "")),
        "node_id": payload.get("node_id"),
        "widget": payload.get("widget"),
        "downloaded": 0,
        "total": _size_value(payload.get("size")),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    DOWNLOAD_TASKS[job_id] = asyncio.create_task(_run_download_job(job_id, payload))
    return web.json_response(DOWNLOAD_JOBS[job_id])


@PromptServer.instance.routes.get("/findmodels/download/jobs")
async def download_model_jobs(request: web.Request) -> web.Response:
    _purge_download_jobs()
    jobs = sorted(DOWNLOAD_JOBS.values(), key=lambda job: job.get("created_at", 0), reverse=True)
    return web.json_response({"jobs": jobs})


@PromptServer.instance.routes.post("/findmodels/download/progress")
async def download_model_progress(request: web.Request) -> web.Response:
    payload = await request.json()
    job_id = str(payload.get("job_id", "")).strip()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise web.HTTPNotFound(text="Download task not found")
    return web.json_response(job)


@PromptServer.instance.routes.post("/findmodels/download")
async def download_model(request: web.Request) -> web.Response:
    return web.json_response(await _download_model_payload(await request.json()))
