from __future__ import annotations

import asyncio
import os
import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web

import folder_paths
from server import PromptServer

from .model_finder import MODEL_EXTENSIONS, analyze, basename, normalized_stem


TIMEOUT = aiohttp.ClientTimeout(total=12)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
ALLOWED_DOWNLOAD_HOSTS = {
    "civitai.com",
    "huggingface.co",
    "cdn-lfs.hf.co",
    "cdn-lfs-us-1.hf.co",
    "cdn-lfs-eu-1.hf.co",
}


def _safe_query(name: str) -> str:
    return re.sub(r"[_\-.]+", " ", basename(name).rsplit(".", 1)[0]).strip()


def _is_https_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _allowed_download_url(value: Any) -> bool:
    if not _is_https_url(value):
        return False
    host = (urlparse(value).hostname or "").lower()
    return host in ALLOWED_DOWNLOAD_HOSTS or host.endswith(".civitai.com") or host.endswith(".hf.co")


def _safe_filename(value: str) -> str:
    name = basename(value).strip()
    if not name or not name.lower().endswith(tuple(MODEL_EXTENSIONS)):
        raise web.HTTPBadRequest(text="Invalid model filename")
    return name


def _target_directory(category: str) -> Path:
    try:
        paths = folder_paths.get_folder_paths(category)
    except Exception as error:
        raise web.HTTPBadRequest(text=f"Unknown model category: {category}") from error
    if not paths:
        raise web.HTTPBadRequest(text=f"No configured folder for category: {category}")
    target = Path(paths[0]).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


async def _get_json(session: aiohttp.ClientSession, url: str) -> Any:
    try:
        async with session.get(url, headers={"User-Agent": "ComfyUI_FindModels/1.0"}) as response:
            if response.status == 200:
                return await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        pass
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
                        "confidence": round(confidence, 3),
                    }
                )
    return candidates


@PromptServer.instance.routes.post("/findmodels/scan")
async def scan_models(request: web.Request) -> web.Response:
    payload = await request.json()
    return web.json_response(analyze(payload, folder_paths.get_filename_list))


@PromptServer.instance.routes.post("/findmodels/sources")
async def find_sources(request: web.Request) -> web.Response:
    payload = await request.json()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise web.HTTPBadRequest(text="Missing model name")
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        civitai, huggingface = await asyncio.gather(
            _civitai_candidates(session, name),
            _huggingface_candidates(session, name),
        )
    candidates = sorted(civitai + huggingface, key=lambda item: item["confidence"], reverse=True)[:12]
    quark_url = f"https://www.google.com/search?q={quote(f'site:pan.quark.cn/s/ {name}')}"
    return web.json_response({"name": name, "candidates": candidates, "quark_url": quark_url})


@PromptServer.instance.routes.post("/findmodels/download")
async def download_model(request: web.Request) -> web.Response:
    payload = await request.json()
    url = str(payload.get("url", "")).strip()
    category = str(payload.get("category", "")).strip()
    filename = _safe_filename(str(payload.get("filename", "")))
    if not _allowed_download_url(url):
        raise web.HTTPBadRequest(text="Only approved HTTPS model providers are allowed")

    target_dir = _target_directory(category)
    target = (target_dir / filename).resolve()
    if target.parent != target_dir:
        raise web.HTTPBadRequest(text="Invalid target path")
    if target.exists():
        raise web.HTTPConflict(text=f"Model already exists: {target}")

    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".part", dir=target_dir)
        os.close(fd)
        temp_path = Path(temp_name)
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(url, headers={"User-Agent": "ComfyUI_FindModels/1.1.0"}) as response:
                if response.status != 200 or not _allowed_download_url(str(response.url)):
                    raise web.HTTPBadGateway(text=f"Download failed with HTTP {response.status}")
                with temp_path.open("wb") as output:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        output.write(chunk)
        temp_path.replace(target)
    except web.HTTPException:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
        raise web.HTTPBadGateway(text=f"Download failed: {error}") from error
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()

    return web.json_response({"downloaded": True, "filename": filename, "category": category, "path": str(target)})
