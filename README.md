# ComfyUI_FindModels

`ComfyUI_FindModels` scans the workflow currently open in ComfyUI, identifies model
references that are missing locally, suggests compatible installed models, and finds
candidate direct-download URLs from Civitai and Hugging Face.

## Features

- Scans explicit model-selector widgets on the live workflow after a workflow opens.
- Recognizes checkpoints, LoRAs, VAEs, ControlNet, text encoders, diffusion models,
  embeddings, and upscale models.
- Uses ComfyUI's configured model paths, including paths from `extra_model_paths.yaml`.
- Distinguishes installed, adaptable, and missing model references.
- Shows only unresolved models. Installed models and successfully loaded models disappear
  from the panel after the next scan.
- Treats a current dropdown value as installed when ComfyUI still lists it, including
  Chinese-named and other custom model selectors.
- Applies only high-confidence local replacements with one click.
- Finds candidate direct-download URLs without automatically downloading unverified files.
- Adds **查找模型** to the ComfyUI top run bar, with a legacy run-bar fallback.
- Downloads selected Civitai, Hugging Face, or public Quark-share candidates into the matching configured
  ComfyUI model folder.
- Shows candidate file sizes and loads successfully downloaded files into their workflow nodes.
- Searches the configured Quark Netdisk libraries directly for missing model filenames.
- Audits existing model locations and reports only files whose expected official folder
  can be determined clearly. The audit never moves files.
- Leaves ambiguous checkpoint/diffusion model files in place instead of guessing their
  architecture from names such as `flux`, `wan`, or `z_image`.
- Ignores serialized workflow metadata, URLs, free-text fields, and generic `model`
  fields on non-loader custom nodes to prevent false missing-model reports.
- Does not move, delete, or overwrite model files.

## Installation

Clone this repository into `ComfyUI/custom_nodes`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/YOUR_NAME/ComfyUI_FindModels.git
```

Restart ComfyUI. A persistent **查找模型** button appears beside the Queue/Run
controls in the top toolbar. Hover over it to see the latest missing-model count.
The button is placed immediately before **显示图像流** when that control is available.
The panel stays closed during startup and workflow loading; open it from the toolbar.

No extra Python packages are required.

## Usage

1. Open or drag a workflow into ComfyUI.
2. The extension scans automatically. You can also click **查找模型** in the top bar.
3. Review local replacement suggestions.
4. Click **一键加载模型** to load safe high-confidence local matches into their nodes, or apply an
   individual suggestion.
5. For missing models, click **查找下载来源**. You can download a Civitai or Hugging
   Face candidate or a public match from the two configured Quark Netdisk model libraries
   directly into its matching configured model folder.

The download results are search candidates. Verify the model page, license, base model,
and filename before downloading. Some Civitai files require authentication, so their
direct URL may redirect to a sign-in page.

Only sources whose filename exactly matches the missing workflow filename and whose
download endpoint is currently usable are shown. Similar filenames and restricted Quark
files are excluded.

Downloads are accepted only from approved Civitai and Hugging Face HTTPS hosts. Existing
files are never overwritten. Completed downloads clear ComfyUI's model filename cache so
the model appears in the matching node selector. Quark downloads use its public share API
without reading account cookies. Quark may refuse direct downloads for large or restricted
files; the extension reports that restriction and does not bypass it.

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

Workflow model filenames are sent to Civitai, Hugging Face, and the two configured public
Quark shares only when you explicitly click **查找下载来源**. Regular scans remain local.

## License

MIT
