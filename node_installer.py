from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


COMFY_MANAGER_NODE_MAP_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json"
PROTECTED_DEPENDENCIES = {
    "torch",
    "torchvision",
    "torchaudio",
    "xformers",
    "triton",
    "onnxruntime",
    "onnxruntime-gpu",
}
FRONTEND_ONLY_NODE_HINTS = ("note", "markdown", "注释", "comment", "reroute")


def missing_node_types(node_types: Iterable[Any], registered: Iterable[str]) -> list[str]:
    known = set(registered)
    return sorted(
        {
            str(node_type).strip()
            for node_type in node_types
            if isinstance(node_type, str)
            and node_type.strip()
            and node_type not in known
            and not any(hint in node_type.lower() for hint in FRONTEND_ONLY_NODE_HINTS)
        },
        key=str.lower,
    )


def missing_workflow_node_types(nodes: Iterable[Any], registered: Iterable[str]) -> list[str]:
    return missing_node_types(
        (
            node.get("type")
            for node in nodes
            if isinstance(node, dict)
            and node.get("active") is not False
            and node.get("frontend_registered") is not True
        ),
        registered,
    )


def missing_workflow_node_packages(nodes: Iterable[Any], registered: Iterable[str]) -> list[dict[str, Any]]:
    missing = set(missing_workflow_node_types(nodes, registered))
    packages: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or str(node.get("type") or "").strip() not in missing:
            continue
        node_type = str(node["type"]).strip()
        package_id = str(node.get("package_id") or "").strip()
        key = package_id.lower() if package_id else f"__unknown__:{node_type.lower()}"
        package = packages.setdefault(
            key,
            {
                "id": package_id or "__unknown__",
                "title": package_id or "未知包",
                "known": bool(package_id),
                "version": str(node.get("package_version") or "").strip(),
                "node_types": [],
                "node_ids": [],
                "count": 0,
            },
        )
        if node_type not in package["node_types"]:
            package["node_types"].append(node_type)
        node_id = node.get("id")
        if node_id is not None and str(node_id) not in package["node_ids"]:
            package["node_ids"].append(str(node_id))
        package["count"] += 1
    return sorted(packages.values(), key=lambda item: (not item["known"], item["title"].lower()))


def normalize_repo_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url.lower()


def allowed_repo_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname == "github.com" and len(parsed.path.strip("/").split("/")) >= 2


