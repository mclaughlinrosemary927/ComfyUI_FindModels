import sys
import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Routes:
    def post(self, path):
        return lambda function: function

    def get(self, path):
        return lambda function: function


server = types.ModuleType("server")
server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=Routes()))
folder_paths = types.ModuleType("folder_paths")
folder_paths.get_filename_list = lambda category: []
folder_paths.get_folder_paths = lambda category: [str(Path.cwd() / "models" / category)]
folder_paths.filename_list_cache = {}
folder_paths.models_dir = str(Path.cwd() / "models")
folder_paths.folder_names_and_paths = {
    category: ([str(Path.cwd() / "models" / category)], set())
    for category in ("checkpoints", "loras", "vae", "controlnet", "clip_vision", "text_encoders", "clip", "diffusion_models", "unet", "upscale_models", "embeddings", "audio_encoders")
}
sys.modules.setdefault("server", server)
sys.modules.setdefault("folder_paths", folder_paths)
sys.path.insert(0, str(Path.cwd().parent))

from ComfyUI_FindModels.find_models import (
    KNOWN_MODEL_SOURCES,
    QUARK_MODEL_LIBRARIES,
    _allowed_download_url,
    _allowed_quark_download_url,
    _clear_filename_cache,
    _choose_external_folder,
    _content_range_total,
    _direct_web_fallback,
    _exact_model_name,
    _external_model_index,
    _external_model_index_for_names,
    _registered_model_extensions,
    _resolve_model_category,
    _is_model_payload,
    _move_external_model,
    _official_relative_model_name,
    _public_download_job,
    _quark_candidates,
    _load_quark_cookie,
    _quark_download_url,
    _quark_token,
    _save_quark_cookie,
    _safe_filename,
    _size_value,
    _target_directory,
    scan_models,
)


