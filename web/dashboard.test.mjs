import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { parseProjection, validateProjection, parseMarketSources, ProjectionError, mountDashboard } from "./dashboard.mjs";

const base = {
  projection_version: "dashboard-projection-v1",
  analysis_run_id: "run-verified",
  snapshot_id: "snapshot-verified",
  symbol: "2330",
  trade_date: "2026-10-23",
  generated_at: "2026-10-23T18:01:00+08:00",
  directional_score: 60,
  trend_state: "UPTREND",
  confidence: 70,
  decision_gate: "PASS",
  traffic_light: "GREEN",
  traffic_light_meaning: "EVIDENCE_READINESS_ONLY",
  score_slope_5d: null,
  five_day_change: null,
  most_likely_wrong: null,
  thesis_status: "NOT_ASSESSED",
  historical_pit_certification: "NOT_ESTABLISHED_BY_REPORT",
  limitations: ["Historical PIT completeness is not certified"]
};
const changed = (patch) => ({ ...base, ...patch });
const rejects = (patch) => assert.throws(() => validateProjection(changed(patch)), ProjectionError);

test("strict v1 projection preserves supplied fields without recomputing", () => {
  const input = JSON.stringify(base);
  const parsed = parseProjection(input);
  assert.deepEqual(parsed, base);
  assert.equal(parsed.directional_score, 60);
  assert.equal(parsed.confidence, 70);
  assert.equal(parsed.historical_pit_certification, "NOT_ESTABLISHED_BY_REPORT");
  assert.ok(Object.isFrozen(parsed));
});
test("reject unknown versions, unknown keys and missing required fields", () => {
  rejects({ projection_version: "dashboard-projection-v2" });
  rejects({ extra: "field" });
  const missing = { ...base };
  delete missing.snapshot_id;
  assert.throws(() => validateProjection(missing), ProjectionError);
});
test("reject contradictory traffic lights and invented analyses", () => {
  rejects({ decision_gate: "BLOCKED" });
  rejects({ decision_gate: "DEGRADED", traffic_light: "GREEN" });
  rejects({ traffic_light_meaning: "BUY_SIGNAL" });
  rejects({ five_day_change: 3 });
  rejects({ most_likely_wrong: "guessed" });
  rejects({ thesis_status: "APPROVED" });
  rejects({ historical_pit_certification: "CERTIFIED" });
});
test("reject unknown trend, malformed date/time, invalid scores", () => {
  rejects({ trend_state: "UNKNOWN" });
  rejects({ trade_date: "2026-02-30" });
  rejects({ generated_at: "2026-10-23T18:01:00" });
  rejects({ generated_at: "2026-02-30T18:01:00+08:00" });
  rejects({ generated_at: "2026-10-23T25:01:00+08:00" });
  rejects({ generated_at: "2026-10-23T18:01:60+08:00" });
  rejects({ generated_at: "2026-10-23T18:01:00+24:00" });
  rejects({ directional_score: 101 });
  rejects({ confidence: -1 });
  rejects({ score_slope_5d: Infinity });
  rejects({ limitations: [123] });
});
test("reject oversized/invalid JSON without silent fallback", () => {
  assert.throws(() => parseProjection("{"), ProjectionError);
  assert.throws(() => parseProjection("x".repeat(131073)), ProjectionError);
  assert.throws(() => parseProjection("null"), ProjectionError);
});
test("yellow/red represent evidence readiness, never trade direction", () => {
  assert.equal(validateProjection(changed({ decision_gate: "DEGRADED", traffic_light: "YELLOW" })).traffic_light, "YELLOW");
  assert.equal(validateProjection(changed({ decision_gate: "BLOCKED", traffic_light: "RED" })).traffic_light, "RED");
});
test("mobile UI contains required panels and uses textContent only", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./dashboard.mjs", import.meta.url), "utf8");
  for (const id of ["score","trend","confidence","gate","slope","change","thesis","wrong","pit","limitations","snapshot-id","projection-file","market-symbol","market-refresh","market-status","market-data","market-source-list"]) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.match(html, /viewport/);
  assert.match(html, /aria-live="polite"/);
  assert.match(js, /textContent/);
  assert.doesNotMatch(js, /innerHTML|eval\s*\(/);
  assert.doesNotMatch(html, /<script[^>]*>\s*\{/);
  assert.doesNotMatch(html, /"directional_score"\s*:/);
});

test("official source snapshot accepts only pinned endpoints and RAW evidence", () => {
  const urls = [
    "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    "https://www.twse.com.tw/rwd/zh/fund/T86",
    "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
    "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
  ];
  const ids = ["twse_ohlcv","tpex_ohlcv","twse_institutional","tpex_institutional","twse_margin","tpex_margin","tdcc_ownership"];
  const snapshot = {
    schema_version: "official-market-snapshot-v1", generated_at: "2026-10-23T20:00:00+08:00",
    data_status: "RAW_UNVERIFIED",
    sources: ids.map((id, index) => ({ id, label: id, url: urls[index], status: "RAW_UNVERIFIED",
      observed_at: "2026-10-23T20:00:00+08:00", content_sha256: "a".repeat(64), record_count: 1, missing_count: 0, trade_date: index === 6 ? null : "2026-10-22" })),
    symbols: { "2330": { market: "TWSE", trade_date: "2026-10-22", sources: {
      ohlcv: { status: "RAW", source: "TWSE_OPENAPI", evidence_id: "twse:2026-10-22:2330:ohlcv",
        observed_at: "2026-10-23T20:00:00+08:00", content_sha256: "b".repeat(64),
        payload: { trade_date: "2026-10-22", open: 100, high: 102, low: 99, close: 101, volume: 1000, change: 1 } }
    } } }
  };
  assert.equal(parseMarketSources(JSON.stringify(snapshot)).symbols["2330"].sources.ohlcv.payload.close, 101);
  const forged = structuredClone(snapshot);
  forged.sources[0].url = "https://attacker.invalid/data";
  assert.throws(() => parseMarketSources(JSON.stringify(forged)), ProjectionError);
  const verified = structuredClone(snapshot);
  verified.symbols["2330"].sources.ohlcv.status = "VERIFIED";
  assert.throws(() => parseMarketSources(JSON.stringify(verified)), ProjectionError);
});

test("dashboard loads compressed official sources even when score projection is absent", async () => {
  const now = new Date().toISOString();
  const urls = [
    "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    "https://www.twse.com.tw/rwd/zh/fund/T86",
    "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
    "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
  ];
  const ids = ["twse_ohlcv","tpex_ohlcv","twse_institutional","tpex_institutional","twse_margin","tpex_margin","tdcc_ownership"];
  const observed = now;
  const snapshot = {
    schema_version: "official-market-snapshot-v1", generated_at: now, data_status: "RAW_UNVERIFIED",
    sources: ids.map((id, index) => ({ id, label: id, url: urls[index], status: "RAW_UNVERIFIED",
      observed_at: observed, content_sha256: "a".repeat(64), record_count: 1, missing_count: 0,
      trade_date: index === 6 ? null : "2026-10-22" })),
    symbols: { "2330": { market: "TWSE", trade_date: "2026-10-22", sources: {
      ohlcv: { status: "RAW", source: "TWSE_OPENAPI", evidence_id: "twse:2026-10-22:2330:ohlcv",
        observed_at: observed, content_sha256: "b".repeat(64),
        payload: { trade_date: "2026-10-22", open: 100, high: 102, low: 99, close: 101, volume: 1000, change: 1 } }
    } } }
  };
  const nodes = new Map();
  const getNode = (id) => {
    if (!nodes.has(id)) nodes.set(id, {
      hidden: false, dataset: {}, textContent: "", files: null, value: id === "market-symbol" ? "2330" : "", children: [],
      addEventListener(_type, fn) { this.change = fn; },
      replaceChildren(...children) { this.children = children; },
      append(...children) { this.children.push(...children); },
      get childElementCount() { return this.children.length; }
    });
    return nodes.get(id);
  };
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  globalThis.document = { getElementById: getNode, createElement: () => ({ className: "", textContent: "", children: [], append(...children) { this.children.push(...children); } }) };
  globalThis.fetch = async (url) => String(url).includes("market-sources.json.gz")
    ? { ok: true, headers: { get: () => null }, arrayBuffer: async () => gzipSync(JSON.stringify(snapshot)) }
    : { ok: false };
  try {
    await mountDashboard();
    assert.match(getNode("market-status").textContent, /RAW／未驗證/);
    assert.equal(getNode("market-data").childElementCount, 1);
    assert.equal(getNode("market-data").children[0].children[1].children[3].textContent, "100");
    assert.equal(getNode("status").dataset.level, "BLOCKED");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});


test("latest file selection wins over delayed initial fetch and earlier imports", async () => {
  const nodes = new Map();
  const getNode = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: false, dataset: {}, textContent: "", files: null, value: id === "market-symbol" ? "2330" : "", children: [], replaceChildren(...children) { this.children = children; }, addEventListener(_type, fn) { this.change = fn; } });
    return nodes.get(id);
  };
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  let releaseFetch;
  globalThis.document = { getElementById: getNode };
  globalThis.fetch = (url) => String(url).includes("market-sources.json.gz")
    ? Promise.resolve({ ok: false })
    : new Promise(resolve => { releaseFetch = resolve; });
  try {
    const initial = mountDashboard();
    const input = getNode("projection-file");
    let releaseFirst;
    input.files = [{ size: 300, text: () => new Promise(resolve => { releaseFirst = resolve; }) }];
    const first = input.change();
    input.files = [{ size: 300, text: async () => JSON.stringify(changed({ directional_score: 51 })) }];
    await input.change();
    assert.equal(getNode("score").textContent, "51");
    releaseFirst(JSON.stringify(changed({ directional_score: 72 })));
    await first;
    releaseFetch({ ok: true, text: async () => JSON.stringify(changed({ directional_score: 99 })) });
    await initial;
    assert.equal(getNode("score").textContent, "51");
    assert.equal(getNode("data").hidden, false);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("accept pinned signed PIT attestation status without changing evidence light semantics", () => {
  const parsed = validateProjection(changed({
    historical_pit_certification: "SIGNED_PIT_V1_ATTESTATION_VERIFIED"
  }));
  assert.equal(parsed.historical_pit_certification, "SIGNED_PIT_V1_ATTESTATION_VERIFIED");
  assert.equal(parsed.traffic_light, "GREEN");
  assert.equal(parsed.traffic_light_meaning, "EVIDENCE_READINESS_ONLY");
});

test("local import cannot claim verified PIT or green readiness from JSON alone", async () => {
  const nodes = new Map();
  const getNode = (id) => {
    if (!nodes.has(id)) nodes.set(id, {
      hidden: false, dataset: {}, textContent: "", files: null, value: id === "market-symbol" ? "2330" : "", children: [],
      addEventListener(_type, fn) { this.change = fn; }
      , replaceChildren(...children) { this.children = children; }
    });
    return nodes.get(id);
  };
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  globalThis.document = { getElementById: getNode };
  globalThis.fetch = async () => ({ ok: false });
  try {
    await mountDashboard();
    const input = getNode("projection-file");
    input.files = [{
      size: 512,
      text: async () => JSON.stringify(changed({
        historical_pit_certification: "SIGNED_PIT_V1_ATTESTATION_VERIFIED",
        decision_gate: "PASS", traffic_light: "GREEN"
      }))
    }];
    await input.change();
    assert.equal(getNode("data").hidden, false);
    assert.equal(getNode("score").textContent, "60");
    assert.equal(getNode("status").dataset.level, "BLOCKED");
    assert.match(getNode("status").textContent, /本機匯入未驗證來源/);
    assert.match(getNode("pit").textContent, /未驗證簽章/);
    assert.doesNotMatch(getNode("pit").textContent, /已通過 SIGNED_PIT_V1/);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
