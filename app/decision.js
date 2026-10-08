"use strict";
/* 「决策训练」页：训练环境、数据集（标注 / 导入）、模型、训练任务。和 workbench.html 里的脚本共用 I18N、S、t()、h()、$()、api()、
   questionFromSpec()、pretty()、pct()、toast() 等工具；接口见 docs/CONTRACT.md §5。 */
(function () {

/* ---------- 文案 / UI strings ---------- */
Object.assign(I18N.zh, {
  "d.env": "训练环境", "d.refresh": "重新探测", "d.probing": "正在探测…", "d.device": "设备", "d.gpu": "显卡", "d.vram": "显存", "d.tier": "档位",
  "d.noGpu": "没有检测到显卡（用 CPU）", "d.notInstalled": "未安装", "d.installed": "已安装", "d.cliMissing": "找不到训练脚本 app/decision_train.py",
  "d.unavailable": "当前环境没有安装训练组件（torch / laya），只能管理数据集。重新运行安装脚本（install.bat / install.sh）并保持 install_training 为 true 即可补装。",
  "d.recommend": "推荐", "d.recLine": "编码器 {enc}　模式 {mode}　micro_batch × grad_accum = {mb} × {ga}　max_len {ml}",
  "d.svc": "决策模型服务", "d.svc.running": "运行中", "d.svc.paused": "训练中已暂停", "d.svc.starting": "启动中…", "d.svc.exited": "已退出（代码 {n}）",
  "d.svc.disabled": "未启用", "d.svc.external": "使用外部服务", "d.svc.active": "默认模型：{name}", "d.svc.official": "默认模型：官方 {name}",
  "d.tier.small": "小（无 GPU 或 < 6 GB）", "d.tier.base": "中（6–11 GB）", "d.tier.large": "大（≥ 11 GB）",
  "d.datasets": "数据集", "d.dataset": "数据集", "d.newName": "新数据集的名字（字母、数字、中文）", "d.newTitle": "标题（可选）", "d.create": "新建",
  "d.noDatasets": "还没有数据集。新建一个，然后用右边的标注器逐条添加，或者粘贴 JSONL / CSV 导入。", "d.rows": "{n} 条", "d.created": "创建于 {t}",
  "d.template": "题目模板", "d.noTemplate": "（还没有题目）", "d.export": "导出 JSONL", "d.delDataset": "删除数据集", "d.confirm": "确认删除",
  "d.th.n": "#", "d.th.state": "素材", "d.th.expected": "正确答案", "d.th.op": "", "d.delRow": "删除", "d.page": "第 {a} – {b} 条，共 {n} 条", "d.prev": "上一页", "d.next": "下一页",
  "d.noRows": "这个数据集还没有数据", "d.deleted": "已删除", "d.needName": "请先填写名字",
  "d.tab.label": "标注", "d.tab.import": "导入", "d.tab.reviews": "从检测方案导入",
  "d.state": "素材（state）", "d.statePh": "粘贴一段要判定的文本，比如一条检测记录、一封邮件、一段对话",
  "d.questions": "题目", "d.loadTemplate": "载入模板", "d.fromText": "用文本判定页的题目", "d.qEmpty": "添加题目，或从数据集的题目模板 / 文本判定页载入",
  "d.expected": "正确答案", "d.add": "加入数据集", "d.added": "已加入，数据集现有 {n} 条", "d.needDataset": "请先选择或新建一个数据集",
  "d.needState": "请填写素材", "d.needQuestions": "请至少添加一道题目", "d.qProblem": "题目有问题：{msg}",
  "d.fmt": "格式", "d.pasteJsonl": "每行一个 JSON 对象：{\"state\": …, \"questions\": {…}, \"expected\": {…}}；也接受文本判定页复核导出的 {state, questions, gold}",
  "d.pasteCsv": "第一行是列名，至少要有文本列和标签列；每行变成一道单选题", "d.chooseFile": "选择文件", "d.import": "导入", "d.importing": "导入中…",
  "d.textCol": "文本列", "d.labelCol": "标签列", "d.qId": "题目 ID", "d.qIns": "题目文本（问模型的问题）", "d.qInsPh": "例如：这条评价的情绪是？",
  "d.importTarget": "导入到数据集", "d.needText": "请先粘贴内容或选择文件", "d.imported": "已导入 {n} 条{skipped}", "d.skipped": "，跳过 {n} 条有问题的行", "d.skipList": "被跳过的行",
  "d.reviewsNote": "把「视觉检测」里某个方案的自检边界用例（答案来自硬规则）和人工复核记录导入成训练数据。", "d.recipe": "检测方案",
  "d.models": "模型", "d.noModels": "还没有模型。先在右边用一个编码器新建空白模型，或者直接以官方权重为起点训练。",
  "d.active": "当前默认", "d.training": "训练中", "d.incomplete": "未完成", "d.setActive": "设为默认", "d.unsetActive": "取消默认", "d.evaluate": "评估", "d.info": "详情", "d.delete": "删除",
  "d.modelMeta": "底座 {enc}　{params}　{size} MB　{acc}　{time}", "d.params": "{n} M 参数", "d.acc": "留出集准确率 {v}", "d.noAcc": "未评估",
  "d.activated": "已设为默认并重启模型服务", "d.activatedNoRestart": "已写入 config.json；模型服务不是本启动器拉起的，请手动重启", "d.evalNeedDataset": "评估需要先选一个数据集",
  "d.newModel": "新建模型", "d.encoder": "编码器（Hugging Face）", "d.customEnc": "或者填一个 Hugging Face 模型 id", "d.modelName": "模型名字", "d.headLayers": "决策头层数", "d.maxLen": "max_len",
  "d.build": "新建", "d.building": "新建中…", "d.needEncoder": "请选择或填写编码器", "d.newNote": "新建的是空白的 Laya 格式模型：编码器用预训练权重，决策头随机初始化，必须训练后才能用。首次使用某个编码器要从 Hugging Face 下载。",
  "d.recStar": "推荐", "d.official": "官方 Laya 权重",
  "d.train": "训练", "d.base": "起点", "d.baseModel": "已有模型", "d.baseOfficial": "官方权重", "d.outName": "训练结果保存为", "d.mode": "模式",
  "d.mode.full": "full（全部参数）", "d.mode.freeze": "freeze（冻结词嵌入）", "d.mode.lora": "lora（低秩适配，省显存）",
  "d.epochs": "轮数", "d.mb": "micro_batch", "d.ga": "grad_accum", "d.encLr": "编码器学习率", "d.headLr": "决策头学习率", "d.loss": "损失", "d.holdout": "留出比例",
  "d.resume": "续训（从 checkpoint_latest 继续）", "d.start": "开始训练", "d.cancel": "取消", "d.cancelling": "取消中…",
  "d.needBase": "请选择起点", "d.needOut": "请填写保存名字", "d.needPeft": "lora 模式需要 peft，当前环境没有安装",
  "d.job": "任务", "d.noJob": "还没有任务。填好左边的参数点「开始训练」。", "d.state.queued": "排队中", "d.state.running": "运行中", "d.state.done": "完成", "d.state.error": "失败", "d.state.cancelled": "已取消",
  "d.stage.download": "下载", "d.stage.prepare": "准备数据", "d.stage.train": "训练", "d.stage.calibrate": "校准", "d.stage.save": "保存", "d.stage.evaluate": "评估",
  "d.epoch": "第 {a}/{b} 轮", "d.step": "步 {a}/{b}", "d.lossV": "loss {v}", "d.eta": "剩余约 {t}", "d.elapsed": "已用 {t}", "d.oom": "显存不足自动降档 {n} 次",
  "d.lossCurve": "loss 曲线", "d.log": "日志", "d.result": "结果", "d.r.acc": "留出集准确率", "d.r.noul": "是非", "d.r.choice": "单选", "d.r.score": "打分", "d.r.all": "总体",
  "d.r.items": "训练 {a} 条，校准 {b} 条，留出 {c} 条", "d.r.vram": "显存峰值 {v} MB", "d.r.seconds": "用时 {t}", "d.r.epochs": "完成 {n} 轮，模式 {m}", "d.r.skipped": "跳过 {n} 条无法训练的题目",
  "d.r.params": "参数量 {a} M（编码器 {b} M），隐层 {h}", "d.r.calib": "校准温度 {v}", "d.r.perQ": "各题准确率", "d.r.evalItems": "{n} 条",
  "d.kind.new": "新建模型", "d.kind.train": "训练", "d.kind.evaluate": "评估", "d.recent": "最近任务", "d.failed": "失败：{msg}",
  "d.sec": "{s} 秒", "d.min": "{m} 分 {s} 秒", "d.hour": "{h} 小时 {m} 分"
});
Object.assign(I18N.en, {
  "d.env": "Training environment", "d.refresh": "Probe again", "d.probing": "Probing…", "d.device": "Device", "d.gpu": "GPU", "d.vram": "VRAM", "d.tier": "Tier",
  "d.noGpu": "No GPU detected (CPU)", "d.notInstalled": "not installed", "d.installed": "installed", "d.cliMissing": "Training script app/decision_train.py not found",
  "d.unavailable": "The training components (torch / laya) are not installed; only datasets can be managed. Run the installer (install.bat / install.sh) again with install_training true to add them.",
  "d.recommend": "Recommended", "d.recLine": "encoder {enc}, mode {mode}, micro_batch × grad_accum = {mb} × {ga}, max_len {ml}",
  "d.svc": "Decision model service", "d.svc.running": "running", "d.svc.paused": "paused while training", "d.svc.starting": "starting…", "d.svc.exited": "exited (code {n})",
  "d.svc.disabled": "not enabled", "d.svc.external": "using an external service", "d.svc.active": "default model: {name}", "d.svc.official": "default model: official {name}",
  "d.tier.small": "small (no GPU or < 6 GB)", "d.tier.base": "base (6–11 GB)", "d.tier.large": "large (≥ 11 GB)",
  "d.datasets": "Datasets", "d.dataset": "Dataset", "d.newName": "Name of the new dataset (letters, digits)", "d.newTitle": "Title (optional)", "d.create": "Create",
  "d.noDatasets": "No datasets yet. Create one, then add rows with the labeler on the right or paste JSONL / CSV to import.", "d.rows": "{n} rows", "d.created": "created {t}",
  "d.template": "Question template", "d.noTemplate": "(no questions yet)", "d.export": "Export JSONL", "d.delDataset": "Delete dataset", "d.confirm": "Confirm delete",
  "d.th.n": "#", "d.th.state": "Material", "d.th.expected": "Expected", "d.th.op": "", "d.delRow": "Delete", "d.page": "Rows {a} – {b} of {n}", "d.prev": "Previous", "d.next": "Next",
  "d.noRows": "This dataset has no rows yet", "d.deleted": "Deleted", "d.needName": "Enter a name first",
  "d.tab.label": "Label", "d.tab.import": "Import", "d.tab.reviews": "From a recipe",
  "d.state": "Material (state)", "d.statePh": "Paste the text to decide on: an inspection record, an email, a conversation…",
  "d.questions": "Questions", "d.loadTemplate": "Load template", "d.fromText": "Use the Text decisions questions", "d.qEmpty": "Add questions, or load them from the dataset template / the Text decisions page",
  "d.expected": "Expected answer", "d.add": "Add to dataset", "d.added": "Added; the dataset now has {n} rows", "d.needDataset": "Select or create a dataset first",
  "d.needState": "Enter the material", "d.needQuestions": "Add at least one question", "d.qProblem": "Question problem: {msg}",
  "d.fmt": "Format", "d.pasteJsonl": "One JSON object per line: {\"state\": …, \"questions\": {…}, \"expected\": {…}}; the {state, questions, gold} review export also works",
  "d.pasteCsv": "The first line holds column names; a text column and a label column are needed. Each row becomes one choice question", "d.chooseFile": "Choose file", "d.import": "Import", "d.importing": "Importing…",
  "d.textCol": "Text column", "d.labelCol": "Label column", "d.qId": "Question ID", "d.qIns": "Question text (what to ask the model)", "d.qInsPh": "e.g. What is the sentiment of this review?",
  "d.importTarget": "Import into dataset", "d.needText": "Paste some content or choose a file first", "d.imported": "Imported {n} rows{skipped}", "d.skipped": ", skipped {n} problem rows", "d.skipList": "Skipped rows",
  "d.reviewsNote": "Import a recipe's self-test boundary cases (answers from the hard rules) plus its human review records from Visual inspection as training data.", "d.recipe": "Recipe",
  "d.models": "Models", "d.noModels": "No models yet. Create a blank model from an encoder on the right, or train directly from the official weights.",
  "d.active": "default", "d.training": "training", "d.incomplete": "incomplete", "d.setActive": "Set as default", "d.unsetActive": "Unset default", "d.evaluate": "Evaluate", "d.info": "Details", "d.delete": "Delete",
  "d.modelMeta": "base {enc}, {params}, {size} MB, {acc}, {time}", "d.params": "{n} M params", "d.acc": "hold-out accuracy {v}", "d.noAcc": "not evaluated",
  "d.activated": "Set as default; the model service is restarting", "d.activatedNoRestart": "Saved to config.json; the model service was not started by this launcher, restart it yourself", "d.evalNeedDataset": "Select a dataset to evaluate on first",
  "d.newModel": "New model", "d.encoder": "Encoder (Hugging Face)", "d.customEnc": "or type a Hugging Face model id", "d.modelName": "Model name", "d.headLayers": "Head layers", "d.maxLen": "max_len",
  "d.build": "Create", "d.building": "Creating…", "d.needEncoder": "Choose or type an encoder", "d.newNote": "This creates a blank Laya-format model: the encoder keeps its pretrained weights, the decision head is random, so it must be trained before use. An encoder is downloaded from Hugging Face on first use.",
  "d.recStar": "recommended", "d.official": "Official Laya weights",
  "d.train": "Train", "d.base": "Starting point", "d.baseModel": "Existing model", "d.baseOfficial": "Official weights", "d.outName": "Save result as", "d.mode": "Mode",
  "d.mode.full": "full (all parameters)", "d.mode.freeze": "freeze (frozen word embeddings)", "d.mode.lora": "lora (low-rank adapters, saves memory)",
  "d.epochs": "Epochs", "d.mb": "micro_batch", "d.ga": "grad_accum", "d.encLr": "Encoder LR", "d.headLr": "Head LR", "d.loss": "Loss", "d.holdout": "Hold-out fraction",
  "d.resume": "Resume (continue from checkpoint_latest)", "d.start": "Start training", "d.cancel": "Cancel", "d.cancelling": "Cancelling…",
  "d.needBase": "Choose a starting point", "d.needOut": "Enter a name to save as", "d.needPeft": "lora mode needs peft, which is not installed",
  "d.job": "Job", "d.noJob": "No job yet. Fill in the parameters on the left and press Start training.", "d.state.queued": "queued", "d.state.running": "running", "d.state.done": "done", "d.state.error": "failed", "d.state.cancelled": "cancelled",
  "d.stage.download": "downloading", "d.stage.prepare": "preparing data", "d.stage.train": "training", "d.stage.calibrate": "calibrating", "d.stage.save": "saving", "d.stage.evaluate": "evaluating",
  "d.epoch": "epoch {a}/{b}", "d.step": "step {a}/{b}", "d.lossV": "loss {v}", "d.eta": "about {t} left", "d.elapsed": "{t} elapsed", "d.oom": "out of memory, downshifted {n}×",
  "d.lossCurve": "Loss curve", "d.log": "Log", "d.result": "Result", "d.r.acc": "Hold-out accuracy", "d.r.noul": "yes/no", "d.r.choice": "choice", "d.r.score": "score", "d.r.all": "overall",
  "d.r.items": "{a} training, {b} calibration, {c} hold-out rows", "d.r.vram": "peak VRAM {v} MB", "d.r.seconds": "took {t}", "d.r.epochs": "{n} epochs done, mode {m}", "d.r.skipped": "{n} untrainable questions skipped",
  "d.r.params": "{a} M parameters (encoder {b} M), hidden {h}", "d.r.calib": "calibration temperature {v}", "d.r.perQ": "Accuracy per question", "d.r.evalItems": "{n} rows",
  "d.kind.new": "New model", "d.kind.train": "Training", "d.kind.evaluate": "Evaluation", "d.recent": "Recent jobs", "d.failed": "Failed: {msg}",
  "d.sec": "{s} s", "d.min": "{m} min {s} s", "d.hour": "{h} h {m} min"
});

/* ---------- 状态 ---------- */
const OFFICIAL = ["multilingual", "english", "typed-decisions"];
const STAGES = ["download", "prepare", "train", "calibrate", "save", "evaluate"];
const D = {
  loaded: false, loading: false, env: null, envLoading: false,
  datasets: [], dataset: "", rows: null, page: 0, pageSize: 20, dsTab: "label", confirm: "", msg: null,
  lab: { state: "", questions: [], expected: {}, msg: null },
  imp: { format: "jsonl", text: "", name: "", csv: { text_column: "text", label_column: "label", question: "label", instructions: "" }, busy: false, msg: null, skipped: [] },
  recipes: [], recipe: "", reviewsMsg: null,
  models: [], info: {}, modelMsg: null,
  nm: { name: "", encoder: "", custom: "", head_layers: 2, max_len: 512, msg: null },
  tr: { base: "", name: "", dataset: "", mode: "", epochs: 4, micro_batch: "", grad_accum: "", encoder_lr: 2.5e-5, head_lr: 1e-4, loss: "rlcd", max_len: "", holdout: 0.1, resume: false, msg: null },
  job: null, jobs: [], polling: false, cancelling: false
};
const DS_KEY = "laya-workbench-decision-dataset", BASE_KEY = "laya-workbench-decision-base";
try { D.dataset = localStorage.getItem(DS_KEY) || ""; D.tr.base = localStorage.getItem(BASE_KEY) || ""; } catch (e) { /* 用默认值 */ }

async function dget(path) {
  const resp = await api(path, { cache: "no-store" });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 不是 JSON */ }
  return { ok: resp.ok, status: resp.status, data: data };
}
async function dpost(path, body) {
  const resp = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 不是 JSON */ }
  return { ok: resp.ok, status: resp.status, data: data };
}
function errText(res) {
  const d = res && res.data;
  if (d && d.detail != null) return typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
  return "HTTP " + (res ? res.status : 0);
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function fmtTime(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return t("d.sec", { s: sec });
  if (sec < 3600) return t("d.min", { m: Math.floor(sec / 60), s: sec % 60 });
  return t("d.hour", { h: Math.floor(sec / 3600), m: Math.floor((sec % 3600) / 60) });
}
function stageText(stage) { return STAGES.includes(stage) ? t("d.stage." + stage) : (stage || ""); }
function num(v, digits) { return v == null || !isFinite(Number(v)) ? "-" : Number(v).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, ""); }
function available() { return !!(D.env && D.env.available); }
function recommend() { return (D.env && D.env.probe && D.env.probe.recommend) || null; }
function decisionStatus() { return (S.status && S.status.decision) || null; }
function activeName() { const d = decisionStatus(); return d && d.active ? d.active : ""; }
function busy() { return !!(D.job && (D.job.state === "queued" || D.job.state === "running")); }
function remember(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* 记不住也没关系 */ } }

