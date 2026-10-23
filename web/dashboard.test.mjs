import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseProjection, validateProjection, ProjectionError, mountDashboard } from "./dashboard.mjs";

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
  for (const id of ["score","trend","confidence","gate","slope","change","thesis","wrong","pit","limitations","snapshot-id","projection-file"]) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.match(html, /viewport/);
  assert.match(html, /aria-live="polite"/);
  assert.match(js, /textContent/);
  assert.doesNotMatch(js, /innerHTML|eval\s*\(/);
  assert.doesNotMatch(html, /<script[^>]*>\s*\{/);
  assert.doesNotMatch(html, /"directional_score"\s*:/);
});


test("latest file selection wins over delayed initial fetch and earlier imports", async () => {
  const nodes = new Map();
  const getNode = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: false, dataset: {}, textContent: "", files: null, addEventListener(_type, fn) { this.change = fn; } });
    return nodes.get(id);
  };
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  let releaseFetch;
  globalThis.document = { getElementById: getNode };
  globalThis.fetch = () => new Promise(resolve => { releaseFetch = resolve; });
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
