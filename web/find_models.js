import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EXTENSION = "ComfyUI.FindModels";
let lastResult = null;
let toolbarObserver = null;
let downloadMonitor = null;
let workflowMonitor = null;
let activeTab = "models";
let scanRequestId = 0;
let scanTimer = null;
let enrichTimer = null;
let observedWorkflowSignature = "";
let nativeDockState = null;
const resolvedNodePackages = new Set();
const nodeActivities = new Map();
const downloadStatuses = new Map();
const confirmedModelSelections = new Map();

function normalizedModelValue(value) {
  return typeof value === "string" ? value.replaceAll("\\", "/").replace(/^\/+/, "") : "";
}

function modelSelectionKey(nodeId, widgetName) {
  return `${String(nodeId)}:${String(widgetName || "")}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(String(value));
    return;
  }
  const input = document.createElement("textarea");
  input.value = String(value);
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  input.remove();
}

function formatSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return "大小未知";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  return `${(size / (1024 ** index)).toFixed(index > 1 ? 2 : 0)} ${units[index]}`;
}

function statusText(status) {
  return {
    adaptable: "路径不一致，可一键加载",
    missing: "缺失",
  }[status] || status;
}

function downloadProgressText(job) {
  const downloaded = formatSize(job.downloaded);
  const total = Number(job.total);
  const details = [
    job.speed ? `速度 ${formatSize(job.speed)}/s` : "",
    job.elapsed ? `已耗时 ${formatDuration(job.elapsed)}` : "",
    job.eta ? `预计剩余 ${formatDuration(job.eta)}` : "",
  ].filter(Boolean).join(" · ");
  if (!Number.isFinite(total) || total <= 0) return `已下载 ${downloaded}${details ? ` · ${details}` : ""}`;
  const percent = Math.min(100, Math.round((Number(job.downloaded || 0) / total) * 100));
  return `已下载 ${downloaded} / ${formatSize(total)} · ${percent}%${details ? ` · ${details}` : ""}`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours ? `${hours}小时${minutes}分` : minutes ? `${minutes}分${rest}秒` : `${rest}秒`;
}

function downloadStatusText(job) {
  if (job.status === "failed") return `失败：${job.error || "未知错误"}`;
  if (job.status === "paused") return `已暂停 · ${downloadProgressText(job)}`;
  if (job.status === "pausing") return `正在暂停 · ${downloadProgressText(job)}`;
  if (job.status === "cancelled") return "已取消";
  if (job.status === "completed") return `下载完成 · ${formatSize(job.total)}`;
  if (job.status === "queued") return `等待下载 · ${downloadProgressText(job)}`;
  return downloadProgressText(job);
}

function downloadControlsHtml(job) {
  const pause = ["queued", "downloading"].includes(job.status)
    ? `<button data-download-control="pause" data-job-id="${escapeHtml(job.id)}">暂停</button>` : "";
  const resume = ["paused", "failed"].includes(job.status)
    ? `<button data-download-control="resume" data-job-id="${escapeHtml(job.id)}">${job.status === "failed" ? "重试" : "继续"}</button>` : "";
  const cancel = !["completed", "cancelled"].includes(job.status)
    ? `<button data-download-control="cancel" data-job-id="${escapeHtml(job.id)}">取消</button>` : "";
  return pause + resume + cancel;
}

function isExplicitModelWidget(name) {
  const normalized = String(name || "").toLowerCase().replace(/[^a-z0-9_]+/g, "");
  const exact = new Set([
    "ckpt_name", "checkpoint_name", "lora_name", "vae_name", "control_net_name",
    "controlnet_name", "clip_name", "clip_vision", "clip_vision_name", "text_encoder_name",
    "unet_name", "diffusion_model", "diffusion_model_name", "upscale_model",
    "upscale_model_name", "embedding_name",
  ]);
  return exact.has(normalized)
    || /^(?:lora|lycoris)_?\d+$/.test(normalized)
    || /^(?:ckpt|checkpoint|vae|controlnet|control_net|clip|clip_vision|text_encoder|unet|diffusion_model|upscale_model)_?\d+$/.test(normalized)
    || /^(?:model|model_name)_\d+$/.test(normalized);
}

function isModelNodeType(type) {
  const normalized = String(type || "").toLowerCase().replace(/[^a-z0-9_]+/g, "");
  return [
    "loader", "model", "instantid", "instant_id", "ipadapter", "ip_adapter",
    "samloader", "sam_loader", "ultralytics", "detector",
    "checkpoint", "lora", "vae", "controlnet", "clip", "textencode",
    "text_encoder", "unet", "diffusion", "upscale", "embedding",
  ].some((hint) => normalized.includes(hint));
}

function workflowSnapshot() {
  let serializedGraph = null;
  try {
    serializedGraph = app.graph?.serialize?.();
  } catch (error) {
    console.debug("[ComfyUI_FindModels] Unable to serialize graph", error);
  }
  const nodes = app.graph?._nodes?.map((node) => {
      let serialized = null;
      try {
        serialized = node.serialize?.();
      } catch (error) {
        console.debug("[ComfyUI_FindModels] Unable to serialize node", node.type, error);
      }
      const widgetsValues = serialized?.widgets_values || [];
      const selectedValues = new Set([
        ...(Array.isArray(widgetsValues) ? widgetsValues : Object.values(widgetsValues)),
        ...(node.widgets || []).map((widget) => widget.value),
      ].filter((value) => typeof value === "string"));
      const properties = serialized?.properties || node.properties || {};
      const packageId = [properties.aux_id, properties.cnr_id, properties.package_id]
        .find((value) => typeof value === "string" && value.trim());
      const packageVersion = [properties.ver, properties.version]
        .find((value) => typeof value === "string" && value.trim());
      return {
        id: node.id,
        type: node.type,
        package_id: packageId || null,
        package_version: packageVersion || null,
        active: ![2, 4].includes(node.mode),
        frontend_registered: Boolean(
          globalThis.LiteGraph?.registered_node_types?.[node.type]
          || node.constructor?.type === node.type
          || node.constructor?.nodeData?.name === node.type
        ),
        models: (node.properties?.models || []).filter((model) => selectedValues.has(model.name)),
        widgets_values: widgetsValues,
        widgets: (node.widgets || []).flatMap((widget) => {
          let rawValues = widget.options?.values;
          if (typeof rawValues === "function") {
            try {
              rawValues = rawValues();
            } catch (error) {
              console.debug("[ComfyUI_FindModels] Unable to inspect combo values", widget.name, error);
            }
          }
          const values = Array.isArray(rawValues) ? rawValues : [];
          const hasModelOptions = values.some((value) =>
            typeof value === "string" && /\.(bin|ckpt|gguf|onnx|pt|pth|safetensors|sft)$/i.test(value)
          );
          const isAsset = widget.type === "asset";
          const isModelSelector = isAsset || hasModelOptions || isExplicitModelWidget(widget.name)
            || (isModelNodeType(node.type) && typeof widget.value === "string"
              && /\.(bin|ckpt|gguf|onnx|pt|pt2|pth|pkl|safetensors|sft)$/i.test(widget.value));
          const normalizedValue = normalizedModelValue(widget.value) || null;
          const selectionKey = modelSelectionKey(node.id, widget.name);
          const confirmedValue = confirmedModelSelections.get(selectionKey);
          if (confirmedValue && confirmedValue !== normalizedValue) {
            confirmedModelSelections.delete(selectionKey);
          }
          const modelValueValid = confirmedValue === normalizedValue && normalizedValue !== null
            ? true
            : hasModelOptions && normalizedValue !== null
            ? values.some((value) =>
              typeof value === "string" && normalizedModelValue(value) === normalizedValue
            )
            : null;
          const modelMetadata = (node.properties?.models || []).find((model) =>
            typeof widget.value === "string" && model.name === widget.value
          );
          return [{
            name: widget.name,
            type: widget.type,
            value: widget.value,
            model_selector: isModelSelector,
            model_value_valid: modelValueValid,
            asset_selector: isAsset,
            directory: modelMetadata?.directory
              || widget.options?.directory
              || widget.options?.folder
              || widget.options?.model_folder,
            source_url: modelMetadata?.url,
            source_hash: modelMetadata?.hash,
            source_hash_type: modelMetadata?.hash_type,
            source_size: modelMetadata?.size,
          }];
        }),
      };
    }) || [];
  return {
    models: serializedGraph?.models || [],
    nodes,
  };
}

function workflowSignature(snapshot) {
  return JSON.stringify({
    nodes: (snapshot.nodes || []).map((node) => [
      node.id,
      node.type,
      node.active,
      node.widgets_values,
    ]),
    models: (snapshot.models || []).map((model) => [
      model.name,
      model.directory,
      model.url,
      model.hash,
      model.size,
    ]),
  });
}

function removeResolvedModel(name) {
  if (!lastResult?.models) return;
  const normalized = normalizedModelValue(name);
  lastResult.models = lastResult.models.filter((model) => normalizedModelValue(model.name) !== normalized);
  lastResult.summary = { ...lastResult.summary, unresolved: lastResult.models.length };
  render(lastResult);
  observedWorkflowSignature = workflowSignature(workflowSnapshot());
}

function scheduleScan(delay = 0, quick = true) {
  window.clearTimeout(scanTimer);
  scanTimer = window.setTimeout(() => scan(true, { quick }), delay);
}

function scheduleEnrichedScan(delay = 180) {
  window.clearTimeout(enrichTimer);
  enrichTimer = window.setTimeout(() => scan(true, { quick: false }), delay);
}

function startWorkflowMonitor() {
  window.clearInterval(workflowMonitor);
  observedWorkflowSignature = workflowSignature(workflowSnapshot());
  workflowMonitor = window.setInterval(() => {
    const signature = workflowSignature(workflowSnapshot());
    if (signature === observedWorkflowSignature) return;
    observedWorkflowSignature = signature;
    resolvedNodePackages.clear();
    scanRequestId += 1;
    scheduleScan(0, true);
  }, 250);
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

async function get(path) {
  const response = await api.fetchApi(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function downloadJobsHtml(jobs, nodeJobs = [...nodeActivities.values()]) {
  if (!jobs.length && !nodeJobs.length) {
    return '<div class="fm-empty"><strong>暂无下载任务</strong><span>模型下载与节点安装进度会统一显示在这里</span></div>';
  }
  const modelJobs = jobs.map((job) => `
    <div class="fm-download-job fm-download-${escapeHtml(job.status)}">
      <span class="fm-job-kind">模型</span>
      <div class="fm-download-job-info"><strong>${escapeHtml(job.filename)}</strong><span>${escapeHtml(downloadStatusText(job))}</span></div>
      <div class="fm-download-controls">${downloadControlsHtml(job)}</div>
    </div>`).join("");
  const pluginJobs = nodeJobs.map((job) => `
    <div class="fm-download-job fm-download-${escapeHtml(job.status)}">
      <span class="fm-job-kind fm-job-node">节点</span>
      <div class="fm-download-job-info"><strong>${escapeHtml(job.title)}</strong><span>${escapeHtml(job.message)}</span>
        <div class="fm-install-progress ${job.status === "downloading" ? "active" : ""}"><i style="width:${Math.max(0, Math.min(100, Number(job.progress) || 0))}%"></i></div>
      </div>
    </div>`).join("");
  return `<section class="fm-download-jobs">${modelJobs}${pluginJobs}</section>`;
}

async function refreshDownloadJobs() {
  const panel = ensurePanel();
  try {
    const { jobs = [] } = await get("/findmodels/download/jobs");
    panel.querySelector(".fm-downloads").innerHTML = downloadJobsHtml(jobs);
    panel.querySelector('[data-tab-count="downloads"]').textContent =
      jobs.filter((job) => !["completed", "cancelled"].includes(job.status)).length
      + [...nodeActivities.values()].filter((job) => job.status === "downloading").length;
    const sectionCount = panel.querySelector('[data-section-count="downloads"]');
    if (sectionCount) sectionCount.textContent =
      jobs.filter((job) => !["completed", "cancelled"].includes(job.status)).length
      + [...nodeActivities.values()].filter((job) => job.status === "downloading").length;
    for (const job of jobs) {
      const previous = downloadStatuses.get(job.id);
      downloadStatuses.set(job.id, job.status);
      if (job.status === "completed" && previous && previous !== "completed") {
        const model = lastResult?.models?.find((item) => item.name === job.original);
        await applyMatchEverywhere(model || {
          node_id: job.node_id,
          widget: job.widget,
          name: job.original,
          match: { name: job.result?.relative_name },
        });
        removeResolvedModel(job.original);
        scheduleScan(0, true);
        scheduleEnrichedScan();
      }
    }
  } catch (error) {
    console.warn("[ComfyUI_FindModels] Unable to refresh download jobs", error);
  }
}

function startDownloadMonitor() {
  window.clearInterval(downloadMonitor);
  refreshDownloadJobs();
  downloadMonitor = window.setInterval(refreshDownloadJobs, 750);
}

function findTargetWidget(node, model) {
  const widgets = node?.widgets || [];
  return widgets.find((item) => item.name === model.widget)
    || widgets.find((item) => item.value === model.name)
    || widgets.find((item) => typeof item.value === "string" && item.value.replaceAll("\\", "/") === model.name)
    || widgets.find((item) => modelValueContains(item.value, model.name));
}

function modelValueContains(value, target) {
  if (typeof value === "string") {
    return modelValueMatches(value, target);
  }
  if (Array.isArray(value)) {
    return value.some((item) => modelValueContains(item, target));
  }
  if (value && typeof value === "object") {
    return Object.values(value).some((item) => modelValueContains(item, target));
  }
  return false;
}

function modelValueMatches(value, target) {
  const normalizedValue = normalizedModelValue(value);
  const normalizedTarget = normalizedModelValue(target);
  if (!normalizedValue || !normalizedTarget) return false;
  return normalizedValue === normalizedTarget
    || normalizedValue.split("/").pop()?.toLowerCase() === normalizedTarget.split("/").pop()?.toLowerCase();
}

function replaceModelValue(value, target, replacement) {
  if (typeof value === "string") {
    return modelValueMatches(value, target)
      ? { value: replacement, changed: true }
      : { value, changed: false };
  }
  if (Array.isArray(value)) {
    let changed = false;
    const next = value.map((item) => {
      const result = replaceModelValue(item, target, replacement);
      changed = changed || result.changed;
      return result.value;
    });
    return { value: changed ? next : value, changed };
  }
  if (value && typeof value === "object") {
    let changed = false;
    const next = {};
    for (const [key, item] of Object.entries(value)) {
      const result = replaceModelValue(item, target, replacement);
      changed = changed || result.changed;
      next[key] = result.value;
    }
    return { value: changed ? next : value, changed };
  }
  return { value, changed: false };
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
    if (Array.isArray(widget.options?.values) && !widget.options.values.includes(model.match.name)) {
      widget.options.values.push(model.match.name);
    }
    const nested = replaceModelValue(widget.value, model.name, model.match.name);
    widget.value = nested.changed ? nested.value : model.match.name;
    if (typeof widget.callback === "function") {
      await Promise.resolve(widget.callback(widget.value, app.canvas, node, [0, 0], {}));
    }
    node.onWidgetChanged?.(widget.name, widget.value, previous, widget);
    node.graph?.afterChange?.(node);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
    app.canvas?.setDirty?.(true, true);
    const applied = normalizedModelValue(widget.value) === normalizedModelValue(model.match.name)
      || modelValueContains(widget.value, model.match.name);
    if (applied) {
      confirmedModelSelections.set(
        modelSelectionKey(node.id, widget.name),
        normalizedModelValue(widget.value) || normalizedModelValue(model.match.name),
      );
    }
    return applied;
  } catch (error) {
    widget.value = previous;
    node.graph?.afterChange?.(node);
    console.error("[ComfyUI_FindModels] Failed to load model", model, error);
    return false;
  }
}

async function applyMatchEverywhere(model) {
  const references = model.referencing_nodes?.length
    ? model.referencing_nodes
    : [{ node_id: model.node_id, widget: model.widget, node_type: model.node_type }];
  let applied = 0;
  for (const reference of references) {
    if (await applyMatch({ ...model, ...reference })) applied += 1;
  }
  return applied === references.length;
}

function locateNode(nodeId) {
  const numericId = Number(nodeId);
  const node = app.graph?.getNodeById?.(Number.isNaN(numericId) ? nodeId : numericId)
    || app.graph?._nodes?.find((item) => String(item.id) === String(nodeId));
  if (!node) return false;
  app.canvas?.selectNode?.(node);
  app.canvas?.centerOnNode?.(node);
  node.setDirtyCanvas?.(true, true);
  return true;
}

function sourceHtml(item, model) {
  const quark = item.quark ? escapeHtml(JSON.stringify(item.quark)) : "";
  const downloadButton = item.downloadable !== false
    ? `<button data-download="${escapeHtml(item.url || "")}" data-quark-download="${quark}"
      data-filename="${escapeHtml(item.name)}"
      data-size="${escapeHtml(item.size || "")}"
      data-category="${escapeHtml(model.category)}" data-node-id="${escapeHtml(model.node_id)}"
      data-widget="${escapeHtml(model.widget)}" data-original="${escapeHtml(model.name)}">下载到模型目录</button>`
    : '<span class="fm-candidate-warning">相似候选，请打开核对</span>';
  return `<div class="fm-source">
    ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">` : "<span>"}
      ${escapeHtml(item.provider)} · ${escapeHtml(item.name)} · ${formatSize(item.size)} · ${Math.round(item.confidence * 100)}%
    ${item.url ? "</a>" : "</span>"}
    ${downloadButton}
    <div class="fm-download-progress" aria-live="polite"></div>
  </div>`;
}

function officialSourceHtml(model) {
  if (!model.source_url) return "";
  return sourceHtml({
    provider: "工作流内嵌来源",
    name: model.name,
    url: model.source_url,
    size: model.size,
    confidence: 1,
  }, model);
}

function externalCandidatesHtml(model) {
  const candidates = model.external_candidates || [];
  if (!candidates.length) return "";
  return `<div class="fm-external-candidates">${candidates.map((item) => `
    <div class="fm-source fm-external-source">
      <span>外部模型库 · ${escapeHtml(item.path)} · ${formatSize(item.size)}</span>
      ${model.category === "unknown" ? '<span class="fm-target-warning">未能从节点注册信息或外部目录识别官方模型分类，请检查该节点插件的模型目录注册。</span>' : `<button class="fm-external-move" data-external-move="${escapeHtml(item.path)}"
        data-name="${escapeHtml(model.name)}" data-category="${escapeHtml(model.category)}"
        data-node-id="${escapeHtml(model.node_id)}" data-widget="${escapeHtml(model.widget)}">
        剪切到模型目录
      </button>`}
    </div>`).join("")}</div>`;
}

function referenceText(model) {
  const count = model.referencing_nodes?.length || (model.node_id ? 1 : 0);
  return count ? `${count} 个引用节点` : "工作流模型元数据";
}

function modelCardHtml(model) {
  try {
    const confidence = Number(model.match?.confidence);
    const exactLocalMatch = model.match?.reason === "exact_filename" && confidence >= 0.99;
    return `
      <article class="fm-item fm-model-card fm-${escapeHtml(model.status || "missing")}">
        <div class="fm-item-title"><span class="fm-status-icon">${model.status === "missing" ? "!" : "↻"}</span><strong title="${escapeHtml(model.name)}">${escapeHtml(model.name)}</strong><button class="fm-copy-name" data-copy-model-name="${escapeHtml(model.name)}" title="复制模型名称">⧉</button></div>
        <div class="fm-meta"><span class="fm-badge">${escapeHtml(model.category || "unknown")}</span><span>${escapeHtml(model.official_missing ? "工作流总览判定缺失" : statusText(model.status))}</span><span>${referenceText(model)}</span><span data-model-size>大小：${formatSize(model.size)}</span></div>
        ${exactLocalMatch ? `<div class="fm-match">本地模型候选：${escapeHtml(model.match.name)} (99%)</div>` : ""}
        ${externalCandidatesHtml(model)}
        <div class="fm-sources">${officialSourceHtml(model)}</div>
        <div class="fm-item-actions fm-model-actions">
          ${model.node_id ? `<button data-locate-node="${escapeHtml(model.node_id)}">定位引用节点</button>` : ""}
          ${exactLocalMatch && model.match?.auto_apply ? `<button class="fm-local-load" data-apply="${escapeHtml(model.node_id)}:${escapeHtml(model.widget)}">加载本地模型</button>` : ""}
          <button data-source="${escapeHtml(model.name)}">查找下载来源</button>
        </div>
      </article>`;
  } catch (error) {
    console.error("[ComfyUI_FindModels] Failed to render missing model card", model, error);
    return `
      <article class="fm-item fm-model-card fm-missing">
        <div class="fm-item-title"><span class="fm-status-icon">!</span><strong>${escapeHtml(model?.name || "未知缺失模型")}</strong></div>
        <div class="fm-meta"><span class="fm-badge">${escapeHtml(model?.category || "unknown")}</span><span>模型详情渲染异常，但模型仍然缺失</span></div>
      </article>`;
  }
}

function nodeCandidatesHtml(nodeType, candidates, githubSearchUrl = "", packageId = "") {
    const links = candidates.map((item) => `
      <div class="fm-source">
        <a href="${escapeHtml(item.repo_url)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(item.title)} · ${escapeHtml(item.author)} · ${Math.round(item.confidence * 100)}%
        </a>
        <button data-node-install="${escapeHtml(item.id)}" data-node-type="${escapeHtml(nodeType)}"
          data-package-id="${escapeHtml(packageId)}">安装或更新插件</button>
      </div>`).join("");
    const searchTerm = packageId || nodeType;
    const searchUrl = githubSearchUrl || `https://github.com/search?q=${encodeURIComponent(`${searchTerm} ComfyUI`)}&type=repositories`;
    return `${links || "<span>官方映射暂未找到精确插件，可使用工作流提供的 GitHub 仓库或自定义链接。</span>"}
      <div class="fm-node-actions">
        <button data-node-refresh="${escapeHtml(nodeType)}" data-package-id="${escapeHtml(packageId)}">重新查找插件</button>
        <a href="${escapeHtml(searchUrl)}" target="_blank" rel="noopener noreferrer">GitHub 搜索</a>
      </div>`;
}

