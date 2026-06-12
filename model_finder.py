from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable


MODEL_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
}

CATEGORY_HINTS = (
    ("controlnet", ("controlnet", "control_net", "control")),
    ("upscale_models", ("upscale", "esrgan", "super_resolution", "superresolution")),
    ("embeddings", ("embedding", "textual_inversion")),
    ("vae", ("vae",)),
    ("loras", ("lora", "lycoris")),
    ("text_encoders", ("text_encoder", "text encoder", "clip", "t5")),
    ("diffusion_models", ("diffusion_model", "diffusion model", "unet")),
    ("checkpoints", ("checkpoint", "ckpt", "model_name", "model name", "loader")),
)

CATEGORY_ALIASES = {
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "vae": ("vae",),
    "controlnet": ("controlnet",),
    "text_encoders": ("text_encoders", "clip"),
    "diffusion_models": ("diffusion_models", "unet"),
    "upscale_models": ("upscale_models",),
    "embeddings": ("embeddings",),
    "unknown": (
        "checkpoints",
        "loras",
        "vae",
        "controlnet",
        "text_encoders",
        "clip",
        "diffusion_models",
        "unet",
        "upscale_models",
        "embeddings",
    ),
}


@dataclass(frozen=True)
class Reference:
    name: str
    category: str
    node_id: str | None = None
    widget: str | None = None
    node_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "node_id": self.node_id,
            "widget": self.widget,
            "node_type": self.node_type,
        }


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def basename(value: str) -> str:
    return PurePosixPath(normalize_path(value)).name


def is_model_name(value: str) -> bool:
    clean = normalize_path(value).split("?", 1)[0].split("#", 1)[0]
    return PurePosixPath(clean).suffix.lower() in MODEL_EXTENSIONS


def classify(hint: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", hint.lower())
    for category, terms in CATEGORY_HINTS:
        if any(term.replace(" ", "_") in normalized for term in terms):
            return category
    return "unknown"


def normalized_stem(value: str) -> str:
    stem = PurePosixPath(normalize_path(value)).stem.lower()
    tokens = re.split(r"[^a-z0-9]+", stem)
    ignored = re.compile(r"^(fp8|fp16|fp32|bf16|pruned|ema|final|v\d+)$")
    return "".join(token for token in tokens if token and not ignored.match(token))


def extract_references(payload: Any) -> list[Reference]:
    found: dict[tuple[str, str, str | None, str | None], Reference] = {}

    def add(value: str, hint: str, node_id: Any = None, widget: Any = None, node_type: Any = None) -> None:
        if not is_model_name(value):
            return
        ref = Reference(
            name=normalize_path(value),
            category=classify(hint),
            node_id=None if node_id is None else str(node_id),
            widget=None if widget is None else str(widget),
            node_type=None if node_type is None else str(node_type),
        )
        found[(ref.name.lower(), ref.category, ref.node_id, ref.widget)] = ref

    def walk(value: Any, hint: str = "", node_id: Any = None, node_type: Any = None) -> None:
        if isinstance(value, str):
            add(value, hint, node_id=node_id, node_type=node_type)
            return
        if isinstance(value, list):
            for item in value:
                walk(item, hint, node_id, node_type)
            return
        if not isinstance(value, dict):
            return

        current_id = value.get("id", node_id)
        current_type = value.get("type") or value.get("class_type") or node_type
        if isinstance(value.get("widgets"), list):
            for widget in value["widgets"]:
                if isinstance(widget, dict):
                    widget_name = widget.get("name")
                    widget_value = widget.get("value")
                    if isinstance(widget_value, str):
                        add(
                            widget_value,
                            f"{hint} {current_type or ''} {widget_name or ''}",
                            current_id,
                            widget_name,
                            current_type,
                        )

        for key, item in value.items():
            if key == "widgets":
                continue
            walk(item, f"{hint} {current_type or ''} {key}", current_id, current_type)

    walk(payload)
    references = list(found.values())
    located = {(ref.name.lower(), ref.category) for ref in references if ref.node_id is not None}
    return [
        ref
        for ref in references
        if ref.node_id is not None or (ref.name.lower(), ref.category) not in located
    ]


def load_installed(get_filename_list: Callable[[str], Iterable[str]]) -> dict[str, list[str]]:
    installed: dict[str, list[str]] = {}
    for category in {alias for aliases in CATEGORY_ALIASES.values() for alias in aliases}:
        try:
            installed[category] = sorted({normalize_path(str(name)) for name in get_filename_list(category)})
        except Exception:
            installed[category] = []
    return installed


def match_reference(reference: Reference, installed: dict[str, list[str]]) -> dict[str, Any]:
    categories = CATEGORY_ALIASES.get(reference.category, CATEGORY_ALIASES["unknown"])
    candidates = [(category, name) for category in categories for name in installed.get(category, [])]
    wanted_path = normalize_path(reference.name).lower()
    wanted_base = basename(reference.name).lower()
    wanted_stem = normalized_stem(reference.name)

    best: tuple[float, str, str, str] | None = None
    for category, candidate in candidates:
        candidate_path = normalize_path(candidate)
        candidate_base = basename(candidate_path)
        if candidate_path.lower() == wanted_path:
            score, reason = 1.0, "exact_path"
        elif candidate_base.lower() == wanted_base:
            score, reason = 0.99, "exact_filename"
        elif wanted_stem and normalized_stem(candidate_path) == wanted_stem:
            score, reason = 0.96, "normalized_filename"
        else:
            score = SequenceMatcher(None, wanted_stem, normalized_stem(candidate_path)).ratio()
            reason = "similar_filename"
        if best is None or score > best[0]:
            best = (score, candidate_path, category, reason)

    if best is None or best[0] < 0.62:
        return {"status": "missing", "match": None}

    score, name, category, reason = best
    status = "installed" if score >= 0.96 else "adaptable" if score >= 0.78 else "missing"
    return {
        "status": status,
        "match": {
            "name": name,
            "category": category,
            "confidence": round(score, 3),
            "reason": reason,
            "auto_apply": status == "adaptable" and score >= 0.86,
        },
    }


def analyze(payload: Any, get_filename_list: Callable[[str], Iterable[str]]) -> dict[str, Any]:
    references = extract_references(payload)
    installed = load_installed(get_filename_list)
    results = []
    for reference in references:
        results.append({**reference.as_dict(), **match_reference(reference, installed)})
    return {
        "summary": {
            "references": len(results),
            "installed": sum(item["status"] == "installed" for item in results),
            "adaptable": sum(item["status"] == "adaptable" for item in results),
            "missing": sum(item["status"] == "missing" for item in results),
        },
        "models": results,
    }
