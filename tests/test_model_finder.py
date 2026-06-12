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
                {"id": 1, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "model-v1.safetensors"}]},
                {"id": 2, "type": "LoraLoader", "widgets": [{"name": "lora_name", "value": "HeroStyle.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["installed"], 1)
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertTrue(result["models"][1]["match"]["auto_apply"])

    def test_prefers_located_reference_over_serialized_duplicate(self):
        payload = {
            "nodes": [{"id": 3, "type": "VAELoader", "widgets": [{"name": "vae_name", "value": "x.vae.safetensors"}]}],
            "workflow": {"nodes": [{"type": "VAELoader", "widgets_values": ["x.vae.safetensors"]}]},
        }
        refs = extract_references(payload)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].node_id, "3")


if __name__ == "__main__":
    unittest.main()
