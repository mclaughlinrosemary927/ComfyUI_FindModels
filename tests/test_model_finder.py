import unittest

from model_finder import analyze, classify, extract_references, normalized_stem


FILES = {
    "checkpoints": ["sdxl/base/model-v1.safetensors"],
    "loras": ["characters/HeroStyles_fp16.safetensors"],
    "vae": [],
    "controlnet": [],
    "text_encoders": [],
    "clip": [],
    "diffusion_models": [],
    "unet": [],
    "upscale_models": [],
    "embeddings": [],
}


class ModelFinderTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify("LoraLoader lora_name"), "loras")
        self.assertEqual(classify("ControlNetLoader control_net_name"), "controlnet")
        self.assertEqual(classify("RIFE VFI rife47.pth"), "upscale_models")
        self.assertEqual(classify("Load CLIP Vision clip_vision_h.safetensors"), "clip_vision")

    def test_normalized_stem_removes_common_precision_suffix(self):
        self.assertEqual(normalized_stem("Hero_v2_fp16.safetensors"), "hero")

    def test_extracts_widget_reference_with_location(self):
        refs = extract_references(
            {"nodes": [{"id": 7, "type": "LoraLoader", "widgets": [{"name": "lora_name", "value": "Hero.safetensors"}]}]}
        )
        self.assertEqual(refs[0].node_id, "7")
        self.assertEqual(refs[0].widget, "lora_name")
        self.assertEqual(refs[0].category, "loras")

    def test_analyze_exact_and_adaptable(self):
        payload = {
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "sdxl/base/model-v1.safetensors"}]},
                {"id": 2, "type": "LoraLoader", "widgets": [{"name": "lora_name", "value": "HeroStyle.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["installed"], 1)
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(len(result["models"]), 1)
        self.assertTrue(result["models"][0]["match"]["auto_apply"])

    def test_exact_filename_in_subfolder_requires_loading_into_node(self):
        payload = {
            "nodes": [
                {"id": 4, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "model-v1.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertEqual(result["models"][0]["match"]["reason"], "exact_filename")
        self.assertTrue(result["models"][0]["match"]["auto_apply"])

    def test_hides_installed_models(self):
        payload = {
            "nodes": [
                {"id": 5, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "sdxl/base/model-v1.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["unresolved"], 0)
        self.assertEqual(result["models"], [])

    def test_ignores_serialized_workflow_data(self):
        payload = {
            "nodes": [],
            "workflow": {
                "nodes": [
                    {
                        "type": "CheckpointLoaderSimple",
                        "widgets_values": ["z_image_turbo_bf16.safetensors"],
                    }
                ]
            },
        }
        refs = extract_references(payload)
        self.assertEqual(refs, [])

    def test_ignores_generic_custom_node_model_references(self):
        payload = {
            "nodes": [{"id": 8, "type": "CustomGGUFNode", "widgets": [{"name": "model", "value": "model.gguf"}]}]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["external"], 0)
        self.assertEqual(result["models"], [])

    def test_shows_same_missing_file_only_once(self):
        payload = {
            "nodes": [
                {"id": 10, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "missing.safetensors"}]},
                {"id": 11, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "missing.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(len(result["models"]), 1)

    def test_ignores_model_urls_in_text_widgets(self):
        payload = {
            "nodes": [{
                "id": 12,
                "type": "TextNode",
                "widgets": [{
                    "name": "text",
                    "value": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/model.safetensors",
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"], [])

    def test_ignores_filename_in_non_model_text_widget(self):
        payload = {
            "nodes": [{"id": 13, "type": "TextNode", "widgets": [{"name": "text", "value": "model.safetensors"}]}]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"], [])

    def test_ignores_generic_model_widget_on_non_loader_custom_node(self):
        payload = {
            "nodes": [{"id": 14, "type": "Workflow-Encrypt ChatNode", "widgets": [{"name": "model", "value": "z_image_turbo_bf16.safetensors"}]}]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"], [])

    def test_accepts_confirmed_custom_model_selector(self):
        payload = {
            "nodes": [{
                "id": 15,
                "type": "Dapao_LlamaChat",
                "widgets": [{
                    "name": "模型文件",
                    "value": "Qwen3.5-9B-Uncensored.gguf",
                    "model_selector": True,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["external"], 1)
        self.assertEqual(result["models"], [])


if __name__ == "__main__":
    unittest.main()
