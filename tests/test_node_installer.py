import tempfile
import unittest
from pathlib import Path

from node_installer import (
    allowed_repo_url,
    declared_dependency_conflicts,
    dependency_conflicts,
    github_fallback_candidates,
    missing_node_types,
    missing_workflow_node_packages,
    missing_workflow_node_types,
)


class NodeInstallerTests(unittest.TestCase):
    def test_finds_only_unregistered_node_types(self):
        self.assertEqual(missing_node_types(["Known", "Missing", "Missing"], ["Known"]), ["Missing"])

    def test_ignores_frontend_annotation_nodes(self):
        self.assertEqual(missing_node_types(["Markdown注释", "注释+(mtb)", "Note"], []), [])

    def test_ignores_nodes_registered_by_frontend_extensions(self):
        nodes = [
            {"type": "获取点", "frontend_registered": True, "active": True},
            {"type": "ActualMissingNode", "frontend_registered": False, "active": True},
            {"type": "InactiveMissingNode", "frontend_registered": False, "active": False},
        ]
        self.assertEqual(missing_workflow_node_types(nodes, []), ["ActualMissingNode"])

    def test_groups_missing_nodes_by_workflow_package_id(self):
        nodes = [
            {
                "id": 230,
                "type": "AudioDurationToFrames",
                "package_id": "syq890610-crypto/Comfyui-Mk-tools",
                "package_version": "70cd94a6",
            },
            {
                "id": 241,
                "type": "PresetSizeSelector",
                "package_id": "syq890610-crypto/Comfyui-Mk-tools",
                "package_version": "70cd94a6",
            },
        ]
        packages = missing_workflow_node_packages(nodes, [])
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["id"], "syq890610-crypto/Comfyui-Mk-tools")
        self.assertEqual(packages[0]["count"], 2)
        self.assertEqual(packages[0]["node_ids"], ["230", "241"])

    def test_groups_unmapped_missing_node_as_unknown_package(self):
        packages = missing_workflow_node_packages([{"id": 1, "type": "UnknownNode"}], [])
        self.assertFalse(packages[0]["known"])
        self.assertEqual(packages[0]["node_types"], ["UnknownNode"])

    def test_builds_github_fallback_from_workflow_package_id(self):
        result = github_fallback_candidates(
            "syq890610-crypto/Comfyui-Mk-tools",
            "AudioDurationToFrames",
            {},
        )
        self.assertEqual(result[0]["repo_url"], "https://github.com/syq890610-crypto/Comfyui-Mk-tools")
        self.assertEqual(result[0]["reason"], "workflow_package_github")

    def test_builds_github_fallback_from_manager_mapping(self):
        result = github_fallback_candidates(
            "",
            "MappedNode",
            {"https://github.com/example/mapped-pack": [["MappedNode"], {}]},
        )
        self.assertEqual(result[0]["repo_url"], "https://github.com/example/mapped-pack")
        self.assertEqual(result[0]["reason"], "comfy_manager_github")

    def test_does_not_install_from_untrusted_package_text(self):
        self.assertEqual(github_fallback_candidates("not a github repository", "UnknownNode", {}), [])

    def test_rejects_non_github_install_urls(self):
        self.assertFalse(allowed_repo_url("https://example.com/plugin"))
        self.assertTrue(allowed_repo_url("https://github.com/example/plugin"))

    def test_blocks_core_runtime_dependency_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "requirements.txt").write_text("torch>=2.0\nrequests\n", encoding="utf-8")
            self.assertTrue(any("核心运行依赖" in item for item in dependency_conflicts(path)))

    def test_blocks_declared_core_runtime_dependency_changes(self):
        self.assertTrue(declared_dependency_conflicts(["xformers>=0.0.30"]))
        self.assertFalse(declared_dependency_conflicts(["torch"]))


if __name__ == "__main__":
    unittest.main()
