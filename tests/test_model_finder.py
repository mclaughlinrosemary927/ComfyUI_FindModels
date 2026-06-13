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

    def test_clip_vision_filename_classifies_translated_loader(self):
        payload = {
            "nodes": [{
                "id": 17,
                "type": "加载CLIP视觉",
                "widgets": [{"name": "clip名称", "value": "clip_vision_h.safetensors", "model_selector": True}],
            }]
        }
        result = analyze(payload, lambda category: ["clip_vision_h.safetensors"] if category == "clip_vision" else [])
        self.assertEqual(result["models"], [])

    def test_normalized_stem_removes_common_precision_suffix(self):
        self.assertEqual(normalized_stem("Hero_v2_fp16.safetensors"), "hero")

    def test_removes_leading_path_separators(self):
        refs = extract_references(
            {"nodes": [{"id": 6, "type": "VAELoader", "widgets": [{"name": "vae_name", "value": "\\/folder/model.safetensors"}]}]}
        )
        self.assertEqual(refs[0].name, "folder/model.safetensors")

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
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["models"][0]["name"], "Qwen3.5-9B-Uncensored.gguf")

    def test_fantasytalking_model_uses_diffusion_models_folder(self):
        payload = {
            "nodes": [{
                "id": 16,
                "type": "FantasyTalkingModelLoader",
                "widgets": [{
                    "name": "model",
                    "value": "万相JK/fantasytalking_fp16.safetensors",
                    "model_selector": True,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"][0]["category"], "diffusion_models")

    def test_detects_missing_model_in_custom_loader_with_translated_widget(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideo Model Loader",
                "widgets": [{
                    "name": "模型",
                    "value": "Wan/Wan14Bi2vFusioniX_fp8.safetensors",
                    "model_selector": False,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["models"][0]["category"], "diffusion_models")
        self.assertEqual(result["models"][0]["name"], "Wan/Wan14Bi2vFusioniX_fp8.safetensors")

    def test_hides_installed_model_in_custom_loader_with_translated_widget(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideo Model Loader",
                "widgets": [{
                    "name": "模型",
                    "value": "Wan/Wan14Bi2vFusioniX_fp8.safetensors",
                    "model_selector": False,
                }],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["Wan/Wan14Bi2vFusioniX_fp8.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["models"], [])

    def test_extracts_serialized_widget_values_from_live_node_snapshot(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideoModelLoader",
                "widgets": [],
                "widgets_values": ["FusioniX/Wan14Bi2vFusioniX_fp8.safetensors", "fp16_fast"],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["Wan/Wan14Bi2vFusioniX_fp8.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertEqual(result["models"][0]["name"], "FusioniX/Wan14Bi2vFusioniX_fp8.safetensors")
        self.assertEqual(result["models"][0]["match"]["name"], "Wan/Wan14Bi2vFusioniX_fp8.safetensors")

    def test_extracts_model_filename_nested_in_custom_widget_value(self):
        payload = {
            "nodes": [{
                "id": 23,
                "type": "CustomModelLoader",
                "widgets": [{
                    "name": "model",
                    "value": {"selected": ["folder/missing.safetensors"]},
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["models"][0]["name"], "folder/missing.safetensors")

    def test_wanvideo_vae_loader_is_classified_as_vae_before_wanvideo(self):
        payload = {
            "nodes": [{
                "id": 38,
                "type": "WanVideoVAELoader",
                "widgets_values": ["万相KJ/Wan2_1_VAE_bf16.safetensors", "bf16"],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["Wan2_1_VAE_bf16.safetensors"] if category == "vae" else [],
        )
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertEqual(result["models"][0]["category"], "vae")

    def test_official_combo_missing_stays_missing_even_when_file_exists(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideoModelLoader",
                "widgets": [{
                    "name": "model",
                    "value": "Wan/Wan14Bi2vFusioniX_fp8.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["Wan/Wan14Bi2vFusioniX_fp8.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertTrue(result["models"][0]["official_missing"])

    def test_official_combo_valid_hides_installed_model(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideoModelLoader",
                "widgets": [{
                    "name": "model",
                    "value": "Wan/Wan14Bi2vFusioniX_fp8.safetensors",
                    "model_selector": True,
                    "model_value_valid": True,
                }],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["Wan/Wan14Bi2vFusioniX_fp8.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["models"], [])

    def test_scans_official_embedded_node_model_metadata(self):
        payload = {
            "nodes": [{
                "id": 22,
                "type": "WanVideoModelLoader",
                "models": [{
                    "name": "embedded-missing.safetensors",
                    "directory": "diffusion_models",
                    "url": "https://huggingface.co/example/model",
                }],
                "widgets": [],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["models"][0]["name"], "embedded-missing.safetensors")

    def test_scans_official_top_level_model_metadata(self):
        payload = {
            "models": [{
                "name": "top-level-missing.safetensors",
                "directory": "loras",
                "url": "https://huggingface.co/example/model",
            }],
            "nodes": [],
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["models"][0]["category"], "loras")

    def test_official_missing_reference_wins_over_adaptable_duplicate(self):
        payload = {
            "nodes": [
                {
                    "id": 1,
                    "type": "WanVideoModelLoader",
                    "widgets": [{
                        "name": "model",
                        "value": "Wan/model.safetensors",
                        "model_selector": True,
                        "model_value_valid": False,
                    }],
                },
                {
                    "id": 2,
                    "type": "WanVideoModelLoader",
                    "widgets_values": ["Wan/model.safetensors"],
                },
            ]
        }
        result = analyze(
            payload,
            lambda category: ["Other/model.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(result["models"][0]["status"], "missing")
        self.assertTrue(result["models"][0]["official_missing"])


if __name__ == "__main__":
    unittest.main()
