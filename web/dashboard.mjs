/** Read-only, fail-closed projection consumer. No browser-side market computation. */
export const VERSION = "dashboard-projection-v1";
const TRENDS = new Set(["STRONG_UPTREND","UPTREND","PULLBACK_IN_UPTREND","SIDEWAYS","REVERSAL_WATCH","DISTRIBUTION","DOWNTREND","STRONG_DOWNTREND"]);
const LIGHTS = Object.freeze({ PASS: "GREEN", DEGRADED: "YELLOW", BLOCKED: "RED" });
const FIELDS = new Set(["projection_version","analysis_run_id","snapshot_id","symbol","trade_date","generated_at","directional_score","trend_state","confidence","decision_gate","traffic_light","traffic_light_meaning","score_slope_5d","five_day_change","most_likely_wrong","thesis_status","historical_pit_certification","limitations"]);

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
  return typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value));
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
  requireField(value.historical_pit_certification === "NOT_ESTABLISHED_BY_REPORT", "不得宣稱歷史 PIT 認證");
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

function put(id, value) {
  document.getElementById(id).textContent = String(value);
}
function clear() {
  document.getElementById("data").hidden = true;
  document.getElementById("status").textContent = "無可信投影資料。請載入正式 DashboardProjection JSON。";
  document.getElementById("status").dataset.level = "BLOCKED";
}
function show(projection) {
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
  put("pit", "未經正式歷史 PIT 認證");
  put("limitations", projection.limitations.length ? projection.limitations.join("；") : "未提供額外限制；歷史 PIT 仍未認證。");
  const status = document.getElementById("status");
  status.dataset.level = projection.decision_gate;
  status.textContent = ({ PASS: "🟢 證據檢查通過", DEGRADED: "🟡 證據降級", BLOCKED: "🔴 證據阻擋" })[projection.decision_gate] + "｜燈號僅代表證據就緒度，非買賣訊號";
  document.getElementById("data").hidden = false;
}

/** Static hosting works without backend. Missing/invalid source stays BLOCKED. */
export async function mountDashboard() {
  clear();
  const input = document.getElementById("projection-file");
  input.addEventListener("change", async () => {
    clear();
    const file = input.files?.[0];
    if (!file) return;
    try {
      if (file.size > 131072) throw new ProjectionError("檔案超過 128 KiB");
      show(parseProjection(await file.text()));
    } catch (error) {
      clear();
      put("status", error instanceof ProjectionError ? error.message : "讀取失敗");
    }
  });
  try {
    const response = await fetch(new URL("./projection.json", import.meta.url), { cache: "no-store", credentials: "omit" });
    if (!response.ok) return;
    const body = await response.text();
    show(parseProjection(body));
  } catch {
    clear();
  }
}

if (typeof document !== "undefined" && document.getElementById("projection-file")) {
  void mountDashboard();
}
