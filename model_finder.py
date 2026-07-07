from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable


MODEL_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".gguf",
    ".onnx",
    ".pt",
    ".pt2",
    ".pth",
    ".pkl",
    ".safetensors",
    ".sft",
}
STANDARD_LOADER_HINTS = (
    "instantid",
    "ipadapter",
    "ip_adapter",
    "samloader",
    "sam_loader",
    "ultralytics",
    "checkpoint",
    "lora",
    "vae",
    "controlnet",
    "clip",
    "textencoder",
    "text_encoder",
    "textencode",
    "unet",
    "diffusion",
    "upscale",
    "embedding",
)
EXPLICIT_MODEL_WIDGETS = (
    "ckpt_name",
    "checkpoint_name",
    "lora_name",
    "vae_name",
    "control_net_name",
    "controlnet_name",
    "clip_name",
    "clip_vision",
    "clip_vision_name",
    "text_encoder_name",
    "unet_name",
    "diffusion_model",
    "diffusion_model_name",
    "upscale_model",
    "upscale_model_name",
    "embedding_name",
)
WIDGET_CATEGORY_OVERRIDES = {
    "ckpt_name": "checkpoints",
    "checkpoint_name": "checkpoints",
    "lora_name": "loras",
    "vae_name": "vae",
    "control_net_name": "controlnet",
    "controlnet_name": "controlnet",
    "clip_vision": "clip_vision",
    "clip_vision_name": "clip_vision",
    "text_encoder_name": "text_encoders",
    "unet_name": "diffusion_models",
    "diffusion_model": "diffusion_models",
    "diffusion_model_name": "diffusion_models",
    "upscale_model": "upscale_models",
    "upscale_model_name": "upscale_models",
    "embedding_name": "embeddings",
}
MODEL_WIDGET_PATTERNS = (
    re.compile(r"^(?:lora|lycoris)_?\d+$"),
    re.compile(r"^(?:ckpt|checkpoint|vae|controlnet|control_net|clip|clip_vision|text_encoder|unet|diffusion_model|upscale_model)_?\d+$"),
    re.compile(r"^(?:model|model_name)_\d+$"),
)

CATEGORY_HINTS = (
    ("LLM", ("llama_cpp", "llama cpp", "llama-cpp", "llm", "mmproj")),
    # InstantID uses an IP-Adapter-format file, but its loader registers the
    # official ComfyUI category as "instantid". Keep this before ipadapter.
    ("instantid", ("instantid", "instant_id", "instant id")),
    ("ipadapter", ("ipadapter", "ip_adapter", "ip adapter")),
    ("ultralytics_segm", ("ultralytics_segm", "ultralytics segm", "segm_", "segm/")),
    ("ultralytics_bbox", ("ultralytics_bbox", "ultralytics bbox", "bbox_", "bbox/")),
    ("sams", ("samloader", "sam_loader", "sam loader", "sam_model", "sam model")),
    ("diffusion_models", ("fantasytalking", "fantasyportrait", "infinitetalk", "scail", "ltx", "ltxvideo")),
    ("detection", ("detection", "detector", "vitpose", "yolo")),
    ("frame_interpolation", ("rife", "frame_interpolation", "frame interpolation", "film")),
    ("audio_encoders", ("audio_encoder", "audio encoder", "wav2vec", "whisper")),
    ("background_removal", ("background_removal", "background removal", "rembg")),
    ("geometry_estimation", ("geometry_estimation", "geometry estimation", "depth_anything")),
    ("optical_flow", ("optical_flow", "optical flow")),
    ("upscale_models", ("upscale", "esrgan", "super_resolution", "superresolution")),
    ("controlnet", ("controlnet", "control_net", "control")),
    ("embeddings", ("embedding", "textual_inversion")),
    ("vae", ("vae",)),
    ("loras", ("lora", "lycoris")),
    ("clip_vision", ("clip_vision", "clip vision")),
    ("text_encoders", ("text_encoder", "text encoder", "clip", "t5")),
    ("diffusion_models", ("diffusion_model", "diffusion model", "unet", "wanvideo")),
    ("checkpoints", ("checkpoint", "ckpt", "model_name", "model name")),
)

