"use strict";
const $ = (s, root = document) => root.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const labels = {
  company_name: "企业名称",
  industry: "所属行业",
  area: "经营地区",
  contact_name: "联系人",
  contact_title: "职位",
  phone: "手机号",
  intent_level: "意向等级",
  intent_reason: "意向判断依据",
  demand_summary: "客户需求",
  mendian: "门店数",
  shejishi: "设计师人数",
  call_time: "通话时间",
  next_action: "建议下一步",
  confidence_score: "证据支持度",
  need_human_review: "需要人工审核",
};
const intentName = { high: "高意向", medium: "中意向", low: "低意向" };
const statusName = {
  pending: "待审核",
  ready: "自动完成",
  approved: "已通过",
  rejected: "待补充",
};
const sourceName = {
  assignment_example: "题目示例",
  synthetic: "合成测试",
  recording: "录音转写",
  manual: "手动输入",
  file: "上传记录",
};
const companyStatus = {
  missing: "名称待确认",
  verified: "已核验主体",
  self_reported: "自报名称待核验",
  brand_only: "品牌候选",
  ambiguous: "主体存在歧义",
  unresolved: "主体待核验",
};
const paths = {
  chat: "M4 4h16v12H9l-5 4V4Z M8 8h8 M8 12h5",
  review: "M9 5H5v15h14V5h-4 M9 3h6v4H9z M8 13l3 3 5-6",
  chart: "M4 19h17 M7 15V9 M12 15V5 M17 15v-7",
  spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z",
  arrow: "M5 12h14 M14 7l5 5-5 5",
  check: "m5 12 4 4L19 6",
  shield: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z M8 12l3 3 5-6",
  audio: "M5 9v6 M9 5v14 M13 8v8 M17 3v18 M21 9v6",
  download: "M12 3v12 M7 10l5 5 5-5 M5 17v4h14v-4",
  clock: "M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  layers: "m12 3 9 5-9 5-9-5 9-5Z M3 12l9 5 9-5 M3 16l9 5 9-5",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 3v2 M12 19v2 M3 12h2 M19 12h2",
};
const icon = (name) =>
  `<span class="ico" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${paths[name] || paths.chat}"/></svg></span>`;
const S = {
  view: "analyze",
  config: {},
  initialized: false,
  leads: [],
  samples: [],
  recordings: [],
  report: {},
  current: null,
  tab: "overview",
  uploading: false,
  loadingInput: false,
  fileMeta: null,
  recordingItem: null,
  inputType: "text",
  inputDrafts: {},
  reviewDrafts: {},
  pollFailures: 0,
  pendingRequest: null,
  jobInfo: null,
  busy: false,
  error: "",
  text: "",
  title: "新通话",
  callTime: "",
  source: "manual",
  recordingId: "",
  mode: "llm",
  sampleId: "",
  reviewId: "",
  filter: "pending",
  search: "",
  selected: new Set(),
  transcript: null,
  audioUrl: "",
  job: null,
};
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(
    () => $("#toast").classList.remove("show"),
    4800,
  );
}
async function api(path, options = {}, raw = false) {
  const token = sessionStorage.getItem("sdr_token") || "";
  let response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...(options.headers || {}),
      },
    });
  } catch {
    throw new Error("无法连接后台服务，请确认项目正在运行后重试。");
  }
  if (!response.ok) {
    let body = {};
    try {
      body = await response.json();
    } catch {}
    if (response.status === 401) showAuth();
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : response.status === 422
          ? "输入格式不正确，请检查必填项。"
          : `请求失败 (${response.status})`,
    );
  }
  return raw ? response : response.json();
}
function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}
function stat(label, value, ico, green = false) {
  return `<div class="stat"><div><div class="stat-label">${label}</div><div class="stat-num">${value}</div></div><div class="stat-icon ${green ? "green" : ""}">${icon(ico)}</div></div>`;
}
function badge(level) {
  return `<span class="pill ${esc(level)}">${intentName[level] || esc(level)}</span>`;
}
function formatTime(value) {
  if (!value) return "时间未提供";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? esc(value)
    : d.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
}
function shell() {
  const pending = S.leads.filter((l) => l.status === "pending").length;
  return `<div class="shell"><aside class="sidebar"><div class="brand"><img src="/static/favicon.svg" alt=""><span>AI SDR Agent<small>LEAD WORKSPACE</small></span></div><div class="nav-label">工作空间</div><button class="nav ${S.view === "analyze" ? "active" : ""}" data-nav="analyze">${icon("chat")}通话分析</button><button class="nav ${S.view === "review" ? "active" : ""}" data-nav="review">${icon("review")}人工审核${pending ? `<span class="counter">${pending}</span>` : ""}</button><button class="nav ${S.view === "report" ? "active" : ""}" data-nav="report">${icon("chart")}效果验证</button><div class="sidebar-foot"><div><span class="status-dot"></span><b>${S.config.llm_configured ? "模型已配置" : "等待模型配置"}</b></div><div style="margin-top:5px">证据可追溯 · 修改有记录</div><button data-action="auth">${icon("settings")} 访问设置</button></div></aside><div class="workspace"><header class="topbar"><div class="breadcrumb">工作空间 <span>/</span><b>${{ analyze: "通话分析", review: "人工审核", report: "效果验证" }[S.view]}</b></div><div class="top-meta"><span>AI SDR · 销售线索工作台</span><span class="pill"><span class="status-dot"></span>本地工作区</span><span class="avatar">SDR</span></div></header><main class="main">${S.view === "analyze" ? analysisPage() : S.view === "review" ? reviewPage() : reportPage()}<div class="footer-note"><span>AI SDR Agent · 通话线索工作台</span><span>规则版本 ${esc(S.config.scorecard_version || "1.0")} · 数据保存在本地工作区</span></div></main></div></div>`;
}
function pageHead(title, description, right = "") {
  return `<div class="page-head"><div><h1>${title}</h1><p>${description}</p></div>${right}</div>`;
}
function analysisPage() {
  return `${pageHead("通话分析", "上传录音或输入通话记录，提取企业信息与客户意向。")}<div class="stats">${stat("累计分析", S.leads.length, "layers")}${stat("待人工审核", S.leads.filter((l) => l.status === "pending").length, "review")}${stat("高意向线索", S.leads.filter((l) => l.result.intent_level === "high").length, "spark", true)}${stat("审核已通过", S.leads.filter((l) => l.status === "approved").length, "check", true)}</div><div class="grid"><div><section class="panel"><div class="panel-head"><div class="panel-title">${icon("chat")}输入通话</div><div class="segmented"><button data-input="text" class="${S.inputType === "text" ? "active" : ""}" ${inputLocked() ? "disabled" : ""}>通话文本</button><button data-input="audio" class="${S.inputType === "audio" ? "active" : ""}" ${inputLocked() ? "disabled" : ""}>真实录音</button></div></div><div class="panel-body">${S.inputType === "audio" ? audioInput() : textInput()}<div class="form-row"><div class="field"><label for="call-title">通话名称</label><input id="call-title" data-state="title" ${inputLocked() ? "disabled" : ""} value="${esc(S.title)}" maxlength="120"></div><div class="field"><label for="call-time">通话时间 <span class="helper">选填</span></label><input id="call-time" type="datetime-local" data-state="callTime" ${inputLocked() ? "disabled" : ""} value="${esc(S.callTime)}"></div></div><div class="text-between" style="margin-bottom:14px"><label class="helper" for="mode">分析方式</label><select id="mode" data-state="mode" ${inputLocked() ? "disabled" : ""} class="sample-select"><option value="llm" ${S.mode === "llm" ? "selected" : ""}>模型分析 · DeepSeek</option><option value="baseline" ${S.mode === "baseline" ? "selected" : ""}>本地规则 · 对照基线</option></select></div>${S.error ? `<div class="error-box" role="alert">${esc(S.error)}</div>` : ""}<button class="button primary full" data-action="analyze" ${S.busy || S.uploading || S.loadingInput || S.job ? "disabled" : ""}>${S.busy ? '<span class="spinner"></span> 正在分析，请稍候' : `${icon("spark")} 开始分析 ${icon("arrow")}`}</button><div class="helper" style="text-align:center;margin-top:9px">${sourceName[S.source]} · ${S.mode === "llm" ? "仅将当前文本发送至已配置的模型服务" : "本地基线用于流程演示，结果需人工核实"}</div></div></section><div class="principle">${icon("shield")}<div><b>分析提示</b><br>缺少依据的字段留空，存在歧义的主体进入人工审核。</div></div></div><div><section class="panel" id="analysis-result">${S.busy ? `<div class="loading-result"><div><div class="spinner"></div><h3>正在分析通话</h3><p>提取事实与原文依据，完成企业候选和意向评分。<br>请保持页面打开，结果会自动显示。</p></div></div>` : S.current ? resultPanel(S.current) : emptyResult()}</section></div></div>`;
}

