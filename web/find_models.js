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

function workflowSnapshot() {
  return {
    nodes: app.graph?._nodes?.map((node) => ({
      id: node.id,
      type: node.type,
      widgets: (node.widgets || []).map((widget) => ({ name: widget.name, value: widget.value })),
    })) || [],
    workflow: app.graph?.serialize?.() || {},
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
  return `<div class="fm-source">
    <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
      ${escapeHtml(item.provider)} · ${escapeHtml(item.name)} · ${Math.round(item.confidence * 100)}%
    </a>
    <button data-download="${escapeHtml(item.url)}" data-filename="${escapeHtml(item.name)}"
      data-category="${escapeHtml(model.category)}">下载到模型目录</button>
  </div>`;
}

function ensurePanel() {
  let panel = document.getElementById("find-models-panel");
  if (panel) return panel;
  panel = document.createElement("section");
  panel.id = "find-models-panel";
  panel.innerHTML = `
    <div class="fm-header"><strong>ComfyUI Find Models</strong><button data-action="close">×</button></div>
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
    const sourceButton = event.target.closest("[data-source]");
    if (sourceButton) {
      sourceButton.disabled = true;
      sourceButton.textContent = "查询中…";
      const model = lastResult?.models?.find((item) => item.name === sourceButton.dataset.source);
      const target = sourceButton.closest(".fm-item").querySelector(".fm-sources");
      try {
        const data = await post("/findmodels/sources", { name: sourceButton.dataset.source });
        const links = data.candidates.map((item) => sourceHtml(item, model)).join("");
        const quarkLibraries = data.quark_libraries.map((item) => `
          <button data-quark="${escapeHtml(item.url)}" data-query="${escapeHtml(data.name)}">
            ${escapeHtml(item.name)}：复制模型名并打开
          </button>`).join("");
        target.innerHTML = `${links || "<span>未找到可靠直链候选</span>"}
          <a href="${escapeHtml(data.quark_search_url)}" target="_blank" rel="noopener noreferrer">夸克模型库搜索直达</a>
          ${quarkLibraries}`;
      } catch (error) {
        target.textContent = `查询失败：${error.message}`;
      } finally {
        sourceButton.disabled = false;
        sourceButton.textContent = "查找下载来源";
      }
      return;
    }

    const quarkButton = event.target.closest("[data-quark]");
    if (quarkButton) {
      try {
        await navigator.clipboard.writeText(quarkButton.dataset.query);
        panel.querySelector(".fm-summary").textContent = `已复制模型名：${quarkButton.dataset.query}`;
      } catch {
        panel.querySelector(".fm-summary").textContent = `请在夸克中搜索：${quarkButton.dataset.query}`;
      }
      window.open(quarkButton.dataset.quark, "_blank", "noopener,noreferrer");
      return;
    }

    const downloadButton = event.target.closest("[data-download]");
    if (!downloadButton) return;
    downloadButton.disabled = true;
    downloadButton.textContent = "正在下载…";
    try {
      await post("/findmodels/download", {
        url: downloadButton.dataset.download,
        filename: downloadButton.dataset.filename,
        category: downloadButton.dataset.category,
      });
      downloadButton.textContent = "下载完成";
      window.setTimeout(() => scan(false), 300);
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
  updateToolbarButton(summary.missing);
  panel.querySelector(".fm-summary").textContent =
    `引用 ${summary.references} · 已安装 ${summary.installed} · 可加载 ${summary.adaptable} · 缺失 ${summary.missing}`;
  panel.querySelector(".fm-list").innerHTML = result.models.map((model) => `
    <article class="fm-item fm-${escapeHtml(model.status)}">
      <div><strong>${escapeHtml(model.name)}</strong><span>${escapeHtml(model.category)} · ${escapeHtml(model.status)}</span></div>
      ${model.match ? `<div class="fm-match">本地候选：${escapeHtml(model.match.name)} (${Math.round(model.match.confidence * 100)}%) ${model.match.auto_apply ? `<button data-apply="${escapeHtml(model.node_id)}:${escapeHtml(model.widget)}">加载</button>` : ""}</div>` : ""}
      ${model.status === "missing" ? `<button data-source="${escapeHtml(model.name)}">查找下载来源</button><div class="fm-sources"></div>` : ""}
    </article>`).join("") || "<p>当前工作流中未识别到模型引用。</p>";
  panel.querySelectorAll("[data-apply]").forEach((button) => {
    button.onclick = async () => {
      const model = result.models.find((item) => `${item.node_id}:${item.widget}` === button.dataset.apply);
      if (model && await applyMatch(model)) window.setTimeout(() => scan(false), 100);
    };
  });
  if (!quiet || summary.missing || summary.adaptable) panel.classList.add("open");
}

async function scan(quiet = false) {
  const panel = ensurePanel();
  updateToolbarButton(null, "扫描中");
  panel.querySelector(".fm-summary").textContent = "正在扫描…";
  try {
    render(await post("/findmodels/scan", workflowSnapshot()), quiet);
  } catch (error) {
    updateToolbarButton(null, "扫描失败");
    panel.classList.add("open");
    panel.querySelector(".fm-summary").textContent = `扫描失败：${error.message}`;
  }
}

function updateToolbarButton(missing = null, state = null) {
  const button = document.getElementById("find-models-launcher");
  if (!button) return;
  button.textContent = state ? `查找模型 ${state}` : `查找模型 未找到 ${missing ?? 0}`;
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

function findTopToolbar() {
  const runButton = findRunButton();
  if (runButton?.parentElement) return runButton.parentElement;
  return document.querySelector(
    "[data-testid='topbar'], header, .comfyui-body-top, .comfy-menu, #comfy-menu",
  );
}

function mountToolbarButton() {
  let existing = document.getElementById("find-models-launcher");
  const runButton = findRunButton();
  const toolbar = findTopToolbar();

  if (!existing) {
    existing = document.createElement("button");
    existing.id = "find-models-launcher";
    existing.type = "button";
    existing.textContent = "查找模型 未找到 0";
    existing.title = "扫描当前工作流中的缺失模型";
    existing.onclick = () => scan(false);
    document.body.appendChild(existing);
  }

  if (toolbar) {
    existing.classList.remove("toolbar-fallback");
    if (existing.parentElement !== toolbar) {
      runButton ? runButton.insertAdjacentElement("afterend", existing) : toolbar.appendChild(existing);
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
