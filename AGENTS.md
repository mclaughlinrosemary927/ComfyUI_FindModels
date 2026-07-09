# AGENTS.md

本文件给后续 Codex / 开发者使用。新会话处理本项目时，必须先读本文件，再读 `PROJECT_CONTEXT.md` 和 `PROJECT_CONVERSATION_SUMMARY.md`。

## 重要现实限制

GitHub 只能同步项目文件，不能让另一台电脑的 Codex / ChatGPT 界面直接显示本机旧对话记录。
本项目采用可迁移上下文方案：把关键对话、决策、版本状态、用户偏好和开发规则写入仓库文件。新电脑拉取仓库后，Codex 读取这些文件即可继续开发，但不会在界面中还原旧聊天气泡。

必须读取的上下文文件：

- `AGENTS.md`：开发约定和项目规则。
- `PROJECT_CONTEXT.md`：当前版本、已完成功能、验证方法、GitHub 使用方法。
- `PROJECT_CONVERSATION_SUMMARY.md`：历史对话和需求演进摘要，用来恢复项目语境。

## 工作约定

- 修改 JavaScript 文件后必须运行 `npm test`；如果项目当前没有 npm 测试脚本，至少运行 `node --check web/find_models.js` 并说明原因。
- 安装依赖时优先用 `pnpm`。
- 添加新的生产依赖前先询问确认。
- 用户明确要求“上传 GitHub”“提交”“打标签”时，才执行 commit / push / tag。
- 不要删除用户本地模型、Cookie、账号登录态、运行时配置和下载中的文件。
- 不要伪造 Quark 或其他下载源成功；失败必须说明真实原因。

## 项目定位

`ComfyUI_FindModels` 是一个 ComfyUI custom node / frontend extension，用于扫描当前打开的工作流，识别缺失模型和缺失节点，并提供：

- 本地已安装模型识别。
- 外部模型库精确匹配和剪切到官方模型目录。
- 下载来源查找。
- 下载任务进度、暂停、继续、取消、重试。
- 缺失节点 GitHub 安装和可选 requirements 依赖安装。

核心目标是尽量复刻 ComfyUI 内置“工作流总览”的依赖识别结果，并且只显示尚未解决的缺失项。

## 模型识别硬规则

1. 只把 ComfyUI 官方注册目录中的文件视为 installed。
   - 目录必须来自 `folder_paths` 或插件注册的模型目录。
   - 不要根据节点文本里的路径前缀自行创造目标目录。

2. 文件名完全一致才可以作为可自动加载或迁移候选。
   - 大小写可以忽略。
   - 不接受 99% 以下的模糊匹配作为自动操作依据。
   - 模糊结果最多只能作为手动搜索线索。

3. 节点值里的前缀不是官方路径。
   - 例如 `Wan/...`、`Qwen/...`、`FLUX/...`、中文目录名、旧目录名前缀，只是工作流保存值。
   - 保存和迁移目标必须由 ComfyUI 注册目录和模型分类决定。

4. 已能被节点加载且本地存在同名文件的模型，不得继续显示为缺失。
   - 前端确认 widget 当前值在候选列表中，且后端索引中存在同名文件时，应立即从缺失列表移除。
   - 这条规则用于解决“刚加载成功，过一会又跳回缺失列表”的问题。

5. 外部模型库优先精确搜索。
   - 扫描外部文件夹时必须递归多层目录。
   - 找到完全同名文件后，根据官方分类剪切到对应模型目录。
   - 如果无法确认官方分类，不能自动剪切，应提示原因。

6. 只显示未解决依赖。
   - 已安装、已加载、已从外部剪切、已下载完成的模型和节点必须尽快刷新并移出列表。
   - 列表中不得混入正常模型或已解决模型。

## 高风险识别场景

这些类型经常出现漏报或误报，修改识别逻辑时必须重点回归：

- LTX / UNet / diffusion_models。
- WanVideo / FantasyTalking / InfiniteTalk。
- GGUF / LLM / CLIPLoader(GGUF) / mmproj。
- text_encoders / CLIP。
- rgthree 权重 LoRA、多 LoRA、嵌套数组 widget。
- SAM / YOLO / Impact / SEGM。
- InstantID / IPAdapter。
- 同一个工作流中同名模型被多个节点引用。
- 节点能正常加载，但保存值带额外路径前缀。

## 缺失节点规则

- 缺失节点和缺失模型必须分栏显示，不能混在一起。
- 优先读取工作流中的 `aux_id`、包名、节点名和作者信息。
- 可以从可信 GitHub 映射、用户手动 GitHub 链接或可验证搜索结果安装。
- “自动安装插件依赖 requirements.txt”开关打开时才安装依赖。
- 安装依赖前必须保护核心环境包，例如 `torch`、`torchvision`、`torchaudio`、`xformers`、`triton`、`onnxruntime`、`onnxruntime-gpu`。

## Quark 和下载规则

固定 Quark 分享链接：

- `https://pan.quark.cn/s/fb913d649b18`
- `https://pan.quark.cn/s/4680ac866516`

要求：

- 递归检索到最后一层。
- 只接受文件名完全一致的下载候选。
- 下载目标必须是官方模型目录。
- 不覆盖已有模型文件。
- Quark 可能因 token、登录态、权限、风控或限速拒绝直链。遇到这种情况必须提示真实失败原因，并继续查找 Hugging Face / Civitai 等可验证同名直链。

## 一键同步脚本

本项目提供一键上传和一键拉取脚本：

上传到 GitHub：

```powershell
.\scripts\push.bat
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\push.ps1 "Update project"
```

从 GitHub 拉取：

```powershell
.\scripts\pull.bat
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pull.ps1
```

新电脑首次使用：

```powershell
git clone https://github.com/mclaughlinrosemary927/ComfyUI_FindModels.git
cd ComfyUI_FindModels
.\scripts\setup-dev.bat
```

## 验证命令

从仓库根目录执行：

```powershell
python -m unittest discover -s tests
node --check web\find_models.js
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').glob('*.py')]; print('python syntax ok')"
git diff --check
git status --short --branch --untracked-files=all
```

如果修改了前端 JS/CSS，提醒用户重启 ComfyUI 并在浏览器中 `Ctrl+F5`。

## 运行目录同步

用户经常在实际 ComfyUI 环境中测试。需要同步到运行目录时，目标通常是：

```text
\\192.168.0.44\E\Program Files\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_FindModels
```

只同步运行需要的文件，例如：

- `find_models.py`
- `model_finder.py`
- `node_installer.py`
- `__init__.py`
- `pyproject.toml`
- `web/find_models.js`
- `web/find_models.css`

不要同步 `.git/`、`tests/`、`__pycache__/`、本地配置、Cookie、账号文件或用户模型文件。

## 代码清理边界

可以删除：

- 明确未引用、未测试、不是路由入口、不是动态注册入口的代码。
- 缓存目录、测试残留、无用临时文件。

不要删除：

- `@PromptServer.instance.routes.*` 装饰的路由函数。
- 前端事件回调、动态注册、异步下载任务和安装任务相关函数。
- 被测试直接导入的 helper。
- 为 ComfyUI / 第三方插件兼容保留的分类别名和规则。

不确定时先补测试，再删。

## Git 和发布

- 文档或脚本更新可以普通 commit，不需要打版本标签。
- 发布版本时更新：
  - `pyproject.toml`
  - `README.md`
  - `PROJECT_CONTEXT.md`
  - 必要时更新 `PROJECT_HANDOFF.md`
- tag 格式：`vX.Y.Z`
