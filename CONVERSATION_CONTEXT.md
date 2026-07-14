# CONVERSATION_CONTEXT.md

本文件是新电脑或新会话接续 `ComfyUI_FindModels` 项目的对话上下文入口。

详细历史对话、需求演进和关键决策仍以 `PROJECT_CONVERSATION_SUMMARY.md` 为准。新会话开始工作时应先读取：

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `CONVERSATION_CONTEXT.md`
4. `PROJECT_CONVERSATION_SUMMARY.md`
5. 当前源码和测试

然后执行：

```powershell
git status --short --branch
```

## 新电脑正确流程

1. `git clone` 项目。
2. 在 Codex 添加这个项目。
3. 如果项目下面显示“暂无对话”，手动新建一条对话。
4. 第一条消息发送：

```text
继续这个项目。先读取 AGENTS.md、PROJECT_CONTEXT.md、CONVERSATION_CONTEXT.md 和当前源码，理解项目背景、历史问题、用户偏好和安全规则，然后检查 git 状态。
```

## 必须记住的限制

GitHub 只能同步项目文件，不能把旧电脑上的 Codex / ChatGPT 对话气泡导入另一台电脑的对话列表。新电脑继续开发依赖仓库里的上下文文件，而不是恢复旧聊天 UI。

## 当前工作原则

- 直接解决问题，不只给方案。
- 模型识别必须尽量对齐 ComfyUI 内置“工作流总览”。
- 只显示尚未解决的缺失模型和缺失节点。
- 已加载成功或已在官方注册目录中的同名模型，必须尽快从缺失列表移除。
- 模型保存和迁移目标必须来自 ComfyUI 官方注册目录，不能根据节点保存值里的路径前缀乱建目录。
- 外部模型库和 Quark 分享只接受文件名完全一致的候选。
- Quark 或其他下载源失败时必须说明真实原因，不能伪造成成功。
- 修改 JavaScript 文件后必须运行 `npm test`；如果没有 npm 测试脚本，至少运行 `node --check web/find_models.js` 并说明原因。
- 本项目使用 GitHub Pull Request 工作流。上传 GitHub 默认创建 `codex/...` 分支、提交、推送分支并创建 PR，不直接推送到 `main`，除非用户明确要求。
