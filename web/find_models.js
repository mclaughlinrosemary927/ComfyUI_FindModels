import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION = "ComfyUI.FindModels";
let lastResult = null;

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
    const button = event.target.closest("[data-source]");
    if (!button) return;
    button.disabled = true;
    button.textContent = "查询中…";
    try {
      const data = await post("/findmodels/sources", { name: button.dataset.source });
      const target = button.closest(".fm-item").querySelector(".fm-sources");
      target.innerHTML = data.candidates.length
        ? data.candidates.map((item) => `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.provider)} · ${escapeHtml(item.name)} · ${Math.round(item.confidence * 100)}%</a>`).join("")
        : "<span>未找到可靠下载候选</span>";
    } catch (error) {
      button.closest(".fm-item").querySelector(".fm-sources").textContent = `查询失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "查找下载直链";
    }
  });
  return panel;
}

function render(result, quiet) {
  const panel = ensurePanel();
  lastResult = result;
  const summary = result.summary;
  panel.querySelector(".fm-summary").textContent =
    `引用 ${summary.references} · 已安装 ${summary.installed} · 可适配 ${summary.adaptable} · 缺失 ${summary.missing}`;
  panel.querySelector(".fm-list").innerHTML = result.models.map((model) => `
    <article class="fm-item fm-${escapeHtml(model.status)}">
      <div><strong>${escapeHtml(model.name)}</strong><span>${escapeHtml(model.category)} · ${escapeHtml(model.status)}</span></div>
      ${model.match ? `<div class="fm-match">本地候选：${escapeHtml(model.match.name)} (${Math.round(model.match.confidence * 100)}%) ${model.match.auto_apply ? `<button data-apply="${escapeHtml(model.node_id)}:${escapeHtml(model.widget)}">应用</button>` : ""}</div>` : ""}
      ${model.status === "missing" ? `<button data-source="${escapeHtml(model.name)}">查找下载直链</button><div class="fm-sources"></div>` : ""}
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
  panel.querySelector(".fm-summary").textContent = "正在扫描…";
  try {
    render(await post("/findmodels/scan", workflowSnapshot()), quiet);
  } catch (error) {
    panel.classList.add("open");
    panel.querySelector(".fm-summary").textContent = `扫描失败：${error.message}`;
  }
}

app.registerExtension({
  name: EXTENSION,
  setup() {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = new URL("./find_models.css", import.meta.url).href;
    document.head.appendChild(style);
    const button = document.createElement("button");
    button.id = "find-models-launcher";
    button.textContent = "Find Models";
    button.title = "扫描当前工作流中的缺失模型";
    button.onclick = () => scan(false);
    document.body.appendChild(button);
    ensurePanel();
  },
  async afterConfigureGraph() {
    window.clearTimeout(window.__findModelsTimer);
    window.__findModelsTimer = window.setTimeout(() => scan(true), 700);
  },
});