/* ---------- 加载 ---------- */
async function loadEnv(refresh) {
  D.envLoading = true; renderEnv();
  const res = await dget("/v1/decision/env" + (refresh ? "?refresh=1" : ""));
  D.env = res.ok ? res.data : { probe: { error: errText(res) }, encoders: [], installed: {}, available: false };
  D.envLoading = false;
  const rec = recommend();
  if (rec) {
    if (!D.tr.mode) D.tr.mode = rec.mode || "full";
    if (D.tr.micro_batch === "") D.tr.micro_batch = rec.micro_batch || 4;
    if (D.tr.grad_accum === "") D.tr.grad_accum = rec.grad_accum || 16;
    if (D.tr.max_len === "") D.tr.max_len = rec.max_len || 512;
    if (!D.nm.encoder) D.nm.encoder = rec.encoder || "";
  }
  render();
}
async function loadDatasets() {
  const res = await dget("/v1/decision/datasets");
  D.datasets = res.ok && Array.isArray(res.data) ? res.data : [];
  if (!D.datasets.some(d => d.name === D.dataset)) D.dataset = D.datasets.length ? D.datasets[0].name : "";
  if (!D.tr.dataset || !D.datasets.some(d => d.name === D.tr.dataset)) D.tr.dataset = D.dataset;
  if (!D.imp.name) D.imp.name = D.dataset;
}
async function loadRows() {
  if (!D.dataset) { D.rows = null; return; }
  const res = await dget("/v1/decision/datasets/rows?name=" + encodeURIComponent(D.dataset) + "&offset=" + (D.page * D.pageSize) + "&limit=" + D.pageSize);
  D.rows = res.ok ? res.data : null;
  if (D.rows && D.rows.offset >= D.rows.total && D.rows.total > 0) { D.page = Math.max(0, Math.ceil(D.rows.total / D.pageSize) - 1); return loadRows(); }
}
async function loadModels() {
  const res = await dget("/v1/decision/models");
  D.models = res.ok && Array.isArray(res.data) ? res.data : [];
}
async function loadJobs() {
  const res = await dget("/v1/decision/jobs");
  D.jobs = res.ok && Array.isArray(res.data) ? res.data : [];
  if (!D.job && D.jobs.length) D.job = D.jobs[0];
  else if (D.job) { const cur = D.jobs.find(j => j.id === D.job.id); if (cur) D.job = cur; }
  if (busy() && !D.polling) watchJob(D.job.id);
}
async function loadRecipes() {
  const res = await dget("/_wb/recipes?lang=" + LANG);
  D.recipes = res.ok && Array.isArray(res.data) ? res.data : [];
  if (!D.recipes.some(r => r.id === D.recipe)) D.recipe = D.recipes.length ? D.recipes[0].id : "";
}
async function loadAll() {
  if (D.loading) return;
  D.loading = true;
  await Promise.all([loadEnv(false), loadDatasets(), loadModels(), loadJobs(), loadRecipes()]);
  await loadRows();
  if (!D.lab.questions.length) loadTemplate();     // 标注器默认带上数据集的题目模板
  D.loaded = true; D.loading = false;
  render();
}
async function selectDataset(name) {
  D.dataset = name; D.page = 0; D.confirm = ""; D.msg = null; D.imp.name = name;
  if (!D.tr.dataset) D.tr.dataset = name;
  remember(DS_KEY, name);
  await loadRows();
  if (!D.lab.questions.length) loadTemplate();
  render();
}
function currentDataset() { return D.datasets.find(d => d.name === D.dataset) || null; }