class DownloadHelperTests(unittest.TestCase):
    def test_normalizes_quark_file_token_shapes(self):
        self.assertEqual(_quark_token(" token "), "token")
        self.assertEqual(_quark_token(["token"]), "token")
        self.assertEqual(_quark_token({"share_fid_token": "token"}), "token")

    def test_quick_scan_includes_exact_external_library_search(self):
        class Request:
            async def json(self):
                return {"quick": True, "nodes": []}

        analyzed = {
            "models": [],
            "summary": {"unresolved": 0, "references": 0},
        }
        with (
            patch("ComfyUI_FindModels.find_models.analyze", return_value=analyzed),
            patch("ComfyUI_FindModels.find_models._external_candidates_index", return_value={}) as external_search,
            patch("ComfyUI_FindModels.find_models._load_external_folder", return_value=None),
        ):
            response = asyncio.run(scan_models(Request()))

        external_search.assert_called_once()
        self.assertIn(b'"quick": true', response.body)

    def test_allows_known_model_hosts(self):
        self.assertTrue(_allowed_download_url("https://civitai.com/api/download/models/1"))
        self.assertTrue(_allowed_download_url("https://huggingface.co/repo/resolve/main/model.safetensors"))
        self.assertTrue(_allowed_download_url("https://cdn-lfs.hf.co/file"))

    def test_rejects_unknown_or_insecure_hosts(self):
        self.assertFalse(_allowed_download_url("http://huggingface.co/model.safetensors"))
        self.assertFalse(_allowed_download_url("https://example.com/model.safetensors"))

    def test_allows_only_official_quark_download_hosts(self):
        self.assertTrue(_allowed_quark_download_url("https://download.uc.cn/model.safetensors"))
        self.assertTrue(_allowed_quark_download_url("https://drive-pc.quark.cn/model.safetensors"))
        self.assertFalse(_allowed_quark_download_url("https://example.com/model.safetensors"))

    def test_sanitizes_filename(self):
        self.assertEqual(_safe_filename("../../model.safetensors"), "model.safetensors")

    def test_normalizes_source_sizes(self):
        self.assertEqual(_size_value(1024), 1024)
        self.assertEqual(_size_value(2048, 1024), 2097152)
        self.assertIsNone(_size_value(None))

    def test_reads_total_size_from_content_range(self):
        self.assertEqual(_content_range_total("bytes 1024-2047/8192"), 8192)
        self.assertIsNone(_content_range_total(None))

    def test_public_download_job_hides_resume_payload_and_temp_path(self):
        public = _public_download_job({
            "id": "job",
            "status": "paused",
            "payload": {"url": "secret"},
            "temp_path": "private.part",
        })
        self.assertEqual(public, {"id": "job", "status": "paused"})

    def test_public_download_job_reports_speed_elapsed_and_eta(self):
        with patch("ComfyUI_FindModels.find_models.time.time", return_value=110):
            public = _public_download_job({
                "id": "job",
                "status": "downloading",
                "started_at": 100,
                "downloaded": 1000,
                "total": 5000,
            })
        self.assertEqual(public["elapsed"], 10)
        self.assertEqual(public["speed"], 100)
        self.assertEqual(public["eta"], 40)

    def test_source_filename_must_match_missing_model_exactly(self):
        self.assertTrue(_exact_model_name("folder/model.safetensors", "model.safetensors"))
        self.assertFalse(_exact_model_name("model-v1.safetensors", "model-v2.safetensors"))

    def test_rejects_git_lfs_pointer_as_model(self):
        path = Path.cwd() / "test-lfs-pointer.safetensors"
        path.write_bytes(b"version https://git-lfs.github.com/spec/v1\n" + b"x" * 1024)
        try:
            self.assertFalse(_is_model_payload(path))
        finally:
            path.unlink()

    def test_uses_matching_comfyui_model_folder(self):
        self.assertEqual(_target_directory("loras"), (Path.cwd() / "models" / "loras").resolve())

    def test_rejects_unknown_download_folder(self):
        with self.assertRaises(Exception):
            _target_directory("unknown")

    def test_supports_registered_dynamic_model_folder(self):
        original = folder_paths.get_folder_paths
        folder_paths.get_folder_paths = lambda category: (
            [str(Path.cwd() / "models" / category)] if category == "audio_encoders" else []
        )
        try:
            self.assertEqual(
                _target_directory("audio_encoders"),
                (Path.cwd() / "models" / "audio_encoders").resolve(),
            )
        finally:
            folder_paths.get_folder_paths = original

    def test_unknown_model_category_uses_exact_external_official_folder_hint(self):
        category = _resolve_model_category(
            {"name": "model.bin", "category": "unknown", "node_type": "CustomLoader", "widget": "model"},
            [{"path": "models/audio_encoders/model.bin", "category_hint": "audio_encoders"}],
        )
        self.assertEqual(category, "audio_encoders")

    def test_unknown_model_category_uses_exact_local_candidate_registration(self):
        category = _resolve_model_category(
            {
                "name": "model.bin",
                "category": "unknown",
                "node_type": "CustomLoader",
                "widget": "model",
                "match": {"name": "model.bin", "category": "audio_encoders"},
            },
            [],
        )
        self.assertEqual(category, "audio_encoders")

    def test_registered_node_category_overrides_generic_clip_guess(self):
        class ClipLoaderGGUF:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"clip_name": (["Z-Image-Engineer-V6-Q8_0.gguf"],)}}

        nodes = types.ModuleType("nodes")
        nodes.NODE_CLASS_MAPPINGS = {"CLIPLoader (GGUF)": ClipLoaderGGUF}
        original_get_filename_list = folder_paths.get_filename_list
        folder_paths.get_filename_list = lambda category: (
            ["Z-Image-Engineer-V6-Q8_0.gguf"] if category == "clip" else []
        )
        try:
            with patch.dict(sys.modules, {"nodes": nodes}):
                category = _resolve_model_category(
                    {
                        "name": "Z-Image-Engineer-V6-Q8_0.gguf",
                        "category": "text_encoders",
                        "node_type": "CLIPLoader (GGUF)",
                        "widget": "clip_name",
                    },
                    [],
                )
        finally:
            folder_paths.get_filename_list = original_get_filename_list

        self.assertEqual(category, "clip")

    def test_supports_legacy_comfyui_folder_aliases(self):
        original = folder_paths.get_folder_paths
        folder_paths.get_folder_paths = lambda category: [] if category == "text_encoders" else [str(Path.cwd() / "models" / category)]
        try:
            self.assertEqual(_target_directory("text_encoders"), (Path.cwd() / "models" / "clip").resolve())
        finally:
            folder_paths.get_folder_paths = original

    def test_clears_matching_model_cache_after_download(self):
        folder_paths.filename_list_cache = {"loras": ("cached",), "vae": ("keep",)}
        _clear_filename_cache("loras")
        self.assertNotIn("loras", folder_paths.filename_list_cache)
        self.assertIn("vae", folder_paths.filename_list_cache)

    def test_contains_requested_quark_libraries(self):
        urls = [item["url"] for item in QUARK_MODEL_LIBRARIES]
        self.assertEqual(urls, [
            "https://pan.quark.cn/s/fb913d649b18",
            "https://pan.quark.cn/s/4680ac866516",
        ])

    def test_quark_download_uses_refreshed_singular_fid_token(self):
        calls = []

        async def fake_quark_json(session, method, path, *, share_id, data=None):
            calls.append((method, path, data))
            if "sharepage/token" in path:
                return {"data": {"stoken": "fresh-stoken"}}
            return {"data": [{"download_url": "https://download.uc.cn/model.safetensors"}]}

        async def fake_candidates(session, name, category, library):
            return [{
                "name": name,
                "quark": {
                    "share_id": library["share_id"],
                    "fid": "fresh-fid",
                    "fid_token": "fresh-token",
                    "filename": name,
                },
            }]

        with patch("ComfyUI_FindModels.find_models._quark_json", side_effect=fake_quark_json), patch(
            "ComfyUI_FindModels.find_models._quark_candidates", side_effect=fake_candidates
        ):
            url = asyncio.run(_quark_download_url(None, {
                "share_id": "share",
                "fid": "stale-fid",
                "fid_token": "stale-token",
                "filename": "model.safetensors",
            }))

        self.assertEqual(url, "https://download.uc.cn/model.safetensors")
        download_payload = calls[-1][2]
        self.assertEqual(download_payload["fids"], ["fresh-fid"])
        self.assertNotIn("fids_token", download_payload)
        self.assertEqual(download_payload["fid_token"], ["fresh-token"])

    def test_quark_search_recurses_and_paginates_until_exact_file(self):
        calls = []

        async def fake_quark_json(session, method, path, *, share_id, data=None):
            calls.append(path)
            if "sharepage/token" in path:
                return {"data": {"stoken": "token"}}
            if "pdir_fid=0" in path:
                return {"data": {"list": [{"dir": True, "fid": "nested", "file_name": "models"}]}}
            if "_page=1" in path:
                return {"data": {"list": [
                    {"dir": False, "fid": str(index), "file_name": f"other-{index}.safetensors", "share_fid_token": "x"}
                    for index in range(200)
                ]}}
            return {"data": {"list": [{
                "dir": False,
                "fid": "wanted",
                "file_name": "MODEL.SAFETENSORS",
                "share_fid_token": "wanted-token",
                "size": 2048,
            }]}}

        library = {"name": "Quark", "share_id": "share", "url": "https://pan.quark.cn/s/share"}
        with patch("ComfyUI_FindModels.find_models._quark_json", side_effect=fake_quark_json):
            result = asyncio.run(_quark_candidates(None, "model.safetensors", "unknown", library))

        self.assertEqual(result[-1]["name"], "MODEL.SAFETENSORS")
        self.assertEqual(result[-1]["confidence"], 1.0)
        self.assertTrue(any("_page=2" in path for path in calls))

    def test_saves_and_clears_quark_cookie_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "quark_auth.json"
            with patch("ComfyUI_FindModels.find_models.QUARK_AUTH_CONFIG", config):
                _save_quark_cookie("foo=bar")
                self.assertEqual(_load_quark_cookie(), "foo=bar")
                _save_quark_cookie("")
                self.assertEqual(_load_quark_cookie(), "")
                self.assertFalse(config.exists())

    def test_direct_fallback_accepts_only_verified_exact_filename(self):
        async def fake_huggingface(session, name):
            return [
                {"provider": "Hugging Face", "name": name, "url": "https://huggingface.co/repo/resolve/main/model.safetensors"},
                {"provider": "Hugging Face", "name": "wrong.safetensors", "url": "https://huggingface.co/repo/resolve/main/wrong.safetensors"},
            ]

        async def fake_validate(session, candidate):
            return candidate

        with patch("ComfyUI_FindModels.find_models._huggingface_candidates", side_effect=fake_huggingface), patch(
            "ComfyUI_FindModels.find_models._civitai_candidates", return_value=[]
        ), patch("ComfyUI_FindModels.find_models._validate_web_candidate", side_effect=fake_validate):
            result = asyncio.run(_direct_web_fallback(None, "model.safetensors"))

        self.assertEqual(result["name"], "model.safetensors")

    def test_contains_verified_fantasytalking_source(self):
        source = KNOWN_MODEL_SOURCES["fantasytalking_fp16.safetensors"]
        self.assertEqual(source["name"], "fantasytalking_fp16.safetensors")
        self.assertTrue(source["url"].startswith("https://huggingface.co/Kijai/WanVideo_comfy/"))

    def test_external_model_index_only_contains_model_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "nested" / "wanted.safetensors"
            model.parent.mkdir()
            model.write_bytes(b"x" * 2048)
            (root / "notes.txt").write_text("not a model", encoding="utf-8")
            index = _external_model_index(root)
            self.assertEqual(index["wanted.safetensors"][0]["path"], str(model.resolve()))
            self.assertNotIn("notes.txt", index)

    def test_external_model_index_searches_deep_registered_model_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "archive" / "models" / "detection" / "people" / "pose.pt2"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"x" * 2048)
            index = _external_model_index(root)
            self.assertEqual(index["pose.pt2"][0]["path"], str(model.resolve()))
            self.assertEqual(index["pose.pt2"][0]["category_hint"], "detection")

    def test_external_priority_scan_finds_exact_deep_gguf_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wanted = root / "diffusion_models" / "Wan" / "Wan2.1-InfiniteTalk_Single_Q6_K.gguf"
            unrelated = root / "diffusion_models" / "Wan" / "another-model.gguf"
            duplicate = root / "archive" / "Wan2.1-InfiniteTalk_Single_Q6_K.gguf"
            wanted.parent.mkdir(parents=True)
            duplicate.parent.mkdir(parents=True)
            wanted.write_bytes(b"x" * 2048)
            unrelated.write_bytes(b"x" * 2048)
            duplicate.write_bytes(b"x" * 2048)

            index = _external_model_index_for_names(
                root,
                {"Wan/Wan2.1-InfiniteTalk_Single_Q6_K.gguf"},
                {"Wan/Wan2.1-InfiniteTalk_Single_Q6_K.gguf": "diffusion_models"},
            )

            self.assertEqual(list(index), ["wan2.1-infinitetalk_single_q6_k.gguf"])
            self.assertEqual(len(index["wan2.1-infinitetalk_single_q6_k.gguf"]), 1)
            self.assertEqual(index["wan2.1-infinitetalk_single_q6_k.gguf"][0]["path"], str(wanted.resolve()))
            self.assertEqual(index["wan2.1-infinitetalk_single_q6_k.gguf"][0]["category_hint"], "diffusion_models")

    def test_external_priority_scan_rejects_unicode_punctuation_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "loras" / "Qwen" / "任务拆解二次元,.safetensors"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"x" * 2048)
            wanted = "Qwen/任务拆解二次元， .safetensors"

            index = _external_model_index_for_names(root, {wanted}, {wanted: "loras"})

            self.assertEqual(index, {})

    def test_external_model_index_uses_custom_registered_extensions(self):
        original = folder_paths.folder_names_and_paths
        folder_paths.folder_names_and_paths = {
            **original,
            "custom_weights": ([str(Path.cwd() / "models" / "custom_weights")], {".weights"}),
        }
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                model = root / "many" / "nested" / "custom.weights"
                model.parent.mkdir(parents=True)
                model.write_bytes(b"x" * 2048)
                self.assertIn(".weights", _registered_model_extensions())
                self.assertIn("custom.weights", _external_model_index(root))
        finally:
            folder_paths.folder_names_and_paths = original

    def test_native_folder_selector_returns_selected_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = types.SimpleNamespace(returncode=0, stdout=f"\ufeff{directory}\n", stderr="")
            with patch("ComfyUI_FindModels.find_models.subprocess.run", return_value=completed) as run:
                self.assertEqual(_choose_external_folder(), Path(directory).resolve())
            script = run.call_args.args[0][-1]
            self.assertIn("$owner.TopMost = $true", script)
            self.assertIn("$dialog.ShowDialog($owner)", script)

    def test_moves_external_model_to_official_category_root(self):
        with tempfile.TemporaryDirectory() as external, tempfile.TemporaryDirectory() as models:
            source = Path(external) / "wanted.safetensors"
            source.write_bytes(b"x" * 2048)
            original = folder_paths.get_folder_paths
            folder_paths.get_folder_paths = lambda category: [str(Path(models) / category)]
            try:
                result = _move_external_model(
                    str(source),
                    "Wan/wanted.safetensors",
                    "diffusion_models",
                    Path(external).resolve(),
                )
            finally:
                folder_paths.get_folder_paths = original
            self.assertFalse(source.exists())
            self.assertTrue((Path(models) / "diffusion_models" / "wanted.safetensors").exists())
            self.assertEqual(result["relative_name"], "wanted.safetensors")

    def test_external_move_strips_redundant_official_folder_prefix(self):
        with tempfile.TemporaryDirectory() as external, tempfile.TemporaryDirectory() as models:
            source = Path(external) / "wanted.safetensors"
            source.write_bytes(b"x" * 2048)
            original = folder_paths.get_folder_paths
            folder_paths.get_folder_paths = lambda category: [str(Path(models) / category)]
            try:
                result = _move_external_model(
                    str(source),
                    "models/loras/characters/wanted.safetensors",
                    "loras",
                    Path(external).resolve(),
                )
            finally:
                folder_paths.get_folder_paths = original
            expected = Path(models) / "loras" / "wanted.safetensors"
            self.assertTrue(expected.exists())
            self.assertEqual(result["relative_name"], "wanted.safetensors")

    def test_official_relative_name_ignores_node_subfolders(self):
        self.assertEqual(
            _official_relative_model_name("Wan/wanted.safetensors", "diffusion_models").as_posix(),
            "wanted.safetensors",
        )

    def test_target_directory_prefers_canonical_official_folder_over_legacy_alias(self):
        original = folder_paths.get_folder_paths
        folder_paths.get_folder_paths = lambda category: [
            str(Path.cwd() / "models" / "unet"),
            str(Path.cwd() / "models" / "diffusion_models"),
        ] if category == "diffusion_models" else []
        try:
            self.assertEqual(
                _target_directory("diffusion_models"),
                (Path.cwd() / "models" / "diffusion_models").resolve(),
            )
        finally:
            folder_paths.get_folder_paths = original

    def test_target_directory_supports_official_uppercase_llm_category(self):
        original = folder_paths.get_folder_paths
        folder_paths.get_folder_paths = lambda category: [str(Path.cwd() / "models" / "LLM")] if category == "LLM" else []
        try:
            self.assertEqual(
                _target_directory("LLM"),
                (Path.cwd() / "models" / "LLM").resolve(),
            )
        finally:
            folder_paths.get_folder_paths = original

    def test_target_directory_supports_official_instantid_category(self):
        original = folder_paths.get_folder_paths
        folder_paths.get_folder_paths = lambda category: [str(Path.cwd() / "models" / "instantid")] if category == "instantid" else []
        try:
            self.assertEqual(
                _target_directory("instantid"),
                (Path.cwd() / "models" / "instantid").resolve(),
            )
        finally:
            folder_paths.get_folder_paths = original

    def test_external_move_rejects_wrong_filename(self):
        with tempfile.TemporaryDirectory() as external:
            source = Path(external) / "wrong.safetensors"
            source.write_bytes(b"x" * 2048)
            with self.assertRaises(Exception):
                _move_external_model(
                    str(source),
                    "wanted.safetensors",
                    "checkpoints",
                    Path(external).resolve(),
                )

    def test_external_move_rejects_punctuation_variant_filename(self):
        with tempfile.TemporaryDirectory() as external:
            source = Path(external) / "model,.safetensors"
            source.write_bytes(b"x" * 2048)
            with self.assertRaises(Exception):
                _move_external_model(
                    str(source),
                    "model，.safetensors",
                    "checkpoints",
                    Path(external).resolve(),
                )

    def test_external_move_never_overwrites_existing_model(self):
        with tempfile.TemporaryDirectory() as external, tempfile.TemporaryDirectory() as models:
            source = Path(external) / "wanted.safetensors"
            source.write_bytes(b"x" * 2048)
            target = Path(models) / "checkpoints" / "wanted.safetensors"
            target.parent.mkdir()
            target.write_bytes(b"existing" * 256)
            original = folder_paths.get_folder_paths
            folder_paths.get_folder_paths = lambda category: [str(Path(models) / category)]
            try:
                with self.assertRaises(Exception):
                    _move_external_model(
                        str(source),
                        "wanted.safetensors",
                        "checkpoints",
                        Path(external).resolve(),
                    )
            finally:
                folder_paths.get_folder_paths = original
            self.assertTrue(source.exists())
            self.assertTrue(target.exists())

if __name__ == "__main__":
    unittest.main()
