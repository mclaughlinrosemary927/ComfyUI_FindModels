$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

$required = @(
    "AGENTS.md",
    "PROJECT_CONTEXT.md",
    "PROJECT_CONVERSATION_SUMMARY.md",
    "CODEX_START_HERE.md"
)

foreach ($file in $required) {
    if (-not (Test-Path $file)) {
        throw "Missing required context file: $file"
    }
}

$prompt = @"
请接手这个 ComfyUI_FindModels 项目。

开始前请按顺序读取以下文件：

1. AGENTS.md
2. PROJECT_CONTEXT.md
3. PROJECT_CONVERSATION_SUMMARY.md

读取后请执行：

git status --short --branch

然后基于这些文件恢复项目上下文。重点遵守：

- GitHub 不能还原 Codex 旧对话界面，只能通过项目文件恢复上下文。
- 模型识别必须对齐 ComfyUI 内置“工作流总览”。
- 只显示未解决的缺失模型和缺失节点。
- 已加载成功或已在官方目录中的模型必须马上从缺失列表移除。
- 模型必须按 ComfyUI 官方注册目录存放，不能根据节点文本路径乱建目录。
- 外部模型库必须递归精确匹配文件名。
- Quark 下载失败不能伪造成成功，要说明真实原因并查找其他可验证直链。

如果我要求继续修复，请先读相关测试，再读实现文件，修复后运行验证命令。
"@

Set-Clipboard -Value $prompt

Write-Host "[ComfyUI_FindModels] Codex handoff prompt copied to clipboard."
Write-Host "[ComfyUI_FindModels] On the new computer, open a new Codex thread for this repository and paste the prompt."
Write-Host ""
Write-Host "Important limitation:"
Write-Host "  GitHub cannot import old Codex chat bubbles into the conversation UI."
Write-Host "  The repository restores project context through Markdown files instead."