/* ---------- 任务轮询 ---------- */
async function watchJob(id) {
  if (D.polling) return;
  D.polling = true;
  try {
    while (true) {
      await sleep(1000);
      const res = await dget("/v1/decision/jobs?id=" + encodeURIComponent(id));
      if (!res.ok) { if (D.job && D.job.id === id) D.job = Object.assign({}, D.job, { state: "error", error: errText(res) }); break; }
      D.job = res.data;
      if (!(D.job.state === "queued" || D.job.state === "running")) break;
      renderProgress();
    }
  } finally { D.polling = false; D.cancelling = false; }
  await Promise.all([loadModels(), loadDatasets(), loadJobs()]);
  render();
  pollStatus();
}
async function startJob(path, body, onFail) {
  if (busy()) return;
  const res = await dpost(path, body);
  if (!res.ok) { onFail(errText(res)); return render(); }
  D.job = res.data; D.cancelling = false;
  render();
  watchJob(D.job.id);
  pollStatus();                    // 服务可能被暂停了，让顶部状态尽快反映出来
}
async function cancelJob() {
  if (!busy() || D.cancelling) return;
  D.cancelling = true; renderProgress();
  await dpost("/v1/decision/jobs/cancel", { id: D.job.id });
}

/* ---------- 标注器 ---------- */
let qSeq = 0;
function newQ(type) {
  const taken = new Set(D.lab.questions.map(q => q.id));
  let n = D.lab.questions.length + 1;
  while (taken.has("q" + n)) n++;
  const q = { uid: "d" + (++qSeq), id: "q" + n, type: type, instructions: "", options: [], levels: [], extra: {} };
  if (type === "choice") q.options = [{ key: "a", desc: "" }, { key: "b", desc: "" }];
  if (type === "score") q.levels = ["", "", ""];
  return q;
}
function fromSpecs(specs) {
  return Object.keys(specs || {}).map(id => {
    const spec = specs[id];
    const q = questionFromSpec(id, spec.type === "score" && Array.isArray(spec.levels) ? Object.assign({}, spec, { criteria: spec.levels }) : spec);
    delete q.extra.levels;
    return q;
  });
}
function loadTemplate() {
  const ds = currentDataset();
  if (!ds || !ds.questions || !Object.keys(ds.questions).length) return false;
  D.lab.questions = fromSpecs(ds.questions); D.lab.expected = {}; D.lab.msg = null;
  return true;
}
function specOf(q) {
  const spec = { type: q.type, instructions: q.instructions.trim() };
  if (q.type === "choice") { spec.criteria = {}; q.options.forEach(o => { if (o.key.trim()) spec.criteria[o.key.trim()] = o.desc.trim() || null; }); }
  if (q.type === "score") spec.levels = q.levels.map(v => v.trim());
  return spec;
}
function labelProblem() {
  if (!D.dataset) return t("d.needDataset");
  if (!D.lab.state.trim()) return t("d.needState");
  if (!D.lab.questions.length) return t("d.needQuestions");
  const seen = new Set();
  for (let i = 0; i < D.lab.questions.length; i++) {
    const q = D.lab.questions[i], id = q.id.trim(), name = id || t("p.nth", { n: i + 1 });
    if (!id) return t("d.qProblem", { msg: t("p.noId", { n: i + 1 }) });
    if (seen.has(id)) return t("d.qProblem", { msg: t("p.dupId", { id: id }) });
    seen.add(id);
    if (!q.instructions.trim()) return t("d.qProblem", { msg: t("p.noText", { name: name }) });
    if (q.type === "choice") {
      const keys = q.options.map(o => o.key.trim()).filter(Boolean);
      if (keys.length < 2) return t("d.qProblem", { msg: t("p.opt2", { name: name }) });
      if (new Set(keys).size !== keys.length) return t("d.qProblem", { msg: t("p.optDup", { name: name }) });
    }
    if (q.type === "score" && q.levels.filter(v => v.trim()).length < 2) return t("d.qProblem", { msg: t("p.lvl2", { name: name }) });
  }
  return "";
}
function expectedOptions(q) {
  if (q.type === "noul") return [["true", t("r.yes")], ["false", t("r.no")]];
  if (q.type === "choice") return q.options.map(o => o.key.trim()).filter(Boolean).map(k => [k, k]);
  return q.levels.map((text, i) => [String(i), i + " · " + text]);
}
async function addRow() {
  const problem = labelProblem();
  if (problem) { D.lab.msg = { cls: "bad", text: problem }; return renderLabeler(); }
  const questions = {}, expected = {};
  D.lab.questions.forEach(q => {
    const id = q.id.trim();
    questions[id] = specOf(q);
    const opts = expectedOptions(q);
    const raw = D.lab.expected[q.uid] != null ? D.lab.expected[q.uid] : opts[0][0];
    expected[id] = q.type === "noul" ? raw === "true" : q.type === "score" ? Number(raw) : raw;
  });
  const res = await dpost("/v1/decision/datasets/append", { name: D.dataset, rows: [{ state: D.lab.state, questions: questions, expected: expected }] });
  if (!res.ok) { D.lab.msg = { cls: "bad", text: errText(res) }; return renderLabeler(); }
  D.lab.state = ""; D.lab.msg = { cls: "ok", text: t("d.added", { n: res.data.rows }) };
  await loadDatasets(); await loadRows();
  render();
  const el = $("#d-state"); if (el) el.focus();
}
async function importText() {
  const imp = D.imp;
  const name = imp.name.trim() || D.dataset;
  if (!name) { imp.msg = { cls: "bad", text: t("d.needDataset") }; return render(); }
  if (!imp.text.trim()) { imp.msg = { cls: "bad", text: t("d.needText") }; return render(); }
  imp.busy = true; imp.msg = { cls: "", text: t("d.importing") }; imp.skipped = []; render();
  const res = await dpost("/v1/decision/datasets/import", { name: name, format: imp.format, text: imp.text, csv: imp.csv });
  imp.busy = false;
  if (!res.ok) { imp.msg = { cls: "bad", text: errText(res) }; return render(); }
  imp.text = ""; imp.skipped = res.data.skipped || [];
  imp.msg = { cls: "ok", text: t("d.imported", { n: res.data.added, skipped: res.data.skipped_total ? t("d.skipped", { n: res.data.skipped_total }) : "" }) };
  await loadDatasets();
  if (D.dataset !== name) { D.dataset = name; remember(DS_KEY, name); }
  D.page = 0; await loadRows();
  if (!D.lab.questions.length) loadTemplate();
  render();
}
async function importReviews() {
  const name = D.imp.name.trim() || D.dataset;
  if (!name) { D.reviewsMsg = { cls: "bad", text: t("d.needDataset") }; return render(); }
  if (!D.recipe) return;
  D.reviewsMsg = { cls: "", text: t("d.importing") }; render();
  const res = await dpost("/v1/decision/datasets/from_reviews", { name: name, recipe: D.recipe });
  if (!res.ok) { D.reviewsMsg = { cls: "bad", text: errText(res) }; return render(); }
  D.reviewsMsg = { cls: "ok", text: t("d.imported", { n: res.data.added, skipped: res.data.skipped_total ? t("d.skipped", { n: res.data.skipped_total }) : "" }) };
  await loadDatasets();
  if (D.dataset !== name) { D.dataset = name; remember(DS_KEY, name); }
  D.page = 0; await loadRows();
  if (!D.lab.questions.length) loadTemplate();
  render();
}

