# PROJECT_CONTEXT.md

本文件用于让新电脑或新会话中的 Codex 快速接上 `ComfyUI_FindModels` 项目上下文。GitHub 不能同步旧对话界面，但可以同步这些上下文文件。

## 当前项目状态

- 项目名：`ComfyUI_FindModels`
- GitHub：`https://github.com/mclaughlinrosemary927/ComfyUI_FindModels`
- 当前主分支：`main`
- 最近发布标签：`v1.26.9`
- 主要用途：扫描当前 ComfyUI 工作流，识别缺失模型和缺失节点，只显示尚未解决的依赖，并辅助加载、迁移、下载和安装。

## 已完成的主要功能

- 顶部工具栏按钮：`查找模型`。
- 右侧面板标题：`查找缺失模型和节点`。
- 四个独立页面：
  - 缺失模型
  - 缺失节点
  - 下载任务
  - 设置
- 对齐 ComfyUI 内置“工作流总览”的依赖识别思路。
- 自动扫描当前工作流。
- 只显示未解决依赖。
- 支持本地模型候选、外部模型库候选、下载源候选。
- 支持模型名称复制按钮。
- 支持下载任务进度、速度、已下载大小、剩余时间、暂停、继续、取消和重试。
- 支持缺失节点 GitHub 安装。
- 支持依赖安装开关，避免默认破坏 ComfyUI Python 环境。
- 支持 Quark 分享目录递归查找。
- 支持一键上传和一键拉取脚本。

## 近期重点修复

- 修复 LTX / UNet / diffusion_models 模型识别漏报。
- 修复 GGUF / LLM / CLIPLoader(GGUF) 相关模型加载后仍显示缺失。
- 修复 rgthree 权重 LoRA、多 LoRA、嵌套 widget 读取不完整。
- 修复同一工作流中同名模型被多个节点引用时只处理一处的问题。
- 修复“加载本地模型”后短时间消失又重新出现的问题。
- 修复前端读取模型值时只读普通字符串 widget，遗漏数组和对象结构的问题。
- 修复后端过度依赖通用分类，未优先使用节点真实 `INPUT_TYPES` / ComfyUI 注册目录的问题。
- 修复项目文档乱码问题，重新整理 `AGENTS.md` 和本上下文文件。

## 用户偏好

- 用户希望直接解决问题，不希望只给方案。
- 模型识别必须精准，不能靠模糊匹配冒充成功。
- 已解决的模型和节点必须马上从缺失列表移除。
- 模型必须按 ComfyUI 官方注册目录存放，不允许按节点文本路径乱建目录。
- 外部模型库必须优先递归精确查找。
- Quark 能用则用，但不能伪造直链成功。
- 本项目使用 GitHub Pull Request 工作流。修改后如果用户要求上传 GitHub，默认新建 `codex/...` 分支、提交、推送分支并创建 PR；不直接推送到 `main`，除非用户明确要求。

## 新电脑恢复开发流程

首次克隆：

```powershell
git clone https://github.com/mclaughlinrosemary927/ComfyUI_FindModels.git
cd ComfyUI_FindModels
.\scripts\setup-dev.bat
.\scripts\codex-context.bat
```

Codex 内的正确流程：

1. `git clone` 项目。
2. 在 Codex 添加这个项目。
3. 项目下面如果显示“暂无对话”，手动新建一条对话。
4. 第一条消息发送：`继续这个项目。先读取 AGENTS.md、PROJECT_CONTEXT.md、CONVERSATION_CONTEXT.md 和当前源码，理解项目背景、历史问题、用户偏好和安全规则，然后检查 git 状态。`

`codex-context.bat` 会把这条新会话接续提示复制到剪贴板。

限制说明：GitHub 不能把旧 Codex 对话气泡导入另一台电脑的 UI，也不能让项目列表自动显示旧聊天。当前可靠做法是同步上下文文件，并用 `CODEX_START_HERE.md` / `codex-context.bat` 让新会话接上项目。

继续开发前：

```powershell
.\scripts\pull.bat
```

上传修改：

```powershell
.\scripts\push.bat
```

带提交信息上传：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\push.ps1 "Fix model detection"
```

注意：项目当前协作方式是 GitHub Pull Request。上传 GitHub 时优先走分支 + PR，不直接推送到 `main`；旧的一键上传脚本只在用户明确要求直接推送时使用。

## 新会话接续步骤

1. 读取 `AGENTS.md`。
2. 读取 `PROJECT_CONTEXT.md`。
3. 读取 `CONVERSATION_CONTEXT.md`。
4. 读取当前源码和测试；需要更完整历史时继续读取 `PROJECT_CONVERSATION_SUMMARY.md`。
5. 执行 `git status --short --branch`。
6. 如果用户继续修 bug，先读相关测试，再读实现文件。
7. 修改后运行验证命令。
8. 只有用户明确要求上传时，才 commit / push / 创建 PR。
9. 上传 GitHub 默认走 Pull Request：创建 `codex/...` 分支、提交、推送分支、创建 PR；不直接推送到 `main`，除非用户明确要求。

## 验证命令

```powershell
python -m unittest discover -s tests
node --check web\find_models.js
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').glob('*.py')]; print('python syntax ok')"
git diff --check
git status --short --branch --untracked-files=all
```

## 下一步开发方向

- 继续对齐 ComfyUI “工作流总览”的识别结果。
- 为用户截图中出现过的真实工作流持续补回归测试。
- 强化模型分类解析，避免 LoRA / diffusion_models / text_encoders 互相误判。
- 强化外部模型库索引，提升首屏识别速度。
- 继续优化 Quark 失败后的备用下载源排序和错误提示。
