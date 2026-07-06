# AGENTS.md

本文件给后续 Codex / 开发者使用。新会话开始处理本项目时，必须先阅读本文件，再阅读 `PROJECT_CONTEXT.md`。

## 项目定位

`ComfyUI_FindModels` 是一个 ComfyUI custom node / frontend extension，用于扫描当前打开的工作流，识别缺失模型和缺失节点，并提供本地候选、外部模型库迁移、下载来源和缺失节点安装能力。

核心目标不是“猜模型”，而是尽量复刻 ComfyUI 内置“工作流总览”的依赖识别结果，并且只显示尚未解决的依赖。

## 必读文件

- `PROJECT_CONTEXT.md`：当前版本、已完成功能、近期修复、用户偏好、下一步方向、GitHub 使用方法。
- `model_finder.py`：模型引用提取、分类、installed/adaptable/missing 判定。
- `find_models.py`：ComfyUI HTTP 路由、外部模型库索引、模型迁移、下载、Quark、节点安装入口。
- `node_installer.py`：缺失节点包识别、GitHub 候选、插件安装和依赖冲突保护。
- `web/find_models.js`：前端工作流快照、自动扫描、右侧面板、加载/定位/下载/安装交互。
- `tests/`：回归测试。每次修复真实误报/漏报都要补测试。

## 本地状态不要提交

以下都是本地运行或测试产物，不能提交：

- `__pycache__/`
- `.pytest_cache/`
- `models/`
- `external_model_folder.json`
- `quark_auth.json`
- 下载中的临时文件或用户本地模型文件

这些应保持在 `.gitignore` 中。

## 模型识别硬规则

1. 官方目录才算 installed。
   - `diffusion_models` 只有在 ComfyUI 注册的 `models/diffusion_models` 中才算已解决。
   - `text_encoders` 只有在 ComfyUI 注册的 `models/text_encoders` 中才算已解决。
   - 旧目录或兼容目录，例如 `unet`、`clip`，只能作为本地候选或已被节点确认有效的选择依据，不能随便让缺失项消失。

2. 文件名完全一致但路径不一致是 adaptable。
   - 文件名完全一致，大小写可忽略，但保存路径和当前节点值不一致时，应显示“加载本地模型”。
   - 不允许用相似文件名自动替换。

3. 未知分类不能自动迁移或下载。
   - `unknown` 只能显示信息和搜索入口。
   - 不能把 unknown 模型写入任意目录。

4. 不要使用节点值里的路径前缀作为官方目录。
   - 工作流里的 `Wan/...`、`Qwen/...`、中文目录、旧目录前缀只是节点保存值，不等于目标目录。
   - 目标目录必须来自 ComfyUI `folder_paths` 或插件注册的模型分类。

5. 点击加载后不能退化。
   - 如果前端确认当前 widget 值在节点候选列表中，并且本地任意注册目录存在完全同名文件，可以视为已解决并从列表移除。
   - 如果本地没有该文件，仍然必须显示缺失，不能误隐藏。

6. 只显示未解决依赖。
   - 已在官方目录匹配成功的模型不显示。
   - 外部剪切、下载完成、加载本地模型后必须重新扫描并尽快移出列表。

## 缺失节点规则

- 缺失节点和缺失模型必须分开显示，不能混入同一列表。
- 缺失节点按工作流 `aux_id` / 包信息分组。
- 只能从以下来源安装：
  - 工作流明确给出的 GitHub `owner/repo`
  - ComfyUI-Manager 官方 node map
  - 用户手动输入的 HTTPS GitHub 链接
- 安装依赖前必须保护核心依赖：`torch`、`torchvision`、`torchaudio`、`xformers`、`triton`、`onnxruntime`、`onnxruntime-gpu`。

## Quark 和下载规则

- 固定 Quark 分享链接：
  - `https://pan.quark.cn/s/fb913d649b18`
  - `https://pan.quark.cn/s/4680ac866516`
- Quark 可能因为 token、登录态、限速或权限拒绝直链。不要伪造成成功。
- 下载只允许文件名完全一致的候选。
- 下载目标必须是已注册的官方模型分类目录。
- 永远不要覆盖已有模型文件。

## 清理代码边界

可以删除：

- 明确未被引用、未被测试、不是路由入口、不是动态注册入口的代码。
- 本地缓存、测试残留目录、未跟踪运行状态文件。

不要删除：

- `@PromptServer.instance.routes.*` 装饰的路由函数，即使静态扫描看起来未调用。
- 被测试直接导入的 helper。
- 前端事件回调、动态注册、异步下载任务和安装任务相关函数。
- 为 ComfyUI / 插件兼容保留的分类别名。

如果不确定，先补测试证明无用或无行为影响，再删除。

## 验证命令

从仓库根目录执行：

```powershell
python -m unittest discover -s tests
node --check web\find_models.js
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in map(pathlib.Path, ['model_finder.py','find_models.py','node_installer.py','__init__.py'])]; print('python syntax ok')"
git diff --check
git status --short --branch --untracked-files=all
```

如果修改前端 JS/CSS，提醒用户重启 ComfyUI 并在浏览器中 `Ctrl+F5`。

## 运行目录同步

用户常在实际 ComfyUI 环境中测试。代码改完后，如需同步运行目录，目标通常是：

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

不要同步 `.git/`、`tests/`、`__pycache__/`、本地配置、Cookie 或用户模型文件。同步后用 `Get-FileHash` 校验关键文件一致。

## Git 和发布

- 用户明确要求“上传 GitHub”或“提交”时才 commit / push。
- 发布前更新版本号：
  - `pyproject.toml`
  - `README.md`
  - `PROJECT_CONTEXT.md`
  - `PROJECT_HANDOFF.md`（如果仍维护）
- release commit 格式沿用：

```text
Release version X.Y.Z
```

- tag 格式：

```text
vX.Y.Z
```

普通文档或脚本更新可以使用描述性 commit，不必打版本标签。

## 当前重点风险

- 模型已经能被节点加载时，不能继续显示在缺失模型列表。
- 模型本地不存在时，不能因为控件值看起来有效而误隐藏。
- LTX、WanVideo、LLM/GGUF、text encoder、multi-LoRA、Impact/SAM/YOLO、InstantID/IPAdapter 是高风险分类。
- 每次新增识别规则都要防止把 LoRA 误分到 `diffusion_models`，或把 UNet/diffusion 模型误分到 `loras`。
- 不要为了减少漏报扩大自由文本扫描范围，否则会引入大量误报。
