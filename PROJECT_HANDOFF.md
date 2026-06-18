# ComfyUI_FindModels 项目交接文档

> 更新时间：2026-06-18
> 当前版本：`1.25.0`
> 当前分支：`main`
> 发布基线：`bbd569e Improve missing dependency detection and native panel UI`
> 状态：核心功能、原生右侧分栏 UI 与实时插件已同步
> 发布约束：仅在用户明确要求时提交或上传 GitHub

## 1. 项目目标

`ComfyUI_FindModels` 是 ComfyUI 自定义插件，核心目标是参考 ComfyUI 内置“工作流总览”：

- 快速、精准识别当前工作流真正缺失的模型和自定义节点。
- 只显示需要处理的模型；已安装、已加载、已适配模型立即消失。
- 从 ComfyUI 当前 models 目录或外部模型库一键适配模型路径。
- 严格按照 ComfyUI 或具体模型插件注册的官方模型类别和目录存放文件。
- 提供可靠模型下载来源、文件大小、下载进度、暂停、继续和取消。
- 缺失节点使用工作流包元数据、ComfyUI-Manager 官方映射或用户明确输入的 GitHub 仓库，并处理依赖冲突。

## 2. 关键路径与状态

| 项目 | 当前值 |
|---|---|
| 本地仓库 | `<workspace>/ComfyUI_FindModels` |
| 实时插件目录 | `<ComfyUI>/custom_nodes/ComfyUI_FindModels` |
| GitHub 仓库 | `https://github.com/mclaughlinrosemary927/ComfyUI_FindModels` |
| 外部模型库 | 用户在设置页选择的任意本地目录 |
| ComfyUI models 根目录 | `<ComfyUI>/models` |
| 当前版本 | `1.25.0` |
| 最新测试 | `94 tests passed` |

不要执行 `git reset --hard`、`git checkout --` 或其他会丢失现有修改的操作。

## 3. 核心设计决策

### 3.1 模型识别原则

- 优先读取实时节点 widgets、序列化 widget 值和 ComfyUI 官方嵌入模型元数据。
- 支持翻译控件、自定义加载器、动态控件、多 LoRA 控件和嵌套值。
- 忽略自由文本、URL、注释节点、非加载器节点中的泛化 `model` 字段。
- 忽略 bypass/disabled 节点。
- 同一缺失文件只显示一次，同时保留全部引用节点。
- 不通过扩大模糊扫描范围解决漏报；每个真实漏报案例必须新增回归测试。

### 3.2 已安装、可加载与缺失的区别

- 节点路径与 ComfyUI 注册路径完全一致：已安装，不显示。
- 文件名一致，但节点使用无效旧前缀或错误路径：显示为“路径不一致，可一键加载”。
- 一键加载必须写入 ComfyUI 实际注册路径，加载成功后立即隐藏。
- 文件不存在：显示为缺失模型。
- 相似文件名不能自动替代，仅能作为人工参考。

### 3.3 官方模型目录原则

- 目标目录由 ComfyUI 或对应模型插件注册的模型类别决定。
- 不能根据工作流节点中的路径前缀决定目标目录。
- 下载和外部迁移都必须使用官方类别根目录，并使用 basename。
- 未知类别禁止自动剪切或下载，防止模型放错位置。
- 不覆盖已有模型文件。

已适配的重要类别：

| 类别 | 官方目录或注册目录 |
|---|---|
| `diffusion_models` | `models\diffusion_models`，优先于旧别名 `models\unet` |
| `loras` | `models\loras` |
| `text_encoders` | `models\text_encoders` |
| `vae` | `models\vae` |
| `LLM` | 大小写敏感的 `models\LLM` |

### 3.4 外部模型库优先查找

- 扫描工作流时，第一优先级在外部模型库中查找当前所需的精确文件名。
- 优先扫描对应官方类别子目录，例如 `models\diffusion_models`、`models\LLM`。
- 精确找到后立即返回，不等待完整外部库索引。
- 完整外部索引在后台刷新。
- 外部库支持多层递归扫描和 `.gguf`、`.safetensors`、`.onnx` 等模型格式。
- 外部模型匹配后显示文件大小和剪切操作。

性能案例：

- `Wan2.1-InfiniteTalk_Single_Q6_K.gguf` 从全库扫描约 `1711 ms` 优化为分类目录扫描约 `3.8 ms`。

### 3.5 缺失节点识别与安装

- 前端读取工作流节点属性中的 `aux_id`、`ver`。
- 缺失节点按插件包分组，而不是逐个节点类型误报。
- 同一 `aux_id` 的多个节点合并成一个缺失节点包。
- 无包元数据的节点归入“未知包”。
- 模型引用绝不能混入缺失节点。

安装来源优先级：

1. 工作流 `aux_id` 明确提供的 `owner/repository` GitHub 仓库。
2. ComfyUI-Manager 官方节点映射提供的 GitHub 仓库。
3. 用户在界面中明确输入的 HTTPS GitHub 仓库。

安全边界：

