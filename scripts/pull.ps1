$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

$status = git status --porcelain
if ($status) {
    Write-Host "[ComfyUI_FindModels] Local changes detected. Commit or stash them before pulling." -ForegroundColor Yellow
    git status --short
    exit 1
}

Write-Host "[ComfyUI_FindModels] Fetching latest code..."
git fetch origin

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Host "[ComfyUI_FindModels] Pulling origin/$branch..."
git pull --ff-only origin $branch

Write-Host "[ComfyUI_FindModels] Pull complete."