function setActiveTab(panel, tab) {
  activeTab = tab;
  panel.querySelectorAll("[data-tab]").forEach((button) =>
    button.classList.toggle("active", button.dataset.tab === tab)
  );
  panel.querySelectorAll("[data-tab-panel]").forEach((content) =>
    content.classList.toggle("active", content.dataset.tabPanel === tab)
  );
  panel.scrollTop = 0;
}

function installDependenciesEnabled(panel) {
  return panel.querySelector("[data-install-dependencies]")?.checked !== false;
}

async function waitForPropertiesPanel() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const properties = document.querySelector("[data-testid='properties-panel']");
    if (properties) return properties;
    await new Promise((resolve) => window.setTimeout(resolve, 25));
  }
  return null;
}

async function openDockedPanel(panel) {
  if (nativeDockState && panel.classList.contains("native-docked")) return true;
  let properties = document.querySelector("[data-testid='properties-panel']");
  const wasOpen = Boolean(properties);
  let openedByUs = false;
  if (!properties) {
    const toggle = findPropertyPanelButton();
    if (toggle) {
      toggle.click();
      openedByUs = true;
      properties = await waitForPropertiesPanel();
    }
  }
  if (!properties?.parentElement) {
    panel.classList.remove("native-docked");
    panel.classList.add("open");
    return false;
  }
  const host = properties.parentElement;
  nativeDockState = {
    properties,
    host,
    openedByUs,
    wasOpen,
    previousDisplay: properties.style.display,
  };
  properties.style.display = "none";
  properties.setAttribute("aria-hidden", "true");
  host.appendChild(panel);
  panel.classList.add("native-docked", "open");
  return true;
}