/* ---------- 模型操作 ---------- */
async function activate(name) {
  D.modelMsg = null;
  const res = await dpost("/v1/decision/models/activate", { name: name });
  if (!res.ok) { D.modelMsg = { cls: "bad", text: errText(res) }; return render(); }
  D.modelMsg = { cls: "ok", text: res.data.restarted ? t("d.activated") : t("d.activatedNoRestart") };
  await pollStatus(); await loadModels(); render();
}
async function showInfo(name) {
  if (D.info[name]) { delete D.info[name]; return render(); }
  const res = await dget("/v1/decision/models/info?name=" + encodeURIComponent(name));
  D.info[name] = res.ok ? res.data : { error: errText(res) };
  render();
}
function evaluateModel(name) {
  if (!D.tr.dataset) { D.modelMsg = { cls: "bad", text: t("d.evalNeedDataset") }; return render(); }
  startJob("/v1/decision/evaluate", { model: name, dataset: D.tr.dataset }, msg => { D.modelMsg = { cls: "bad", text: msg }; });
}
function buildModel() {
  const nm = D.nm;
  const encoder = (nm.custom.trim() || nm.encoder || "").trim();
  if (!encoder) { nm.msg = { cls: "bad", text: t("d.needEncoder") }; return render(); }
  if (!nm.name.trim()) { nm.msg = { cls: "bad", text: t("d.needName") }; return render(); }
  nm.msg = null;
  startJob("/v1/decision/new", { name: nm.name.trim(), encoder: encoder, head_layers: nm.head_layers, max_len: nm.max_len }, msg => { nm.msg = { cls: "bad", text: msg }; });
}
function startTrain() {
  const tr = D.tr;
  if (!tr.base) { tr.msg = { cls: "bad", text: t("d.needBase") }; return render(); }
  if (!tr.dataset) { tr.msg = { cls: "bad", text: t("d.needDataset") }; return render(); }
  if (!tr.name.trim()) { tr.msg = { cls: "bad", text: t("d.needOut") }; return render(); }
  if (tr.mode === "lora" && D.env && D.env.installed && D.env.installed.peft === false) { tr.msg = { cls: "bad", text: t("d.needPeft") }; return render(); }
  tr.msg = null;
  const body = { name: tr.name.trim(), base: tr.base, dataset: tr.dataset, mode: tr.mode || "full", epochs: tr.epochs, micro_batch: tr.micro_batch, grad_accum: tr.grad_accum,
    encoder_lr: tr.encoder_lr, head_lr: tr.head_lr, loss: tr.loss, max_len: tr.max_len, holdout: tr.holdout, resume: tr.resume };
  startJob("/v1/decision/train", body, msg => { tr.msg = { cls: "bad", text: msg }; });
}

/* ---------- 渲染 ---------- */
function msgLine(m) { return m ? h("div", { class: "prov-msg " + (m.cls || "") }, m.text) : null; }
function field(label, control, id) { return h("div", { class: "vfield" }, h("label", { for: id || null }, label), control); }
function numInput(obj, key, opts) {
  return h("input", Object.assign({ type: "number", value: obj[key] === "" || obj[key] == null ? "" : String(obj[key]), oninput: e => { obj[key] = e.target.value === "" ? "" : Number(e.target.value); } }, opts || {}));
}