CATEGORY_ALIASES = {
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
    "diffusion_models": ("diffusion_models",),
    "upscale_models": ("upscale_models",),
    "embeddings": ("embeddings",),
    "detection": ("detection",),
    "frame_interpolation": ("frame_interpolation",),
    "audio_encoders": ("audio_encoders",),
    "background_removal": ("background_removal",),
    "geometry_estimation": ("geometry_estimation",),
    "optical_flow": ("optical_flow",),
    "unknown": (
        "LLM",
        "instantid",
        "ipadapter",
        "sams",
        "ultralytics_bbox",
        "ultralytics_segm",
        "checkpoints",
        "loras",
        "vae",
        "controlnet",
        "clip_vision",
        "text_encoders",
        "clip",
        "diffusion_models",
        "unet",
        "upscale_models",
        "embeddings",
    ),
}

OFFICIAL_CATEGORY_ALIASES = {
    category: (category,)
    for category in CATEGORY_ALIASES
    if category != "unknown"
}
OFFICIAL_CATEGORY_ALIASES["unknown"] = CATEGORY_ALIASES["unknown"]


@dataclass(frozen=True)
class Reference:
    name: str
    category: str
    node_id: str | None = None
    widget: str | None = None
    node_type: str | None = None
    strict: bool = True
    official_missing: bool = False
    official_valid: bool = False
    source_url: str | None = None
    source_hash: str | None = None
    source_hash_type: str | None = None
    source_size: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "node_id": self.node_id,
            "widget": self.widget,
            "node_type": self.node_type,
            "strict": self.strict,
            "official_missing": self.official_missing,
            "official_valid": self.official_valid,
            "source_url": self.source_url,
            "source_hash": self.source_hash,
            "source_hash_type": self.source_hash_type,
            "source_size": self.source_size,
        }


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("/")


def basename(value: str) -> str:
    return PurePosixPath(normalize_path(value)).name


def is_model_name(value: str) -> bool:
    if "://" in value or value.startswith(("http:", "https:")):
        return False
    clean = normalize_path(value).split("?", 1)[0].split("#", 1)[0]
    return PurePosixPath(clean).suffix.lower() in MODEL_EXTENSIONS


def classify(hint: str, registered_categories: Iterable[str] = ()) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", hint.lower())
    for category, terms in CATEGORY_HINTS:
        if any(term.replace(" ", "_") in normalized for term in terms):
            return category
    for category in registered_categories:
        category_hint = re.sub(r"[^a-z0-9]+", "_", str(category).lower()).strip("_")
        if len(category_hint) >= 4 and (
            category_hint in normalized
            or category_hint.replace("_", "") in normalized.replace("_", "")
        ):
            return str(category)
    return "unknown"


def normalized_stem(value: str) -> str:
    stem = PurePosixPath(normalize_path(value)).stem.lower()
    tokens = re.split(r"[^a-z0-9]+", stem)
    ignored = re.compile(r"^(fp8|fp16|fp32|bf16|pruned|ema|final|v\d+)$")
    return "".join(token for token in tokens if token and not ignored.match(token))


def is_explicit_model_widget(value: Any) -> bool:
    widget_hint = re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())
    return widget_hint in EXPLICIT_MODEL_WIDGETS or any(pattern.fullmatch(widget_hint) for pattern in MODEL_WIDGET_PATTERNS)


def context_category(widget: Any, node_type: Any) -> str | None:
    widget_hint = re.sub(r"[^a-z0-9_]+", "", str(widget or "").lower())
    node_hint = re.sub(r"[^a-z0-9_]+", "", str(node_type or "").lower())
    if widget_hint in WIDGET_CATEGORY_OVERRIDES:
        return WIDGET_CATEGORY_OVERRIDES[widget_hint]
    if re.fullmatch(r"(?:lora|lycoris)_?\d+", widget_hint):
        return "loras"
    if "lora" in node_hint or "lycoris" in node_hint:
        return "loras"
    if "unet" in node_hint or "diffusion" in node_hint:
        return "diffusion_models"
    if "checkpoint" in node_hint or "ckpt" in node_hint:
        return "checkpoints"
    if "vae" in node_hint:
        return "vae"
    if "controlnet" in node_hint or "control_net" in node_hint:
        return "controlnet"
    if "clip_vision" in node_hint:
        return "clip_vision"
    if "textencoder" in node_hint or "text_encoder" in node_hint:
        return "text_encoders"
    return None


def is_loader_node_type(node_type: Any) -> bool:
    raw = str(node_type or "").lower()
    node_hint = re.sub(r"[^a-z0-9_]+", "", raw)
    return (
        "loader" in node_hint
        or "加载器" in raw
        or "加载" in raw
        or any(term in node_hint for term in STANDARD_LOADER_HINTS)
    )


