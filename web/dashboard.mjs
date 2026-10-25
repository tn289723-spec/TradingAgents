/** Read-only, fail-closed projection consumer. No browser-side market computation. */
export const VERSION = "dashboard-projection-v1";
const TRENDS = new Set(["STRONG_UPTREND","UPTREND","PULLBACK_IN_UPTREND","SIDEWAYS","REVERSAL_WATCH","DISTRIBUTION","DOWNTREND","STRONG_DOWNTREND"]);
const LIGHTS = Object.freeze({ PASS: "GREEN", DEGRADED: "YELLOW", BLOCKED: "RED" });
const PIT_CERTIFICATIONS = new Set(["NOT_ESTABLISHED_BY_REPORT","SIGNED_PIT_V1_ATTESTATION_VERIFIED"]);
const FIELDS = new Set(["projection_version","analysis_run_id","snapshot_id","symbol","trade_date","generated_at","directional_score","trend_state","confidence","decision_gate","traffic_light","traffic_light_meaning","score_slope_5d","five_day_change","most_likely_wrong","thesis_status","historical_pit_certification","limitations"]);
const MARKET_SOURCES_VERSION = "official-market-snapshot-v1";
const SOURCE_URLS = Object.freeze({
  twse_ohlcv: "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
  tpex_ohlcv: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
  twse_institutional: "https://www.twse.com.tw/rwd/zh/fund/T86",
  tpex_institutional: "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
  twse_margin: "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
  tpex_margin: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
  tdcc_ownership: "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
});
const SOURCE_LABELS = Object.freeze({
  ohlcv: "日線價量", institutional_flow: "三大法人淨買賣超", margin_balance: "融資融券",
  ownership_distribution: "集保持股分級"
});

export class ProjectionError extends Error {
  constructor(message) { super(message); this.name = "ProjectionError"; }
}
function requireField(ok, name) {
  if (!ok) throw new ProjectionError("投影資料不可信：" + name);
}
function text(value, max = 256) {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max;
}
function finiteRange(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
}
function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
function validTimestamp(value) {
  if (typeof value !== "string") return false;
  const parts = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!parts || !validDate(parts[1])) return false;
  if (+parts[2] > 23 || +parts[3] > 59 || +parts[4] > 59) return false;
  if (parts[5] !== "Z") {
    const hours = Number(parts[5].slice(1, 3));
    const minutes = Number(parts[5].slice(4, 6));
    if (hours > 23 || minutes > 59) return false;
  }
  return Number.isFinite(Date.parse(value));
}

/** Only accepts the exact v1 JSON emitted by render_dashboard_projection_json. */
export function validateProjection(value) {
  requireField(value !== null && typeof value === "object" && !Array.isArray(value), "物件格式");
  const keys = Object.keys(value);
  requireField(keys.length === FIELDS.size && keys.every(key => FIELDS.has(key)), "未知或缺少欄位");
  requireField(value.projection_version === VERSION, "不支援的版本");
  for (const key of ["analysis_run_id","snapshot_id","symbol"]) {
    requireField(text(value[key], 128), key);
  }
  requireField(validDate(value.trade_date), "交易日期");
  requireField(validTimestamp(value.generated_at), "產生時間與時區");
  requireField(finiteRange(value.directional_score), "方向分數");
  requireField(finiteRange(value.confidence), "信心分數");
  requireField(TRENDS.has(value.trend_state), "趨勢狀態");
  requireField(Object.hasOwn(LIGHTS, value.decision_gate), "證據閘門");
  requireField(value.traffic_light === LIGHTS[value.decision_gate], "燈號與閘門矛盾");
  requireField(value.traffic_light_meaning === "EVIDENCE_READINESS_ONLY", "燈號意義");
  requireField(value.score_slope_5d === null || (typeof value.score_slope_5d === "number" && Number.isFinite(value.score_slope_5d)), "五日斜率");
  requireField(value.five_day_change === null && value.most_likely_wrong === null, "不得推測缺失分析");
  requireField(value.thesis_status === "NOT_ASSESSED", "Thesis 尚未評估");
  requireField(PIT_CERTIFICATIONS.has(value.historical_pit_certification), "歷史 PIT 認證狀態");
  requireField(Array.isArray(value.limitations) && value.limitations.length <= 100 &&
    value.limitations.every(item => typeof item === "string" && item.length <= 1000), "限制說明");
  return Object.freeze({ ...value, limitations: Object.freeze([...value.limitations]) });
}

