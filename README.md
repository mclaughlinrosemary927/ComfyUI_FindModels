# ComfyUI_FindModels

Current version: `1.26.8`

`ComfyUI_FindModels` scans the workflow currently open in ComfyUI, identifies model
references that are missing locally, suggests compatible installed models, and finds
candidate direct-download URLs from Civitai and Hugging Face.

## Features

- Scans explicit model-selector widgets on the live workflow after a workflow opens.
- Scans live widget values, nested custom-widget values, and serialized widget values used by dynamic custom loaders.
- Mirrors ComfyUI's workflow overview by scanning embedded model metadata and treating invalid official model-selector values as missing.
- Detects model selectors by their model-file option lists, including custom multi-LoRA widgets whose type is not `combo`.
- Ignores bypassed/disabled nodes, prioritizes live combo and asset widgets, preserves official model URLs and groups all referencing nodes.
- Recognizes checkpoints, LoRAs, VAEs, ControlNet, text encoders, diffusion models,
  embeddings, and upscale models.
- Uses ComfyUI's configured model paths, including paths from `extra_model_paths.yaml`.
- Distinguishes installed, adaptable, and missing model references.
- Shows only unresolved models. Installed models and successfully loaded models disappear
  from the panel after the next scan.
- Verifies Chinese-named and other custom model-selector values against files registered
  on disk instead of assuming a stale dropdown value is installed.
- Applies only high-confidence local replacements with one click.
- Finds candidate direct-download URLs without automatically downloading unverified files.
- Adds **查找模型** to the ComfyUI top run bar, with a legacy run-bar fallback.
- Downloads selected Civitai, Hugging Face, or public Quark-share candidates into the matching configured
  ComfyUI model folder.
- Shows candidate file sizes and loads successfully downloaded files into their workflow nodes.
- Shows live downloaded bytes, total size, and percentage while a model download is running.
- Supports pausing, resuming with HTTP range requests, retrying, and cancelling model downloads.
- Keeps downloads running when the panel closes and restores active download progress when it is reopened or the page reloads.
- Searches the configured Quark Netdisk libraries directly for missing model filenames.
- Ignores serialized workflow metadata, URLs, free-text fields, and generic `model`
  fields on non-loader custom nodes to prevent false missing-model reports.
- Detects node types missing from ComfyUI's live node registry and matches them against
  workflow package metadata plus ComfyUI-Manager's official node map.
- Makes every missing-node card clickable and provides retry plus GitHub search actions.
- Excludes node types already registered by frontend-only LiteGraph extensions to avoid false missing-node reports.
- Separates missing models, missing nodes, downloads, and settings into dedicated overview-style tabs and can locate referencing nodes on the canvas.
- Can install missing-node plugins from verified mappings or an explicitly entered GitHub repository URL.
- Installs or updates only GitHub repositories selected by the user. Before installation it checks
  duplicate repositories, performs a dependency dry run, blocks core runtime dependency
  changes, and runs `pip check`.
- Can search a user-configured external model library for exact missing filenames and,
  after explicit confirmation, move them into the matching registered ComfyUI model folder.
- Opens the native Windows folder selector when choosing an external model library.
- Shows the missing model size when workflow metadata, a verified source, or an exact external-library match provides it.
- Never overwrites an existing model file.

## Installation

Clone this repository into `ComfyUI/custom_nodes`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/mclaughlinrosemary927/ComfyUI_FindModels.git
```

Restart ComfyUI. A persistent **查找模型** button appears after the active-task control
and before the property-panel toggle. The panel stays closed during startup and mounts
inside ComfyUI's native resizable right-side panel when opened.

No extra Python packages are required.

## GitHub Sync

Use these commands on another computer for first-time setup:

```powershell
cd path\to\ComfyUI\custom_nodes
git clone https://github.com/mclaughlinrosemary927/ComfyUI_FindModels.git
cd ComfyUI_FindModels
```

Daily pull from GitHub:

```powershell
.\scripts\pull.bat
```

Daily upload to GitHub:

```powershell
.\scripts\push.bat
```

You can also pass a custom commit message:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\push.ps1 "Fix model detection"
```

The upload script runs the Python tests, checks `web/find_models.js`, stages all tracked
and untracked project files, commits, and pushes. The pull script refuses to pull when
there are local uncommitted changes, so work on another computer is not overwritten.

Local runtime files such as `models/`, `external_model_folder.json`, `quark_auth.json`,
`__pycache__/`, and `.pytest_cache/` are intentionally ignored and are not uploaded.

When continuing this project in a fresh Codex conversation on another computer, read
`AGENTS.md` first, then `PROJECT_CONTEXT.md`. GitHub cannot restore previous chat
history, but these files preserve the project rules, current state, and next steps.

## Usage

1. Open or drag a workflow into ComfyUI.
2. The extension scans automatically. You can also click **查找模型** in the top bar.
3. Review local replacement suggestions.
4. Click **一键加载模型** to load safe high-confidence local matches into their nodes, or apply an
   individual suggestion.
5. For missing models, click **查找下载来源**. You can download a Civitai or Hugging
   Face candidate or a public match from the two configured Quark Netdisk model libraries
   directly into its matching configured model folder.
6. Missing nodes use workflow metadata and ComfyUI-Manager's official mapping. Review the
   repository before installing, or enter a custom GitHub repository URL, then restart ComfyUI.

The download results are search candidates. Verify the model page, license, base model,
and filename before downloading. Some Civitai files require authentication, so their
direct URL may redirect to a sign-in page.

Only sources whose filename exactly matches the missing workflow filename are shown.
Matching Quark files are shown as download buttons instead of fallback search links.
The download endpoint rejects unknown model categories rather than placing files in an
incorrect folder.

Downloads are accepted only from approved Civitai and Hugging Face HTTPS hosts. Existing
files are never overwritten. Completed downloads clear ComfyUI's model filename cache so
the model appears in the matching node selector. Quark downloads use its public share API;
an optional login Cookie can be stored locally for files that require authentication. Quark
may still refuse restricted files, in which case the extension tries a verified exact-name source.

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
Quark shares only when you explicitly click **下载缺失模型**. Regular scans remain local.
Missing node names are sent to ComfyUI-Manager's official node map when finding verified
plugin candidates. An optional Quark Cookie is stored only in the local ignored configuration file.

## License

MIT