def extract_references(payload: Any, registered_categories: Iterable[str] = ()) -> list[Reference]:
    registered_categories = tuple(registered_categories)
    found: dict[tuple[str, str, str | None, str | None], Reference] = {}

    def add(
        value: str,
        hint: str,
        node_id: Any = None,
        widget: Any = None,
        node_type: Any = None,
        model_selector: bool = False,
        model_value_valid: bool | None = None,
        source_url: Any = None,
        source_hash: Any = None,
        source_hash_type: Any = None,
        source_size: Any = None,
        category_override: Any = None,
    ) -> None:
        if not is_model_name(value):
            return
        if node_id is not None:
            explicit_widget = is_explicit_model_widget(widget)
            # Custom loaders frequently translate the widget label (for example
            # "模型"), so the file extension plus the loader node type is the
            # reliable signal. Non-loader custom nodes remain excluded.
            loader_node = is_loader_node_type(node_type)
            if not explicit_widget and not loader_node and not model_selector:
                return
        ref = Reference(
            name=normalize_path(value),
            category=(
                str(category_override)
                if isinstance(category_override, str) and category_override
                else context_category(widget, node_type) or classify(f"{hint} {value}", registered_categories)
            ),
            node_id=None if node_id is None else str(node_id),
            widget=None if widget is None else str(widget),
            node_type=None if node_type is None else str(node_type),
            strict=model_selector
            or is_explicit_model_widget(widget)
            or is_loader_node_type(node_type),
            official_missing=model_selector and model_value_valid is False,
            official_valid=model_selector and model_value_valid is True,
            source_url=source_url if isinstance(source_url, str) else None,
            source_hash=source_hash if isinstance(source_hash, str) else None,
            source_hash_type=source_hash_type if isinstance(source_hash_type, str) else None,
            source_size=int(source_size) if isinstance(source_size, (int, float)) and source_size > 0 else None,
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
        if current_id is not None and value.get("active") is False:
            return
        if isinstance(value.get("name"), str) and isinstance(value.get("directory"), str):
            add(
                value["name"],
                f"{hint} {value['directory']}",
                current_id,
                None,
                current_type,
                True,
                None,
                value.get("url"),
                value.get("hash"),
                value.get("hash_type"),
                value.get("size"),
                value.get("directory"),
            )
        if isinstance(value.get("widgets"), list):
            for widget in value["widgets"]:
                if isinstance(widget, dict):
                    widget_name = widget.get("name")
                    widget_value = widget.get("value")
                    widget_hint = f"{hint} {current_type or ''} {widget_name or ''}"

                    def add_widget_value(item: Any) -> None:
                        if isinstance(item, str):
                            add(
                                item,
                                widget_hint,
                                current_id,
                                widget_name,
                                current_type,
                                bool(widget.get("model_selector")),
                                widget.get("model_value_valid"),
                                widget.get("source_url"),
                                widget.get("source_hash"),
                                widget.get("source_hash_type"),
                                widget.get("source_size"),
                                widget.get("directory"),
                            )
                        elif isinstance(item, list):
                            for nested in item:
                                add_widget_value(nested)
                        elif isinstance(item, dict):
                            for nested in item.values():
                                add_widget_value(nested)

                    add_widget_value(widget_value)

        for key, item in value.items():
            if key == "widgets":
                continue
            if current_id is None and key not in {"nodes", "models"}:
                continue
            walk(item, f"{hint} {current_type or ''} {key}", current_id, current_type)

    walk(payload)
    references = list(found.values())
    located_names = {ref.name.lower() for ref in references if ref.node_id is not None}
    live_widget_refs = {
        (ref.name.lower(), ref.node_id)
        for ref in references
        if ref.node_id is not None and ref.widget is not None
    }
    filtered = [
        ref
        for ref in references
        if (
            (ref.node_id is not None or ref.name.lower() not in located_names)
            and not (
                ref.node_id is not None
                and ref.widget is None
                and (ref.name.lower(), ref.node_id) in live_widget_refs
            )
        )
    ]
    deduplicated: dict[tuple[str, str | None, str | None], Reference] = {}
    for ref in filtered:
        key = (ref.name.lower(), ref.node_id, ref.widget)
        current = deduplicated.get(key)
        if current is None or (ref.official_missing and not current.official_missing) or current.category == "unknown":
            deduplicated[key] = ref
    return list(deduplicated.values())


def load_installed(
    get_filename_list: Callable[[str], Iterable[str]], extra_categories: Iterable[str] = ()
) -> dict[str, list[str]]:
    installed: dict[str, list[str]] = {}
    categories = {alias for aliases in CATEGORY_ALIASES.values() for alias in aliases}
    categories.update(category for category in extra_categories if category and category != "unknown")
    for category in categories:
        try:
            installed[category] = sorted({normalize_path(str(name)) for name in get_filename_list(category)})
        except Exception:
            installed[category] = []
    return installed


def match_reference(reference: Reference, installed: dict[str, list[str]]) -> dict[str, Any]:
    official_categories = OFFICIAL_CATEGORY_ALIASES.get(
        reference.category,
        CATEGORY_ALIASES["unknown"] if reference.category == "unknown" else (reference.category,),
    )
    categories = CATEGORY_ALIASES.get(
        reference.category,
        CATEGORY_ALIASES["unknown"] if reference.category == "unknown" else (reference.category,),
    )
    if reference.official_missing or reference.official_valid:
        categories = tuple(dict.fromkeys((*categories, *CATEGORY_ALIASES["unknown"], *installed.keys())))
    candidates = [(category, name) for category in categories for name in installed.get(category, [])]
    wanted_path = normalize_path(reference.name).lower()
    wanted_base = basename(reference.name).lower()
    exact_filename: tuple[str, str] | None = None
    for category, candidate in candidates:
        candidate_path = normalize_path(candidate)
        candidate_base = basename(candidate_path)
        if reference.official_valid and candidate_base.lower() == wanted_base:
            return {"status": "installed", "match": None}
        if candidate_path.lower() == wanted_path:
            if category in official_categories:
                return {"status": "installed", "match": None}
            if exact_filename is None:
                exact_filename = (candidate_path, category)
        if exact_filename is None and candidate_base.lower() == wanted_base:
            exact_filename = (candidate_path, category)

    if exact_filename is None:
        if not reference.strict:
            return {"status": "external", "match": None}
        return {"status": "missing", "match": None}

    name, category = exact_filename
    return {
        "status": "adaptable",
        "match": {
            "name": name,
            "category": category,
            "confidence": 0.99,
            "reason": "exact_filename",
            "auto_apply": reference.node_id is not None,
        },
    }


def analyze(
    payload: Any,
    get_filename_list: Callable[[str], Iterable[str]],
    registered_categories: Iterable[str] = (),
) -> dict[str, Any]:
    registered_categories = tuple(registered_categories)
    references = extract_references(payload, registered_categories)
    installed = load_installed(
        get_filename_list,
        (*registered_categories, *(reference.category for reference in references)),
    )
    results = []
    for reference in references:
        results.append({**reference.as_dict(), **match_reference(reference, installed)})
    resolved_widgets = {
        (item["node_id"], item["widget"])
        for item in results
        if item["status"] == "installed" and item["node_id"] is not None and item["widget"] is not None
    }
    resolved_models = {
        (item["category"], basename(item["name"]).lower())
        for item in results
        if item["status"] == "installed"
    }
    exact_resolved: dict[str, set[tuple[str | None, str | None]]] = {}
    for item in results:
        if item["status"] == "installed" and item["node_id"] is not None and item["widget"] is not None:
            key = item["name"].lower()
            exact_resolved.setdefault(key, set()).add((item["node_id"], item["widget"]))
    unresolved_by_name: dict[str, dict[str, Any]] = {}
    for item in results:
        if item["status"] not in {"adaptable", "missing"}:
            continue
        if (
            (item["node_id"], item["widget"]) in resolved_widgets
            or (item["category"], basename(item["name"]).lower()) in resolved_models
        or (item["name"].lower(), item["node_id"], item["widget"]) in {
                (name, nid, wid)
                for name, entries in exact_resolved.items()
                for nid, wid in entries
            }
        ):
            continue
        key = item["name"].lower()
        reference = {"node_id": item["node_id"], "widget": item["widget"], "node_type": item["node_type"]}
        current = unresolved_by_name.get(key)
        if (
            current is None
            or (item["official_missing"] and not current["official_missing"])
            or (
                item["status"] == "missing"
                and current["status"] == "adaptable"
                and item["official_missing"] == current["official_missing"]
            )
        ):
            item["referencing_nodes"] = [reference] if item["node_id"] is not None else []
            unresolved_by_name[key] = item
        elif item["node_id"] is not None:
            refs = current.setdefault("referencing_nodes", [])
            if reference not in refs:
                refs.append(reference)
    unresolved = list(unresolved_by_name.values())
    return {
        "summary": {
            "references": len(results),
            "installed": sum(item["status"] == "installed" for item in results),
            "adaptable": sum(item["status"] == "adaptable" for item in results),
            "missing": sum(item["status"] == "missing" for item in results),
            "external": sum(item["status"] == "external" for item in results),
            "unresolved": len(unresolved),
        },
        "models": unresolved,
    }