function renderEnv() {
  const box = $("#d-env");
  if (!box) return;
  box.textContent = "";
  const env = D.env, probe = env && env.probe, inst = (env && env.installed) || {};
  const head = h("div", { class: "head" }, h("h2", {}, t("d.env")),
    h("button", { class: "btn small", type: "button", disabled: D.envLoading, onclick: () => loadEnv(true) }, D.envLoading ? t("d.probing") : t("d.refresh")));
  box.append(head);
  /* 决策服务状态 */
  const line = h("div", { class: "vstatus" });
  const st = S.status, mode = st && st.service;
  if (st === undefined) line.append(h("span", { class: "dot" }), t("s.connecting"));
  else if (!st) line.append(h("span", { class: "dot bad" }), t("s.offline"));
  else {
    const dot = mode === "running" || mode === "external" ? "ok" : mode === "paused" || mode === "starting" ? "wait" : "bad";
    const text = mode === "running" ? t("d.svc.running") : mode === "external" ? t("d.svc.external") : mode === "paused" ? t("d.svc.paused") : mode === "starting" ? t("d.svc.starting")
      : mode === "exited" ? t("d.svc.exited", { n: st.exit_code }) : t("d.svc.disabled");
    line.append(h("span", { class: "dot " + dot }), t("d.svc") + t("sep.colon") + text);
    const d = decisionStatus();
    if (d) line.append(h("span", { class: "hint" }, d.active ? t("d.svc.active", { name: d.active }) : t("d.svc.official", { name: (d.builtin || "multilingual").split(",")[0] })));
  }
  box.append(line);
  if (!env) { box.append(h("div", { class: "fine" }, t("d.probing"))); return; }
  const kv = h("div", { class: "kv" });
  const cell = (k, v, cls) => kv.append(h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v " + (cls || "") }, v)));
  if (probe && probe.device) {
    cell(t("d.device"), probe.device + (probe.cuda ? "  CUDA " + probe.cuda : ""));
    cell(t("d.gpu"), probe.gpu_name || t("d.noGpu"));
    cell(t("d.vram"), probe.vram_mb ? Math.round(probe.vram_mb / 1024 * 10) / 10 + " GB" : "-");
    cell(t("d.tier"), probe.tier ? t("d.tier." + probe.tier) : "-");
  } else cell(t("d.device"), (probe && probe.error) || "-", "hint bad");
  cell("torch", probe && probe.torch ? probe.torch : (inst.torch ? t("d.installed") : t("d.notInstalled")));
  cell("laya", probe && probe.laya ? probe.laya : (inst.laya ? t("d.installed") : t("d.notInstalled")));
  cell("peft", inst.peft ? t("d.installed") : t("d.notInstalled"));
  cell("torchvision", probe && probe.torchvision ? probe.torchvision : (inst.torchvision ? t("d.installed") : t("d.notInstalled")));
  box.append(kv);
  const rec = recommend();
  if (rec) box.append(h("p", { class: "fine" }, h("strong", {}, t("d.recommend") + t("sep.colon")),
    (LANG === "en" ? rec.note_en : rec.note_zh) || "", " ", t("d.recLine", { enc: rec.encoder, mode: rec.mode, mb: rec.micro_batch, ga: rec.grad_accum, ml: rec.max_len })));
  if (!env.cli) box.append(h("div", { class: "banner info" }, t("d.cliMissing")));
  else if (!env.available) box.append(h("div", { class: "banner info" }, t("d.unavailable")));
}

function renderDatasets() {
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("d.datasets"))));
  const select = h("select", { class: "inline-input grow", "aria-label": t("d.dataset"), onchange: e => selectDataset(e.target.value) });
  D.datasets.forEach(d => select.append(h("option", { value: d.name }, d.name + "  (" + d.rows + ")")));
  select.value = D.dataset;
  const newName = h("input", { class: "inline-input grow", placeholder: t("d.newName") });
  const newTitle = h("input", { class: "inline-input grow", placeholder: t("d.newTitle") });
  const create = async () => {
    const name = newName.value.trim();
    if (!name) return toast(t("d.needName"));
    const res = await dpost("/v1/decision/datasets/create", { name: name, title: newTitle.value.trim() });
    if (!res.ok) { D.msg = { cls: "bad", text: errText(res) }; return render(); }
    D.msg = null; await loadDatasets(); D.lab.questions = []; await selectDataset(name);
  };
  card.append(h("div", { class: "rowline" }, D.datasets.length ? select : null, newName, newTitle,
    h("button", { class: "btn small", type: "button", onclick: create }, t("d.create"))));
  if (D.msg) card.append(msgLine(D.msg));
  const ds = currentDataset();
  if (!ds) { card.append(h("div", { class: "empty" }, t("d.noDatasets"))); return card; }

  const meta = h("div", { class: "fine" }, h("strong", {}, ds.title || ds.name), t("sep.gap"), t("d.rows", { n: ds.rows }), ds.created ? t("sep.gap") + t("d.created", { t: ds.created }) : "", ds.note ? h("br") : null, ds.note || "");
  card.append(meta);
  const qids = Object.keys(ds.questions || {});
  const tpl = h("div", { class: "fine" }, t("d.template") + t("sep.colon"));
  if (!qids.length) tpl.append(t("d.noTemplate"));
  qids.forEach(id => { const q = ds.questions[id]; tpl.append(h("span", { class: "badge " + q.type, title: q.instructions, style: "margin-right:6px" }, id)); });
  card.append(tpl);

  /* 分页浏览 */
  const rows = D.rows;
  if (rows && rows.total) {
    const tb = h("tbody");
    rows.items.forEach(item => {
      const r = item.row;
      const state = typeof r.state === "string" ? r.state : JSON.stringify(r.state);
      const exp = Object.keys(r.expected || {}).map(k => k + "=" + (typeof r.expected[k] === "boolean" ? (r.expected[k] ? t("r.yes") : t("r.no")) : r.expected[k])).join(t("sep.list"));
      tb.append(h("tr", {}, h("td", { class: "num" }, String(item.index + 1)), h("td", { class: "cell-state", title: state }, state), h("td", {}, exp),
        h("td", {}, D.confirm === "r:" + item.index
          ? h("button", { class: "btn small danger", type: "button", onclick: async () => { D.confirm = ""; const res = await dpost("/v1/decision/datasets/delete", { name: ds.name, index: item.index }); if (!res.ok) toast(errText(res)); await loadDatasets(); await loadRows(); render(); } }, t("d.confirm"))
          : h("button", { class: "x", type: "button", title: t("d.delRow"), "aria-label": t("d.delRow"), onclick: () => { D.confirm = "r:" + item.index; render(); } }, "×"))));
    });
    card.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "num" }, t("d.th.n")), h("th", {}, t("d.th.state")), h("th", {}, t("d.th.expected")), h("th", {}, ""))), tb)));
    const last = Math.min(rows.total, rows.offset + rows.items.length);
    card.append(h("div", { class: "pager" },
      h("button", { class: "btn small", type: "button", disabled: D.page === 0, onclick: async () => { D.page--; await loadRows(); render(); } }, t("d.prev")),
      h("span", {}, t("d.page", { a: rows.offset + 1, b: last, n: rows.total })),
      h("button", { class: "btn small", type: "button", disabled: last >= rows.total, onclick: async () => { D.page++; await loadRows(); render(); } }, t("d.next"))));
  } else card.append(h("div", { class: "empty" }, t("d.noRows")));
  card.append(h("div", { class: "rowline" },
    h("a", { class: "btn small", href: "/v1/decision/datasets/export?name=" + encodeURIComponent(ds.name), download: "" }, t("d.export")),
    h("span", { class: "spacer", style: "flex:1" }),
    D.confirm === "d" ? h("button", { class: "btn small danger", type: "button", onclick: async () => {
        D.confirm = ""; const res = await dpost("/v1/decision/datasets/delete", { name: ds.name }); if (!res.ok) toast(errText(res)); else toast(t("d.deleted"));
        D.dataset = ""; D.lab.questions = []; await loadDatasets(); await loadRows(); render(); } }, t("d.confirm"))
      : h("button", { class: "btn small danger", type: "button", onclick: () => { D.confirm = "d"; render(); } }, t("d.delDataset"))));
  return card;
}