def github_fallback_candidates(
    package_id: str,
    node_type: str,
    node_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build installable candidates only from workflow or official-manager GitHub mappings."""
    candidates: dict[str, dict[str, Any]] = {}
    normalized_package = package_id.strip().strip("/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized_package):
        repo_url = f"https://github.com/{normalized_package}"
        candidates[normalize_repo_url(repo_url)] = {
            "id": normalized_package,
            "title": normalized_package,
            "author": normalized_package.split("/", 1)[0],
            "description": "工作流 aux_id 提供的 GitHub 插件仓库",
            "repo_url": repo_url,
            "confidence": 1.0,
            "reason": "workflow_package_github",
            "installable": True,
            "pip": [],
            "apt_dependency": [],
        }
    for repo_url, value in (node_map or {}).items():
        if (
            allowed_repo_url(str(repo_url))
            and isinstance(value, list)
            and value
            and isinstance(value[0], list)
            and node_type in value[0]
        ):
            normalized = normalize_repo_url(str(repo_url))
            parts = normalized.rsplit("/", 2)
            candidates[normalized] = {
                "id": "/".join(parts[-2:]),
                "title": parts[-1],
                "author": parts[-2],
                "description": "ComfyUI-Manager 官方节点映射提供的 GitHub 插件仓库",
                "repo_url": str(repo_url).rstrip("/"),
                "confidence": 0.99,
                "reason": "comfy_manager_github",
                "installable": True,
                "pip": [],
                "apt_dependency": [],
            }
    return sorted(candidates.values(), key=lambda item: (-item["confidence"], item["title"].lower()))


def _comfy_root(folder_paths_module: Any) -> Path:
    module_file = getattr(folder_paths_module, "__file__", None)
    if module_file:
        return Path(module_file).resolve().parent
    return Path(folder_paths_module.models_dir).resolve().parent


def _launcher_preferences(root: Path) -> dict[str, Any]:
    path = root / ".launcher" / "preference.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _resolve_tool(root: Path, configured: str | None, fallback: str) -> str:
    if configured:
        path = (root / configured).resolve()
        if path.exists():
            return str(path)
    return fallback


def _resolve_python(root: Path, configured: str | None) -> str:
    candidates = [
        (root / configured).resolve() if configured else None,
        Path(sys.executable).resolve(),
        (root.parent / "python_embeded" / "python.exe").resolve(),
        (root / "venv" / "Scripts" / "python.exe").resolve(),
    ]
    portable_root = root.parent.resolve()
    for candidate in candidates:
        if candidate and candidate.exists() and (portable_root == candidate.parent or portable_root in candidate.parents):
            return str(candidate)
    return sys.executable


def _install_environment(root: Path) -> tuple[str, str, dict[str, str]]:
    preference = _launcher_preferences(root)
    expert = preference.get("expert_settings") or {}
    network = preference.get("network_preference") or {}
    python = _resolve_python(root, expert.get("python_path_override"))
    git = _resolve_tool(root, expert.get("git_path_override"), shutil.which("git") or "git")
    env = os.environ.copy()
    proxy = str(network.get("proxy_address") or "").strip()
    if proxy and not _proxy_available(proxy):
        proxy = _windows_proxy()
    if proxy and network.get("proxy_env"):
        env.update({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "http_proxy": proxy, "https_proxy": proxy})
    return python, git, env


def _proxy_available(value: str) -> bool:
    parsed = urlparse(value if "://" in value else f"http://{value}")
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


def _windows_proxy() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
        return f"http://{server}" if enabled and server else ""
    except (ImportError, OSError):
        return ""


def _run(
    command: list[str], cwd: Path, env: dict[str, str], timeout: int = 900, allow_failure: bool = False
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode and not allow_failure:
        raise RuntimeError(result.stdout.strip() or f"Command failed: {command[0]}")
    return result.stdout.strip()


def _requirement_files(repo: Path) -> list[Path]:
    result = []
    queue = [repo / "requirements.txt"]
    visited = set()
    while queue:
        path = queue.pop(0).resolve()
        if path in visited or not path.is_file() or repo.resolve() not in path.parents:
            continue
        visited.add(path)
        result.append(path)
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith(("-r ", "--requirement ")):
                nested = line.split(maxsplit=1)[1].strip()
                queue.append(path.parent / nested)
    return result


def dependency_conflicts(repo: Path) -> list[str]:
    conflicts = []
    for path in _requirement_files(repo):
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(("-r ", "--requirement ")):
                continue
            if line.startswith("-") or ("://" in line and not line.startswith("git+https://github.com/")):
                conflicts.append(f"不安全或无法预检的依赖声明: {line}")
                continue
            package = re.split(r"[\s\[<>=!~;]", line, maxsplit=1)[0].lower().replace("_", "-")
            if package in PROTECTED_DEPENDENCIES and re.search(r"[<>=!~]", line):
                conflicts.append(f"插件要求修改核心运行依赖: {line}")
    return conflicts


def declared_dependency_conflicts(requirements: Iterable[Any]) -> list[str]:
    conflicts = []
    for value in requirements:
        line = str(value).strip()
        if not line:
            continue
        if line.startswith("-") or ("://" in line and not line.startswith("git+https://github.com/")):
            conflicts.append(f"不安全或无法预检的市场依赖声明: {line}")
            continue
        package = re.split(r"[\s\[<>=!~;]", line, maxsplit=1)[0].lower().replace("_", "-")
        if package in PROTECTED_DEPENDENCIES and re.search(r"[<>=!~]", line):
            conflicts.append(f"插件要求修改核心运行依赖: {line}")
    return conflicts


def _existing_repo(custom_nodes: Path, repo_url: str, git: str, env: dict[str, str]) -> Path | None:
    wanted = normalize_repo_url(repo_url)
    for directory in custom_nodes.iterdir():
        if not directory.is_dir() or not (directory / ".git").exists():
            continue
        try:
            remote = _run([git, "remote", "get-url", "origin"], directory, env, timeout=30)
        except RuntimeError:
            continue
        if normalize_repo_url(remote) == wanted:
            return directory
    return None


def install_market_plugin(
    folder_paths_module: Any,
    candidate: dict[str, Any],
    install_dependencies: bool = True,
) -> dict[str, Any]:
    repo_url = str(candidate.get("repo_url") or "")
    if not candidate.get("installable") or not allowed_repo_url(repo_url):
        raise RuntimeError("只允许安装工作流 aux_id、ComfyUI-Manager 官方映射或用户指定的 GitHub 插件")

    root = _comfy_root(folder_paths_module)
    custom_nodes = root / "custom_nodes"
    python, git, env = _install_environment(root)
    existing = _existing_repo(custom_nodes, repo_url, git, env)
    installed_path = existing
    action = "updated" if existing else "installed"
    temp_path: Path | None = None
    try:
        if existing:
            _run([git, "pull", "--ff-only"], existing, env)
            repo = existing
        else:
            repo_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", urlparse(repo_url).path.rstrip("/").rsplit("/", 1)[-1])
            target = custom_nodes / repo_name
            if target.exists():
                raise RuntimeError(f"目标目录已存在但不是同一仓库: {target.name}")
            temp_path = Path(tempfile.mkdtemp(prefix=".findmodels-install-", dir=custom_nodes))
            _run([git, "clone", "--depth", "1", repo_url, str(temp_path)], custom_nodes, env)
            repo = temp_path

        declared = candidate.get("pip") or []
        conflicts = dependency_conflicts(repo) + declared_dependency_conflicts(declared) if install_dependencies else []
        if install_dependencies and candidate.get("apt_dependency"):
            conflicts.append("插件需要系统级 apt 依赖，当前 Windows 环境无法安全自动安装")
        if conflicts:
            raise RuntimeError("\n".join(conflicts))
        requirements = _requirement_files(repo)
        conflicts_before = set()
        if install_dependencies:
            conflicts_before = set(
                _run([python, "-m", "pip", "check"], repo, env, allow_failure=True).splitlines()
            )
            for requirement in requirements:
                _run([python, "-m", "pip", "install", "--dry-run", "-r", str(requirement)], repo, env)
            for requirement in requirements:
                _run([python, "-m", "pip", "install", "-r", str(requirement)], repo, env)
            if declared:
                _run([python, "-m", "pip", "install", "--dry-run", *map(str, declared)], repo, env)
                _run([python, "-m", "pip", "install", *map(str, declared)], repo, env)
        if install_dependencies and (repo / "install.py").is_file():
            _run([python, "install.py"], repo, env)
        conflicts_after = (
            set(_run([python, "-m", "pip", "check"], repo, env, allow_failure=True).splitlines())
            if install_dependencies else conflicts_before
        )
        new_conflicts = sorted(conflicts_after - conflicts_before)
        if new_conflicts:
            raise RuntimeError(
                "安装依赖后发现新的环境冲突，插件未启用：\n" + "\n".join(new_conflicts)
            )

        if temp_path:
            temp_path.replace(target)
            installed_path = target
            temp_path = None
        return {
            "action": action,
            "title": candidate.get("title"),
            "path": str(installed_path),
            "dependencies": len(requirements) if install_dependencies else 0,
            "dependencies_skipped": not install_dependencies,
            "existing_conflicts": sorted(conflicts_before),
            "new_conflicts": new_conflicts,
            "pip_check": "No new broken requirements found." if not new_conflicts else "\n".join(new_conflicts),
            "restart_required": True,
        }
    finally:
        if temp_path and temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
