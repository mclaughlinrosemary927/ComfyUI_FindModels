import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION = "ComfyUI.FindModels";
let lastResult = null;
let toolbarObserver = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function formatSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return "大小未知";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  return `${(size / (1024 ** index)).toFixed(index > 1 ? 2 : 0)} ${units[index]}`;
}

function workflowSnapshot() {
  return {
    nodes: app.graph?._nodes?.map((node) => ({
      id: node.id,
      type: node.type,
      widgets: (node.widgets || []).flatMap((widget) => {
        const values = Array.isArray(widget.options?.values) ? widget.options.values : [];
        const isModelSelector = values.some((value) =>
          typeof value === "string" && /\.(bin|ckpt|gguf|onnx|pt|pth|safetensors)$/i.test(value),
        );
        return [{ name: widget.name, value: widget.value, model_selector: isModelSelector }];
      }),
    })) || [],
  };
}

async function post(path, body) {
  const response = await api.fetchApi(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function findTargetWidget(node, model) {
  const widgets = node?.widgets || [];
  return widgets.find((item) => item.name === model.widget)
    || widgets.find((item) => item.value === model.name)
    || widgets.find((item) => typeof item.value === "string" && item.value.replaceAll("\\", "/") === model.name);
}

async function applyMatch(model) {
  const numericId = Number(model.node_id);
  const node = app.graph?.getNodeById?.(Number.isNaN(numericId) ? model.node_id : numericId)
    || app.graph?._nodes?.find((item) => String(item.id) === String(model.node_id));
  const widget = findTargetWidget(node, model);
  if (!node || !widget || !model.match?.name) return false;

  const previous = widget.value;
  try {
    node.graph?.beforeChange?.(node);
    widget.value = model.match.name;
    if (typeof widget.callback === "function") {
      await Promise.resolve(widget.callback(widget.value, app.canvas, node, [0, 0], {}));
    }
    node.onWidgetChanged?.(widget.name, widget.value, previous, widget);
    node.graph?.afterChange?.(node);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
    app.canvas?.setDirty?.(true, true);
    return widget.value === model.match.name;
  } catch (error) {
    widget.value = previous;
    node.graph?.afterChange?.(node);
    console.error("[ComfyUI_FindModels] Failed to load model", model, error);
    return false;
  }
}

function sourceHtml(item, model) {
  const quark = item.quark ? escapeHtml(JSON.stringify(item.quark)) : "";
  return `<div class="fm-source">
    ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">` : "<span>"}
      ${escapeHtml(item.provider)} · ${escapeHtml(item.name)} · ${formatSize(item.size)} · ${Math.round(item.confidence * 100)}%
    ${item.url ? "</a>" : "</span>"}
    <button data-download="${escapeHtml(item.url || "")}" data-quark-download="${quark}"
      data-filename="${escapeHtml(item.name)}"
      data-size="${escapeHtml(item.size || "")}"
      data-category="${escapeHtml(model.category)}" data-node-id="${escapeHtml(model.node_id)}"
      data-widget="${escapeHtml(model.widget)}" data-original="${escapeHtml(model.name)}">下载到模型目录</button>
  </div>`;
}

async function loadNodeCandidates(nodeType, target) {
  target.textContent = "正在查询 TE 官方插件市场…";
  try {
    const data = await post("/findnodes/candidates", { node_type: nodeType });
    const candidates = data.candidates.map((item) => `
      <div class="fm-source">
        <a href="${escapeHtml(item.repo_url)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(item.title)} · ${escapeHtml(item.author)} · ${Math.round(item.confidence * 100)}%
        </a>
        <button data-node-install="${escapeHtml(item.id)}" data-node-type="${escapeHtml(nodeType)}">安装或更新插件</button>
      </div>`).join("");
    const fallback = `<a href="${escapeHtml(data.github_search_url)}" target="_blank" rel="noopener noreferrer">GitHub 搜索（未验证，不自动安装）</a>`;
    target.innerHTML = candidates || `TE 官方市场没有精确匹配。${fallback}`;
  } catch (error) {
    target.textContent = `插件市场查询失败：${error.message}`;
  }
}

function ensurePanel() {
  let panel = document.getElementById("find-models-panel");
  if (panel) return panel;
  panel = document.createElement("section");
  panel.id = "find-models-panel";
  panel.innerHTML = `
    <div class="fm-header"><strong>查找模型</strong><button data-action="close">×</button></div>
    <div class="fm-actions">
      <button data-action="scan">扫描当前工作流</button>
      <button data-action="adapt">一键加载模型</button>
    </div>
    <div class="fm-summary">尚未扫描</div><div class="fm-list"></div>`;
  document.body.appendChild(panel);
  panel.querySelector('[data-action="close"]').onclick = () => panel.classList.remove("open");
  panel.querySelector('[data-action="scan"]').onclick = () => scan(false);
  panel.querySelector('[data-action="adapt"]').onclick = async () => {
    const button = panel.querySelector('[data-action="adapt"]');
    button.disabled = true;
    let count = 0;
    let failed = 0;
    for (const model of lastResult?.models || []) {
      if (!model.match?.auto_apply) continue;
      if (await applyMatch(model)) count += 1;
      else failed += 1;
    }
    panel.querySelector(".fm-summary").textContent =
      `已加载 ${count} 个模型${failed ? `，${failed} 个加载失败` : ""}。请检查节点后保存工作流。`;
    button.disabled = false;
    if (count) window.setTimeout(() => scan(false), 100);
  };
  panel.addEventListener("click", async (event) => {
    const installButton = event.target.closest("[data-node-install]");
    if (installButton) {
      installButton.disabled = true;
      installButton.textContent = "正在检查依赖并安装…";
      try {
        const result = await post("/findnodes/install", {
          node_type: installButton.dataset.nodeType,
          plugin_id: installButton.dataset.nodeInstall,
        });
        installButton.textContent = result.action === "updated" ? "更新完成，需重启" : "安装完成，需重启";
        panel.querySelector(".fm-summary").textContent =
          `${result.title} 已${result.action === "updated" ? "更新" : "安装"}；`
          + `${result.new_conflicts?.length ? `发现 ${result.new_conflicts.length} 个新增依赖冲突，请查看终端。` : "未发现新增依赖冲突。"}`
          + "请重启 ComfyUI。";
      } catch (error) {
        installButton.disabled = false;
        installButton.textContent = "安装失败，重试";
        panel.querySelector(".fm-summary").textContent = `插件安装已停止：${error.message}`;
      }
      return;
    }

    const sourceButton = event.target.closest("[data-source]");
    if (sourceButton) {
      sourceButton.disabled = true;
      sourceButton.textContent = "正在获取下载项…";
      const model = lastResult?.models?.find((item) => item.name === sourceButton.dataset.source);
      const target = sourceButton.closest(".fm-item").querySelector(".fm-sources");
      try {
        const data = await post("/findmodels/sources", {
          name: sourceButton.dataset.source,
          category: model.category,
        });
        const links = data.candidates.map((item) => sourceHtml(item, model)).join("");
        target.innerHTML = links || "<span>未找到文件名完全一致的可下载模型</span>";
      } catch (error) {
        target.textContent = `获取下载项失败：${error.message}`;
      } finally {
        sourceButton.disabled = false;
        sourceButton.textContent = "下载缺失模型";
      }
      return;
    }

    const downloadButton = event.target.closest("[data-download]");
    if (!downloadButton) return;
    downloadButton.disabled = true;
    downloadButton.textContent = "正在下载…";
    try {
      const downloaded = await post("/findmodels/download", {
        url: downloadButton.dataset.download,
        quark: downloadButton.dataset.quarkDownload ? JSON.parse(downloadButton.dataset.quarkDownload) : null,
        filename: downloadButton.dataset.filename,
        size: downloadButton.dataset.size || null,
        category: downloadButton.dataset.category,
      });
      downloadButton.textContent = "下载完成，正在加载";
      await applyMatch({
        node_id: downloadButton.dataset.nodeId,
        widget: downloadButton.dataset.widget,
        name: downloadButton.dataset.original,
        match: { name: downloaded.relative_name },
      });
      window.setTimeout(() => scan(false), 500);
    } catch (error) {
      downloadButton.disabled = false;
      downloadButton.textContent = "下载失败，重试";
      panel.querySelector(".fm-summary").textContent = `下载失败：${error.message}`;
    }
  });
  return panel;
}

function render(result, quiet) {
  const panel = ensurePanel();
  lastResult = result;
  const summary = result.summary;
  const missingNodes = result.missing_nodes || [];
  updateToolbarButton(summary.unresolved + missingNodes.length);
  panel.querySelector(".fm-summary").textContent =
    `缺失节点：${missingNodes.length}；未加载模型：${summary.unresolved}`;
  const nodeHtml = missingNodes.map((nodeType) => `
    <article class="fm-item fm-missing">
      <div><strong>${escapeHtml(nodeType)}</strong><span>缺失节点</span></div>
      <div class="fm-node-candidates" data-node-candidates="${escapeHtml(nodeType)}"></div>
    </article>`).join("");
  panel.querySelector(".fm-list").innerHTML = nodeHtml + result.models.map((model) => `
    <article class="fm-item fm-${escapeHtml(model.status)}">
      <div><strong>${escapeHtml(model.name)}</strong><span>${escapeHtml(model.category)} · ${escapeHtml(model.status)}</span></div>
      ${model.match ? `<div class="fm-match">本地候选：${escapeHtml(model.match.name)} (${Math.round(model.match.confidence * 100)}%) ${model.match.auto_apply ? `<button data-apply="${escapeHtml(model.node_id)}:${escapeHtml(model.widget)}">加载</button>` : ""}</div>` : ""}
      ${model.status === "missing" ? `<button data-source="${escapeHtml(model.name)}">下载缺失模型</button><div class="fm-sources"></div>` : ""}
    </article>`).join("") || "<p>当前工作流中未发现缺失节点或模型。</p>";
  panel.querySelectorAll("[data-node-candidates]").forEach((target) =>
    loadNodeCandidates(target.dataset.nodeCandidates, target),
  );
  panel.querySelectorAll("[data-apply]").forEach((button) => {
    button.onclick = async () => {
      const model = result.models.find((item) => `${item.node_id}:${item.widget}` === button.dataset.apply);
      if (model && await applyMatch(model)) window.setTimeout(() => scan(false), 100);
    };
  });
  if (!quiet) panel.classList.add("open");
}

async function scan(quiet = false) {
  const panel = ensurePanel();
  updateToolbarButton(null, "扫描中");
  panel.querySelector(".fm-summary").textContent = "正在扫描…";
  try {
    render(await post("/findmodels/scan", workflowSnapshot()), quiet);
  } catch (error) {
    updateToolbarButton(null, "扫描失败");
    if (!quiet) panel.classList.add("open");
    panel.querySelector(".fm-summary").textContent = `扫描失败：${error.message}`;
  }
}

function updateToolbarButton(missing = null, state = null) {
  const button = document.getElementById("find-models-launcher");
  if (!button) return;
  button.textContent = "查找模型";
  button.title = state ? `查找模型：${state}` : `查找模型：未找到 ${missing ?? 0}`;
  button.dataset.missing = String(missing ?? 0);
  button.classList.toggle("has-missing", Number(missing) > 0);
}

function findRunButton() {
  const selectors = [
    "[data-testid='queue-button']",
    "[data-testid='run-button']",
    "button[aria-label*='Queue']",
    "button[aria-label*='Run']",
    "button[title*='Queue']",
    "button[title*='Run']",
  ];
  return selectors.map((selector) => document.querySelector(selector)).find(Boolean);
}

function findImageStreamButton() {
  const selectors = [
    "[data-testid='image-feed-button']",
    "[data-testid='image-stream-button']",
    "button[aria-label='显示图像流']",
    "button[title='显示图像流']",
    "button[aria-label*='图像流']",
    "button[title*='图像流']",
    "button[aria-label*='image feed']",
    "button[title*='image feed']",
  ];
  const direct = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (direct) return direct;
  return [...document.querySelectorAll("button")].find((button) =>
    ["显示图像流", "Show image feed", "Show image stream"].includes(button.textContent?.trim()),
  );
}

function findTopToolbar() {
  const imageStreamButton = findImageStreamButton();
  if (imageStreamButton?.parentElement) return imageStreamButton.parentElement;
  const runButton = findRunButton();
  if (runButton?.parentElement) return runButton.parentElement;
  return document.querySelector(
    "[data-testid='topbar'], header, .comfyui-body-top, .comfy-menu, #comfy-menu",
  );
}

function mountToolbarButton() {
  let existing = document.getElementById("find-models-launcher");
  const imageStreamButton = findImageStreamButton();
  const runButton = findRunButton();
  const toolbar = findTopToolbar();

  if (!existing) {
    existing = document.createElement("button");
    existing.id = "find-models-launcher";
    existing.type = "button";
    existing.textContent = "查找模型";
    existing.title = "扫描当前工作流中的缺失模型";
    existing.onclick = () => scan(false);
    document.body.appendChild(existing);
  }

  if (toolbar) {
    existing.classList.remove("toolbar-fallback");
    if (existing.parentElement !== toolbar) {
      if (imageStreamButton) imageStreamButton.insertAdjacentElement("beforebegin", existing);
      else if (runButton) runButton.insertAdjacentElement("afterend", existing);
      else toolbar.appendChild(existing);
    } else if (imageStreamButton && existing.nextElementSibling !== imageStreamButton) {
      imageStreamButton.insertAdjacentElement("beforebegin", existing);
    }
    return true;
  }

  existing.classList.add("toolbar-fallback");
  if (existing.parentElement !== document.body) document.body.appendChild(existing);
  return false;
}

function watchTopToolbar() {
  mountToolbarButton();
  toolbarObserver?.disconnect();
  toolbarObserver = new MutationObserver(() => mountToolbarButton());
  toolbarObserver.observe(document.body, { childList: true, subtree: true });
}

app.registerExtension({
  name: EXTENSION,
  setup() {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = new URL("./find_models.css", import.meta.url).href;
    document.head.appendChild(style);
    ensurePanel();
    watchTopToolbar();
    window.setTimeout(() => scan(true), 1200);
  },
  async afterConfigureGraph() {
    window.clearTimeout(window.__findModelsTimer);
    window.__findModelsTimer = window.setTimeout(() => scan(true), 700);
  },
});
