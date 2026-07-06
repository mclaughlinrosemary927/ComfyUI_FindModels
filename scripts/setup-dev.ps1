$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

function Test-Command {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        Write-Host "[OK] $Name -> $($command.Source)"
        return $true
    }
    Write-Host "[MISSING] $Name is not available in PATH" -ForegroundColor Yellow
    return $false
}

Write-Host "ComfyUI_FindModels development environment check"
Write-Host "Repository: $repo"
Write-Host ""

$ok = $true
$ok = (Test-Command "git") -and $ok
$ok = (Test-Command "python") -and $ok
$nodeOk = Test-Command "node"

Write-Host ""
Write-Host "Git status:"
git status --short --branch

Write-Host ""
Write-Host "Python version:"
python --version

if ($nodeOk) {
    Write-Host ""
    Write-Host "Node version:"
    node --version
} else {
    Write-Host ""
    Write-Host "Node.js is optional for running the ComfyUI plugin, but required for 'node --check web\\find_models.js'." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Running Python tests..."
python -m unittest discover -s tests

if ($nodeOk) {
    Write-Host ""
    Write-Host "Checking frontend syntax..."
    node --check web\find_models.js
}

Write-Host ""
Write-Host "Checking Python syntax..."
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in map(pathlib.Path, ['model_finder.py','find_models.py','node_installer.py','__init__.py'])]; print('python syntax ok')"

Write-Host ""
Write-Host "Checking whitespace..."
git diff --check

if (-not $ok) {
    Write-Host ""
    Write-Host "Required tools are missing. Install Git and Python, then run this script again." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Development environment check complete."
Write-Host "Next steps:"
Write-Host "  1. Restart ComfyUI after changing Python or frontend files."
Write-Host "  2. Press Ctrl+F5 in the browser after changing web/find_models.js."
Write-Host "  3. Use scripts\\pull.bat before editing on another computer."
Write-Host "  4. Use scripts\\push.bat after testing your changes."