function closeDockedPanel(panel) {
  panel.classList.remove("open", "native-docked");
  document.body.appendChild(panel);
  const state = nativeDockState;
  nativeDockState = null;
  if (!state) return;
  state.properties.style.display = state.previousDisplay;
  state.properties.removeAttribute("aria-hidden");
  if (state.openedByUs && !state.wasOpen) {
    window.requestAnimationFrame(() => findPropertyPanelButton()?.click());
  }
}

function enablePanelResize(panel) {
  const handle = panel.querySelector(".fm-resize-handle");
  if (!handle || handle.dataset.ready) return;
  handle.dataset.ready = "true";
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = panel.getBoundingClientRect().width;
    const move = (current) => {
      if (panel.classList.contains("native-docked")) return;
      const width = Math.max(420, Math.min(window.innerWidth - 24, startWidth + startX - current.clientX));
      panel.style.width = `${width}px`;
      localStorage.setItem("findmodels.panelWidth", String(width));
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

function ensurePanel() {
  let panel = document.getElementById("find-models-panel");
  if (panel) return panel;
  panel = document.createElement("section");
  panel.id = "find-models-panel";
  panel.innerHTML = `
    <div class="fm-header">
      <div class="fm-resize-handle" title="拖动调整宽度"></div>
      <div class="fm-header-copy"><strong>查找缺失模型和节点</strong><span>当前工作流缺失依赖管理</span></div>
      <div class="fm-window-actions"><button data-action="scan" title="扫描当前工作流">↻</button><button data-action="close" title="关闭">×</button></div>
    </div>
    <div class="fm-scan-state"><span class="fm-scan-dot"></span><span data-scan-status>等待扫描当前工作流</span><button data-action="scan">重新扫描</button></div>
    <nav class="fm-tabs">
      <button data-tab="models"><span class="fm-tab-icon">缺</span><strong class="fm-tab-label">缺失模型</strong><b data-tab-count="models">0</b></button>
      <button data-tab="nodes"><span class="fm-tab-icon">节</span><strong class="fm-tab-label">缺失节点</strong><b data-tab-count="nodes">0</b></button>
      <button data-tab="downloads"><span class="fm-tab-icon">↓</span><strong class="fm-tab-label">下载任务</strong><b data-tab-count="downloads">0</b></button>
      <button data-tab="settings"><span class="fm-tab-icon">设</span><strong class="fm-tab-label">设置</strong></button>
    </nav>
    <div class="fm-summary" aria-live="polite">尚未扫描</div>
    <div class="fm-tab-panel" data-tab-panel="models">
      <div class="fm-section-toolbar"><div><strong>缺失模型 <em data-section-count="models">0</em></strong><span>仅显示尚未加载的模型，解决后立即移出</span></div><div><button data-action="scan">↻ 扫描当前工作流</button><button class="fm-primary" data-action="adapt">⇧ 一键加载模型</button></div></div>
      <div class="fm-model-list"></div>
    </div>
    <div class="fm-tab-panel" data-tab-panel="nodes">
      <div class="fm-section-toolbar"><div><strong>缺失节点 <em data-section-count="nodes">0</em></strong><span>仅显示当前工作流尚未安装的节点包</span></div><div><button data-action="scan">↻ 扫描当前工作流</button><button class="fm-primary" data-action="install-missing-nodes">↓ 安装缺失节点</button></div></div>
      <div class="fm-node-install-options">
        <label><input data-install-dependencies type="checkbox" checked> 自动安装插件依赖 requirements.txt</label>
        <div><input data-custom-github type="url" placeholder="输入自定义 GitHub 插件仓库链接"><button data-action="install-custom-github">链接安装插件</button></div>
      </div>
      <div class="fm-node-list"></div>
    </div>
    <div class="fm-tab-panel" data-tab-panel="downloads">
      <div class="fm-section-toolbar"><div><strong>下载任务 <em data-section-count="downloads">0</em></strong><span>模型下载与节点安装任务统一显示</span></div><div><button data-action="refresh-downloads">↻ 刷新任务</button></div></div>
      <div class="fm-downloads"></div>
    </div>
    <div class="fm-tab-panel" data-tab-panel="settings">
      <div class="fm-section-toolbar"><div><strong>设置</strong><span>配置外部模型库与夸克网盘下载能力</span></div></div>
      <div class="fm-settings-card"><strong>外部模型库</strong><span>指定本机外部模型目录，只精确匹配当前工作流缺失的模型文件名。</span>
        <div class="fm-external-config">
          <input data-external-folder type="text" placeholder="请选择外部模型库文件夹" readonly>
          <button data-action="select-external-folder">选择文件夹</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(panel);
  const savedWidth = Number(localStorage.getItem("findmodels.panelWidth"));
  if (Number.isFinite(savedWidth) && savedWidth >= 420) panel.style.width = `${savedWidth}px`;
  enablePanelResize(panel);
  panel.querySelector('[data-tab-panel="settings"]')?.insertAdjacentHTML("beforeend", `
    <div class="fm-settings-card"><strong>夸克模型库</strong><span>“查找下载来源”会分页递归到分享目录最深层，并只下载文件名完全一致的模型。公开分享的大文件可能要求有效登录 Cookie。</span>
      <div class="fm-quark-libraries" data-quark-libraries><span>正在读取分享库状态…</span></div>
      <button data-action="check-quark-libraries">检测分享链接</button>
      <div class="fm-quark-auth-config">
        <input data-quark-cookie type="password" placeholder="可选：夸克登录 Cookie（仅保存在本机）">
        <button data-action="save-quark-cookie">保存</button>
        <button data-action="clear-quark-cookie">清除</button>
      </div>
      <span data-quark-auth-status>正在检查夸克登录态...</span>
    </div>`);
  const renderQuarkLibraries = (result) => {
    const libraries = panel.querySelector("[data-quark-libraries]");
    if (libraries) libraries.innerHTML = (result.libraries || []).map((library) => `
      <div class="fm-quark-library">
        <div><strong>${escapeHtml(library.name)}</strong><a href="${escapeHtml(library.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(library.url)}</a></div>
        <span class="${library.reachable === false ? "failed" : "ready"}">${library.reachable === false ? "连接失败" : library.reachable === true ? "连接正常" : "已配置"}</span>
      </div>`).join("");
  };
  get("/findmodels/quark-auth").then((result) => {
    renderQuarkLibraries(result);
    const status = panel.querySelector("[data-quark-auth-status]");
    if (status) status.textContent = result.configured ? "已保存夸克登录态，可重试直链下载。" : "未保存夸克登录态，公开分享大文件可能被夸克限制。";
  }).catch(() => {});
  panel.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => setActiveTab(panel, button.dataset.tab);
  });
  setActiveTab(panel, activeTab);
  panel.querySelector('[data-action="close"]').onclick = () => {
    closeDockedPanel(panel);
  };
  panel.querySelectorAll('[data-action="scan"]').forEach((button) => {
    button.onclick = () => scheduleScan(0, true);
  });
  panel.querySelector('[data-action="refresh-downloads"]').onclick = () => refreshDownloadJobs();
  panel.querySelector('[data-action="install-missing-nodes"]').onclick = async () => {
    const button = panel.querySelector('[data-action="install-missing-nodes"]');
    button.disabled = true;
    let installed = 0;
    const failures = [];
    const packages = lastResult?.missing_node_packages || [];
    for (const nodePackage of packages) {
      const nodeType = nodePackage.node_types?.[0] || "";
      const packageId = nodePackage.known ? nodePackage.id : "";
      const activityId = packageId || nodeType;
      nodeActivities.set(activityId, { title: nodePackage.title, status: "downloading", progress: 15, message: "正在查找可信插件来源…" });
      await refreshDownloadJobs();
      button.textContent = `正在查找 ${nodePackage.title}…`;
      try {
        const found = await post("/findnodes/candidates", { node_type: nodeType, package_id: packageId });
        const candidate = (found.candidates || []).find((item) => [
          "workflow_package_id",
          "workflow_package_github",
          "official_node_mapping",
          "comfy_manager_node_mapping",
          "comfy_manager_github",
        ].includes(item.reason));
        if (!candidate) throw new Error("没有找到由工作流 aux_id 或 ComfyUI-Manager 官方映射确认的 GitHub 仓库");
        button.textContent = `正在安装 ${nodePackage.title}…`;
        nodeActivities.set(activityId, { title: nodePackage.title, status: "downloading", progress: 55, message: "正在检查 requirements.txt、依赖冲突并安装…" });
        await refreshDownloadJobs();
        await post("/findnodes/install", {
          node_type: nodeType,
          package_id: packageId,
          plugin_id: candidate.id,
          install_dependencies: installDependenciesEnabled(panel),
        });
        resolvedNodePackages.add(activityId);
        nodeActivities.set(activityId, { title: nodePackage.title, status: "completed", progress: 100, message: "安装完成，重启 ComfyUI 后生效" });
        installed += 1;
      } catch (error) {
        nodeActivities.set(activityId, { title: nodePackage.title, status: "failed", progress: 100, message: `安装失败：${error.message}` });
        failures.push(`${nodePackage.title}: ${error.message}`);
      }
      await refreshDownloadJobs();
    }
    button.disabled = false;
    button.textContent = "安装缺失节点";
    panel.querySelector(".fm-summary").textContent =
      `已安装或更新 ${installed} 个精确匹配插件。${failures.length ? `失败 ${failures.length} 个：${failures.join("；")}` : "请重启 ComfyUI。"}`
    if (installed) {
      render(lastResult);
      scheduleScan(0, true);
    }
  };
  panel.querySelector('[data-action="select-external-folder"]').onclick = async () => {
    const button = panel.querySelector('[data-action="select-external-folder"]');
    const input = panel.querySelector("[data-external-folder]");
    button.disabled = true;
    button.textContent = "等待选择…";
    try {
      const result = await post("/findmodels/external-folder/select", {});
      if (!result.cancelled) {
        input.value = result.path;
        scheduleScan(0, true);
        scheduleEnrichedScan();
      }
    } catch (error) {
      panel.querySelector(".fm-summary").textContent = `选择外部模型库失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "选择文件夹";
    }
  };
  panel.querySelector('[data-action="install-custom-github"]').onclick = async () => {
    const button = panel.querySelector('[data-action="install-custom-github"]');
    const input = panel.querySelector("[data-custom-github]");
    const nodePackage = lastResult?.missing_node_packages?.[0];
    const nodeType = nodePackage?.node_types?.[0] || "CustomNode";
    if (!input.value.trim()) {
      panel.querySelector(".fm-summary").textContent = "请输入完整的 GitHub 插件仓库链接。";
      return;
    }
    button.disabled = true;
    button.textContent = "正在安装…";
    const activityId = input.value.trim();
    nodeActivities.set(activityId, { title: activityId, status: "downloading", progress: 45, message: "正在克隆仓库并检查 requirements.txt…" });
    await refreshDownloadJobs();
    try {
      const result = await post("/findnodes/install", {
        node_type: nodeType,
        package_id: nodePackage?.known ? nodePackage.id : "custom-github",
        repo_url: input.value.trim(),
        install_dependencies: installDependenciesEnabled(panel),
      });
      input.value = "";
      nodeActivities.set(activityId, { title: result.title, status: "completed", progress: 100, message: "安装完成，重启 ComfyUI 后生效" });
      panel.querySelector(".fm-summary").textContent = `${result.title} 已安装，请重启 ComfyUI。`;
      await refreshDownloadJobs();
    } catch (error) {
      nodeActivities.set(activityId, { title: activityId, status: "failed", progress: 100, message: `安装失败：${error.message}` });
      panel.querySelector(".fm-summary").textContent = `GitHub 插件安装失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "链接安装插件";
    }
  };
  panel.querySelector('[data-action="check-quark-libraries"]').onclick = async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "正在检测…";
    try {
      const result = await post("/findmodels/quark-libraries/check", {});
      renderQuarkLibraries(result);
      panel.querySelector("[data-quark-auth-status]").textContent = result.configured
        ? "分享链接可用性已刷新；已配置登录 Cookie。"
        : "分享链接可用性已刷新；大文件直链仍可能要求登录 Cookie。";
    } catch (error) {
      panel.querySelector("[data-quark-auth-status]").textContent = `检测夸克分享链接失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "检测分享链接";
    }
  };
  panel.querySelector('[data-action="save-quark-cookie"]').onclick = async () => {
    const input = panel.querySelector("[data-quark-cookie]");
    const status = panel.querySelector("[data-quark-auth-status]");
    try {
      const result = await post("/findmodels/quark-auth", { cookie: input.value });
      input.value = "";
      status.textContent = result.configured ? "已保存夸克登录态，可重试直链下载。" : "Cookie 为空，未保存登录态。";
    } catch (error) {
      status.textContent = `保存夸克登录态失败：${error.message}`;
    }
  };
  panel.querySelector('[data-action="clear-quark-cookie"]').onclick = async () => {
    const input = panel.querySelector("[data-quark-cookie]");
    const status = panel.querySelector("[data-quark-auth-status]");
    try {
      await post("/findmodels/quark-auth", { cookie: "" });
      input.value = "";
      status.textContent = "已清除夸克登录态。";
    } catch (error) {
      status.textContent = `清除夸克登录态失败：${error.message}`;
    }
  };
  panel.querySelector('[data-action="adapt"]').onclick = async () => {
    const button = panel.querySelector('[data-action="adapt"]');
    button.disabled = true;
    let count = 0;
    let failed = 0;
    for (const model of lastResult?.models || []) {
      if (!model.match?.auto_apply) continue;
      if (await applyMatchEverywhere(model)) count += 1;
      else failed += 1;
    }
    panel.querySelector(".fm-summary").textContent =
      `已加载 ${count} 个模型${failed ? `，${failed} 个加载失败` : ""}。请检查节点后保存工作流。`;
    button.disabled = false;
    if (count) {
      for (const model of [...(lastResult?.models || [])]) {
        if (model.match?.auto_apply) removeResolvedModel(model.name);
      }
      scheduleScan(0, true);
    }
  };
  panel.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-model-name]");
    if (copyButton) {
      try {
        await copyText(copyButton.dataset.copyModelName);
        const original = copyButton.textContent;
        copyButton.textContent = "已复制";
        window.setTimeout(() => { copyButton.textContent = original; }, 1200);
      } catch (error) {
        panel.querySelector(".fm-summary").textContent = `复制模型名称失败：${error.message}`;
      }
      return;
    }

    const locateButton = event.target.closest("[data-locate-node]");
    if (locateButton) {
      if (!locateNode(locateButton.dataset.locateNode)) {
        panel.querySelector(".fm-summary").textContent = "无法定位节点，节点可能已被删除。";
      }
      return;
    }

    const controlButton = event.target.closest("[data-download-control]");
    if (controlButton) {
      controlButton.disabled = true;
      try {
        await post(`/findmodels/download/${controlButton.dataset.downloadControl}`, {
          job_id: controlButton.dataset.jobId,
        });
        await refreshDownloadJobs();
      } catch (error) {
        panel.querySelector(".fm-summary").textContent = `下载任务操作失败：${error.message}`;
        controlButton.disabled = false;
      }
      return;
    }

    const nodeRefreshButton = event.target.closest("[data-node-refresh]");
    if (nodeRefreshButton) {
      nodeRefreshButton.disabled = true;
      nodeRefreshButton.textContent = "正在查找…";
      const target = nodeRefreshButton.closest(".fm-item").querySelector(".fm-node-candidates");
      try {
        const data = await post("/findnodes/candidates", {
          node_type: nodeRefreshButton.dataset.nodeRefresh,
          package_id: nodeRefreshButton.dataset.packageId,
        });
        target.innerHTML = nodeCandidatesHtml(
          data.node_type,
          data.candidates || [],
          data.github_search_url,
          data.package_id,
        );
      } catch (error) {
        nodeRefreshButton.disabled = false;
        nodeRefreshButton.textContent = "重新查找插件";
        panel.querySelector(".fm-summary").textContent = `查找缺失节点插件失败：${error.message}`;
      }
      return;
    }

    const moveButton = event.target.closest("[data-external-move]");
    if (moveButton) {
      moveButton.disabled = true;
      moveButton.textContent = "正在剪切…";
      try {
        const moved = await post("/findmodels/external-move", {
          source: moveButton.dataset.externalMove,
          name: moveButton.dataset.name,
          category: moveButton.dataset.category,
        });
        const model = (lastResult?.models || []).find((item) => item.name === moveButton.dataset.name);
        const references = model?.referencing_nodes?.length
          ? model.referencing_nodes
          : [{ node_id: moveButton.dataset.nodeId, widget: moveButton.dataset.widget }];
        for (const reference of references) {
          await applyMatch({
            ...reference,
            name: moveButton.dataset.name,
            match: { name: moved.relative_name },
          });
        }
        removeResolvedModel(moveButton.dataset.name);
        panel.querySelector(".fm-summary").textContent =
          `已剪切 ${moved.relative_name} 到 ${moved.category} 模型目录。`;
        scheduleScan(0, true);
        scheduleEnrichedScan();
      } catch (error) {
        moveButton.disabled = false;
        moveButton.textContent = "剪切失败，重试";
        panel.querySelector(".fm-summary").textContent = `剪切模型失败：${error.message}`;
      }
      return;
    }

    const installButton = event.target.closest("[data-node-install]");
    if (installButton) {
      const activityId = installButton.dataset.packageId || installButton.dataset.nodeType;
      installButton.disabled = true;
      installButton.textContent = "正在检查依赖并安装…";
      nodeActivities.set(activityId, { title: activityId, status: "downloading", progress: 50, message: "正在检查 requirements.txt、依赖冲突并安装…" });
      await refreshDownloadJobs();
      try {
        const result = await post("/findnodes/install", {
          node_type: installButton.dataset.nodeType,
          package_id: installButton.dataset.packageId,
          plugin_id: installButton.dataset.nodeInstall,
          install_dependencies: installDependenciesEnabled(panel),
        });
        resolvedNodePackages.add(activityId);
        nodeActivities.set(activityId, {
          title: result.title,
          status: "completed",
          progress: 100,
          message: "安装完成，重启 ComfyUI 后生效",
        });
        installButton.textContent = result.action === "updated" ? "更新完成，需重启" : "安装完成，需重启";
        panel.querySelector(".fm-summary").textContent =
          `${result.title} 已${result.action === "updated" ? "更新" : "安装"}；`
          + `${result.new_conflicts?.length ? `发现 ${result.new_conflicts.length} 个新增依赖冲突，请查看终端。` : "未发现新增依赖冲突。"}`
          + "请重启 ComfyUI。";
        await refreshDownloadJobs();
        render(lastResult);
        scheduleScan(0, true);
      } catch (error) {
        nodeActivities.set(activityId, { title: activityId, status: "failed", progress: 100, message: `安装失败：${error.message}` });
        await refreshDownloadJobs();
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
        if (data.size) {
          model.size = data.size;
          const sizeLabel = sourceButton.closest(".fm-item").querySelector("[data-model-size]");
          if (sizeLabel) sizeLabel.textContent = `大小：${formatSize(data.size)}`;
        }
        const links = data.candidates.map((item) => sourceHtml(item, model)).join("");
        const searches = data.search_urls
          ? `<div class="fm-node-actions"><a href="${escapeHtml(data.search_urls.huggingface)}" target="_blank" rel="noopener noreferrer">Hugging Face 搜索</a><a href="${escapeHtml(data.search_urls.civitai)}" target="_blank" rel="noopener noreferrer">Civitai 搜索</a></div>`
          : "";
        target.innerHTML = links
          ? `${data.exact_count ? "" : '<span class="fm-candidate-warning">未找到完全同名文件，以下为高置信相似候选，需人工核对。</span>'}${links}${searches}`
          : `<span>未找到完全同名或高置信候选。</span>${searches}`;
      } catch (error) {
        target.textContent = `获取下载项失败：${error.message}`;
      } finally {
        sourceButton.disabled = false;
        sourceButton.textContent = "查找下载来源";
      }
      return;
    }

    const downloadButton = event.target.closest("[data-download]");
    if (!downloadButton) return;
    downloadButton.disabled = true;
    downloadButton.textContent = "正在下载…";
    try {
      const job = await post("/findmodels/download/start", {
        url: downloadButton.dataset.download,
        quark: downloadButton.dataset.quarkDownload ? JSON.parse(downloadButton.dataset.quarkDownload) : null,
        filename: downloadButton.dataset.filename,
        size: downloadButton.dataset.size || null,
        category: downloadButton.dataset.category,
        node_id: downloadButton.dataset.nodeId,
        widget: downloadButton.dataset.widget,
        original: downloadButton.dataset.original,
      });
      downloadStatuses.set(job.id, job.status);
      downloadButton.textContent = "后台下载中";
      await refreshDownloadJobs();
    } catch (error) {
      downloadButton.disabled = false;
      downloadButton.textContent = "下载失败，重试";
      panel.querySelector(".fm-summary").textContent = `下载失败：${error.message}`;
    }
  });
  return panel;
}