- 普通 GitHub 关键词搜索结果不能自动安装。
- 仅允许 HTTPS GitHub 仓库。
- 优先使用当前 ComfyUI 启动器配置的 Python、Git 和代理。
- 安装前执行依赖 dry-run。
- 阻止带版本约束地修改 `torch`、`torchvision`、`torchaudio`、`xformers`、`triton`、`onnxruntime` 等核心依赖。
- 安装后执行 `pip check`。
- 安装产生新的依赖冲突时判定失败，不启用临时克隆的插件。

### 3.6 下载来源与下载任务

- 只有文件名完全一致的候选允许直接下载。
- 相似候选只能作为搜索参考。
- 支持 Hugging Face、Civitai 和两个固定夸克分享库。
- 下载目标必须是已知官方模型类别。
- 支持进度、下载速度、已耗时、预计剩余时间、暂停、继续、重试和取消。
- 面板关闭后下载继续，重新打开后恢复状态。
- 拒绝未知主机、非 HTTPS URL、Git LFS 指针和覆盖已有文件。

夸克分享库：

- `https://pan.quark.cn/s/fb913d649b18`
- `https://pan.quark.cn/s/4680ac8665162`

夸克使用公开分享 API，不读取账号 Cookie；大文件、权限或 token 限制无法绕过。

## 4. 已完成部分

### 4.1 工作流模型识别

- 支持 checkpoints、LoRA、VAE、ControlNet、text encoders、diffusion models、embeddings、upscale models、检测模型及插件动态类别。
- 支持多 LoRA 控件中所有模型引用。
- 支持 WanVideo、FantasyTalking、InfiniteTalk、自定义翻译加载器。
- 修复已适配模型反复重新出现的问题。
- 修复加载成功后长时间才消失的问题。
- 修复模型路径前导 `/` 或 `\` 导致的误报。

### 4.2 一键加载模型

- 文件存在但节点路径无效时，会显示为可加载候选。
- 支持一键更新所有引用节点。
- 多 LoRA 节点旧前缀案例已覆盖：
  - 工作流值：`万相lora/WanAnimate_relight_lora_fp16.safetensors`
  - 实际注册路径：`WanAnimate_relight_lora_fp16.safetensors`
- 路径已经完全正确时不会重复显示。

### 4.3 外部模型库

- Windows 原生文件夹选择器。
- 多层精确扫描。
- 当前工作流文件优先扫描。
- 按官方类别目录优先扫描。
- 精确模型大小显示。
- 剪切后清理模型缓存并立即从缺失列表移除。

已验证案例包括深层 `diffusion_models/Wan` GGUF 和 `models/LLM` 主模型及 mmproj 文件。

### 4.4 LLM 官方类别适配

根据 `ComfyUI-llama-cpp` 和 `ComfyUI-llama-cpp_vlm` 的注册方式：

- `Llama-cpp Model Loader` 主模型和 `mmproj` 模型归类为大小写敏感的 `LLM`。
- 外部模型优先扫描所选外部库中的 `models/LLM` 或 `LLM`。
- 迁移目标为 `<ComfyUI>/models/LLM`。
- 不再显示 `unknown` 或“工作流未提供模型目录”。

参考源码：

- `https://github.com/abdozmantar/ComfyUI-llama-cpp`
- `https://github.com/SeanScripts/ComfyUI-llama-cpp_vlm`

### 4.5 缺失节点包

- 已复刻“工作流总览”的 `aux_id/ver` 包分组思路。
- `AudioDurationToFrames` 可归入 `syq890610-crypto/Comfyui-Mk-tools`。
- 缺失包支持定位节点、重新查找插件、GitHub 搜索和安装。
- “安装缺失节点”会逐个包主动查找可信候选并安装。

### 4.6 UI 和生命周期

- 顶部运行栏显示“查找模型”。
- 面板默认不自动弹出，用户点击后挂载到 ComfyUI 官方右侧 SplitterPanel。
- 关闭后可以再次打开。
- 缺失模型、缺失节点、下载任务和设置使用独立标签页。
- 面板关闭后下载任务继续。

## 5. 当前验证状态

最新测试命令：

```powershell
python -m unittest discover -s tests
python -m py_compile find_models.py model_finder.py node_installer.py __init__.py
node --check web\find_models.js
git diff --check
```

最新测试结果：

```text
Ran 94 tests
OK
```

实时状态：

- 实时插件目录存在。
- 实时版本为 `1.25.0`。
- 外部模型库路径由本机忽略配置保存，不写入仓库。
- `models/LLM` 等动态类别按 ComfyUI 注册目录处理。

## 6. 重要文件修改记录

### `model_finder.py`

职责：

- 提取工作流模型引用。
- 模型分类。
- 判断 installed、adaptable、missing。
- 合并引用和过滤误报。

重要修改：

- 支持动态、多 LoRA、翻译控件和嵌套 widget。
- `InfiniteTalk` 归类为 `diffusion_models`。
- `Llama-cpp`、`LLM` 和 `mmproj` 归类为大小写敏感的 `LLM`。
- 文件名一致但节点路径无效时判定为 adaptable，可一键加载。

