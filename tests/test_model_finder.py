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
        self.assertEqual(classify("RIFE VFI rife47.pth"), "frame_interpolation")
        self.assertEqual(classify("Load CLIP Vision clip_vision_h.safetensors"), "clip_vision")
        self.assertEqual(classify("VitPose Loader vitpose-l-wholebody.onnx"), "detection")
        self.assertEqual(classify("Llama-cpp Model Loader llama_model"), "LLM")
        self.assertEqual(classify("Llama-cpp Model Loader mmproj_model"), "LLM")
        self.assertEqual(classify("Load InstantID Model ip-adapter.bin"), "instantid")
        self.assertEqual(classify("IPAdapter Model Loader ip-adapter.bin"), "ipadapter")
        self.assertEqual(classify("Load CustomWeights file.bin", ["custom_weights"]), "custom_weights")
        self.assertEqual(classify("SAMLoader (Impact) sam_vit_b_01ec64.pth"), "sams")
        self.assertEqual(classify("检测加载器 segm/face_yolov8n_v2.pt"), "ultralytics_segm")

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

    def test_similar_filename_is_missing_without_local_candidate(self):
        payload = {
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "sdxl/base/model-v1.safetensors"}]},
                {"id": 2, "type": "LoraLoader", "widgets": [{"name": "lora_name", "value": "HeroStyle.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["installed"], 1)
        self.assertEqual(result["summary"]["adaptable"], 0)
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(len(result["models"]), 1)
        self.assertIsNone(result["models"][0]["match"])

    def test_exact_filename_with_different_registered_path_is_adaptable(self):
        payload = {
            "nodes": [
                {"id": 4, "type": "CheckpointLoaderSimple", "widgets": [{"name": "ckpt_name", "value": "model-v1.safetensors"}]},
            ]
        }
        result = analyze(payload, lambda category: FILES.get(category, []))
        self.assertEqual(result["summary"]["adaptable"], 1)
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(result["models"][0]["match"]["reason"], "exact_filename")
        self.assertEqual(result["models"][0]["match"]["confidence"], 0.99)

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

    def test_infinitetalk_model_uses_diffusion_models_folder(self):
        payload = {
            "nodes": [{
                "id": 120,
                "type": "Multi/InfiniteTalk Model Loader",
                "widgets": [{
                    "name": "模型",
                    "value": "Wan/Wan2.1-InfiniteTalk_Single_Q6_K.gguf",
                    "model_selector": True,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"][0]["category"], "diffusion_models")

    def test_scail_checkpoint_uses_wanvideo_diffusion_models_folder(self):
        payload = {
            "nodes": [{
                "id": 121,
                "type": "Custom Model Loader",
                "widgets": [{
                    "name": "model",
                    "value": "wan2.1_14B_SCAIL_2_fp8_scaled.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        model = analyze(payload, lambda category: [])["models"][0]
        self.assertEqual(model["category"], "diffusion_models")

    def test_llama_cpp_models_use_official_uppercase_llm_folder(self):
        payload = {
            "nodes": [{
                "id": 48,
                "type": "Llama-cpp Model Loader",
                "widgets": [
                    {
                        "name": "llama_model",
                        "value": "Huihui-Qwen3-VL-8B-Instruct-abliterated.Q8_0.gguf",
                        "model_selector": True,
                    },
                    {
                        "name": "mmproj_model",
                        "value": "Huihui-Qwen3-VL-8B-Instruct-abliterated.mmproj-Q8_0.gguf",
                        "model_selector": True,
                    },
                ],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(len(result["models"]), 2)
        self.assertTrue(all(model["category"] == "LLM" for model in result["models"]))

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

    def test_detects_model_in_textencode_cached_node(self):
        payload = {
            "nodes": [{
                "id": 95,
                "type": "WanVideo TextEncode Cached",
                "widgets": [{
                    "name": "模型名",
                    "value": "umt5-xxl-enc-fp8_e4m3fn.safetensors",
                    "model_selector": False,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(result["models"][0]["category"], "text_encoders")

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
        self.assertEqual(result["models"][0]["match"]["name"], "Wan2_1_VAE_bf16.safetensors")

    def test_official_combo_missing_hides_when_registered_path_is_already_exact(self):
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
        self.assertEqual(result["summary"]["unresolved"], 0)
        self.assertEqual(result["models"], [])

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

    def test_official_combo_valid_still_reports_missing_when_file_not_registered(self):
        payload = {
            "nodes": [{
                "id": 400,
                "type": "UNetLoader",
                "widgets": [{
                    "name": "unet_name",
                    "value": "ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
                    "model_selector": True,
                    "model_value_valid": True,
                }],
            }]
        }
        model = analyze(payload, lambda category: [])["models"][0]
        self.assertEqual(model["status"], "missing")
        self.assertEqual(model["category"], "diffusion_models")

    def test_ltx_loader_uses_diffusion_models_folder(self):
        payload = {
            "nodes": [{
                "id": 401,
                "type": "LTX Model Loader",
                "widgets": [{
                    "name": "model",
                    "value": "ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        model = analyze(payload, lambda category: [])["models"][0]
        self.assertEqual(model["category"], "diffusion_models")

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

    def test_exact_official_filename_suppresses_stale_missing_reference(self):
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
        self.assertEqual(result["models"][0]["status"], "adaptable")
        self.assertEqual(result["models"][0]["match"]["name"], "Other/model.safetensors")

    def test_official_flat_model_can_replace_invalid_legacy_prefix(self):
        payload = {
            "nodes": [{
                "id": 90,
                "type": "LoraLoaderModelOnly",
                "widgets": [{
                    "name": "lora_name",
                    "value": "图图黑丝/model.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        result = analyze(
            payload,
            lambda category: ["model.safetensors"] if category == "loras" else [],
        )
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(result["models"][0]["status"], "adaptable")
        self.assertEqual(result["models"][0]["match"]["name"], "model.safetensors")
        self.assertTrue(result["models"][0]["match"]["auto_apply"])

    def test_multi_lora_invalid_paths_are_available_to_one_click_load(self):
        names = [
            "WanAnimate_relight_lora_fp16.safetensors",
            "Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors",
            "FastWan_T2V_14B_480p_lora_rank_128_bf16.safetensors",
        ]
        payload = {
            "nodes": [{
                "id": 40,
                "type": "WanVideo Lora Select Multi",
                "widgets": [
                    {
                        "name": f"lora_{index}",
                        "value": f"万相lora/{name}",
                        "model_selector": True,
                        "model_value_valid": False,
                    }
                    for index, name in enumerate(names)
                ],
            }]
        }
        result = analyze(payload, lambda category: names if category == "loras" else [])
        self.assertEqual(result["summary"]["unresolved"], 3)
        self.assertTrue(all(model["status"] == "adaptable" for model in result["models"]))
        self.assertTrue(all(model["match"]["auto_apply"] for model in result["models"]))

    def test_instantid_model_uses_registered_official_category(self):
        payload = {
            "nodes": [{
                "id": 91,
                "type": "Load InstantID Model",
                "widgets": [{
                    "name": "instantid_file",
                    "value": "ip-adapter.bin",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        model = analyze(payload, lambda category: [])["models"][0]
        self.assertEqual(model["category"], "instantid")
        self.assertEqual(model["name"], "ip-adapter.bin")

    def test_impact_models_use_registered_official_categories(self):
        payload = {
            "nodes": [
                {
                    "id": 169,
                    "type": "检测加载器",
                    "widgets": [{"name": "model_name", "value": "segm/face_yolov8n_v2.pt", "model_selector": True, "model_value_valid": False}],
                },
                {
                    "id": 170,
                    "type": "SAMLoader (Impact)",
                    "widgets": [{"name": "model_name", "value": "sam_vit_b_01ec64.pth", "model_selector": True, "model_value_valid": False}],
                },
            ]
        }
        result = analyze(payload, lambda category: [], ["ultralytics_segm", "sams"])
        categories = {model["name"]: model["category"] for model in result["models"]}
        self.assertEqual(categories["segm/face_yolov8n_v2.pt"], "ultralytics_segm")
        self.assertEqual(categories["sam_vit_b_01ec64.pth"], "sams")

    def test_one_click_load_finds_local_model_even_when_node_category_is_stale(self):
        payload = {
            "nodes": [{
                "id": 169,
                "type": "检测加载器",
                "widgets": [{
                    "name": "model_name",
                    "value": "segm/face_yolov8n_v2.pt",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        installed = {"ultralytics_bbox": ["face_yolov8n_v2.pt"]}
        model = analyze(payload, lambda category: installed.get(category, []), ["ultralytics_bbox", "ultralytics_segm"])["models"][0]
        self.assertEqual(model["status"], "adaptable")
        self.assertEqual(model["match"]["name"], "face_yolov8n_v2.pt")
        self.assertEqual(model["match"]["category"], "ultralytics_bbox")
        self.assertTrue(model["match"]["auto_apply"])

    def test_one_click_load_searches_dynamic_registered_local_categories(self):
        payload = {
            "nodes": [{
                "id": 200,
                "type": "Custom Model Loader",
                "widgets": [{
                    "name": "model_name",
                    "value": "old-prefix/local-model.bin",
                    "model_selector": True,
                    "model_value_valid": False,
                    "directory": "stale_category",
                }],
            }]
        }
        installed = {"plugin_official_models": ["real-folder/local-model.bin"]}
        model = analyze(payload, lambda category: installed.get(category, []), installed.keys())["models"][0]
        self.assertEqual(model["status"], "adaptable")
        self.assertEqual(model["match"]["name"], "real-folder/local-model.bin")
        self.assertEqual(model["match"]["category"], "plugin_official_models")
        self.assertTrue(model["match"]["auto_apply"])

    def test_unicode_lora_official_relative_path_matches_exactly(self):
        name = "Qwen/任务拆解二次元， .safetensors"
        payload = {
            "nodes": [{
                "id": 42,
                "type": "LoraLoaderModelOnly",
                "widgets": [{
                    "name": "lora_name",
                    "value": name.replace("/", "\\"),
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        result = analyze(payload, lambda category: [name] if category == "loras" else [])
        self.assertEqual(result["models"], [])
        self.assertEqual(result["summary"]["installed"], 1)

    def test_unicode_lora_punctuation_variant_is_not_a_local_candidate(self):
        workflow_name = "Qwen/任务拆解二次元， .safetensors"
        installed_name = "Qwen/任务拆解二次元,.safetensors"
        payload = {
            "nodes": [{
                "id": 42,
                "type": "LoraLoaderModelOnly",
                "widgets": [{
                    "name": "lora_name",
                    "value": workflow_name,
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        model = analyze(payload, lambda category: [installed_name] if category == "loras" else [])["models"][0]
        self.assertEqual(model["status"], "missing")
        self.assertIsNone(model["match"])

    def test_exact_filename_match_is_case_insensitive(self):
        payload = {
            "nodes": [{
                "id": 43,
                "type": "LoraLoaderModelOnly",
                "widgets": [{
                    "name": "lora_name",
                    "value": "old/MODEL.SAFETENSORS",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        model = analyze(payload, lambda category: ["new/model.safetensors"] if category == "loras" else [])["models"][0]
        self.assertEqual(model["status"], "adaptable")
        self.assertEqual(model["match"]["name"], "new/model.safetensors")
        self.assertEqual(model["match"]["confidence"], 0.99)

    def test_ignores_inactive_node_models_like_workflow_overview(self):
        payload = {
            "nodes": [{
                "id": 40,
                "type": "CheckpointLoaderSimple",
                "active": False,
                "widgets": [{
                    "name": "ckpt_name",
                    "value": "inactive-missing.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                }],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["models"], [])

    def test_preserves_embedded_download_metadata(self):
        payload = {
            "models": [{
                "name": "downloadable.safetensors",
                "directory": "checkpoints",
                "url": "https://huggingface.co/example/resolve/main/downloadable.safetensors",
                "hash": "abc",
                "hash_type": "sha256",
                "size": 123456,
            }],
            "nodes": [],
        }
        result = analyze(payload, lambda category: [])
        model = result["models"][0]
        self.assertEqual(model["source_url"], payload["models"][0]["url"])
        self.assertEqual(model["source_hash"], "abc")
        self.assertEqual(model["source_hash_type"], "sha256")
        self.assertEqual(model["source_size"], 123456)

    def test_live_widget_verdict_suppresses_serialized_duplicate(self):
        payload = {
            "nodes": [{
                "id": 50,
                "type": "CheckpointLoaderSimple",
                "widgets": [{
                    "name": "ckpt_name",
                    "value": "valid.safetensors",
                    "model_selector": True,
                    "model_value_valid": True,
                }],
                "widgets_values": ["valid.safetensors"],
            }]
        }
        result = analyze(payload, lambda category: ["valid.safetensors"] if category == "checkpoints" else [])
        self.assertEqual(result["models"], [])

    def test_adapted_installed_model_suppresses_stale_missing_metadata(self):
        payload = {
            "models": [{
                "name": "old-folder/model.safetensors",
                "directory": "diffusion_models",
            }],
            "nodes": [{
                "id": 51,
                "type": "WanVideoModelLoader",
                "widgets": [{
                    "name": "model",
                    "value": "new-folder/model.safetensors",
                    "model_selector": True,
                    "model_value_valid": True,
                    "directory": "diffusion_models",
                }],
            }],
        }
        result = analyze(
            payload,
            lambda category: ["new-folder/model.safetensors"] if category == "diffusion_models" else [],
        )
        self.assertEqual(result["summary"]["unresolved"], 0)
        self.assertEqual(result["models"], [])

    def test_supports_official_sft_model_extension(self):
        result = analyze(
            {"models": [{"name": "missing.sft", "directory": "checkpoints"}], "nodes": []},
            lambda category: [],
        )
        self.assertEqual(result["models"][0]["name"], "missing.sft")

    def test_uses_dynamic_official_model_directory(self):
        payload = {
            "models": [{"name": "custom-model.bin", "directory": "audio_encoders"}],
            "nodes": [],
        }
        installed = {"audio_encoders": ["custom-model.bin"]}
        result = analyze(payload, lambda category: installed.get(category, []))
        self.assertEqual(result["models"], [])

    def test_live_widget_preserves_enriched_official_metadata(self):
        payload = {
            "nodes": [{
                "id": 70,
                "type": "CustomLoader",
                "widgets": [{
                    "name": "model",
                    "value": "missing.safetensors",
                    "model_selector": True,
                    "model_value_valid": False,
                    "directory": "audio_encoders",
                    "source_url": "https://huggingface.co/example/resolve/main/missing.safetensors",
                    "source_hash": "abc",
                    "source_hash_type": "sha256",
                }],
                "widgets_values": ["missing.safetensors"],
            }]
        }
        model = analyze(payload, lambda category: [])["models"][0]
        self.assertEqual(model["category"], "audio_encoders")
        self.assertEqual(model["source_url"], payload["nodes"][0]["widgets"][0]["source_url"])

    def test_detects_all_missing_models_from_multi_lora_selector(self):
        names = [
            "万相lora/WanAnimate_relight_lora_fp16.safetensors",
            "万相lora/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors",
            "万相lora/FastWan_T2V_14B_480p_lora_rank128_bf16.safetensors",
            "万相lora/Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors",
            "万相lora/Wan2.2-Fun-A14B-InP-low-noise-HPS2.1.safetensors",
        ]
        payload = {
            "nodes": [{
                "id": 80,
                "type": "WanVideo Lora Select Multi",
                "widgets": [
                    {
                        "name": f"lora_{index}",
                        "value": name,
                        "model_selector": True,
                        "model_value_valid": False,
                    }
                    for index, name in enumerate(names)
                ],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["unresolved"], 5)
        self.assertEqual({model["name"] for model in result["models"]}, set(names))
        self.assertTrue(all(model["category"] == "loras" for model in result["models"]))

    def test_detects_multi_lora_widgets_without_frontend_selector_metadata(self):
        names = [
            "万相lora/WanAnimate_relight_lora_fp16.safetensors",
            "万相lora/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors",
            "万相lora/FastWan_T2V_14B_480p_lora_rank128_bf16.safetensors",
            "万相lora/Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors",
            "万相lora/Wan2.2-Fun-A14B-InP-low-noise-HPS2.1.safetensors",
        ]
        payload = {
            "nodes": [{
                "id": 81,
                "type": "WanVideo Lora Select Multi",
                "widgets": [
                    {"name": f"lora_{index}", "value": name, "model_selector": False}
                    for index, name in enumerate(names)
                ],
            }]
        }
        result = analyze(payload, lambda category: [])
        self.assertEqual(result["summary"]["unresolved"], 5)
        self.assertEqual({model["name"] for model in result["models"]}, set(names))


if __name__ == "__main__":
    unittest.main()
