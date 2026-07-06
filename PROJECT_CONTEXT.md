# PROJECT_CONTEXT.md

本文件用于让新电脑或新会话中的 Codex 快速接上 `ComfyUI_FindModels` 项目上下文。GitHub 不能同步旧对话记录，但可以通过 `AGENTS.md` + 本文件恢复项目状态和开发约束。

## 当前项目状态

- 项目名：`ComfyUI_FindModels`
- 当前版本：`1.26.8`
- 当前分支：`main`
- GitHub：`https://github.com/mclaughlinrosemary927/ComfyUI_FindModels`
- 远程仓库：`origin`
- 主要用途：扫描当前 ComfyUI 工作流，识别缺失模型和缺失节点，只显示未解决依赖，并提供本地加载、外部模型库迁移、下载来源、节点安装能力。

## 已完成的功能

- 顶部工具栏按钮：`查找模型`，打开右侧面板。
- 四个独立页面：
  - 缺失模型
  - 缺失节点
  - 下载任务
  - 设置
- 自动扫描当前工作流，并尽量对齐 ComfyUI 内置“工作流总览”的识别结果。
- 识别模型类型：
  - checkpoints
  - loras
  - vae
  - controlnet
  - clip_vision
  - text_encoders / clip 兼容路径
  - diffusion_models / unet 兼容路径
  - embeddings
  - upscale_models
  - LLM / GGUF / mmproj
  - SAM / YOLO / InstantID / IPAdapter 等插件注册目录
- 支持动态和嵌套 widget：
  - multi-LoRA
  - rgthree 权重 LoRA
  - CLIPLoader (GGUF)
  - LTX / WanVideo / FantasyTalking / InfiniteTalk 相关加载器
- 本地模型候选：只接受文件名完全一致的候选，大小写可忽略。
- 已能被节点加载且本地确有同名文件的模型，会从缺失列表移除。
- 外部模型库：
  - 支持用户选择任意外部文件夹。
  - 支持多层递归搜索。
  - 找到完全同名文件后，可迁移到 ComfyUI 注册的目标模型目录。
- 下载任务：
  - 显示下载进度、速度、耗时、剩余时间。
  - 支持暂停、继续、取消、重试。
  - 面板关闭后下载任务继续运行。
- Quark：
  - 固定两个分享库：
    - `https://pan.quark.cn/s/fb913d649b18`
    - `https://pan.quark.cn/s/4680ac866516`
  - 支持递归查找分享目录。
  - 注意：Quark 直链可能因 token、登录态、权限或限速失败，不能承诺一定成功。
- 缺失节点：
  - 读取工作流 `aux_id` / 包信息。
  - 可通过可信 GitHub 映射或用户输入 GitHub 链接安装。
  - 支持依赖安装开关。
  - 安装前保护核心 Python 依赖，避免破坏 ComfyUI 环境。
- 一键 GitHub 同步脚本：
  - `scripts/push.bat`
  - `scripts/push.ps1`
  - `scripts/pull.bat`
  - `scripts/pull.ps1`

## 近期重点修复

- 修复 `CLIPLoader (GGUF)` / `Z-Image-Engineer-V6-Q8_0.gguf` 加载后仍显示缺失的问题。
- 修复 rgthree 权重 LoRA / 多 LoRA 嵌套控件只识别部分模型或加载后槽位消失的问题。
- 修复 LTX / UNet 类模型没有按正确目录识别的问题。
- 修复模型已经能被节点加载后仍然反复回到缺失列表的问题。
- 修复前端只读取普通字符串 widget，无法读取数组/对象中的模型值的问题。
- 修复后端过度依赖通用分类，未优先读取节点真实 `INPUT_TYPES` 注册目录的问题。
- 修复项目同步脚本缺失问题，已加入一键上传/拉取方法。
- 修复旧 `AGENTS.md` 中文乱码问题，本次已重写为可读中文。

## 用户偏好的交互规则

- 用户希望直接解决问题，不要只给建议。
- 遇到模型漏识别、误报、加载后又出现的问题，要优先检查根因并补回归测试。
- 不要为了“看起来少报错”隐藏真实缺失模型。
- 不要为了“识别更多”扩大自由文本扫描范围，避免大量误报。
- 修改前端 JS 后，必须提醒用户重启 ComfyUI 并 `Ctrl+F5`。
- 用户经常要求上传 GitHub；只有明确要求上传时才 push。
- 用户重点关注：
  - 精准识别缺失模型
  - 加载后立即从缺失列表消失
  - 按官方模型目录存放
  - 不要乱加路径前缀
  - 外部模型库优先精准搜索
  - Quark 能用则用，不能伪装成功

## 下一步开发方向

1. 继续对齐 ComfyUI 内置“工作流总览”。
   - 任何差异都要能解释。
   - 真实漏报/误报必须新增测试。

2. 强化真实工作流回归。
   - 收集用户截图对应的真实 widget 结构。
   - 对 LTX、WanVideo、GGUF、LLM、多 LoRA、SAM/YOLO、InstantID/IPAdapter 继续补案例。

3. 优化 Quark 下载。
   - 当前 Quark 直链受官方 token / 登录态 / 权限限制。
   - 应继续支持递归查找和精确同名匹配。
   - 失败时明确提示原因，并尝试 Hugging Face / Civitai 完全同名候选。

4. 完善插件安装。
   - 安装前更清晰展示将安装的仓库和依赖。
   - 依赖冲突时给出具体冲突包。
   - 避免破坏用户 ComfyUI Python 环境。

5. 维护文档。
   - 每次发布更新 `README.md`、`PROJECT_CONTEXT.md`、必要时更新 `PROJECT_HANDOFF.md`。
   - 重大规则改动同步到 `AGENTS.md`。

## GitHub 使用方法

### 另一台电脑首次克隆

```powershell
cd path\to\ComfyUI\custom_nodes
git clone https://github.com/mclaughlinrosemary927/ComfyUI_FindModels.git
cd ComfyUI_FindModels
```

### 日常拉取最新代码

```powershell
.\scripts\pull.bat
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pull.ps1
```

拉取脚本会检查本地是否有未提交修改；如果有，会停止，避免覆盖当前工作。

### 日常上传修改

```powershell
.\scripts\push.bat
```

或带自定义提交信息：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\push.ps1 "Fix model detection"
```

上传脚本会执行：

1. Python 单元测试
2. `node --check web\find_models.js`
3. Python 语法检查
4. `git diff --check`
5. `git add -A`
6. `git commit`
7. `git push`

## 验证命令

```powershell
python -m unittest discover -s tests
node --check web\find_models.js
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in map(pathlib.Path, ['model_finder.py','find_models.py','node_installer.py','__init__.py'])]; print('python syntax ok')"
git diff --check
git status --short --branch --untracked-files=all
```

当前最近一次验证：

- 111 个 Python 测试通过
- `node --check web\find_models.js` 通过
- Python AST 语法检查通过
- `git diff --check` 通过

## 新会话接续步骤

1. 阅读 `AGENTS.md`。
2. 阅读本文件 `PROJECT_CONTEXT.md`。
3. 执行 `git status --short --branch`。
4. 如果用户要求继续修 bug，先读相关测试，再读实现文件。
5. 修改后运行验证命令。
6. 如涉及实际 ComfyUI 测试，按 `AGENTS.md` 中的运行目录同步规则同步到实际插件目录。
7. 只有用户明确要求上传时，才提交并推送 GitHub。