function render(result) {
  const panel = ensurePanel();
  result.models = result.models || [];
  result.summary = { ...result.summary, unresolved: result.models.length };
  lastResult = result;
  const summary = result.summary;
  const missingNodePackages = (result.missing_node_packages || []).filter((nodePackage) => {
    const nodeType = nodePackage.node_types?.[0] || "";
    return !resolvedNodePackages.has(nodePackage.id) && !resolvedNodePackages.has(nodeType);
  });
  const missingNodeCandidates = result.missing_node_candidates || {};
  updateToolbarButton(summary.unresolved + missingNodePackages.length);
  panel.querySelector('[data-tab-count="models"]').textContent = summary.unresolved;
  panel.querySelector('[data-tab-count="nodes"]').textContent = missingNodePackages.length;
  panel.querySelector('[data-section-count="models"]').textContent = summary.unresolved;
  panel.querySelector('[data-section-count="nodes"]').textContent = missingNodePackages.length;
  const scanStatus = panel.querySelector("[data-scan-status]");
  if (scanStatus) {
    scanStatus.textContent = result.quick
      ? "已快速识别，正在补充外部模型库候选…"
      : "当前工作流扫描完成";
  }
  const externalInput = panel.querySelector("[data-external-folder]");
  if (externalInput && document.activeElement !== externalInput) {
    externalInput.value = result.external_folder || "";
  }
  panel.querySelector(".fm-summary").innerHTML =
    `<span class="fm-summary-ok">✓</span><span>当前页面仅显示尚未解决的依赖项</span>`;
  const nodeHtml = missingNodePackages.map((nodePackage) => {
    const nodeType = nodePackage.node_types?.[0] || "";
    const nodeIds = nodePackage.node_ids || [];
    return `
    <article class="fm-item fm-missing">
      <div class="fm-item-title"><span class="fm-status-icon">!</span><strong>${escapeHtml(nodePackage.title)}</strong><span class="fm-badge">${nodePackage.known ? "缺失节点包" : "未知包"}</span></div>
      <div class="fm-meta"><span>${nodePackage.count} 个节点</span>${nodePackage.version ? `<span>${escapeHtml(nodePackage.version)}</span>` : ""}</div>
      <div class="fm-node-types">${(nodePackage.node_types || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
      ${nodeIds[0] ? `<div class="fm-item-actions"><button data-locate-node="${escapeHtml(nodeIds[0])}">定位节点</button></div>` : ""}
      <div class="fm-node-candidates">${nodeCandidatesHtml(nodeType, missingNodeCandidates[nodeType] || [], "", nodePackage.known ? nodePackage.id : "")}</div>
    </article>`;
  }).join("");
  const modelsHtml = (result.models || []).map(modelCardHtml).join("");
  panel.querySelector(".fm-model-list").innerHTML = modelsHtml
    ? `<div class="fm-table-head fm-model-head"><span>文件名</span><span>类型 / 引用 / 本地候选</span><span>操作</span></div>${modelsHtml}<div class="fm-table-foot">共 ${result.models.length} 项</div>`
    : '<div class="fm-empty"><strong>未发现缺失模型</strong><span>当前工作流模型已就绪</span></div>';
  panel.querySelector(".fm-node-list").innerHTML = nodeHtml
    ? `<div class="fm-table-head fm-node-head"><span>包名（节点集）</span><span>引用 / 来源</span><span>操作</span></div>${nodeHtml}<div class="fm-table-foot">共 ${missingNodePackages.length} 项</div>`
    : '<div class="fm-empty"><strong>未发现缺失节点</strong><span>当前工作流节点均已注册</span></div>';
  panel.querySelectorAll("[data-apply]").forEach((button) => {
    button.onclick = async () => {
      const model = result.models.find((item) => `${item.node_id}:${item.widget}` === button.dataset.apply);
      if (model && await applyMatchEverywhere(model)) {
        removeResolvedModel(model.name);
        scheduleScan(0, true);
      }
    };
  });
}