function renderLabeler() {
  const box = $("#d-labeler");
  if (!box) return;
  box.textContent = "";
  const lab = D.lab;
  box.append(h("div", { class: "vfield" }, h("label", { for: "d-state" }, t("d.state")),
    h("textarea", { id: "d-state", value: lab.state, placeholder: t("d.statePh"), oninput: e => { lab.state = e.target.value; } })));
  const head = h("div", { class: "head" }, h("h3", { style: "margin:0;font-size:15px" }, t("d.questions") + " (" + lab.questions.length + ")"),
    h("div", {}, h("button", { class: "btn small", type: "button", onclick: () => { lab.questions.push(newQ("noul")); renderLabeler(); } }, t("q.addNoul")),
      " ", h("button", { class: "btn small", type: "button", onclick: () => { lab.questions.push(newQ("choice")); renderLabeler(); } }, t("q.addChoice")),
      " ", h("button", { class: "btn small", type: "button", onclick: () => { lab.questions.push(newQ("score")); renderLabeler(); } }, t("q.addScore"))));
  box.append(head);
  box.append(h("div", { class: "tools" },
    h("button", { class: "btn small", type: "button", disabled: !currentDataset() || !Object.keys((currentDataset() || {}).questions || {}).length, onclick: () => { loadTemplate(); renderLabeler(); } }, t("d.loadTemplate")),
    h("button", { class: "btn small", type: "button", disabled: !S.questions.length, onclick: () => { lab.questions = fromSpecs(buildRequest().body.questions); lab.expected = {}; renderLabeler(); } }, t("d.fromText"))));
  if (!lab.questions.length) box.append(h("div", { class: "empty" }, t("d.qEmpty")));
  lab.questions.forEach((q, qi) => {
    const card = h("div", { class: "q" });
    card.append(h("div", { class: "q-top" }, h("span", { class: "badge " + q.type }, t("type." + q.type)),
      h("input", { value: q.id, placeholder: t("q.idPh"), "aria-label": t("q.idAria"), spellcheck: "false", oninput: e => { q.id = e.target.value; } }),
      h("button", { class: "x", type: "button", title: t("q.del"), "aria-label": t("q.del"), onclick: () => { lab.questions.splice(qi, 1); renderLabeler(); } }, "×")));
    card.append(h("textarea", { rows: "2", value: q.instructions, "aria-label": t("q.aria"),
      placeholder: q.type === "noul" ? t("q.phNoul") : q.type === "choice" ? t("q.phChoice") : t("q.phScore"), oninput: e => { q.instructions = e.target.value; } }));
    if (q.type === "choice") {
      const opts = h("div", { class: "opts" });
      q.options.forEach((o, oi) => opts.append(h("div", { class: "opt" },
        h("input", { class: "key", value: o.key, placeholder: t("opt.key"), "aria-label": t("opt.keyAria"), spellcheck: "false", oninput: e => { o.key = e.target.value; }, onchange: renderLabeler }),
        h("input", { value: o.desc, placeholder: t("opt.desc"), "aria-label": t("opt.descAria"), oninput: e => { o.desc = e.target.value; } }),
        h("button", { class: "x", type: "button", title: t("opt.del"), "aria-label": t("opt.del"), onclick: () => { q.options.splice(oi, 1); renderLabeler(); } }, "×"))));
      opts.append(h("button", { class: "btn small", type: "button", onclick: () => { q.options.push({ key: "", desc: "" }); renderLabeler(); } }, t("opt.add")));
      card.append(opts);
    } else if (q.type === "score") {
      const opts = h("div", { class: "opts" });
      q.levels.forEach((text, li) => opts.append(h("div", { class: "opt level" }, h("span", { class: "idx" }, String(li)),
        h("input", { value: text, placeholder: li === 0 ? t("lvl.ph0") : t("lvl.ph"), "aria-label": t("lvl.aria", { n: li }), oninput: e => { q.levels[li] = e.target.value; }, onchange: renderLabeler }),
        h("button", { class: "x", type: "button", title: t("lvl.del"), "aria-label": t("lvl.del"), onclick: () => { q.levels.splice(li, 1); renderLabeler(); } }, "×"))));
      opts.append(h("button", { class: "btn small", type: "button", onclick: () => { q.levels.push(""); renderLabeler(); } }, t("lvl.add")));
      card.append(opts);
    }
    const sel = h("select", { "aria-label": t("d.expected"), onchange: e => { lab.expected[q.uid] = e.target.value; } });
    expectedOptions(q).forEach(o => sel.append(h("option", { value: o[0] }, o[1])));
    if (lab.expected[q.uid] != null && expectedOptions(q).some(o => o[0] === lab.expected[q.uid])) sel.value = lab.expected[q.uid];
    card.append(h("div", { class: "exp" }, t("d.expected") + t("sep.colon"), sel));
    box.append(card);
  });
  box.append(h("div", { class: "rowline", style: "margin-top:10px" },
    h("button", { class: "btn primary", type: "button", disabled: !D.dataset, onclick: addRow }, t("d.add")),
    h("span", { class: "hint" }, D.dataset ? t("d.importTarget") + t("sep.colon") + D.dataset : t("d.needDataset"))));
  if (lab.msg) box.append(msgLine(lab.msg));
}

function renderImport(box) {
  const imp = D.imp;
  const seg = h("div", { class: "seg" });
  [["jsonl", "JSONL"], ["csv", "CSV"]].forEach(p => seg.append(h("button", { type: "button", "aria-pressed": String(imp.format === p[0]), onclick: () => { imp.format = p[0]; render(); } }, p[1])));
  const file = h("input", { type: "file", accept: ".jsonl,.json,.csv,.txt,text/plain,text/csv,application/json", hidden: true, onchange: async e => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    imp.text = (await f.text()).replace(/^﻿/, "");
    if (/\.csv$/i.test(f.name)) imp.format = "csv"; else if (/\.jsonl?$/i.test(f.name)) imp.format = "jsonl";
    render();
  } });
  box.append(file, h("div", { class: "rowline" }, h("span", { class: "hint" }, t("d.fmt")), seg,
    h("button", { class: "btn small", type: "button", onclick: () => file.click() }, t("d.chooseFile"))));
  box.append(h("p", { class: "fine" }, imp.format === "csv" ? t("d.pasteCsv") : t("d.pasteJsonl")));
  box.append(h("textarea", { id: "d-import-text", value: imp.text, spellcheck: "false", oninput: e => { imp.text = e.target.value; } }));
  if (imp.format === "csv") {
    const c = imp.csv;
    box.append(h("div", { class: "form-grid", style: "margin-top:8px" },
      field(t("d.textCol"), h("input", { type: "text", value: c.text_column, oninput: e => { c.text_column = e.target.value; } })),
      field(t("d.labelCol"), h("input", { type: "text", value: c.label_column, oninput: e => { c.label_column = e.target.value; } })),
      field(t("d.qId"), h("input", { type: "text", value: c.question, spellcheck: "false", oninput: e => { c.question = e.target.value; } }))));
    box.append(field(t("d.qIns"), h("input", { type: "text", value: c.instructions, placeholder: t("d.qInsPh"), oninput: e => { c.instructions = e.target.value; } })));
  }
  const list = h("datalist", { id: "d-ds-names" });
  D.datasets.forEach(d => list.append(h("option", { value: d.name })));
  box.append(h("div", { class: "rowline", style: "margin-top:8px" }, h("span", { class: "hint" }, t("d.importTarget")),
    h("input", { class: "inline-input", list: "d-ds-names", value: imp.name, placeholder: t("d.newName"), oninput: e => { imp.name = e.target.value; } }), list,
    h("button", { class: "btn primary", type: "button", disabled: imp.busy, onclick: importText }, imp.busy ? t("d.importing") : t("d.import"))));
  if (imp.msg) box.append(msgLine(imp.msg));
  if (imp.skipped.length) {
    const det = h("details", { class: "fold" }, h("summary", { style: "font-size:13.5px" }, t("d.skipList") + " (" + imp.skipped.length + ")"));
    det.append(h("pre", { class: "code", style: "max-height:160px" }, imp.skipped.map(x => x.error).join("\n")));
    box.append(det);
  }
}
function renderReviews(box) {
  box.append(h("p", { class: "fine" }, t("d.reviewsNote")));
  const sel = h("select", { class: "inline-input grow", "aria-label": t("d.recipe"), onchange: e => { D.recipe = e.target.value; } });
  D.recipes.forEach(r => sel.append(h("option", { value: r.id }, r.title + (r.custom ? t("v.custom") : ""))));
  sel.value = D.recipe;
  const list = h("datalist", { id: "d-ds-names2" });
  D.datasets.forEach(d => list.append(h("option", { value: d.name })));
  box.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("d.recipe")), sel));
  box.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("d.importTarget")),
    h("input", { class: "inline-input", list: "d-ds-names2", value: D.imp.name, placeholder: t("d.newName"), oninput: e => { D.imp.name = e.target.value; } }), list,
    h("button", { class: "btn primary", type: "button", disabled: !D.recipe, onclick: importReviews }, t("d.import"))));
  if (D.reviewsMsg) box.append(msgLine(D.reviewsMsg));
}
function renderDataTools() {
  const card = h("section", { class: "card" });
  const tabs = h("div", { class: "tabs", role: "tablist" });
  ["label", "import", "reviews"].forEach(name => tabs.append(h("button", { type: "button", role: "tab", "aria-selected": String(D.dsTab === name), onclick: () => { D.dsTab = name; render(); } }, t("d.tab." + name))));
  card.append(tabs);
  if (D.dsTab === "label") card.append(h("div", { id: "d-labeler" }));
  else if (D.dsTab === "import") renderImport(card);
  else renderReviews(card);
  return card;
}

