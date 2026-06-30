from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import shutil
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

from .model_finder import MODEL_EXTENSIONS, analyze, basename, normalize_path, normalized_stem
from .node_installer import (
    COMFY_MANAGER_NODE_MAP_URL,
    allowed_repo_url,
    github_fallback_candidates,
    install_plugin,
    missing_workflow_node_packages,
    missing_workflow_node_types,
)


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
    {"name": "夸克模型库 2", "share_id": "4680ac866516", "url": "https://pan.quark.cn/s/4680ac866516"},
)
QUARK_API = "https://drive-pc.quark.cn/1/clouddrive"
QUARK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 "
    "Electron/24.1.3.8 Safari/537.36 Channel/pckk_other_ch"
)
QUARK_CATEGORY_FOLDERS = {
    "LLM": {"LLM", "llm"},
    "instantid": {"instantid"},
    "ipadapter": {"ipadapter", "ip_adapter"},
    "sams": {"sams"},
    "ultralytics_bbox": {"ultralytics_bbox", "bbox"},
    "ultralytics_segm": {"ultralytics_segm", "segm"},
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
    "LLM": ("LLM",),
    "instantid": ("instantid",),
    "ipadapter": ("ipadapter",),
    "sams": ("sams",),
    "ultralytics_bbox": ("ultralytics_bbox",),
    "ultralytics_segm": ("ultralytics_segm",),
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "vae": ("vae",),
    "controlnet": ("controlnet",),
    "clip_vision": ("clip_vision",),
    "text_encoders": ("text_encoders", "clip"),
    "diffusion_models": ("diffusion_models", "unet"),
    "upscale_models": ("upscale_models",),
    "embeddings": ("embeddings",),
    "detection": ("detection",),
    "frame_interpolation": ("frame_interpolation",),
    "audio_encoders": ("audio_encoders",),
    "background_removal": ("background_removal",),
    "geometry_estimation": ("geometry_estimation",),
    "optical_flow": ("optical_flow",),
}
KNOWN_MODEL_SOURCES = {
    "qwen_3_06b_base.safetensors": {
        "provider": "Hugging Face · circlestone-labs/Anima",
        "name": "qwen_3_06b_base.safetensors",
        "url": "https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/text_encoders/qwen_3_06b_base.safetensors?download=true",
        "size": 1192135096,
        "confidence": 1.0,
    },
    "anima-base-v1.0.safetensors": {
        "provider": "Hugging Face · circlestone-labs/Anima",
        "name": "anima-base-v1.0.safetensors",
        "url": "https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/diffusion_models/anima-base-v1.0.safetensors?download=true",
        "size": 4182218328,
        "confidence": 1.0,
    },
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
EXTERNAL_FOLDER_CONFIG = Path(__file__).with_name("external_model_folder.json")
QUARK_AUTH_CONFIG = Path(__file__).with_name("quark_auth.json")
EXTERNAL_INDEX_CACHE: dict[str, list[dict[str, Any]]] = {}
EXTERNAL_INDEX_ROOT: str | None = None
EXTERNAL_INDEX_TASK: asyncio.Task[Any] | None = None


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


def _load_quark_cookie() -> str:
    try:
        data = json.loads(QUARK_AUTH_CONFIG.read_text(encoding="utf-8"))
        return str(data.get("cookie", "")).strip()
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def _quark_token(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return next((_quark_token(item) for item in value if _quark_token(item)), "")
    if isinstance(value, dict):
        for key in ("share_fid_token", "fid_token", "token"):
            token = _quark_token(value.get(key))
            if token:
                return token
    return ""


def _save_quark_cookie(cookie: str) -> None:
    value = str(cookie or "").strip()
    if value:
        QUARK_AUTH_CONFIG.write_text(json.dumps({"cookie": value}, ensure_ascii=False), encoding="utf-8")
    elif QUARK_AUTH_CONFIG.exists():
        QUARK_AUTH_CONFIG.unlink()


def _safe_filename(value: str) -> str:
    name = basename(value).strip()
    if not name or not name.lower().endswith(tuple(MODEL_EXTENSIONS)):
        raise web.HTTPBadRequest(text="Invalid model filename")
    return name


def _official_relative_model_name(value: str, category: str) -> Path:
    normalized = normalize_path(value)
    if category == "ultralytics_bbox" and normalized.lower().startswith("bbox/"):
        normalized = normalized.split("/", 1)[1]
    elif category == "ultralytics_segm" and normalized.lower().startswith("segm/"):
        normalized = normalized.split("/", 1)[1]
    return Path(_safe_filename(normalized))


def _size_value(value: Any, multiplier: int = 1) -> int | None:
    try:
        size = int(float(value) * multiplier)
        return size if size > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _content_range_total(value: Any) -> int | None:
    match = re.search(r"/(\d+)$", str(value or ""))
    return _size_value(match.group(1)) if match else None


def _is_model_payload(path: Path) -> bool:
    if path.stat().st_size < 1024:
        return False
    with path.open("rb") as file:
        prefix = file.read(256).lower()
    return b"git-lfs.github.com/spec" not in prefix and not prefix.lstrip().startswith((b"<html", b"<!doctype", b"{\"error"))


def _target_directory(category: str) -> Path:
    aliases = DOWNLOAD_CATEGORY_ALIASES.get(category, (category,))
    registered = getattr(folder_paths, "folder_names_and_paths", None)
    if category not in DOWNLOAD_CATEGORY_ALIASES and isinstance(registered, dict) and category not in registered:
        raise web.HTTPBadRequest(text=f"No registered model folder for category: {category}")
    for candidate in aliases:
        try:
            paths = folder_paths.get_folder_paths(candidate)
        except Exception:
            continue
        if paths:
            resolved = [Path(path).resolve() for path in paths]
            target = next(
                (path for path in resolved if path.name.lower() == category.lower()),
                next((path for path in resolved if path.name.lower() == candidate.lower()), resolved[0]),
            )
            target.mkdir(parents=True, exist_ok=True)
            return target
    raise web.HTTPBadRequest(text=f"No configured model folder for category: {category}")


def _registered_model_extensions() -> set[str]:
    extensions = {extension.lower() for extension in MODEL_EXTENSIONS}
    registered = getattr(folder_paths, "folder_names_and_paths", None)
    if not isinstance(registered, dict):
        return extensions
    for _, value in registered.items():
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            continue
        accepted = value[1]
        if not isinstance(accepted, (set, tuple, list)):
            continue
        extensions.update(
            str(extension).lower()
            for extension in accepted
            if isinstance(extension, str) and extension.startswith(".")
        )
    return extensions


def _registered_category_roots() -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    registered = getattr(folder_paths, "folder_names_and_paths", None)
    if not isinstance(registered, dict):
        return roots
    for category, value in registered.items():
        if not isinstance(value, (tuple, list)) or not value:
            continue
        paths = value[0]
        if not isinstance(paths, (tuple, list)):
            continue
        for path in paths:
            try:
                roots.append((str(category), Path(path).resolve()))
            except (OSError, TypeError, ValueError):
                continue
    return roots


def _registered_category(value: Any) -> str | None:
    name = str(value or "").strip()
    registered = getattr(folder_paths, "folder_names_and_paths", None)
    if not name or not isinstance(registered, dict):
        return None
    return next((str(category) for category in registered if str(category).lower() == name.lower()), None)


def _node_registered_category(node_type: Any, widget_name: Any) -> str | None:
    """Resolve a model category from the installed node's actual INPUT_TYPES registration."""
    try:
        import nodes

        node_class = nodes.NODE_CLASS_MAPPINGS.get(str(node_type or ""))
        input_types = node_class.INPUT_TYPES()
    except Exception:
        return None
    widget = str(widget_name or "")
    spec = next(
        (
            section.get(widget)
            for section in (input_types.get("required", {}), input_types.get("optional", {}))
            if isinstance(section, dict) and widget in section
        ),
        None,
    )
    values = spec[0] if isinstance(spec, (tuple, list)) and spec else None
    if isinstance(values, (tuple, list)):
        normalized = {normalize_path(str(item)).lower() for item in values if isinstance(item, str)}
        if normalized:
            matches = []
            registered = getattr(folder_paths, "folder_names_and_paths", {})
            for category in registered if isinstance(registered, dict) else ():
                try:
                    available = {
                        normalize_path(str(item)).lower()
                        for item in folder_paths.get_filename_list(category)
                    }
                except Exception:
                    continue
                if normalized == available or normalized.intersection(available):
                    matches.append(str(category))
            if len(set(matches)) == 1:
                return matches[0]
    try:
        source = inspect.getsource(node_class.INPUT_TYPES)
    except (OSError, TypeError):
        return None
    categories = {
        category
        for raw in re.findall(r"get_filename_list\(\s*['\"]([^'\"]+)['\"]", source)
        if (category := _registered_category(raw))
    }
    return next(iter(categories)) if len(categories) == 1 else None


def _resolve_model_category(model: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    current_value = str(model.get("category") or "unknown")
    current = _registered_category(current_value)
    if current or current_value in DOWNLOAD_CATEGORY_ALIASES:
        return current or current_value
    match_category = _registered_category((model.get("match") or {}).get("category"))
    if match_category:
        return match_category
    node_category = _node_registered_category(model.get("node_type"), model.get("widget"))
    if node_category:
        return node_category
    candidate_categories = {
        category
        for candidate in candidates
        if (category := _registered_category(candidate.get("category_hint")))
    }
    return next(iter(candidate_categories)) if len(candidate_categories) == 1 else "unknown"


def _external_category_hint(path: Path, root: Path) -> str | None:
    official_names: dict[str, str] = {
        category.lower(): category for category in DOWNLOAD_CATEGORY_ALIASES
    }
    registered = getattr(folder_paths, "folder_names_and_paths", None)
    if isinstance(registered, dict):
        official_names.update({str(category).lower(): str(category) for category in registered})
    for category, official_root in _registered_category_roots():
        official_names.setdefault(official_root.name.lower(), category)
    try:
        parts = path.resolve().relative_to(root.resolve()).parts[:-1]
    except (OSError, ValueError):
        return None
    for part in reversed(parts):
        category = official_names.get(part.lower())
        if category:
            return category
    return None


def _clear_filename_cache(category: str) -> None:
    cache = getattr(folder_paths, "filename_list_cache", None)
    if isinstance(cache, dict):
        for candidate in DOWNLOAD_CATEGORY_ALIASES.get(category, (category,)):
            cache.pop(candidate, None)


def _load_external_folder() -> Path | None:
    try:
        data = json.loads(EXTERNAL_FOLDER_CONFIG.read_text(encoding="utf-8"))
        path = Path(str(data.get("path", ""))).expanduser().resolve()
        return path if path.is_dir() else None
    except (OSError, ValueError, TypeError):
        return None


def _save_external_folder(path: Path) -> None:
    global EXTERNAL_INDEX_CACHE, EXTERNAL_INDEX_ROOT
    EXTERNAL_FOLDER_CONFIG.write_text(
        json.dumps({"path": str(path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    EXTERNAL_INDEX_CACHE = {}
    EXTERNAL_INDEX_ROOT = None


def _choose_external_folder() -> Path | None:
    if os.name != "nt":
        raise RuntimeError("Native folder selection is currently supported on Windows only")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$owner = New-Object System.Windows.Forms.Form; "
        "$owner.TopMost = $true; "
        "$owner.ShowInTaskbar = $false; "
        "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen; "
        "$owner.Size = New-Object System.Drawing.Size(1, 1); "
        "$owner.Opacity = 0; "
        "$owner.Show(); "
        "$owner.Activate(); "
        "$owner.BringToFront(); "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = '选择外部模型库文件夹'; "
        "$dialog.ShowNewFolderButton = $true; "
        "try { "
        "if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $dialog.SelectedPath } "
        "} finally { $dialog.Dispose(); $owner.Close(); $owner.Dispose(); }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    selected = completed.stdout.strip().lstrip("\ufeff")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Unable to open the folder selector")
    if not selected:
        return None
    path = Path(selected).resolve()
    if not path.is_dir():
        raise RuntimeError("Selected external model folder does not exist")
    return path


def _external_model_index(root: Path | None) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    if root is None or not root.is_dir():
        return index
    extensions = _registered_model_extensions()
    for directory, _, files in os.walk(root, onerror=lambda _: None):
        for filename in files:
            if Path(filename).suffix.lower() not in extensions:
                continue
            path = (Path(directory) / filename).resolve()
            try:
                size = path.stat().st_size
            except OSError:
                continue
            index.setdefault(filename.lower(), []).append(
                {
                    "name": filename,
                    "path": str(path),
                    "size": size,
                    "category_hint": _external_category_hint(path, root),
                }
            )
    return index


def _external_model_index_for_names(
    root: Path | None,
    wanted_names: set[str],
    category_hints: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Quickly find only the exact model filenames required by the current workflow."""
    index: dict[str, list[dict[str, Any]]] = {}
    wanted = {basename(name).lower() for name in wanted_names if basename(name)}
    if root is None or not root.is_dir() or not wanted:
        return index
    extensions = _registered_model_extensions()
    remaining = set(wanted)

    def scan(search_root: Path, names: set[str]) -> None:
        for directory, _, files in os.walk(search_root, onerror=lambda _: None):
            for filename in files:
                key = filename.lower()
                if key not in names or Path(filename).suffix.lower() not in extensions:
                    continue
                path = (Path(directory) / filename).resolve()
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                index.setdefault(key, []).append(
                    {
                        "name": filename,
                        "path": str(path),
                        "size": size,
                        "category_hint": _external_category_hint(path, root),
                    }
                )

    normalized_hints = {
        basename(name).lower(): str(category)
        for name, category in (category_hints or {}).items()
        if basename(name) and category in DOWNLOAD_CATEGORY_ALIASES
    }
    for category in dict.fromkeys(normalized_hints.get(name) for name in wanted):
        if not category:
            continue
        category_names = {name for name in remaining if normalized_hints.get(name) == category}
        category_roots = []
        for alias in DOWNLOAD_CATEGORY_ALIASES[category]:
            category_roots.extend((root / alias, root / "models" / alias, root / "ComfyUI" / "models" / alias))
        for category_root in dict.fromkeys(category_roots):
            if category_root.is_dir() and category_names:
                scan(category_root, category_names)
                category_names.difference_update(index)
                remaining.difference_update(index)
        if not remaining:
            return index

    if remaining:
        scan(root, remaining)
    return index


async def _refresh_external_index(root: Path) -> None:
    global EXTERNAL_INDEX_CACHE, EXTERNAL_INDEX_ROOT, EXTERNAL_INDEX_TASK
    try:
        EXTERNAL_INDEX_CACHE = await asyncio.to_thread(_external_model_index, root)
        EXTERNAL_INDEX_ROOT = str(root)
    finally:
        EXTERNAL_INDEX_TASK = None


async def _external_candidates_index(
    root: Path | None,
    wanted_names: set[str],
    category_hints: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return exact external matches immediately, while refreshing the complete cache in the background."""
    global EXTERNAL_INDEX_TASK
    if root is None:
        return {}
    if EXTERNAL_INDEX_ROOT == str(root):
        return EXTERNAL_INDEX_CACHE
    exact_index = await asyncio.to_thread(_external_model_index_for_names, root, wanted_names, category_hints)
    if EXTERNAL_INDEX_TASK is None:
        EXTERNAL_INDEX_TASK = asyncio.create_task(_refresh_external_index(root))
    return exact_index


def _move_external_model(source_value: str, wanted_name: str, category: str, root: Path | None) -> dict[str, Any]:
    global EXTERNAL_INDEX_CACHE, EXTERNAL_INDEX_ROOT
    if root is None or not root.is_dir():
        raise web.HTTPBadRequest(text="External model folder is not configured")
    source = Path(source_value).expanduser().resolve()
    try:
        source.relative_to(root)
    except ValueError as error:
        raise web.HTTPBadRequest(text="Source file is outside the configured external model folder") from error
    if not source.is_file() or basename(wanted_name).casefold() != source.name.casefold():
        raise web.HTTPBadRequest(text="External model file no longer matches the missing model")
    if not _is_model_payload(source):
        raise web.HTTPBadRequest(text="External file is not a valid model payload")

    target_dir = _target_directory(category)
    relative_name = _official_relative_model_name(source.name, category)
    target = (target_dir / relative_name).resolve()
    try:
        target.relative_to(target_dir)
    except ValueError as error:
        raise web.HTTPBadRequest(text="Invalid target model path") from error
    if target.exists():
        raise web.HTTPConflict(text=f"Model already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    size = source.stat().st_size
    shutil.move(str(source), str(target))
    EXTERNAL_INDEX_CACHE = {}
    EXTERNAL_INDEX_ROOT = None
    _clear_filename_cache(category)
    return {
        "moved": True,
        "filename": target.name,
        "relative_name": relative_name.as_posix(),
        "category": category,
        "path": str(target),
        "size": size,
    }


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
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://pan.quark.cn",
        "Referer": f"https://pan.quark.cn/s/{share_id}",
        "User-Agent": QUARK_USER_AGENT,
    }
    cookie = _load_quark_cookie()
    if cookie:
        headers["Cookie"] = cookie
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
    wanted_filename = basename(name).casefold()
    preferred_folders = QUARK_CATEGORY_FOLDERS.get(category, {category})
    while queue and len(visited) < 2000:
        directory = queue.pop(0)
        if directory in visited:
            continue
        visited.add(directory)
        page = 1
        while page <= 100:
            query = (
                f"/share/sharepage/detail?pr=ucpro&fr=pc&pwd_id={quote(share_id)}"
                f"&stoken={quote(stoken, safe='')}&pdir_fid={quote(directory)}&force=0"
                f"&_page={page}&_size=200&_sort=file_type:asc,file_name:asc"
            )
            detail = await _quark_json(session, "GET", query, share_id=share_id)
            items = ((detail or {}).get("data") or {}).get("list", [])
            if not isinstance(items, list):
                break
            for item in items:
                item_name = str(item.get("file_name", ""))
                if item.get("dir"):
                    if item_name.lower() in preferred_folders:
                        queue.insert(0, item["fid"])
                    else:
                        queue.append(item["fid"])
                    continue
                if not item_name.lower().endswith(tuple(MODEL_EXTENSIONS)):
                    continue
                confidence = SequenceMatcher(None, wanted, normalized_stem(item_name)).ratio()
                if item_name.casefold() == wanted_filename or confidence >= 0.62:
                    candidates.append(
                        {
                            "provider": library["name"],
                            "name": item_name,
                            "url": library["url"],
                            "confidence": 1.0 if item_name.casefold() == wanted_filename else round(confidence, 3),
                            "size": _size_value(item.get("size")),
                            "quark": {
                                "share_id": share_id,
                                "fid": item.get("fid"),
                                "fid_token": _quark_token(item.get("share_fid_token")),
                                "filename": item_name,
                            },
                        }
                    )
                    if item_name.casefold() == wanted_filename:
                        return candidates
            if len(items) < 200:
                break
            page += 1
    return candidates


@PromptServer.instance.routes.post("/findmodels/scan")
async def scan_models(request: web.Request) -> web.Response:
    payload = await request.json()
    quick = bool(payload.get("quick"))
    registered_categories = getattr(folder_paths, "folder_names_and_paths", {})
    result = analyze(
        payload,
        folder_paths.get_filename_list,
        registered_categories.keys() if isinstance(registered_categories, dict) else (),
    )
    external_root = _load_external_folder()
    external_index = await _external_candidates_index(
        external_root,
        {str(model.get("name") or "") for model in result["models"]},
        {
            str(model.get("name") or ""): str(model.get("category") or "")
            for model in result["models"]
        },
    )
    for model in result["models"]:
        candidates = external_index.get(basename(model["name"]).lower(), [])
        model["category"] = _resolve_model_category(model, candidates)
        candidates.sort(
            key=lambda item: (
                item.get("category_hint") != model.get("category"),
                len(Path(item["path"]).parts),
            )
        )
        active_job = next(
            (
                job
                for job in DOWNLOAD_JOBS.values()
                if basename(str(job.get("original") or job.get("filename") or "")).lower()
                == basename(model["name"]).lower()
                and job.get("status") in {"queued", "downloading", "completed"}
            ),
            None,
        )
        model["external_candidates"] = candidates
        model["size"] = (
            model.get("source_size")
            or (candidates[0]["size"] if candidates else None)
            or (KNOWN_MODEL_SOURCES.get(basename(model["name"]).lower()) or {}).get("size")
            or ((active_job or {}).get("total"))
        )
    result["external_folder"] = str(external_root) if external_root else ""
    try:
        import nodes

        registered = nodes.NODE_CLASS_MAPPINGS.keys()
    except (ImportError, AttributeError):
        registered = ()
    result["missing_nodes"] = missing_workflow_node_types(payload.get("nodes", []), registered)
    result["missing_node_packages"] = missing_workflow_node_packages(payload.get("nodes", []), registered)
    result["missing_node_references"] = {
        node_type: [
            str(node.get("id"))
            for node in payload.get("nodes", [])
            if isinstance(node, dict)
            and node.get("type") == node_type
            and node.get("id") is not None
        ]
        for node_type in result["missing_nodes"]
    }
    result["missing_node_candidates"] = {}
    result["quick"] = quick
    return web.json_response(result)


@PromptServer.instance.routes.post("/findmodels/external-folder/select")
async def select_external_folder(request: web.Request) -> web.Response:
    try:
        path = await asyncio.to_thread(_choose_external_folder)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    if path is None:
        return web.json_response({"path": "", "cancelled": True})
    await asyncio.to_thread(_save_external_folder, path)
    return web.json_response({"path": str(path), "cancelled": False})


@PromptServer.instance.routes.get("/findmodels/quark-auth")
async def get_quark_auth(request: web.Request) -> web.Response:
    return web.json_response({
        "configured": bool(_load_quark_cookie()),
        "libraries": [
            {"name": library["name"], "url": library["url"], "share_id": library["share_id"]}
            for library in QUARK_MODEL_LIBRARIES
        ],
    })


@PromptServer.instance.routes.post("/findmodels/quark-libraries/check")
async def check_quark_libraries(request: web.Request) -> web.Response:
    results = []
    async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
        for library in QUARK_MODEL_LIBRARIES:
            token_data = await _quark_json(
                session,
                "POST",
                "/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=",
                share_id=library["share_id"],
                data={"pwd_id": library["share_id"], "passcode": ""},
            )
            results.append({
                "name": library["name"],
                "url": library["url"],
                "reachable": bool(((token_data or {}).get("data") or {}).get("stoken")),
            })
    return web.json_response({"libraries": results, "configured": bool(_load_quark_cookie())})


@PromptServer.instance.routes.post("/findmodels/quark-auth")
async def set_quark_auth(request: web.Request) -> web.Response:
    payload = await request.json()
    await asyncio.to_thread(_save_quark_cookie, str(payload.get("cookie", "")))
    return web.json_response({"configured": bool(_load_quark_cookie())})


@PromptServer.instance.routes.post("/findmodels/external-move")
async def move_external_model(request: web.Request) -> web.Response:
    payload = await request.json()
    result = await asyncio.to_thread(
        _move_external_model,
        str(payload.get("source", "")),
        str(payload.get("name", "")),
        str(payload.get("category", "")),
        _load_external_folder(),
    )
    return web.json_response(result)


async def _official_node_map(session: aiohttp.ClientSession) -> dict[str, Any]:
    data = await _get_json(session, COMFY_MANAGER_NODE_MAP_URL)
    return data if isinstance(data, dict) else {}


@PromptServer.instance.routes.post("/findnodes/candidates")
async def find_node_candidates(request: web.Request) -> web.Response:
    payload = await request.json()
    node_type = str(payload.get("node_type", "")).strip()
    package_id = str(payload.get("package_id", "")).strip()
    if not node_type and not package_id:
        raise web.HTTPBadRequest(text="Missing node type or package id")
    async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
        node_map = await _official_node_map(session)
        candidates = github_fallback_candidates(package_id, node_type, node_map)
    search_term = package_id or node_type
    return web.json_response(
        {
            "node_type": node_type,
            "package_id": package_id,
            "candidates": candidates[:8],
            "github_search_url": f"https://github.com/search?q={quote(f'{search_term} ComfyUI')}&type=repositories",
        }
    )


@PromptServer.instance.routes.post("/findnodes/install")
async def install_node_plugin(request: web.Request) -> web.Response:
    payload = await request.json()
    node_type = str(payload.get("node_type", "")).strip()
    package_id = str(payload.get("package_id", "")).strip()
    plugin_id = str(payload.get("plugin_id", "")).strip()
    custom_url = str(payload.get("repo_url", "")).strip().rstrip("/")
    install_dependencies = bool(payload.get("install_dependencies", True))
    if (not node_type and not package_id) or (not plugin_id and not custom_url):
        raise web.HTTPBadRequest(text="Missing node type, package id, or plugin id")
    if custom_url:
        if not allowed_repo_url(custom_url):
            raise web.HTTPBadRequest(text="自定义地址必须是完整的 GitHub 仓库 HTTPS 链接")
        repo_id = "/".join(urlparse(custom_url).path.strip("/").split("/")[:2])
        candidate = {
            "id": repo_id,
            "title": repo_id,
            "repo_url": custom_url,
            "installable": True,
            "pip": [],
            "apt_dependency": [],
        }
    else:
        async with aiohttp.ClientSession(timeout=SOURCE_TIMEOUT, trust_env=True) as session:
            node_map = await _official_node_map(session)
            candidates = github_fallback_candidates(package_id, node_type, node_map)
        candidate = next((item for item in candidates if item["id"] == plugin_id), None)
    if not candidate:
        raise web.HTTPBadRequest(text="插件不在工作流 aux_id 或 ComfyUI-Manager 官方映射的可信结果中")
    try:
        result = await asyncio.to_thread(
            install_plugin, folder_paths, candidate, install_dependencies
        )
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
    verified_known = []
    if known:
        checked_known = await _validate_web_candidate(session, dict(known))
        if checked_known:
            verified_known.append(checked_known)
    exact_quark = [candidate for candidate in quark if _exact_model_name(name, candidate["name"])]
    checked_web = await asyncio.gather(
        *(_validate_web_candidate(session, candidate) for candidate in exact_web),
        return_exceptions=True,
    )
    exact_candidates = [
        candidate for candidate in [*verified_known, *checked_web, *exact_quark] if isinstance(candidate, dict)
    ]
    for candidate in exact_candidates:
        candidate["exact"] = True
        candidate["downloadable"] = True
    provider_rank = {"Hugging Face": 0, "Civitai": 1, "夸克模型库 1": 2, "夸克模型库 2": 3}
    exact_candidates.sort(
        key=lambda candidate: (
            -float(candidate.get("confidence") or 0),
            provider_rank.get(str(candidate.get("provider") or ""), 9),
        )
    )
    similar_candidates = sorted(
        [
            {**candidate, "exact": False, "downloadable": False}
            for candidate in [*civitai, *huggingface, *quark]
            if not _exact_model_name(name, candidate.get("name", ""))
            and float(candidate.get("confidence") or 0) >= 0.62
        ],
        key=lambda candidate: (
            -float(candidate.get("confidence") or 0),
            provider_rank.get(str(candidate.get("provider") or ""), 9),
        ),
    )
    candidates = [*exact_candidates, *similar_candidates][:12]
    size = next((_size_value(candidate.get("size")) for candidate in candidates if candidate.get("size")), None)
    return web.json_response({
        "name": name,
        "size": size,
        "candidates": candidates,
        "exact_count": len(exact_candidates),
        "search_urls": {
            "huggingface": f"https://huggingface.co/models?search={quote(_safe_query(name))}",
            "civitai": f"https://civitai.com/search/models?sortBy=models_v9&query={quote(_safe_query(name))}",
        },
    })


async def _quark_download_url(session: aiohttp.ClientSession, payload: dict[str, Any]) -> str:
    share_id = str(payload.get("share_id", ""))
    filename = basename(str(payload.get("filename", "")))
    if filename:
        refreshed = await _quark_candidates(
            session,
            filename,
            "unknown",
            {"share_id": share_id, "name": "Quark", "url": f"https://pan.quark.cn/s/{share_id}"},
        )
        exact = next((item for item in refreshed if _exact_model_name(filename, item.get("name", ""))), None)
        if exact:
            payload = exact["quark"]
    token_data = await _quark_json(
        session,
        "POST",
        "/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=",
        share_id=share_id,
        data={"pwd_id": share_id, "passcode": ""},
    )
    stoken = ((token_data or {}).get("data") or {}).get("stoken")
    fid = str(payload.get("fid") or "").strip()
    fid_token = _quark_token(payload.get("fid_token") or payload.get("fids_token"))
    if not stoken:
        raise web.HTTPBadGateway(text="夸克分享 token 获取失败，分享链接可能失效或需要重新登录")
    if not fid or not fid_token:
        raise web.HTTPBadGateway(text="夸克文件 token 缺失，正在使用的分享文件信息已经失效")
    request_data = {
        "fids": [fid],
        "pwd_id": share_id,
        "stoken": stoken,
        "fid_token": [fid_token],
    }
    errors = []
    for endpoint in (
        "/file/download?pr=ucpro&fr=pc&uc_param_str=",
        "/file/share/download?pr=ucpro&fr=pc&uc_param_str=",
    ):
        download = await _quark_json(session, "POST", endpoint, share_id=share_id, data=request_data)
        if download and (download.get("message") or download.get("code")):
            errors.append(f"{download.get('code', '')}: {download.get('message', '')}".strip(": "))
        entries = (download or {}).get("data") or []
        url = entries[0].get("download_url") if entries else None
        if _allowed_quark_download_url(url):
            return url
    detail = errors[0] if errors else "需要登录或文件超过公开下载大小限制"
    if detail.startswith("31001"):
        detail = "夸克要求登录。请在设置中保存已登录 pan.quark.cn 的 Cookie 后重试"
    elif detail.startswith("41020") or "token校验" in detail.lower():
        detail = "夸克文件 token 校验失败，插件已重新读取分享目录但服务端仍拒绝"
    elif detail.startswith("23018") or "download file size limit" in detail.lower():
        detail = "夸克限制该大文件通过公开分享直链下载；请在设置中保存有效登录 Cookie 后重试，或使用已验证的同名备用来源"
    raise web.HTTPBadGateway(text=f"夸克拒绝直链下载：{detail}")


async def _direct_web_fallback(session: aiohttp.ClientSession, filename: str) -> dict[str, Any] | None:
    """Find a verified, exact-name direct URL when a cloud-share download fails."""
    known = KNOWN_MODEL_SOURCES.get(basename(filename).lower())
    if known:
        checked = await _validate_web_candidate(session, dict(known))
        if checked:
            return checked
    civitai, huggingface = await asyncio.gather(
        _civitai_candidates(session, filename),
        _huggingface_candidates(session, filename),
    )
    exact = [
        candidate
        for candidate in [*huggingface, *civitai]
        if _exact_model_name(filename, candidate.get("name", ""))
    ]
    checked = await asyncio.gather(
        *(_validate_web_candidate(session, candidate) for candidate in exact),
        return_exceptions=True,
    )
    return next((candidate for candidate in checked if isinstance(candidate, dict)), None)


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
    persistent_partial = progress is not None
    try:
        if progress is not None:
            temp_path = Path(progress.get("temp_path") or (target_dir / f".{filename}.{progress['id']}.part"))
            progress["temp_path"] = str(temp_path)
            downloaded = temp_path.stat().st_size if temp_path.exists() else 0
            progress.update(
                status="downloading",
                filename=filename,
                category=category,
                downloaded=downloaded,
                total=progress.get("total") or expected_size,
                error=None,
                updated_at=time.time(),
            )
        else:
            fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".part", dir=target_dir)
            os.close(fd)
            temp_path = Path(temp_name)
            downloaded = 0
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT, trust_env=True) as session:
            if isinstance(quark, dict):
                quark.setdefault("filename", filename)
                try:
                    url = await _quark_download_url(session, quark)
                except web.HTTPException as quark_error:
                    fallback = await _direct_web_fallback(session, filename)
                    if not fallback:
                        raise web.HTTPBadGateway(
                            text=f"{quark_error.text}；未找到文件名完全一致且可验证的其他直链"
                        ) from quark_error
                    url = str(fallback["url"])
                    expected_size = expected_size or _size_value(fallback.get("size"))
                    if progress is not None:
                        progress.update(provider=fallback.get("provider"), fallback_from="Quark", updated_at=time.time())
            headers = {"User-Agent": "Mozilla/5.0 ComfyUI_FindModels/1.14.1", "Referer": url}
            if isinstance(quark, dict):
                headers.update({
                    "Origin": "https://pan.quark.cn",
                    "Referer": f"https://pan.quark.cn/s/{quark.get('share_id', '')}",
                    "User-Agent": QUARK_USER_AGENT,
                })
                if _load_quark_cookie():
                    headers["Cookie"] = _load_quark_cookie()
            if downloaded:
                headers["Range"] = f"bytes={downloaded}-"
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
            ) as response:
                allowed = _allowed_download_url(str(response.url)) or _allowed_quark_download_url(str(response.url))
                if response.status not in {200, 206} or not allowed:
                    raise web.HTTPBadGateway(text=f"Download failed with HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    raise web.HTTPBadGateway(text="下载地址返回了网页或错误信息，而不是模型文件")
                if downloaded and response.status != 206:
                    downloaded = 0
                response_size = _size_value(
                    response.headers.get("X-Linked-Size")
                    or response.headers.get("X-File-Size")
                    or response.headers.get("Content-Length")
                )
                total = (
                    expected_size
                    or _content_range_total(response.headers.get("Content-Range"))
                    or ((downloaded + response_size) if downloaded and response_size else response_size)
                )
                if progress is not None:
                    progress.update(total=total, updated_at=time.time())
                with temp_path.open("ab" if downloaded else "wb") as output:
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
        if temp_path and temp_path.exists() and not persistent_partial:
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
        progress.setdefault("started_at", time.time())
        result = await _download_model_payload(payload, progress)
        progress.update(status="completed", result=result, downloaded=result["size"], total=result["size"])
    except asyncio.CancelledError:
        if progress.get("status") != "cancelled":
            progress.update(status="paused")
    except Exception as error:
        progress.update(status="failed", error=getattr(error, "text", None) or str(error))
    finally:
        progress["updated_at"] = time.time()
        DOWNLOAD_TASKS.pop(job_id, None)


def _purge_download_jobs() -> None:
    cutoff = time.time() - 3600
    for job_id, job in list(DOWNLOAD_JOBS.items()):
        if job.get("status") in {"completed", "failed", "cancelled"} and job.get("updated_at", 0) < cutoff:
            DOWNLOAD_JOBS.pop(job_id, None)


async def _cancel_download_task(job_id: str) -> None:
    task = DOWNLOAD_TASKS.get(job_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _public_download_job(job: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in job.items() if key not in {"payload", "temp_path"}}
    started_at = _size_value(job.get("started_at"))
    downloaded = _size_value(job.get("downloaded")) or 0
    total = _size_value(job.get("total"))
    if started_at:
        elapsed = max(0.0, time.time() - started_at)
        speed = downloaded / elapsed if elapsed > 0 and downloaded > 0 else 0
        public["elapsed"] = round(elapsed, 1)
        public["speed"] = round(speed, 1)
        public["eta"] = round((total - downloaded) / speed, 1) if total and speed > 0 and total > downloaded else None
    return public


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
            and job.get("status") in {"queued", "downloading", "paused", "failed"}
        ),
        None,
    )
    if existing:
        return web.json_response(_public_download_job(existing))
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
        "payload": dict(payload),
    }
    DOWNLOAD_TASKS[job_id] = asyncio.create_task(_run_download_job(job_id, payload))
    return web.json_response(_public_download_job(DOWNLOAD_JOBS[job_id]))


@PromptServer.instance.routes.get("/findmodels/download/jobs")
async def download_model_jobs(request: web.Request) -> web.Response:
    _purge_download_jobs()
    jobs = sorted(DOWNLOAD_JOBS.values(), key=lambda job: job.get("created_at", 0), reverse=True)
    return web.json_response({"jobs": [_public_download_job(job) for job in jobs]})


@PromptServer.instance.routes.post("/findmodels/download/pause")
async def pause_download_model(request: web.Request) -> web.Response:
    job_id = str((await request.json()).get("job_id", "")).strip()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise web.HTTPNotFound(text="Download task not found")
    if job.get("status") not in {"queued", "downloading"}:
        raise web.HTTPConflict(text="Only an active download can be paused")
    job.update(status="pausing", updated_at=time.time())
    await _cancel_download_task(job_id)
    job.update(status="paused", updated_at=time.time())
    return web.json_response(_public_download_job(job))


@PromptServer.instance.routes.post("/findmodels/download/resume")
async def resume_download_model(request: web.Request) -> web.Response:
    job_id = str((await request.json()).get("job_id", "")).strip()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise web.HTTPNotFound(text="Download task not found")
    if job.get("status") not in {"paused", "failed"}:
        raise web.HTTPConflict(text="Only a paused or failed download can be resumed")
    payload = job.get("payload")
    if not isinstance(payload, dict):
        raise web.HTTPConflict(text="Download task cannot be resumed")
    job.update(status="queued", error=None, updated_at=time.time())
    DOWNLOAD_TASKS[job_id] = asyncio.create_task(_run_download_job(job_id, payload))
    return web.json_response(_public_download_job(job))


@PromptServer.instance.routes.post("/findmodels/download/cancel")
async def cancel_download_model(request: web.Request) -> web.Response:
    job_id = str((await request.json()).get("job_id", "")).strip()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise web.HTTPNotFound(text="Download task not found")
    if job.get("status") == "completed":
        raise web.HTTPConflict(text="A completed download cannot be cancelled")
    job.update(status="cancelled", updated_at=time.time())
    await _cancel_download_task(job_id)
    temp_value = str(job.get("temp_path", "")).strip()
    if temp_value:
        temp_path = Path(temp_value)
        if temp_path.is_file():
            temp_path.unlink()
    job.update(downloaded=0, updated_at=time.time())
    return web.json_response(_public_download_job(job))