function inputLocked() {
  return S.busy || S.uploading || S.loadingInput || !!S.job;
}
async function switchInput(next) {
  if (inputLocked() || next === S.inputType) return;
  const keys = [
    "text",
    "title",
    "callTime",
    "source",
    "sampleId",
    "recordingId",
    "recordingItem",
    "fileMeta",
    "transcript",
    "current",
    "tab",
  ];
  S.inputDrafts[S.inputType] = structuredClone(
    Object.fromEntries(keys.map((key) => [key, S[key]])),
  );
  resetAttachment();
  Object.assign(
    S,
    {
      text: "",
      title: "新通话",
      callTime: "",
      source: "manual",
      tab: "overview",
    },
    S.inputDrafts[next] || {},
  );
  S.inputType = next;
  if (S.recordingId) {
    S.loadingInput = true;
    render();
    try {
      await restoreAudio();
    } catch (e) {
      S.error = e.message;
    }
    S.loadingInput = false;
  }
  render();
}
function fileControl(kind) {
  const isText = kind === "text";
  return `<button class="button small" data-action="upload-${kind}" ${inputLocked() ? "disabled" : ""}>${S.uploading ? '<span class="spinner"></span> 上传中…' : isText ? "上传文本" : "上传本地录音"}</button><input type="file" id="${kind}-file" accept="${isText ? ".txt,text/plain" : ".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4"}" hidden aria-label="${isText ? "选择 TXT 沟通记录文件" : "选择通话录音文件"}">`;
}
function transcriptEditor(audio = false) {
  return `<textarea class="input-transcript" id="transcript" data-state="text" ${inputLocked() ? "disabled" : ""} placeholder="${audio ? "录音转写完成后，全文会显示在这里，可回听修正。" : "粘贴通话转写文本，建议按行标注角色：&#10;&#10;销售：您好，主要想了解什么需求？&#10;客户：我们设计部有15个人，出图比较慢…"}">${esc(S.text)}</textarea><div class="input-footer"><span>${audio ? "机器转写可修正；未确认说话人会进入审核" : "建议标注「销售：」「客户：」，便于准确归因"}</span><span id="char-count">${S.text.length} / 50,000</span></div>`;
}
function fileNote() {
  return S.fileMeta
    ? `<div class="file-note">已上传：${esc(S.fileMeta.name)}</div>`
    : "";
}
function textInput() {
  return `<div class="text-between" style="margin-bottom:13px"><label class="label" style="margin:0" for="transcript">通话记录</label><select id="sample" aria-label="选择示例体验" class="sample-select" ${inputLocked() ? "disabled" : ""}><option value="">选择示例体验</option>${S.samples.map((x) => `<option value="${esc(x.id)}" ${S.sampleId === x.id ? "selected" : ""}>${esc(x.title)}</option>`).join("")}</select></div>${transcriptEditor()}<div class="upload-row">${fileControl("text")}<span class="helper">TXT · ≤1 MB · 保留原文</span></div>${fileNote()}`;
}
function audioInput() {
  const progress = S.jobInfo?.progress || {};
  const percent = Math.min(99, Math.max(0, Number(progress.percent || 0)));
  return `${S.recordings.length ? `<div class="field"><label for="recording">选择提供的真实录音 · 共 ${S.recordings.length} 段</label><select id="recording" ${inputLocked() ? "disabled" : ""}><option value="">请选择录音</option>${S.recordings.map((r) => `<option value="${esc(r.id)}" ${r.id === S.recordingId ? "selected" : ""}>${esc(r.title)} · ${formatTime(r.call_time)}${r.transcribed ? " · 已转写" : ""}</option>`).join("")}</select></div>` : ""}<div class="upload-row">${fileControl("audio")}<span class="helper">MP3 / WAV / M4A · ≤50 MB</span></div>${fileNote()}
  ${
    S.loadingInput
      ? '<div class="notice" role="status">正在载入录音…</div>'
      : S.recordingId
        ? `<div class="recording-box"><div class="text-between"><span class="file-name">${esc(S.recordingItem?.title || "通话录音")}</span><button class="button small light" data-action="transcribe" ${inputLocked() ? "disabled" : ""}>${S.job ? "正在转写…" : S.text ? "重新转写" : "本地转写"}</button></div><audio controls preload="metadata" ${S.audioUrl ? `src="${esc(S.audioUrl)}"` : ""}></audio>${S.job ? `<div class="asr-progress" role="status"><div class="text-between"><span>${esc(progress.message || "正在准备本地语音模型…")}</span><b>${percent}%</b></div><progress max="100" value="${percent}" aria-label="录音转写进度"></progress>${progress.duration ? `<div class="helper">音频位置 ${Math.round(progress.processed_seconds || 0)} / ${Math.round(progress.duration)} 秒</div>` : ""}</div>` : `<div class="helper">${S.jobInfo?.status === "failed" ? "本次转写未完成，可点击本地转写重试；原有文本已保留。" : S.text ? "转写已完成，可回听核对后点击开始分析。" : "上传的录音会自动转写；题目录音可点击本地转写。"}</div>`}</div>
  ${S.transcript?.quality_flags?.length ? `<div class="notice">${S.transcript.quality_flags.map(esc).join("<br>")}</div>` : ""}
  ${S.transcript?.segments?.length ? `<details class="speaker-details"><summary>核对说话人 <span class="helper">${S.transcript.segments.length} 个片段</span></summary><div class="transcript-segments">${S.transcript.segments.map((r, i) => `<div class="segment"><select data-speaker="${i}" ${inputLocked() ? "disabled" : ""} aria-label="第${i + 1}段说话人"><option value="unknown" ${r.speaker === "unknown" ? "selected" : ""}>待确认</option><option value="sales" ${r.speaker === "sales" ? "selected" : ""}>销售</option><option value="customer" ${r.speaker === "customer" ? "selected" : ""}>客户</option></select><p><small>${r.start}s–${r.end}s</small> ${esc(r.text)}</p></div>`).join("")}</div></details>` : ""}
  <label class="label" for="transcript">转写文本 · 可回听后修正</label>${transcriptEditor(true)}`
        : `<div class="notice">${S.recordings.length ? "选择题目录音，或上传本地录音。" : "上传一段本地通话录音。"}上传后自动转写，完成后点击“开始分析”。</div>`
  }`;
}
function emptyResult() {
  return `<div class="panel-head"><div class="panel-title">${icon("spark")}分析结果</div><span class="pill">等待输入</span></div><div class="empty"><div class="empty-icon">${icon("chat")}</div><h2>等待分析结果</h2><p>输入通话记录，或选择题目示例。<br>企业信息、客户意向与原文依据将在这里呈现。</p><div class="empty-steps"><span><i>01</i> 提取事实</span><span><i>02</i> 核对主体</span><span><i>03</i> 评估意向</span></div><button class="button light" style="margin-top:27px" data-action="load-assignment">载入题目示例 ${icon("arrow")}</button></div>`;
}
function resultPanel(lead, review = false) {
  const r = lead.result,
    a = lead.analysis;
  return `<div class="result-head"><div class="company-row"><div><div class="eyebrow">${review ? "线索详情" : "分析结果"}</div><h2>${esc(r.company_name || "企业名称待确认")}</h2><div class="result-meta"><span>${esc(r.industry || "行业待确认")}</span><span>·</span><span>${esc(r.area || "地区待确认")}</span><span class="source-tag">${sourceName[lead.source] || "手动输入"}</span></div></div><span class="pill intent-badge ${r.intent_level}">${intentName[r.intent_level]}</span></div>${lead.status === "approved" ? `<div class="review-callout" style="background:#edf7f0;color:#4c825f;border-color:#dfede3">审核已通过 · 机器评分与支持度保留作历史参考，当前字段以人工修正为准。</div>` : a.review_reasons.length ? `<div class="review-callout">待核实 · ${esc(humanReason(a.review_reasons[0]))}${a.review_reasons.length > 1 ? `，另有 ${a.review_reasons.length - 1} 项提示` : ""}</div>` : ""}</div><div class="tabs">${[["overview", "线索概览"], ["evidence", "原文证据"], ["score", "意向评分"], ["json", "标准 JSON"], ...(review ? [["history", "审核记录"]] : [])].map(([id, label]) => `<button data-tab="${id}" class="${S.tab === id ? "active" : ""}">${label}</button>`).join("")}</div><div class="result-content">${S.tab === "overview" ? overview(lead) : S.tab === "evidence" ? evidenceView(lead) : S.tab === "score" ? scoreView(lead) : S.tab === "history" ? historyView(lead) : `<div class="helper" style="margin-bottom:9px">${lead.status === "approved" ? "已审核结果" : "待审核草稿"} · 严格对应题目规定的15个字段</div><pre class="code">${esc(JSON.stringify(r, null, 2))}</pre>`}</div>${review ? reviewForm(lead) : `<div class="result-footer"><div class="confidence" title="${esc(a.confidence_note)}"><b>${Math.round(r.confidence_score * 100)}%</b> 证据支持度</div><div class="inline-actions"><button class="button small" data-action="download-current">${icon("download")} JSON</button><button class="button primary small" data-action="open-review">进入审核 ${icon("arrow")}</button></div></div>`}`;
}
function overview(lead) {
  const r = lead.result;
  return `<div class="info-grid">${["contact_name", "contact_title", "phone", "call_time", "mendian", "shejishi"].map((k) => `<div class="info"><label>${labels[k]}</label><div>${r[k] ? esc(k === "call_time" ? formatTime(r[k]) : r[k]) : '<span class="unknown">未确认</span>'}</div></div>`).join("")}</div><div class="section-label">客户需求</div><div class="summary-text">${esc(r.demand_summary || "尚未取得明确需求，建议补充确认。")}</div><div class="section-label">意向判断依据</div><div class="summary-text">${esc(r.intent_reason)}</div><div class="section-label">建议下一步</div><div class="next-action">${esc(r.next_action)}</div>`;
}
function evidenceView(lead) {
  const a = lead.analysis;
  return `<div class="text-between"><div class="section-label first">企业主体识别</div><span class="pill">${companyStatus[a.company.status]}</span></div><div class="summary-text">${esc(a.company.note)}</div>${a.company.candidates.map((c) => `<div class="candidate">${esc(c.company_name)}<small>${esc(c.source || "人工核验记录")} ${c.area ? "· " + esc(c.area) : ""}${c.relationship ? "<br>" + esc(c.relationship) : ""}${c.url?.startsWith("https://") ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">查看官方来源</a>` : ""}</small></div>`).join("")}<button class="button small" data-action="company-search" ${S.config.search_configured ? "" : 'disabled title="需在后台配置搜索服务；可先人工核验主体"'}>检索企业候选</button>${S.config.search_configured ? "" : '<span class="helper" style="margin-left:8px">外部检索未配置，可人工核验</span>'}<div id="search-results"></div>${a.review_reasons.length ? `<div class="section-label">审核提示</div><div class="notice">${a.review_reasons.map((r) => esc(humanReason(r))).join("<br>")}</div>` : ""}<div class="section-label">字段原文依据</div>${
    Object.entries(a.evidence)
      .map(
        ([k, v]) =>
          `<div class="evidence-card"><b>${labels[k] || esc(k)}</b> <span class="helper">${esc(v.value)}</span><div class="quote">“${esc(v.quote)}”<small>${esc(v.turn_id)} · ${a.turns.find((t) => t.id === v.turn_id)?.speaker === "customer" ? "客户" : a.turns.find((t) => t.id === v.turn_id)?.speaker === "sales" ? "销售称呼" : "说话人待确认"}</small></div></div>`,
      )
      .join("") || '<div class="notice">暂无可验证字段证据。</div>'
  }<div class="section-label">完整通话</div><div class="review-source">${esc(lead.text)}</div>`;
}
function scoreView(lead) {
  const a = lead.analysis,
    i = a.intent;
  return `<div class="score-head"><div class="score-value">${i.score}<small> / 100</small></div><div>${badge(i.level)}<div class="helper">机器评分卡 v${i.version} · 当前结果${lead.status === "approved" ? "已人工审核" : "待确认"}</div></div></div>${i.card.map((c) => `<div class="score-row"><div class="score-row-head"><span>${c.label}</span><span>${c.points} / ${c.weight}</span></div><div class="bar"><span style="width:${(c.points / c.weight) * 100}%"></span></div><div class="helper">${esc(c.explanation || "未取得有效积极信号")}</div>${c.quote ? `<div class="quote">${esc(c.quote)}<small>${esc(c.turn_id)}</small></div>` : ""}</div>`).join("")}${i.refusal.value ? `<div class="error-box">明确拒绝优先：${esc(i.refusal.quote)}</div>` : ""}<div class="notice">高意向需总分≥70，且有推进信号与明确近期计划或预算。无信息不等于明确拒绝。机器评分保留用于追溯，人工修正不会伪造重算后的评分。</div><div class="helper">${esc(a.confidence_note)}</div>`;
}
function historyView(lead) {
  return `<div class="section-label first">审核与修正记录</div>${
    (lead.reviews || [])
      .map((h) => {
        const before = JSON.parse(h.before_json),
          after = JSON.parse(h.after_json);
        return `<div class="history"><div class="text-between"><b>${esc(h.reviewer)} · ${h.decision === "approve" ? "审核通过" : "退回补充"}</b><span>${formatTime(h.created_at)}</span></div><div>${esc(h.note)}</div>${Object.keys(
          after,
        )
          .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
          .map(
            (k) =>
              `<div>${labels[k] || esc(k)}：${esc(before[k])} → ${esc(after[k])}</div>`,
          )
          .join(
            "",
          )}${h.verification_source ? `<div>核验来源：${esc(h.verification_source)}</div>` : ""}</div>`;
      })
      .join("") ||
    '<div class="notice">还没有审核记录。每次提交都会保留修改前后结果。</div>'
  }<div class="section-label">运行记录</div><div class="helper">${esc(lead.analysis.provider_model)} · 用时 ${lead.analysis.elapsed_seconds}s · Prompt v${lead.analysis.prompt_version}<br>工作流：${lead.analysis.workflow.join(" → ")}<br>输入摘要：${esc(lead.analysis.input_hash.slice(0, 16))}</div>`;
}
function filteredLeads() {
  return S.leads.filter(
    (l) =>
      (S.filter === "all" || l.status === S.filter) &&
      (!S.search ||
        (l.result.company_name + " " + l.title + " " + l.result.area)
          .toLowerCase()
          .includes(S.search.toLowerCase())),
  );
}
function reviewPage() {
  const leads = filteredLeads();
  const current = S.leads.find((l) => l.id === S.reviewId);
  return `${pageHead("人工审核", "对照原文核实信息，支持单条审核与批量处理。", `<button class="button" data-action="export-approved">${icon("download")} 导出已通过线索</button>`)}<div class="review-toolbar"><input id="lead-search" placeholder="搜索企业、地区或通话名称" value="${esc(S.search)}" aria-label="搜索线索"><select id="lead-filter" aria-label="审核状态">${[
    ["pending", "待审核"],
    ["all", "全部线索"],
    ["approved", "已通过"],
    ["rejected", "待补充"],
    ["ready", "自动完成"],
  ]
    .map(
      ([k, v]) =>
        `<option value="${k}" ${S.filter === k ? "selected" : ""}>${v}</option>`,
    )
    .join(
      "",
    )}</select><span class="helper">${leads.length} 条</span><button class="button small" data-action="select-all">全选当前列表</button><button class="button small light" data-action="batch" ${S.selected.size ? "" : "disabled"}>批量审核 (${S.selected.size})</button></div><div class="review-grid"><section class="panel lead-list">${leads.map((l) => `<div class="lead-item ${l.id === S.reviewId ? "active" : ""}" data-lead="${l.id}" tabindex="0" role="button" aria-label="查看${esc(l.result.company_name || l.title)}"><input type="checkbox" data-select="${l.id}" aria-label="选择${esc(l.title)}" ${S.selected.has(l.id) ? "checked" : ""}><div class="lead-item-main"><h3>${esc(l.result.company_name || l.title)}</h3><div class="inline-actions">${badge(l.result.intent_level)}<span class="pill ${l.status}">${statusName[l.status]}</span></div><p style="margin-top:8px">${esc(l.result.area || "地区待确认")} · ${sourceName[l.source]}</p></div></div>`).join("") || '<div class="empty" style="padding:45px 18px"><h2>这里还没有线索</h2><p>先分析一段通话，或切换筛选条件。</p></div>'}</section><section class="panel">${current ? resultPanel(current, true) : '<div class="empty"><div class="empty-icon">' + icon("review") + "</div><h2>选择一条线索开始审核</h2><p>原文、机器依据和修正表单将在这里显示。</p></div>"}</section></div>`;
}
function reviewForm(lead) {
  const draft = S.reviewDrafts[lead.id];
  const values = draft?.version === lead.version ? draft.values : {};
  const r = { ...lead.result, ...values };
  return `<form id="review-form" class="panel-body" data-version="${lead.version}" data-review-lead="${esc(lead.id)}">${S.selected.size ? `<div class="notice">已勾选 ${S.selected.size} 条，提交将审核全部所选线索。${S.selected.has(lead.id) ? "各条字段修改分别保存，不会相互覆盖。" : "当前详情未勾选，其字段修改不包含在本次提交中。"}</div>` : ""}<div class="section-label first">修正与确认 <span class="helper">版本 ${lead.version}</span></div><div class="form-row">${["company_name", "industry", "area", "contact_name", "contact_title", "phone", "mendian", "shejishi", "call_time"].map((k) => `<div class="field"><label for="edit-${k}">${labels[k]}</label><input id="edit-${k}" name="${k}" value="${esc(r[k])}" maxlength="1500"></div>`).join("")}<div class="field"><label for="edit-intent">意向等级</label><select id="edit-intent" name="intent_level">${Object.entries(
    intentName,
  )
    .map(
      ([k, v]) =>
        `<option value="${k}" ${r.intent_level === k ? "selected" : ""}>${v}</option>`,
    )
    .join(
      "",
    )}</select></div></div>${["demand_summary", "intent_reason", "next_action"].map((k) => `<div class="field"><label for="edit-${k}">${labels[k]}</label><textarea id="edit-${k}" name="${k}" maxlength="3000">${esc(r[k])}</textarea></div>`).join("")}<div class="form-row"><div class="field"><label for="reviewer">审核人 *</label><input id="reviewer" name="reviewer" required maxlength="60" value="${esc(values.reviewer ?? localStorage.getItem("sdr_reviewer") ?? "")}" placeholder="填写姓名或工号"></div><div class="field"><label for="review-note">审核说明 *</label><input id="review-note" name="note" value="${esc(values.note || "")}" required minlength="2" maxlength="1000" placeholder="至少2字，说明核对结果或修正原因"></div></div><details style="margin:8px 0 16px"><summary class="helper">企业核验与反馈学习</summary><div class="field" style="margin-top:10px"><label for="verification">核验来源</label><input id="verification" name="verification_source" value="${esc(values.verification_source || "")}" placeholder="官方链接、客户提供的主体信息等" maxlength="1000"></div><label class="check-label"><input type="checkbox" name="learn_alias" ${values.learn_alias ? "checked" : ""}>将本次核验加入企业别名词库，仅在相同地区与行业下使用。需填写核验来源。</label></details><div class="text-between"><span class="helper">机器依据保留，人工修改单独留痕</span><div class="inline-actions"><button type="submit" name="decision" value="reject" class="button">${S.selected.size ? `退回所选（${S.selected.size}条）` : "退回补充"}</button><button type="submit" name="decision" value="approve" class="button primary">${icon("check")} 保存并通过${S.selected.size ? `（${S.selected.size}条）` : ""}</button></div></div></form>`;
}
function reportPage() {
  const r = S.report;
  return `${pageHead("效果验证", "查看测试结果、模型案例与当前验证范围。")}<div class="stats">${stat("真实录音材料", S.recordings.length, "audio")}${stat("已完成机器转写", S.recordings.filter((x) => x.transcribed).length, "chat")}${stat("最近回归测试", r.test_summary ? `${r.test_summary.passed} / ${r.test_summary.total}` : (r.tests_passed ?? "—"), "check", true)}${stat("模型验证案例", r.llm_cases?.length ?? "—", "spark", true)}</div><div class="report-grid"><section class="panel report-card"><h2>验证范围</h2>${r.test_summary?.failed ? `<div class="error-box">当前测试报告有 ${r.test_summary.failed} 项失败，请先修复再交付。</div>` : ""}<p>${esc(r.summary || "验证报告尚未生成。请运行测试与评估脚本。")}</p><div class="notice">题目示例与合成测试用于验证规则和流程，不能代替真实录音上的独立准确率评估。</div><table class="metric-table"><thead><tr><th>项目</th><th>状态</th></tr></thead><tbody><tr><td>企业主体独立准确率</td><td>尚无已核验真实金标</td></tr><tr><td>真实通话意向 Macro-F1</td><td>待人工标注后计算</td></tr><tr><td>置信度校准</td><td>启发式支持度，未概率校准</td></tr><tr><td>外部检索</td><td>${S.config.search_configured ? "已配置，网页候选仍需核验" : "未配置，可通过人工核验反馈"}</td></tr></tbody></table></section><section class="panel report-card"><h2>模型与规则如何协作</h2><ol><li>模型提取客户事实、意向信号及原文引用。</li><li>程序验证引用来自对应发言，排除销售话术计分。</li><li>企业候选区分品牌、自报名称与已核验主体。</li><li>评分卡计算意向，明确拒绝优先处理。</li><li>证据不足或有歧义时进入人工审核。</li></ol><p>人工通过后可导出标准 SQL 字段。学习企业别名需要明确核验来源，并绑定地区与行业。</p></section><section class="panel report-card wide"><h2>模型案例验证记录</h2><table class="metric-table"><thead><tr><th>案例</th><th>材料类型</th><th>预期意向</th><th>实际结果</th><th>结构与证据</th></tr></thead><tbody>${(r.llm_cases || []).map((c) => `<tr><td>${esc(c.title)}</td><td>${sourceName[c.source] || esc(c.source)}</td><td>${intentName[c.expected_intent] || "未设金标"}</td><td>${c.intent_level ? badge(c.intent_level) : esc(c.error || "未运行")}</td><td>${c.valid_schema ? "15字段结构通过" : "—"}${c.grounded_fields != null ? " · " + c.grounded_fields + "项字段证据" : ""}</td></tr>`).join("") || '<tr><td colspan="5">尚未运行模型案例验证。</td></tr>'}</tbody></table>${realChecks(r)}<div class="helper" style="margin-top:14px">测试时间：${esc(r.generated_at || "尚未运行")} · 实际返回模型：${esc(r.provider_model || "尚未验证")}</div></section></div>`;
}
function saveInputDraft() {
  if (!S.initialized) return;
  try {
    const keys = [
      "inputType",
      "text",
      "title",
      "callTime",
      "source",
      "sampleId",
      "recordingId",
      "recordingItem",
      "fileMeta",
      "mode",
    ];
    sessionStorage.setItem(
      "sdr_input_draft",
      JSON.stringify({
        ...Object.fromEntries(keys.map((k) => [k, S[k]])),
        current_id: S.current?.id || "",
        pending_request: S.pendingRequest,
      }),
    );
  } catch {}
}
async function restoreInputDraft() {
  try {
    const draft = JSON.parse(
      sessionStorage.getItem("sdr_input_draft") || "null",
    );
    if (
      !draft ||
      !["text", "audio"].includes(draft.inputType) ||
      typeof draft.text !== "string" ||
      draft.text.length > 50000
    )
      return;
    for (const key of [
      "inputType",
      "text",
      "title",
      "callTime",
      "source",
      "sampleId",
      "recordingId",
      "mode",
    ]) {
      if (typeof draft[key] === "string") S[key] = draft[key];
    }
    S.fileMeta = draft.fileMeta || null;
    if (
      draft.pending_request?.id &&
      typeof draft.pending_request.signature === "string"
    )
      S.pendingRequest = draft.pending_request;
    S.recordingItem = draft.recordingItem || null;
    S.current =
      S.leads.find((l) => l.id === draft.current_id && l.text === S.text) ||
      null;
    if (S.recordingId) {
      S.loadingInput = true;
      render();
      const [, transcript] = await Promise.all([
        restoreAudio(),
        api("/recordings/" + S.recordingId + "/transcript"),
      ]);
      S.transcript = transcript;
    }
  } catch {
    S.error = "上次的录音暂时无法载入，可以重新选择文件。";
  } finally {
    S.loadingInput = false;
  }
}
function captureReviewDraft(form) {
  S.reviewDrafts[form.dataset.reviewLead] = {
    version: Number(form.dataset.version),
    values: {
      ...Object.fromEntries(new FormData(form)),
      learn_alias: form.elements.learn_alias.checked,
    },
  };
}
function reviewChanges(lead, values) {
  const changes = {};
  for (const key of Object.keys(labels)) {
    if (
      key !== "confidence_score" &&
      key !== "need_human_review" &&
      Object.hasOwn(values, key) &&
      String(values[key]) !== lead.result[key]
    )
      changes[key] = String(values[key]);
  }
  return changes;
}
function selectedReviewItems(includeLearning = false) {
  return S.leads
    .filter((lead) => S.selected.has(lead.id))
    .map((lead) => {
      const draft = S.reviewDrafts[lead.id];
      return {
        id: lead.id,
        version: draft?.version ?? lead.version,
        changes: reviewChanges(lead, draft?.values || {}),
        learn_alias: includeLearning && !!draft?.values.learn_alias,
        verification_source: includeLearning
          ? draft?.values.verification_source || ""
          : "",
      };
    });
}
function render() {
  saveInputDraft();
  document.getElementById("app").innerHTML = shell();
}
async function refresh() {
  S.leads = await api("/leads");
  for (const context of [S, ...Object.values(S.inputDrafts)]) {
    if (context.current)
      context.current =
        S.leads.find((l) => l.id === context.current.id) || null;
  }
  for (const [id, draft] of Object.entries(S.reviewDrafts)) {
    if (S.leads.find((l) => l.id === id)?.version !== draft.version)
      delete S.reviewDrafts[id];
  }
}
function resetAttachment() {
  if (S.audioUrl) URL.revokeObjectURL(S.audioUrl);
  S.audioUrl = "";
  S.recordingId = "";
  S.recordingItem = null;
  S.fileMeta = null;
  S.transcript = null;
  S.jobInfo = null;
  S.sampleId = "";
  S.error = "";
  S.current = null;
}
function loadSample(id) {
  if (S.busy || S.uploading || S.loadingInput || S.job) return;
  const sample = S.samples.find((x) => x.id === id);
  if (!sample) return;
  resetAttachment();
  S.text = sample.text;
  S.title = sample.title;
  S.source = sample.source;
  S.sampleId = id;
  S.callTime = "";
  S.inputType = "text";
  render();
}
async function analyzeInput() {
  if (S.busy || S.uploading || S.loadingInput || S.job) return;
  if (!S.text.trim()) {
    toast(
      S.recordingId
        ? "请先本地转写录音，或在文本框中填写沟通记录"
        : "请先粘贴、输入或上传电话沟通记录",
    );
    return;
  }
  if (S.text.length > 50000) {
    toast("通话文本不能超过50,000字");
    return;
  }
  S.busy = true;
  S.error = "";
  render();
  try {
    const payload = {
      text: S.text,
      title: S.title || "新通话",
      call_time: S.callTime ? S.callTime + ":00+08:00" : "",
      source: S.source,
      recording_id: S.recordingId || null,
      upload_id: S.fileMeta?.id || null,
      mode: S.mode,
    };
    const signature = JSON.stringify(payload);
    if (S.pendingRequest?.signature !== signature)
      S.pendingRequest = { id: crypto.randomUUID(), signature };
    saveInputDraft();
    const lid = await post("/analyze", {
      ...payload,
      request_id: S.pendingRequest.id,
    });
    S.pendingRequest = null;
    S.current = lid;
    S.tab = "overview";
    await refresh();
    toast("分析完成，原文依据与审核提示已生成");
  } catch (e) {
    S.error = e.message;
  } finally {
    S.busy = false;
    render();
  }
}
async function openReview(id, reveal = false) {
  S.reviewId = id;
  S.view = "review";
  S.tab = "overview";
  try {
    const lead = await api("/leads/" + id);
    S.leads = S.leads.map((l) => (l.id === id ? lead : l));
    if (reveal) S.selected.clear();
    if (reveal && !filteredLeads().some((l) => l.id === id)) {
      if (S.filter !== "all" && S.filter !== lead.status)
        S.filter = lead.status;
      S.search = "";
    }
    render();
  } catch (e) {
    toast(e.message);
  }
}
function download(content, name, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}
function restoreAudio() {
  if (S.audioUrl) URL.revokeObjectURL(S.audioUrl);
  S.audioUrl = "";
  // Authenticated audio is fetched by the same API helper, never by a URL token.
  return api("/recordings/" + S.recordingId + "/audio", {}, true).then(
    async (response) => {
      S.audioUrl = URL.createObjectURL(await response.blob());
    },
  );
}
async function chooseRecording(rid, uploadedItem = null) {
  if (S.busy || S.loadingInput || S.job) return;
  if (!rid) return;
  const item = uploadedItem || S.recordings.find((r) => r.id === rid);
  if (!item) return;
  resetAttachment();
  S.recordingId = rid;
  S.recordingItem = item;
  S.text = "";
  S.source = "recording";
  S.title = item.title;
  S.callTime = item.call_time.slice(0, 16);
  S.loadingInput = true;
  render();
  try {
    const [, transcript] = await Promise.all([
      restoreAudio(),
      api("/recordings/" + rid + "/transcript"),
    ]);
    S.transcript = transcript;
    S.text = transcript.text || "";
  } catch (e) {
    S.error = e.message;
  } finally {
    S.loadingInput = false;
    render();
  }
}
async function uploadFile(file) {
  if (!file || S.uploading || S.loadingInput || S.busy || S.job) return;
  const extension = file.name.split(".").pop().toLowerCase();
  const isText = extension === "txt";
  if (!["txt", "mp3", "wav", "m4a"].includes(extension)) {
    toast("请上传 TXT 沟通记录，或 MP3、WAV、M4A 录音。");
    return;
  }
  if (file.size > (isText ? 1 : 50) * 1024 * 1024) {
    toast(isText ? "TXT 文件不能超过1 MB" : "录音不能超过50 MB");
    return;
  }
  let transcribeUploaded = false;
  S.uploading = true;
  S.error = "";
  render();
  try {
    if (!S.config.upload_supported)
      throw new Error("后台尚未加载上传功能，请重启项目服务后刷新页面。");
    const form = new FormData();
    form.append("file", file);
    const imported = await api("/uploads", { method: "POST", body: form });
    if (imported.kind === "audio") {
      S.inputType = "audio";
      await chooseRecording(imported.id, imported.recording);
      transcribeUploaded = !S.error;
    } else {
      resetAttachment();
      S.text = imported.text;
      S.title =
        imported.name.replace(/\.txt$/i, "").slice(0, 120) || "导入记录";
      S.callTime = "";
      S.source = "file";
      S.inputType = "text";
    }
    S.fileMeta = imported;
    toast(
      imported.kind === "audio"
        ? "录音已上传，正在启动完整转写。"
        : "沟通记录已导入，可以编辑后开始分析。",
    );
  } catch (e) {
    S.error = e.message;
  } finally {
    S.uploading = false;
    render();
  }
  if (transcribeUploaded) await transcribe();
}
async function transcribe() {
  if (!S.recordingId || S.job || S.busy || S.uploading || S.loadingInput)
    return;
  S.error = "";
  try {
    const job = await post("/recordings/" + S.recordingId + "/transcribe", {});
    if (job.busy && job.recording_id !== S.recordingId)
      throw new Error("另一段录音正在转写，请稍后再试。");
    S.job = job.job_id;
    S.pollFailures = 0;
    S.jobInfo = null;
    sessionStorage.setItem(
      "sdr_asr_job",
      JSON.stringify({
        id: S.job,
        recording_id: S.recordingId,
        item: S.recordingItem,
        file: S.fileMeta,
      }),
    );
    if (job.busy) toast("已有转写任务正在处理，完成后可重新选择录音。");
    render();
    pollJob();
  } catch (e) {
    S.error = e.message;
    render();
  }
}
async function pollJob() {
  if (!S.job) return;
  try {
    const job = await api("/jobs/" + S.job);
    S.jobInfo = job;
    if (S.pollFailures) {
      S.pollFailures = 0;
      S.error = "";
    }
    if (job.status === "completed") {
      S.job = null;
      sessionStorage.removeItem("sdr_asr_job");
      S.recordings = S.recordings.map((item) =>
        item.id === job.recording_id ? { ...item, transcribed: true } : item,
      );
      if (job.recording_id === S.recordingId) {
        S.transcript =
          job.result ||
          (await api("/recordings/" + S.recordingId + "/transcript"));
        S.text = S.transcript.text || "";
        S.current = null;
        if (!S.text.trim())
          S.error =
            "未识别到可用语音，请回听检查录音，或直接粘贴已有的转写文本。";
      }
      toast(S.error || "机器转写完成，请回听并标注说话人。");
      render();
    } else if (job.status === "failed") {
      S.job = null;
      sessionStorage.removeItem("sdr_asr_job");
      S.error = "转写失败：" + (job.error || "请重新转写，录音已保留。");
      toast(S.error);
      render();
    } else {
      const progressBox = $(".asr-progress");
      if (progressBox) {
        const p = job.progress || {};
        const percent = Math.min(99, Math.max(0, Number(p.percent || 0)));
        progressBox.innerHTML = `<div class="text-between"><span>${esc(p.message || "正在识别整段录音…")}</span><b>${percent}%</b></div><progress max="100" value="${percent}" aria-label="录音转写进度"></progress>${p.duration ? `<div class="helper">音频位置 ${Math.round(p.processed_seconds || 0)} / ${Math.round(p.duration)} 秒</div>` : ""}`;
      }
      setTimeout(pollJob, 2500);
    }
  } catch (e) {
    S.pollFailures += 1;
    if (S.pollFailures <= 3) {
      S.error = "连接暂时中断，正在恢复转写进度…";
      setTimeout(pollJob, 4000);
    } else {
      S.job = null;
      S.error = "转写进度连接中断，请刷新页面恢复任务。";
    }
    render();
  }
}
function showAuth() {
  const m = $("#modal");
  m.innerHTML = `<h2>工作区访问设置</h2><p>如后端启用了访问保护，请输入访问令牌。模型密钥由后端配置，页面无需填写。</p><form id="auth-form"><div class="field"><label for="access-token">访问令牌</label><input id="access-token" name="token" type="password" autocomplete="off"></div><div class="inline-actions"><button type="button" data-action="close-modal" class="button">关闭</button><button class="button primary">保存并连接</button></div></form>`;
  if (!m.open) m.showModal();
}
function showBatch() {
  const rows = S.leads.filter((l) => S.selected.has(l.id));
  if (!rows.length) return;
  const m = $("#modal");
  m.innerHTML = `<h2>批量审核与订正</h2><p>将对选中的 ${rows.length} 条线索执行同一操作。请逐项确认差异，修改会保留审核记录。</p><form id="batch-form"><div class="form-row"><div class="field"><label for="batch-company">统一企业名称（留空不修改）</label><input name="company_name" id="batch-company" maxlength="1500"></div><div class="field"><label for="batch-intent">统一意向等级</label><select name="intent_level" id="batch-intent"><option value="">保持原值</option><option value="high">高意向</option><option value="medium">中意向</option><option value="low">低意向</option></select></div></div><div class="field"><label for="batch-reason">新的意向依据（改等级时必填）</label><input id="batch-reason" name="intent_reason" maxlength="3000"></div><div id="batch-preview" class="batch-preview">${rows.map((l) => `<div>${esc(l.result.company_name || l.title)} · ${intentName[l.result.intent_level]} → 保持原值</div>`).join("")}</div><div class="form-row"><div class="field"><label for="batch-reviewer">审核人 *</label><input id="batch-reviewer" name="reviewer" required value="${esc(localStorage.getItem("sdr_reviewer") || "")}" maxlength="60"></div><div class="field"><label for="batch-note">审核说明 *</label><input id="batch-note" name="note" required minlength="2" maxlength="1000"></div></div><div class="notice">各条草稿修改分别保存，统一修改优先。任一条版本冲突时整批不提交；企业别名反馈请使用详情表单保存。</div><div class="inline-actions"><button type="button" data-action="close-modal" class="button">取消</button><button type="submit" value="reject" name="decision" class="button">全部退回补充</button><button type="submit" value="approve" name="decision" class="button primary">确认并通过</button></div></form>`;
  m.showModal();
  updateBatchPreview();
}
function updateBatchPreview() {
  const f = $("#batch-form");
  if (!f) return;
  const company = f.elements.company_name.value;
  const intent = f.elements.intent_level.value;
  $("#batch-preview").innerHTML = S.leads
    .filter((l) => S.selected.has(l.id))
    .map(
      (l) =>
        `<div>${esc(l.result.company_name || l.title)} / ${intentName[l.result.intent_level]} → ${esc(company || S.reviewDrafts[l.id]?.values.company_name || l.result.company_name || "未确认")} / ${intentName[intent || S.reviewDrafts[l.id]?.values.intent_level || l.result.intent_level]}</div>`,
    )
    .join("");
}
function showReviewError(form, message) {
  let error = form.querySelector("[data-review-error]");
  if (!error) {
    error = document.createElement("div");
    error.dataset.reviewError = "";
    error.className = "error-box";
    error.setAttribute("role", "alert");
    form.insertBefore(error, form.lastElementChild);
  }
  error.textContent = message;
  error.hidden = false;
}
document.addEventListener(
  "invalid",
  (event) => {
    const form = event.target.closest("#review-form, #batch-form");
    if (!form) return;
    const field = event.target;
    const message =
      field.name === "reviewer"
        ? "请填写审核人（姓名或工号）。"
        : field.name === "note"
          ? "请填写至少2字的审核说明，再提交审核。"
          : `请检查${field.labels?.[0]?.textContent || "表单内容"}：${field.validationMessage}`;
    showReviewError(form, message);
  },
  true,
);

document.addEventListener("click", async (event) => {
  const nav = event.target.closest("[data-nav]");
  if (nav) {
    S.view = nav.dataset.nav;
    S.tab = "overview";
    render();
    window.scrollTo(0, 0);
    return;
  }
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    S.tab = tab.dataset.tab;
    render();
    return;
  }
  const input = event.target.closest("[data-input]");
  if (input && !inputLocked()) {
    await switchInput(input.dataset.input);
    return;
  }
  const row = event.target.closest(".lead-item[data-lead]");
  if (row && !event.target.closest("input")) {
    await openReview(row.dataset.lead);
    return;
  }
  const b = event.target.closest("[data-action]");
  if (!b) return;
  try {
    switch (b.dataset.action) {
      case "upload-text":
        $("#text-file").click();
        break;
      case "upload-audio":
        $("#audio-file").click();
        break;
      case "load-assignment":
        loadSample("assignment");
        break;
      case "analyze":
        await analyzeInput();
        break;
      case "open-review":
        await openReview(S.current.id, true);
        break;
      case "download-current":
        download(JSON.stringify(S.current.result, null, 2), "sql-lead.json");
        break;
      case "export-approved": {
        const response = await api(
          "/export?scope=approved&format=csv",
          {},
          true,
        );
        download(await response.text(), "approved-sql-leads.csv", "text/csv");
        break;
      }
      case "auth":
        showAuth();
        break;
      case "close-modal":
        $("#modal").close();
        break;
      case "transcribe":
        await transcribe();
        break;
      case "select-all": {
        const ids = filteredLeads().map((l) => l.id);
        if (ids.every((id) => S.selected.has(id)))
          ids.forEach((id) => S.selected.delete(id));
        else ids.forEach((id) => S.selected.add(id));
        if (S.selected.size && !S.reviewId)
          await openReview([...S.selected][0]);
        else render();
        break;
      }
      case "batch":
        showBatch();
        break;
      case "company-search": {
        b.disabled = true;
        const lead =
          S.view === "review"
            ? S.leads.find((l) => l.id === S.reviewId)
            : S.current;
        const data = await post("/leads/" + lead.id + "/search", {});
        $("#search-results").innerHTML =
          `<div class="notice" style="margin-top:12px">${esc(data.note)}</div>` +
          data.results
            .map(
              (r) =>
                `<div class="candidate"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a><small>${esc(r.content)}</small></div>`,
            )
            .join("");
        b.disabled = false;
        break;
      }
    }
  } catch (e) {
    toast(e.message);
    b.disabled = false;
  }
});
document.addEventListener("input", (event) => {
  const t = event.target;
  if (t.id === "lead-search") {
    S.search = t.value;
    S.selected.clear();
    if (!filteredLeads().some((l) => l.id === S.reviewId)) S.reviewId = "";
    const start = t.selectionStart,
      end = t.selectionEnd;
    render();
    const search = $("#lead-search");
    search.focus();
    search.setSelectionRange(start, end);
    return;
  }
  if (t.dataset.state) {
    S[t.dataset.state] = t.value;
    if (t.dataset.state === "text") {
      if (S.current && S.current.text !== t.value) {
        S.current = null;
        $("#analysis-result").innerHTML = emptyResult();
      }
      $("#char-count") &&
        ($("#char-count").textContent = t.value.length + " / 50,000");
    }
  }
  if (t.dataset.state) saveInputDraft();
  if (t.closest("#review-form")) captureReviewDraft(t.closest("form"));
  if (t.closest("#batch-form")) updateBatchPreview();
});
document.addEventListener("change", async (event) => {
  const t = event.target;
  if (t.dataset.state) {
    S[t.dataset.state] = t.value;
    saveInputDraft();
  }
  if (t.id === "text-file" || t.id === "audio-file") {
    await uploadFile(t.files?.[0]);
    return;
  }
  if (t.id === "sample") loadSample(t.value);
  if (t.id === "recording") await chooseRecording(t.value);
  if (t.id === "lead-filter") {
    S.filter = t.value;
    S.selected.clear();
    if (!filteredLeads().some((l) => l.id === S.reviewId)) S.reviewId = "";
    render();
  }
  if (t.dataset.select) {
    const scroll = $(".lead-list")?.scrollTop || 0;
    if (t.checked) S.selected.add(t.dataset.select);
    else S.selected.delete(t.dataset.select);
    if (t.checked && !S.reviewId) await openReview(t.dataset.select);
    else render();
    if ($(".lead-list")) $(".lead-list").scrollTop = scroll;
  }
  if (t.dataset.speaker != null && S.transcript) {
    const lines = S.text.split("\n");
    if (lines.length !== S.transcript.segments.length) {
      toast(
        "段落数量已调整，请直接在下方文本中标注销售或客户，以保留你的修正。",
      );
      t.value = S.transcript.segments[Number(t.dataset.speaker)].speaker;
      return;
    }
    const idx = Number(t.dataset.speaker);
    const stamp = lines[idx].match(/^\[[^\]]+\]\s*/)?.[0] || "";
    const content = lines[idx]
      .slice(stamp.length)
      .replace(/^(?:销售|客户|sales|customer)\s*[:：]\s*/i, "");
    lines[idx] =
      stamp +
      (t.value === "sales"
        ? "销售："
        : t.value === "customer"
          ? "客户："
          : "") +
      content;
    S.text = lines.join("\n");
    if (S.current?.text !== S.text) S.current = null;
    S.transcript.segments.forEach((r, i) => {
      const line = lines[i].replace(/^\[[^\]]+\]\s*/, "");
      r.speaker = /^(?:销售|sales)\s*[:：]/i.test(line)
        ? "sales"
        : /^(?:客户|customer)\s*[:：]/i.test(line)
          ? "customer"
          : "unknown";
      r.text = line.replace(/^(?:销售|客户|sales|customer)\s*[:：]\s*/i, "");
    });
    render();
  }
  if (t.dataset.state) saveInputDraft();
  if (t.closest("#review-form")) captureReviewDraft(t.closest("form"));
  if (t.closest("#batch-form")) updateBatchPreview();
});
document.addEventListener("keydown", (event) => {
  if (
    (event.key === "Enter" || event.key === " ") &&
    event.target.matches(".lead-item[data-lead]")
  ) {
    event.preventDefault();
    openReview(event.target.dataset.lead);
  }
});
document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const submit = event.submitter;
  if (form.id === "review-form" || form.id === "batch-form") {
    if (!form.elements.reviewer.value.trim()) {
      showReviewError(form, "请填写审核人（姓名或工号）。");
      form.elements.reviewer.focus();
      return;
    }
    if (form.elements.note.value.trim().length < 2) {
      showReviewError(form, "请填写至少2字的审核说明，再提交审核。");
      form.elements.note.focus();
      return;
    }
    const error = form.querySelector("[data-review-error]");
    if (error) error.hidden = true;
  }
  if (form.id === "auth-form") {
    sessionStorage.setItem("sdr_token", form.elements.token.value);
    $("#modal").close();
    await init();
    return;
  }
  if (form.id === "review-form") {
    const lead = S.leads.find((l) => l.id === form.dataset.reviewLead);
    if (!lead) {
      showReviewError(form, "当前线索未载入，请重新选择线索后审核。");
      return;
    }
    captureReviewDraft(form);
    const data = new FormData(form);
    const changes = reviewChanges(lead, Object.fromEntries(data));
    const items = selectedReviewItems(true);
    if (S.selected.size > 100 || items.length !== S.selected.size) {
      showReviewError(
        form,
        "一次最多审核100条，请检查所选线索或减少勾选后重试。",
      );
      return;
    }
    const body = {
      version: Number(form.dataset.version),
      reviewer: String(data.get("reviewer")),
      note: String(data.get("note")),
      changes,
      decision: submit?.value || "approve",
      learn_alias: data.has("learn_alias"),
      verification_source: String(data.get("verification_source") || ""),
    };
    if (form.dataset.submitting) return;
    form.dataset.submitting = "true";
    const submitContent = submit?.innerHTML;
    if (submit) submit.textContent = "正在保存…";
    form
      .querySelectorAll('button[type="submit"]')
      .forEach((b) => (b.disabled = true));
    try {
      let updated;
      if (items.length) {
        await post("/reviews/batch", {
          items,
          reviewer: body.reviewer,
          note: body.note,
          changes: {},
          decision: body.decision,
        });
        for (const item of items) delete S.reviewDrafts[item.id];
        S.selected.clear();
      } else {
        updated = await post("/leads/" + lead.id + "/review", body);
        delete S.reviewDrafts[lead.id];
      }
      localStorage.setItem("sdr_reviewer", body.reviewer);
      await refresh();
      if (!updated) updated = await api("/leads/" + lead.id);
      S.leads = S.leads.map((l) => (l.id === updated.id ? updated : l));
      if (S.current?.id === updated.id) S.current = updated;
      toast(
        items.length
          ? `已${body.decision === "approve" ? "通过" : "退回补充"}所选 ${items.length} 条线索，修改记录已分别保存`
          : "审核已保存，修改记录可追溯",
      );
      render();
    } catch (e) {
      showReviewError(form, e.message);
      delete form.dataset.submitting;
      if (submit) submit.innerHTML = submitContent;
      form
        .querySelectorAll('button[type="submit"]')
        .forEach((b) => (b.disabled = false));
    }
  }
  if (form.id === "batch-form") {
    const data = new FormData(form),
      changes = {};
    for (const k of ["company_name", "intent_level", "intent_reason"])
      if (String(data.get(k) || "").trim())
        changes[k] = String(data.get(k)).trim();
    const body = {
      items: selectedReviewItems(),
      reviewer: String(data.get("reviewer")),
      note: String(data.get("note")),
      changes,
      decision: submit?.value || "approve",
    };
    if (form.dataset.submitting) return;
    form.dataset.submitting = "true";
    const submitContent = submit?.innerHTML;
    if (submit) submit.textContent = "正在保存…";
    form
      .querySelectorAll('button[type="submit"]')
      .forEach((b) => (b.disabled = true));
    try {
      await post("/reviews/batch", body);
      localStorage.setItem("sdr_reviewer", body.reviewer);
      S.selected.clear();
      $("#modal").close();
      await refresh();
      if (S.reviewId) {
        const lead = await api("/leads/" + S.reviewId);
        S.leads = S.leads.map((l) => (l.id === lead.id ? lead : l));
      }
      toast("批量审核已保存");
      render();
    } catch (e) {
      showReviewError(form, e.message);
      delete form.dataset.submitting;
      if (submit) submit.innerHTML = submitContent;
      form
        .querySelectorAll('button[type="submit"]')
        .forEach((b) => (b.disabled = false));
    }
  }
});
async function init() {
  try {
    [S.config, S.leads, S.samples, S.recordings, S.report] = await Promise.all([
      api("/config"),
      api("/leads"),
      api("/samples"),
      api("/recordings"),
      api("/evaluation"),
    ]);
    await restoreInputDraft();
    S.initialized = true;
    render();
    const saved = sessionStorage.getItem("sdr_asr_job");
    if (saved) {
      try {
        const task = JSON.parse(saved);
        S.inputType = "audio";
        if (S.recordingId !== task.recording_id)
          await chooseRecording(task.recording_id, task.item);
        S.fileMeta = task.file;
        S.job = task.id;
        render();
        pollJob();
      } catch {
        sessionStorage.removeItem("sdr_asr_job");
      }
    }
  } catch (e) {
    render();
    toast(e.message);
  }
}
init();

function realChecks(r) {
  return r.real_material_checks?.length
    ? `<div class="section-label">真实转写文本集成验证（非准确率评估）</div><table class="metric-table"><thead><tr><th>材料</th><th>机器片段</th><th>结构</th><th>分流</th></tr></thead><tbody>${r.real_material_checks.map((c) => `<tr><td>${esc(c.title)}</td><td>${c.segments}</td><td>${c.valid_schema ? "15字段通过" : "待检查"}</td><td>${c.need_human_review ? "进入人工审核" : "自动完成"}</td></tr>`).join("")}</tbody></table><div class="helper">已获得两段文本的外部传输授权；说话人未人工确认，无企业主体与意向金标。</div>`
    : "";
}

function humanReason(text) {
  let result = String(text);
  for (const [key, value] of Object.entries(labels))
    result = result.replaceAll(key, value);
  return result;
}