export function parseProjection(json) {
  requireField(typeof json === "string" && json.length <= 131072, "檔案大小");
  let value;
  try { value = JSON.parse(json); }
  catch { throw new ProjectionError("無法解析投影 JSON"); }
  return validateProjection(value);
}

export function validateMarketSources(value) {
  requireField(value !== null && typeof value === "object" && !Array.isArray(value), "官方來源快照物件");
  requireField(Object.keys(value).sort().join(",") === "data_status,generated_at,schema_version,sources,symbols", "官方來源快照欄位");
  requireField(value.schema_version === MARKET_SOURCES_VERSION && value.data_status === "RAW_UNVERIFIED", "官方來源快照版本／狀態");
  requireField(validTimestamp(value.generated_at), "官方來源產生時間");
  requireField(Array.isArray(value.sources) && value.sources.length === Object.keys(SOURCE_URLS).length, "官方來源清單");
  const seenSources = new Set();
  for (const source of value.sources) {
    requireField(source && typeof source === "object" && Object.keys(source).sort().join(",") === "content_sha256,id,label,missing_count,observed_at,record_count,status,trade_date,url", "官方來源描述欄位");
    requireField(Object.hasOwn(SOURCE_URLS, source.id) && source.url === SOURCE_URLS[source.id], "非核准官方來源");
    requireField(!seenSources.has(source.id), "重複官方來源");
    seenSources.add(source.id);
    requireField(source.status === "RAW_UNVERIFIED" && text(source.label, 100), "官方來源狀態");
    requireField(validTimestamp(source.observed_at) && /^[a-f0-9]{64}$/.test(source.content_sha256), "官方來源時間／雜湊");
    requireField(Number.isSafeInteger(source.record_count) && source.record_count >= 0, "官方來源筆數");
    requireField(Number.isSafeInteger(source.missing_count) && source.missing_count >= 0, "官方來源缺漏筆數");
    requireField(source.trade_date === null || validDate(source.trade_date), "官方來源交易日期");
  }
  requireField(value.symbols && typeof value.symbols === "object" && !Array.isArray(value.symbols) && Object.keys(value.symbols).length <= 20000, "官方來源代號數量");
  for (const [symbol, record] of Object.entries(value.symbols)) {
    requireField(/^\d[A-Z0-9]{3,5}$/.test(symbol) && record && typeof record === "object", "官方股票代號");
    requireField(Object.keys(record).sort().join(",") === "market,sources,trade_date", "股票來源資料欄位");
    requireField(["TWSE", "TPEX"].includes(record.market) && validDate(record.trade_date), "股票來源市場／日期");
    requireField(record.sources && typeof record.sources === "object" && !Array.isArray(record.sources), "股票來源證據");
    for (const [key, evidence] of Object.entries(record.sources)) {
      requireField(["ohlcv", "institutional_flow", "margin_balance", "ownership_distribution"].includes(key), "未知證據類型");
      requireField(evidence && typeof evidence === "object" && Object.keys(evidence).sort().join(",") === "content_sha256,evidence_id,observed_at,payload,source,status", "證據欄位");
      requireField(["RAW", "MISSING"].includes(evidence.status) && text(evidence.source, 100), "原始證據狀態");
      requireField(validTimestamp(evidence.observed_at) && /^[a-f0-9]{64}$/.test(evidence.content_sha256), "原始證據時間／雜湊");
      requireField(evidence.status === "RAW" ? text(evidence.evidence_id, 180) : evidence.evidence_id === null, "證據識別碼");
      requireField(evidence.payload && typeof evidence.payload === "object" && !Array.isArray(evidence.payload), "證據內容");
    }
  }
  return value;
}

export function parseMarketSources(json) {
  requireField(typeof json === "string" && json.length <= 25165824, "官方來源快照大小");
  let value;
  try { value = JSON.parse(json); }
  catch { throw new ProjectionError("無法解析官方來源快照"); }
  return validateMarketSources(value);
}

