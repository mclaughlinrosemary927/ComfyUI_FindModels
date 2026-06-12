import tempfile
import unittest
from pathlib import Path

from node_installer import (
    allowed_repo_url,
    declared_dependency_conflicts,
    dependency_conflicts,
    market_candidates,
    missing_node_types,
)


MARKET = [
    {
        "id": "gguf",
        "title": "ComfyUI-GGUF",
        "files": ["https://github.com/city96/ComfyUI-GGUF"],
        "install_type": "git-clone",
        "preemptions": ["UnetLoaderGGUF"],
    },
    {
        "id": "mapped",
        "title": "Mapped Pack",
        "files": ["https://github.com/example/mapped-pack"],
        "install_type": "git-clone",
    },
]


class NodeInstallerTests(unittest.TestCase):
    def test_finds_only_unregistered_node_types(self):
        self.assertEqual(missing_node_types(["Known", "Missing", "Missing"], ["Known"]), ["Missing"])

    def test_ignores_frontend_annotation_nodes(self):
        self.assertEqual(missing_node_types(["Markdown注释", "注释+(mtb)", "Note"], []), [])

    def test_matches_te_market_preemption(self):
        result = market_candidates(MARKET, "UnetLoaderGGUF")
        self.assertEqual(result[0]["id"], "gguf")
        self.assertTrue(result[0]["installable"])

    def test_matches_official_manager_node_map_to_te_market(self):
        node_map = {"https://github.com/example/mapped-pack": [["MappedNode"], {}]}
        result = market_candidates(MARKET, "MappedNode", node_map)
        self.assertEqual(result[0]["id"], "mapped")

    def test_rejects_non_github_install_urls(self):
        self.assertFalse(allowed_repo_url("https://example.com/plugin"))
        self.assertTrue(allowed_repo_url("https://github.com/example/plugin"))

    def test_blocks_core_runtime_dependency_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "requirements.txt").write_text("torch>=2.0\nrequests\n", encoding="utf-8")
            self.assertTrue(any("核心运行依赖" in item for item in dependency_conflicts(path)))

    def test_blocks_market_core_runtime_dependency_changes(self):
        self.assertTrue(declared_dependency_conflicts(["xformers>=0.0.30"]))
        self.assertFalse(declared_dependency_conflicts(["torch"]))


if __name__ == "__main__":
    unittest.main()
