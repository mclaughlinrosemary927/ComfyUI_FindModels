$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

$required = @(
    "AGENTS.md",
    "PROJECT_CONTEXT.md",
    "CONVERSATION_CONTEXT.md",
    "PROJECT_CONVERSATION_SUMMARY.md",
    "CODEX_START_HERE.md"
)

foreach ($file in $required) {
    if (-not (Test-Path $file)) {
        throw "Missing required context file: $file"
    }
}

$startHerePath = Join-Path $repo "CODEX_START_HERE.md"
$startHere = [System.IO.File]::ReadAllText($startHerePath, [System.Text.Encoding]::UTF8)
$match = [regex]::Match($startHere, '(?s)```text\s*(.*?)\s*```')
if (-not $match.Success) {
    throw "Could not find the handoff prompt in CODEX_START_HERE.md"
}
$prompt = $match.Groups[1].Value.Trim()

Set-Clipboard -Value $prompt

Write-Host "[ComfyUI_FindModels] Codex handoff prompt copied to clipboard."
Write-Host "[ComfyUI_FindModels] On the new computer, open a new Codex thread for this repository and paste the prompt."
Write-Host ""
Write-Host "Important limitation:"
Write-Host "  GitHub cannot import old Codex chat bubbles into the conversation UI."
Write-Host "  The repository restores project context through Markdown files instead."