function renderModels() {
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("d.models"))));
  if (!D.models.length) card.append(h("div", { class: "empty" }, t("d.noModels")));
  const active = activeName();
  D.models.forEach(m => {
    const isActive = m.name === active || m.active;
    const head = h("div", { class: "model-head" }, h("strong", {}, m.name));
    if (isActive) head.append(h("span", { class: "badge active" }, t("d.active")));
    if (m.training) head.append(h("span", { class: "badge" }, t("d.training")));
    else if (!m.complete) head.append(h("span", { class: "badge dim" }, t("d.incomplete")));
    head.append(h("span", { class: "spacer" }));
    const lock = busy() || m.training;
    head.append(h("button", { class: "btn small" + (isActive ? "" : " primary"), type: "button", disabled: lock || !m.complete, onclick: () => activate(isActive ? "" : m.name) }, isActive ? t("d.unsetActive") : t("d.setActive")),
      h("button", { class: "btn small", type: "button", disabled: lock || !available() || !m.complete, onclick: () => evaluateModel(m.name) }, t("d.evaluate")),
      h("button", { class: "btn small", type: "button", onclick: () => showInfo(m.name) }, t("d.info")),
      D.confirm === "m:" + m.name
        ? h("button", { class: "btn small danger", type: "button", onclick: async () => { D.confirm = ""; const res = await dpost("/v1/decision/models/delete", { name: m.name }); if (!res.ok) toast(errText(res)); await loadModels(); pollStatus(); render(); } }, t("d.confirm"))
        : h("button", { class: "btn small danger", type: "button", disabled: lock, onclick: () => { D.confirm = "m:" + m.name; render(); } }, t("d.delete")));
    const box = h("div", { class: "model" }, head);
    box.append(h("div", { class: "meta-line" }, t("d.modelMeta", { enc: m.encoder || "-", params: m.params_m != null ? t("d.params", { n: num(m.params_m, 1) }) : "-", size: num(m.size_mb, 0),
      acc: m.accuracy != null ? t("d.acc", { v: pct(m.accuracy) }) : t("d.noAcc"), time: m.created || "" })));
    if (D.info[m.name]) box.append(h("pre", { class: "code", style: "max-height:300px;margin-top:8px" }, pretty(D.info[m.name])));
    card.append(box);
  });
  if (D.modelMsg) card.append(msgLine(D.modelMsg));
  return card;
}
function renderNewModel() {
  const nm = D.nm, rec = recommend();
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("d.newModel"))));
  const sel = h("select", { id: "d-encoder", onchange: e => { nm.encoder = e.target.value; } });
  const encoders = (D.env && D.env.encoders) || [];
  ["small", "base", "large"].forEach(tier => {
    const items = encoders.filter(x => x.tier === tier && !x.official);
    if (!items.length) return;
    const group = h("optgroup", { label: t("d.tier." + tier) });
    items.forEach(x => group.append(h("option", { value: x.id }, (rec && rec.encoder === x.id ? "★ " : "") + x.id + (x.params_m ? "  (" + x.params_m + " M)" : "") + (LANG === "en" ? (x.note_en ? " — " + x.note_en : "") : (x.note_zh ? " — " + x.note_zh : "")))));
    sel.append(group);
  });
  const officials = encoders.filter(x => x.official);
  if (officials.length) { const g = h("optgroup", { label: t("d.official") }); officials.forEach(x => g.append(h("option", { value: x.id }, x.id))); sel.append(g); }
  if (nm.encoder) sel.value = nm.encoder;
  card.append(field(t("d.encoder") + (rec ? "　★ = " + t("d.recStar") : ""), sel, "d-encoder"));
  card.append(field(t("d.customEnc"), h("input", { type: "text", value: nm.custom, spellcheck: "false", placeholder: "org/model-name", oninput: e => { nm.custom = e.target.value; } })));
  card.append(h("div", { class: "form-grid" },
    field(t("d.modelName"), h("input", { type: "text", value: nm.name, spellcheck: "false", oninput: e => { nm.name = e.target.value; } })),
    field(t("d.headLayers"), numInput(nm, "head_layers", { min: "1", max: "8", step: "1" })),
    field(t("d.maxLen"), numInput(nm, "max_len", { min: "64", max: "8192", step: "64" }))));
  card.append(h("div", { class: "rowline" }, h("button", { class: "btn primary", type: "button", disabled: busy() || !available(), onclick: buildModel }, busy() && D.job.kind === "new" ? t("d.building") : t("d.build"))));
  if (nm.msg) card.append(msgLine(nm.msg));
  card.append(h("p", { class: "fine" }, t("d.newNote")));
  return card;
}

function renderTrainForm() {
  const tr = D.tr;
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("d.train"))));
  const base = h("select", { id: "d-base", onchange: e => { tr.base = e.target.value; remember(BASE_KEY, tr.base); if (!tr.name || /-ft$/.test(tr.name)) tr.name = tr.base.replace(/[^\w一-鿿.-]+/g, "-") + "-ft"; render(); } });
  const complete = D.models.filter(m => m.complete);
  if (complete.length) { const g = h("optgroup", { label: t("d.baseModel") }); complete.forEach(m => g.append(h("option", { value: m.name }, m.name))); base.append(g); }
  const g2 = h("optgroup", { label: t("d.baseOfficial") }); OFFICIAL.forEach(n => g2.append(h("option", { value: n }, n))); base.append(g2);
  if (!tr.base || !(complete.some(m => m.name === tr.base) || OFFICIAL.includes(tr.base))) tr.base = complete.length ? complete[0].name : "multilingual";
  base.value = tr.base;
  if (!tr.name) tr.name = tr.base.replace(/[^\w一-鿿.-]+/g, "-") + "-ft";
  const ds = h("select", { id: "d-tr-ds", onchange: e => { tr.dataset = e.target.value; } });
  D.datasets.forEach(d => ds.append(h("option", { value: d.name }, d.name + "  (" + d.rows + ")")));
  ds.value = tr.dataset;
  const mode = h("select", { id: "d-mode", onchange: e => { tr.mode = e.target.value; } });
  ["full", "freeze", "lora"].forEach(m => mode.append(h("option", { value: m }, t("d.mode." + m))));
  mode.value = tr.mode || "full";
  const loss = h("select", { id: "d-loss", onchange: e => { tr.loss = e.target.value; } });
  ["rlcd", "soft-ce"].forEach(m => loss.append(h("option", { value: m }, m)));
  loss.value = tr.loss;
  card.append(h("div", { class: "form-grid" }, field(t("d.base"), base, "d-base"), field(t("d.dataset"), ds, "d-tr-ds")));
  card.append(field(t("d.outName"), h("input", { type: "text", value: tr.name, spellcheck: "false", oninput: e => { tr.name = e.target.value; } })));
  card.append(h("div", { class: "form-grid" },
    field(t("d.mode"), mode, "d-mode"), field(t("d.epochs"), numInput(tr, "epochs", { min: "1", step: "1" })),
    field(t("d.mb"), numInput(tr, "micro_batch", { min: "1", step: "1" })), field(t("d.ga"), numInput(tr, "grad_accum", { min: "1", step: "1" })),
    field(t("d.encLr"), numInput(tr, "encoder_lr", { step: "any" })), field(t("d.headLr"), numInput(tr, "head_lr", { step: "any" })),
    field(t("d.loss"), loss, "d-loss"), field(t("d.maxLen"), numInput(tr, "max_len", { min: "64", step: "64" })),
    field(t("d.holdout"), numInput(tr, "holdout", { min: "0", max: "0.9", step: "0.05" }))));
  card.append(h("div", { class: "checks", style: "margin:4px 0 12px" }, h("label", { class: "check" }, h("input", { type: "checkbox", checked: tr.resume || null, onchange: e => { tr.resume = e.target.checked; } }), t("d.resume"))));
  card.append(h("div", { class: "rowline" },
    h("button", { class: "btn primary", type: "button", disabled: busy() || !available() || !D.datasets.length, onclick: startTrain }, t("d.start")),
    busy() ? h("button", { class: "btn danger", type: "button", disabled: D.cancelling, onclick: cancelJob }, D.cancelling ? t("d.cancelling") : t("d.cancel")) : null));
  if (tr.msg) card.append(msgLine(tr.msg));
  return card;
}