async function decompressMarketSources(buffer) {
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > 25165824) {
      await reader.cancel();
      throw new ProjectionError("官方來源解壓快照超過 24 MiB");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function renderMarketSources(snapshot, symbol) {
  const status = document.getElementById("market-status");
  const output = document.getElementById("market-data");
  const list = document.getElementById("market-source-list");
  output.replaceChildren();
  list.replaceChildren();
  const generated = Date.parse(snapshot.generated_at);
  const age = Date.now() - generated;
  if (age < -300000) throw new ProjectionError("官方快照時間在未來，拒絕顯示");
  if (age > 72 * 60 * 60 * 1000) {
    status.dataset.level = "BLOCKED";
    status.textContent = "🔴 官方來源快照已超過 72 小時｜停止顯示舊資料";
  } else {
    status.dataset.level = "DEGRADED";
    status.textContent = `🟡 ${symbol}｜RAW／未驗證官方資料｜擷取時間 ${snapshot.generated_at}`;
  }
  for (const source of snapshot.sources) {
    const item = document.createElement("li");
    item.textContent = `${source.label}｜RAW／未驗證｜${source.trade_date || "每週快照"}｜觀測 ${source.observed_at}｜可用 ${source.record_count} 筆｜缺漏 ${source.missing_count} 筆`;
    list.append(item);
  }
  if (age > 72 * 60 * 60 * 1000) return;
  const record = snapshot.symbols[symbol];
  if (!record) {
    const empty = document.createElement("p");
    empty.className = "notice";
    empty.textContent = "此代號不在最新官方來源快照中。";
    output.append(empty);
    return;
  }
  const card = (title, rows) => {
    const section = document.createElement("section");
    section.className = "metric";
    const heading = document.createElement("h3");
    heading.className = "label";
    heading.textContent = `${title}｜RAW`;
    section.append(heading);
    const dl = document.createElement("dl");
    for (const [label, value] of rows) {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = String(value);
      dl.append(dt, dd);
    }
    section.append(dl);
    output.append(section);
  };
  const quoteEvidence = record.sources.ohlcv;
  const q = quoteEvidence?.payload;
  if (quoteEvidence?.status === "RAW") card(`日線價量 ${record.trade_date}`, [["市場", record.market], ["開盤", q.open], ["最高", q.high], ["最低", q.low], ["收盤", q.close], ["成交量（股）", q.volume], ["漲跌／除權息", q.change ?? q.change_note ?? "未提供"]]);
  if (quoteEvidence?.status === "MISSING") card(`日線價量 ${record.trade_date}`, [["資料狀態", q.reason]]);
  const flow = record.sources.institutional_flow?.payload;
  if (flow) card("三大法人淨買賣超", [["外資（股）", flow.foreign], ["投信（股）", flow.trust], ["自營商（股）", flow.dealer], ["來源公布合計（股）", flow.total], ["組成合計相符", flow.total_matches_components ? "是" : "否，保留來源差異"]]);
  const margin = record.sources.margin_balance?.payload;
  if (margin) card("融資融券", [["融資前日／今日（張）", `${margin.margin_previous_balance}／${margin.margin_balance}`], ["融券前日／今日（張）", `${margin.short_previous_balance}／${margin.short_balance}`], ["融資買進／賣出（張）", `${margin.margin_buy ?? "未提供"}／${margin.margin_sell ?? "未提供"}`], ["融券賣出／買進（張）", `${margin.short_sell ?? "未提供"}／${margin.short_buy ?? "未提供"}`], ["融資使用率", `${margin.margin_utilization_rate_pct ?? "未提供"}%`], ["融券使用率", `${margin.short_utilization_rate_pct ?? "未提供"}%`], ["官方註記", margin.note || "無"]]);
  const ownership = record.sources.ownership_distribution?.payload;
  if (ownership) {
    const large = ownership.tiers.find(tier => tier.tier === 15);
    card(`集保持股分級｜${ownership.snapshot_date}（每週）`, [["持股 1,000 張以上人數", large?.holders ?? "未提供"], ["持股 1,000 張以上股數", large?.shares ?? "未提供"], ["占集保比例", large ? `${large.custody_pct}%` : "未提供"]]);
  }
  if (!output.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "notice";
    empty.textContent = "此代號目前沒有可呈現的官方原始證據。";
    output.append(empty);
  }
}

async function loadMarketSources() {
  const status = document.getElementById("market-status");
  const output = document.getElementById("market-data");
  const list = document.getElementById("market-source-list");
  const symbol = document.getElementById("market-symbol").value.trim();
  output.replaceChildren();
  list.replaceChildren();
  status.dataset.level = "BLOCKED";
  if (!/^\d[A-Z0-9]{3,5}$/.test(symbol)) {
    status.textContent = "請輸入 4 至 6 碼股票代號（含字母代碼）。";
    return;
  }
  status.textContent = "正在讀取同站官方來源快照…";
  try {
    const response = await fetch(new URL("./market-sources.json.gz", import.meta.url), { cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new ProjectionError("官方來源快照尚未發布");
    if (Number(response.headers.get("content-length") || 0) > 8388608) throw new ProjectionError("官方來源壓縮快照過大");
    if (typeof DecompressionStream !== "function") throw new ProjectionError("瀏覽器不支援官方快照解壓縮");
    const compressed = await response.arrayBuffer();
    if (compressed.byteLength > 8388608) throw new ProjectionError("官方來源壓縮快照過大");
    const body = await decompressMarketSources(compressed);
    const snapshot = parseMarketSources(body);
    renderMarketSources(snapshot, symbol);
  } catch (error) {
    status.dataset.level = "BLOCKED";
    status.textContent = error instanceof ProjectionError ? error.message : "官方來源讀取失敗";
    document.getElementById("market-data").replaceChildren();
  }
}

function put(id, value) {
  document.getElementById(id).textContent = String(value);
}
function clear() {
  document.getElementById("data").hidden = true;
  document.getElementById("status").textContent = "無可信投影資料。請載入正式 DashboardProjection JSON。";
  document.getElementById("status").dataset.level = "BLOCKED";
}
function show(projection, { localImport = false } = {}) {
  put("symbol", projection.symbol);
  put("trade-date", projection.trade_date);
  put("generated-at", projection.generated_at);
  put("run-id", projection.analysis_run_id);
  put("snapshot-id", projection.snapshot_id);
  put("score", projection.directional_score);
  put("trend", projection.trend_state);
  put("confidence", projection.confidence);
  put("gate", projection.decision_gate);
  put("slope", projection.score_slope_5d === null ? "未提供" : projection.score_slope_5d);
  put("change", "未提供（不等同五日斜率）");
  put("thesis", "尚未評估");
  put("wrong", "尚未評估");
  put("pit", localImport
    ? "本機匯入僅通過格式檢查；未驗證簽章、來源或歷史 PIT。檔案自稱的認證狀態不可視為已驗證。"
    : projection.historical_pit_certification === "SIGNED_PIT_V1_ATTESTATION_VERIFIED"
      ? "已通過 SIGNED_PIT_V1 pinned attestor 驗證（完整性仍依賴獨立 attestor 的聲明）"
      : "未經正式歷史 PIT 認證");
  put("limitations", projection.limitations.length ? projection.limitations.join("；") : "未提供額外限制；歷史 PIT 仍未認證。");
  const status = document.getElementById("status");
  status.dataset.level = localImport ? "BLOCKED" : projection.decision_gate;
  status.textContent = localImport
    ? "🔴 本機匯入未驗證來源｜僅供檢視，檔案自稱的 PASS／PIT 認證不可當成可信證據"
    : ({ PASS: "🟢 證據檢查通過", DEGRADED: "🟡 證據降級", BLOCKED: "🔴 證據阻擋" })[projection.decision_gate] + "｜燈號僅代表證據就緒度，非買賣訊號";
  document.getElementById("data").hidden = false;
}

/** Static hosting works without backend. Missing/invalid source stays BLOCKED. */
export async function mountDashboard() {
  clear();
  let generation = 0;
  const input = document.getElementById("projection-file");
  input.addEventListener("change", async () => {
    const ticket = ++generation;
    clear();
    const file = input.files?.[0];
    if (!file) return;
    try {
      if (file.size > 131072) throw new ProjectionError("檔案超過 128 KiB");
      const parsed = parseProjection(await file.text());
      if (ticket === generation) show(parsed, { localImport: true });
    } catch (error) {
      if (ticket !== generation) return;
      clear();
      put("status", error instanceof ProjectionError ? error.message : "讀取失敗");
    }
  });
  document.getElementById("market-refresh").addEventListener("click", () => void loadMarketSources());
  const ticket = ++generation;
  try {
    const response = await fetch(new URL("./projection.json", import.meta.url), { cache: "no-store", credentials: "omit" });
    if (ticket === generation && response.ok) {
      const body = await response.text();
      if (ticket === generation) show(parseProjection(body));
    }
  } catch {
    if (ticket === generation) clear();
  }
  await loadMarketSources();
}

if (typeof document !== "undefined" && document.getElementById("projection-file")) {
  void mountDashboard();
}