async function scan(quiet = false, { quick = false } = {}) {
  const panel = ensurePanel();
  const snapshot = workflowSnapshot();
  const signature = workflowSignature(snapshot);
  const requestId = ++scanRequestId;
  updateToolbarButton(null, "扫描中");
  const scanStatus = panel.querySelector("[data-scan-status]");
  if (scanStatus) scanStatus.textContent = quick ? "正在快速识别当前工作流…" : "正在补充外部模型库候选…";
  if (!quiet && !lastResult) panel.querySelector(".fm-summary").textContent = "正在扫描…";
  try {
    const result = await post("/findmodels/scan", { ...snapshot, quick });
    if (requestId !== scanRequestId || signature !== workflowSignature(workflowSnapshot())) return;
    render(result);
    if (quick) scheduleEnrichedScan();
  } catch (error) {
    if (requestId !== scanRequestId) return;
    updateToolbarButton(null, "扫描失败");
    if (scanStatus) scanStatus.textContent = `扫描失败：${error.message}`;
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

function findPropertyPanelButton() {
  const selectors = [
    "button[aria-label='开关属性面板']",
    "button[title='开关属性面板']",
    "button[aria-label*='属性面板']",
    "button[title*='属性面板']",
    "button[aria-label*='Toggle property panel']",
    "button[title*='Toggle property panel']",
  ];
  const direct = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (direct) return direct;
  return [...document.querySelectorAll("button")].find((button) =>
    ["开关属性面板", "Toggle property panel"].includes(button.textContent?.trim()),
  );
}

function findActiveTasksButton() {
  return [...document.querySelectorAll("button")].find((button) =>
    /(?:\d+\s*个活动任务|\d+\s*active tasks?)/i.test(button.textContent?.trim() || ""),
  );
}

function findTopToolbar() {
  const propertyButton = findPropertyPanelButton();
  if (propertyButton?.parentElement) return propertyButton.parentElement;
  const activeTasksButton = findActiveTasksButton();
  if (activeTasksButton?.parentElement) return activeTasksButton.parentElement;
  const runButton = findRunButton();
  if (runButton?.parentElement) return runButton.parentElement;
  return document.querySelector(
    "[data-testid='topbar'], header, .comfyui-body-top, .comfy-menu, #comfy-menu",
  );
}

function mountToolbarButton() {
  let existing = document.getElementById("find-models-launcher");
  const propertyButton = findPropertyPanelButton();
  const activeTasksButton = findActiveTasksButton();
  const runButton = findRunButton();
  const toolbar = findTopToolbar();

  if (!existing) {
    existing = document.createElement("button");
    existing.id = "find-models-launcher";
    existing.type = "button";
    existing.textContent = "查找模型";
    existing.title = "扫描当前工作流中的缺失模型";
    document.body.appendChild(existing);
  }
  existing.onclick = async () => {
    const panel = ensurePanel();
    if (panel.classList.contains("open")) {
      scan(true, { quick: true });
      return;
    }
    await openDockedPanel(panel);
    scan(true, { quick: true });
  };

  if (toolbar) {
    existing.classList.remove("toolbar-fallback");
    if (existing.parentElement !== toolbar) {
      if (propertyButton) propertyButton.insertAdjacentElement("beforebegin", existing);
      else if (activeTasksButton) activeTasksButton.insertAdjacentElement("afterend", existing);
      else if (runButton) runButton.insertAdjacentElement("afterend", existing);
      else toolbar.appendChild(existing);
    } else if (propertyButton && existing.nextElementSibling !== propertyButton) {
      propertyButton.insertAdjacentElement("beforebegin", existing);
    } else if (!propertyButton && activeTasksButton && activeTasksButton.nextElementSibling !== existing) {
      activeTasksButton.insertAdjacentElement("afterend", existing);
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
    ensurePanel().classList.remove("open");
    watchTopToolbar();
    startDownloadMonitor();
    startWorkflowMonitor();
    scheduleScan(0, true);
  },
  async afterConfigureGraph() {
    scanRequestId += 1;
    resolvedNodePackages.clear();
    scheduleScan(0, true);
  },
});