function drawSpark(canvas, points) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1) || 600, hgt = canvas.height = 90 * (window.devicePixelRatio || 1);
  ctx.clearRect(0, 0, w, hgt);
  if (!points || points.length < 2) return;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  const pad = 6 * (window.devicePixelRatio || 1);
  const X = x => pad + (x1 === x0 ? 0 : (x - x0) / (x1 - x0)) * (w - 2 * pad);
  const Y = y => hgt - pad - (y1 === y0 ? 0.5 : (y - y0) / (y1 - y0)) * (hgt - 2 * pad);
  ctx.strokeStyle = "#e3e9ee"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, Y(y0)); ctx.lineTo(w - pad, Y(y0)); ctx.stroke();
  ctx.strokeStyle = "#14b8a6"; ctx.lineWidth = 2 * (window.devicePixelRatio || 1); ctx.lineJoin = "round";
  ctx.beginPath();
  points.forEach((p, i) => { if (i === 0) ctx.moveTo(X(p[0]), Y(p[1])); else ctx.lineTo(X(p[0]), Y(p[1])); });
  ctx.stroke();
  ctx.fillStyle = "#51606f"; ctx.font = (11 * (window.devicePixelRatio || 1)) + "px sans-serif";
  ctx.fillText(num(y1, 3), pad + 2, pad + 10 * (window.devicePixelRatio || 1));
  ctx.fillText(num(y0, 3), pad + 2, hgt - pad - 2);
}
function resultCard(job) {
  const r = job.result;
  if (!r) return null;
  const box = h("div", { style: "margin-top:12px" }, h("div", { class: "sub" }, t("d.result"), h("small", {}, job.name || job.model || "")));
  if (job.kind === "train") {
    const acc = r.holdout && r.holdout.accuracy;
    if (acc && acc.all != null) {
      box.append(h("div", { class: "acc" }, pct(acc.all), h("small", {}, t("d.r.acc"))));
      box.append(h("div", { class: "jobstat" }, ...["noul", "choice", "score"].filter(k => acc[k] != null).map(k => h("span", {}, t("d.r." + k) + " " + pct(acc[k])))));
    }
    const parts = [t("d.r.epochs", { n: r.epochs_done, m: r.mode || "-" }), t("d.r.items", { a: r.train_items, b: r.calib_items, c: r.holdout ? r.holdout.items : 0 })];
    if (r.peak_vram_mb) parts.push(t("d.r.vram", { v: Math.round(r.peak_vram_mb) }));
    if (r.seconds != null) parts.push(t("d.r.seconds", { t: fmtTime(r.seconds) }));
    const skipped = r.skipped && typeof r.skipped === "object" ? Object.values(r.skipped).reduce((a, b) => a + (Number(b) || 0), 0) : 0;
    if (skipped) parts.push(t("d.r.skipped", { n: skipped }));
    const temp = r.calibration && (r.calibration.temperature || r.calibration.temperatures);
    if (temp) parts.push(t("d.r.calib", { v: Array.isArray(temp) ? temp.map(x => num(x, 2)).join(" / ") : num(temp, 2) }));
    box.append(h("div", { class: "jobstat" }, ...parts.map(x => h("span", {}, x))));
  } else if (job.kind === "evaluate") {
    const acc = r.accuracy || {};
    if (acc.all != null) box.append(h("div", { class: "acc" }, pct(acc.all), h("small", {}, t("d.r.all") + t("sep.gap") + t("d.r.evalItems", { n: r.items }))));
    box.append(h("div", { class: "jobstat" }, ...["noul", "choice", "score"].filter(k => acc[k] != null).map(k => h("span", {}, t("d.r." + k) + " " + pct(acc[k])))));
    const pq = r.per_question || {};
    if (Object.keys(pq).length) {
      const tb = h("tbody");
      Object.keys(pq).forEach(q => tb.append(h("tr", {}, h("td", {}, h("code", {}, q)), h("td", { class: "num" }, String(pq[q].n)), h("td", { class: "num" }, pq[q].accuracy == null ? "-" : pct(pq[q].accuracy)))));
      box.append(h("div", { class: "sub" }, t("d.r.perQ")), h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("v.st.th.q")), h("th", { class: "num" }, "n"), h("th", { class: "num" }, t("d.r.all")))), tb)));
    }
  } else if (job.kind === "new") {
    box.append(h("div", { class: "jobstat" }, h("span", {}, r.encoder || ""), h("span", {}, t("d.r.params", { a: num(r.params_m, 1), b: num(r.encoder_params_m, 1), h: r.hidden || "-" }))));
  }
  const det = h("details", { class: "fold", style: "margin-top:8px" }, h("summary", { style: "font-size:13.5px" }, "JSON"), h("pre", { class: "code", style: "max-height:260px" }, pretty(r)));
  box.append(det);
  return box;
}
function renderJobCard() {
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("d.job"))));
  const job = D.job;
  if (!job) { card.append(h("div", { class: "empty" }, t("d.noJob"))); }
  else {
    card.append(h("div", { class: "vstatus" }, h("span", { class: "dot " + (job.state === "done" ? "ok" : job.state === "error" || job.state === "cancelled" ? "bad" : "wait") }),
      h("strong", {}, t("d.kind." + job.kind) + (job.name ? "　" + job.name : job.model ? "　" + job.model : "")), h("span", { class: "hint" }, job.id), h("span", { class: "badge dim", id: "d-job-state" }, t("d.state." + job.state))));
    card.append(h("div", { class: "progress", id: "d-job-bar" }, h("i")));
    card.append(h("div", { class: "jobstat", id: "d-job-stat" }));
    if (job.state === "error") card.append(h("div", { class: "errbox" }, t("d.failed", { msg: job.error || "" })));
    card.append(h("div", { class: "sub" }, t("d.lossCurve")));
    card.append(h("canvas", { class: "spark", id: "d-spark" }));
    card.append(h("div", { class: "sub" }, t("d.log")));
    card.append(h("pre", { class: "code logtail", id: "d-log" }));
    const res = resultCard(job);
    if (res) card.append(res);
  }
  const others = D.jobs.filter(j => !job || j.id !== job.id).slice(0, 5);
  if (others.length) {
    card.append(h("div", { class: "sub" }, t("d.recent")));
    others.forEach(j => card.append(h("button", { class: "hist", type: "button", onclick: () => { D.job = j; render(); if (busy()) watchJob(j.id); } },
      h("span", {}, t("d.kind." + j.kind) + "　" + (j.name || j.model || "")), h("span", { class: "t" + (j.state === "error" ? " bad" : "") }, t("d.state." + j.state) + t("sep.gap") + (j.started || "")),
      h("span", { class: "s" }, j.error || (j.result ? pretty(j.result).slice(0, 120).replace(/\s+/g, " ") : "")))));
  }
  return card;
}
function renderProgress() {
  const job = D.job, bar = $("#d-job-bar");
  if (!job || !bar) return;
  bar.firstChild.style.width = Math.round((job.progress || 0) * 100) + "%";
  const st = $("#d-job-state"); if (st) st.textContent = t("d.state." + job.state);
  const stat = $("#d-job-stat");
  if (stat) {
    stat.textContent = "";
    const parts = [];
    if (job.stage) parts.push(stageText(job.stage) + "  " + Math.round((job.progress || 0) * 100) + "%");
    if (job.epoch != null && job.epochs != null) parts.push(t("d.epoch", { a: job.epoch, b: job.epochs }));
    if (job.step != null && job.steps != null) parts.push(t("d.step", { a: job.step, b: job.steps }));
    if (job.loss != null) parts.push(t("d.lossV", { v: num(job.loss, 4) }));
    if (job.eta_seconds != null && busy()) parts.push(t("d.eta", { t: fmtTime(job.eta_seconds) }));
    if (job.seconds != null) parts.push(t("d.elapsed", { t: fmtTime(job.seconds) }));
    if (job.oom) parts.push(t("d.oom", { n: job.oom }));
    parts.forEach(x => stat.append(h("span", {}, x)));
  }
  const spark = $("#d-spark"); if (spark) drawSpark(spark, job.loss_curve || []);
  const log = $("#d-log");
  if (log) { log.textContent = (job.log_tail || []).join("\n"); log.scrollTop = log.scrollHeight; }
}

function render() {
  const root = $("#decision-root");
  if (!root || S.view !== "decision") return;
  const keepFocus = document.activeElement && document.activeElement.id;
  root.textContent = "";
  root.append(h("section", { class: "card", id: "d-env" }));
  renderEnv();
  if (!D.loaded) { root.append(h("div", { class: "placeholder" }, t("s.connecting"))); return; }
  const grid1 = h("main", { class: "grid" }, h("div", { class: "col" }, renderDatasets()), h("div", { class: "col" }, renderDataTools()));
  root.append(grid1);
  renderLabeler();
  root.append(h("main", { class: "grid" }, h("div", { class: "col" }, renderModels()), h("div", { class: "col" }, renderNewModel())));
  root.append(h("main", { class: "grid" }, h("div", { class: "col" }, renderTrainForm()), h("div", { class: "col" }, renderJobCard())));
  renderProgress();
  if (keepFocus) { const el = document.getElementById(keepFocus); if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) el.focus(); }
}

/* ---------- 对外 ---------- */
let lastState = "";
window.WBD = {
  onView: function () {
    if (S.view !== "decision") return;
    if (!D.loaded) { render(); loadAll(); } else { render(); loadJobs().then(render); }
  },
  onStatus: function () {
    const d = decisionStatus();
    const state = JSON.stringify([S.status === undefined, !!S.status, S.status && S.status.service, d && d.active, d && d.training, d && (d.custom_models || []).join(",")]);
    if (state === lastState) return;
    lastState = state;
    if (S.view !== "decision") return;
    if (D.loaded) loadModels().then(render); else renderEnv();
  },
  onLang: function () {
    if (S.view === "decision") { loadRecipes().then(render); }
  }
};
})();
