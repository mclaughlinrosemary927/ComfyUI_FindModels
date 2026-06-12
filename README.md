# ComfyUI_FindModels

`ComfyUI_FindModels` scans the workflow currently open in ComfyUI, identifies model
references that are missing locally, suggests compatible installed models, and finds
candidate direct-download URLs from Civitai and Hugging Face.

## Features

- Scans model widgets and serialized workflow data automatically after a workflow opens.
- Recognizes checkpoints, LoRAs, VAEs, ControlNet, text encoders, diffusion models,
  embeddings, and upscale models.
- Uses ComfyUI's configured model paths, including paths from `extra_model_paths.yaml`.
- Distinguishes installed, adaptable, and missing model references.
- Applies only high-confidence local replacements with one click.
- Finds candidate direct-download URLs without automatically downloading unverified files.
- Does not move, delete, or overwrite model files.

## Installation

Clone this repository into `ComfyUI/custom_nodes`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/YOUR_NAME/ComfyUI_FindModels.git
```

Restart ComfyUI. A **Find Models** button appears in the lower-right corner.

No extra Python packages are required.

## Usage

1. Open or drag a workflow into ComfyUI.
2. The extension scans automatically. You can also click **Find Models**.
3. Review local replacement suggestions.
4. Click **一键加载模型** to load safe high-confidence local matches into their nodes, or apply an
   individual suggestion.
5. For missing models, click **查找下载直链** and review the provider, filename,
   and confidence before downloading.

The download results are search candidates. Verify the model page, license, base model,
and filename before downloading. Some Civitai files require authentication, so their
direct URL may redirect to a sign-in page.

## Matching Rules

- Exact configured path: installed.
- Exact filename in a different configured subdirectory: adaptable, because the node value
  must be updated to the configured relative path.
- Same normalized filename after removing common precision/version suffixes: installed.
- Similar filename: shown as an adaptable or missing candidate depending on confidence.
- Automatic application is limited to local matches with confidence of at least `0.86`.

## Development

Run the core tests from the repository root:

```bash
python -m unittest discover -s tests -v
```

## Privacy

Workflow model filenames are sent to Civitai and Hugging Face only when you explicitly
click **查找下载直链**. Regular scans remain local.

## License

MIT