### `find_models.py`

职责：

- HTTP 路由。
- 外部模型库索引和迁移。
- 模型来源查询。
- 下载任务和状态恢复。
- 缺失节点候选和安装路由。

重要修改：

- 当前工作流精确文件名优先扫描。
- 官方类别子目录优先扫描。
- `LLM` 下载、夸克分类和迁移目录支持。
- 缺失节点包数据返回。
- 工作流 `aux_id`、ComfyUI-Manager 和用户指定的 GitHub 候选。

### `node_installer.py`

职责：

- 缺失节点包识别。
- 工作流元数据、ComfyUI-Manager 和用户指定的 GitHub 候选。
- 插件安装、更新和依赖冲突检查。

重要修改：

- 按 `aux_id` 分组缺失节点包。
- 从可信 `owner/repository` 格式 `aux_id` 构建 GitHub 回退候选。
- 未知包只接受 ComfyUI-Manager 官方映射。
- 保护核心依赖、执行 dry-run 和 `pip check`。

### `web/find_models.js`

职责：

- 顶部栏按钮。
- 工作流快照。
- 面板渲染。
- 一键加载、定位、安装和下载控制。

重要修改：

- 发送 `package_id/package_version`。
- 缺失节点按插件包显示。
- 一键安装缺失节点包时主动查询可信来源。
- 一键加载模型更新全部引用节点。
- 恢复活动下载任务。

### `web/find_models.css`

- 工作流总览风格面板。
- 标签页、模型卡片、缺失节点包、下载状态和外部库候选样式。

### 测试文件

- `tests/test_model_finder.py`：模型识别、分类、一键加载、多 LoRA、LLM 等。
- `tests/test_download_helpers.py`：官方目录、外部库、下载安全、夸克和任务状态等。
- `tests/test_node_installer.py`：节点包分组、可信 GitHub 回退和依赖保护等。

## 7. 当前待办事项

### P0：真实 ComfyUI 回归测试

- 重启 ComfyUI 并 `Ctrl+F5`。
- 验证多 LoRA 旧路径能显示为可一键加载，并在点击后写入根目录注册路径。
- 验证 LLM 主模型和 `mmproj` 显示为 `LLM`，可剪切到 `models\LLM`。
- 验证缺失节点包的一键安装在 TE 无结果时使用 `aux_id` GitHub 回退。
- 验证安装失败、代理失败和依赖冲突时 UI 能显示清晰错误。

### P1：继续与“工作流总览”逐案例对齐

- 用户提供任何漏报或误报截图时，先复现真实工作流字段。
- 对每个案例添加回归测试，再修改识别规则。
- 不把模型混入缺失节点，不把注释或前端辅助节点当作缺失插件。

### P1：安装失败后的环境处理

- 当前新插件在临时目录安装，失败时会删除临时目录。
- 已存在插件执行 `git pull` 后，如果依赖安装失败，不会自动回退 Git 提交。
- 后续可以增加已存在插件更新失败时的非破坏性回退机制。

### P2：Git 与发布

- 提交前检查改动、测试和实时插件一致性。
- 本机路径、Cookie 与外部模型库配置不得提交。

## 8. 下一会话建议执行顺序

1. 读取本文件。
2. 核对状态：

   ```powershell
   cd <workspace>/ComfyUI_FindModels
   git status --short
   Select-String pyproject.toml -Pattern '^version'
   python -m unittest discover -s tests
   ```

3. 核对 `<ComfyUI>/custom_nodes/ComfyUI_FindModels` 实时插件目录。

4. 优先处理用户最新截图对应的真实回归案例。
5. 修改后执行完整测试、语法检查和 `git diff --check`。
6. 同步到实时插件目录。
7. 仅在用户明确要求时上传 GitHub。

## 9. 验收标准

### 模型识别与加载

- 与“工作流总览”识别结果一致或能明确解释差异。
- 真正缺失的模型全部显示。
- models 中已有但节点路径错误的模型可一键加载。
- 一键加载后模型立即消失且不会重新出现。
- 下载或外部迁移严格进入官方类别目录。

### 缺失节点

- 按插件包显示。
- 优先 `aux_id` 精确识别。
- 官方映射无结果时只使用用户明确输入的 GitHub 来源。
- 安装依赖不破坏核心运行环境。

### 下载

- 文件名必须完全一致。
- 显示大小、进度、速度、耗时和剩余时间。
- 支持暂停、继续、重试和取消。
- 面板关闭后任务继续并可恢复。

## 10. 不应改变的约束

- 不自动安装普通 GitHub 搜索结果。
- 不自动下载相似文件名模型。
- 不覆盖已有模型。
- 不根据节点里的旧路径前缀决定目标目录。
- 不在初始扫描时执行慢速远程查询。
- 不把模型引用混入缺失节点。
- 不把注释、Markdown 或前端辅助节点误报为缺失插件。
- 仅在用户明确要求时提交或上传 GitHub。
