import sys
import types
import unittest
from pathlib import Path


class Routes:
    def post(self, path):
        return lambda function: function


server = types.ModuleType("server")
server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=Routes()))
folder_paths = types.ModuleType("folder_paths")
folder_paths.get_filename_list = lambda category: []
folder_paths.get_folder_paths = lambda category: [str(Path.cwd() / "models" / category)]
folder_paths.filename_list_cache = {}
sys.modules.setdefault("server", server)
sys.modules.setdefault("folder_paths", folder_paths)
sys.path.insert(0, str(Path.cwd().parent))

from ComfyUI_FindModels.find_models import (
    QUARK_MODEL_LIBRARIES,
    _allowed_download_url,
    _allowed_quark_download_url,
    _clear_filename_cache,
    _exact_model_name,
    _is_model_payload,
    _safe_filename,
    _size_value,
    _target_directory,
)


class DownloadHelperTests(unittest.TestCase):
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
        self.assertEqual(
            [item["url"] for item in QUARK_MODEL_LIBRARIES],
            [
                "https://pan.quark.cn/s/fb913d649b18",
                "https://pan.quark.cn/s/4680ac8665162",
            ],
        )


if __name__ == "__main__":
    unittest.main()
