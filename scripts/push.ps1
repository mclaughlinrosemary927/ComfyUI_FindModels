param(
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

Write-Host "[ComfyUI_FindModels] Running tests..."
python -m unittest discover -s tests

Write-Host "[ComfyUI_FindModels] Checking frontend syntax..."
node --check web\find_models.js

Write-Host "[ComfyUI_FindModels] Checking Python syntax..."
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').glob('*.py')]"

Write-Host "[ComfyUI_FindModels] Checking whitespace..."
git diff --check

$status = git status --porcelain
if (-not $status) {
    Write-Host "[ComfyUI_FindModels] No local changes to upload."
    git push origin HEAD
    exit 0
}

if (-not $Message.Trim()) {
    $Message = "Update ComfyUI_FindModels $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

Write-Host "[ComfyUI_FindModels] Staging changes..."
git add -A

Write-Host "[ComfyUI_FindModels] Creating commit: $Message"
git commit -m $Message

Write-Host "[ComfyUI_FindModels] Pushing to GitHub..."
git push origin HEAD

Write-Host "[ComfyUI_FindModels] Upload complete."
