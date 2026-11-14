import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

test("parseStepsInbox reads day maps, skips zero/future/garbage", () => {
  const doc = { d20261112: { steps: "8,412" }, d20261113: { steps: "0" }, d20261114: { steps: "12034.0" }, d20261120: { steps: "500" }, junk: { steps: "9" }, d20261110: "x" };
  assert.deepEqual(C.parseStepsInbox(doc, "2026-11-14"), [{ date: "2026-11-12", steps: 8412 }, { date: "2026-11-14", steps: 12034 }]);
});

test("mergeSteps updates changed days and keeps a bigger manual entry", () => {
  let n = 0; const id = () => "id" + (++n);
  const rows = [{ id: "a", date: "2026-11-12", steps: 8000, source: "health" }, { id: "b", date: "2026-11-13", steps: 9000, source: "manual" }];
  const r = C.mergeSteps(rows, [{ date: "2026-11-12", steps: 8412 }, { date: "2026-11-13", steps: 4000 }, { date: "2026-11-14", steps: 3000 }], id);
  assert.deepEqual(r.changed, ["2026-11-12", "2026-11-14"]);
  assert.equal(r.steps.find(x => x.date === "2026-11-12").id, "a");
  assert.equal(r.steps.find(x => x.date === "2026-11-13").steps, 9000);
  assert.equal(C.mergeSteps(r.steps, [{ date: "2026-11-12", steps: 8412 }], id).changed.length, 0);
});

test("step XP: 1 per 200 steps, capped at 20k, +25 at goal, minus logged walk/run miles", () => {
  assert.equal(C.stepsDayXP(10000, 0, 8000), 75);          // 50 + 25 bonus
  assert.equal(C.stepsDayXP(7999, 0, 8000), 39);
  assert.equal(C.stepsDayXP(40000, 0, 8000), 125);         // capped: 100 + 25
  assert.equal(C.stepsDayXP(10000, 3, 8000), 45);          // 3 logged miles = 6k steps already counted → 4k left = 20, + goal 25
  assert.equal(C.stepsDayXP(5000, 4, 8000), 0);
  const cardio = [{ date: "2026-11-13", type: "walk", distanceMi: 2 }, { date: "2026-11-13", type: "bike", distanceMi: 10 }];
  assert.equal(C.stepsCoveredMiles(cardio, "2026-11-13"), 2);
  const rows = [{ date: "2026-11-10", steps: 10000 }, { date: "2026-11-13", steps: 10000 }];
  assert.equal(C.stepsXP(rows, cardio, 8000, "2026-11-11"), 55);               // only on/after xpStart; 2-mile walk subtracted
  assert.equal(C.stepsXP(rows, cardio, 8000, "2026-11-01", d => d === "2026-11-10" ? 2 : 1), 150 + 55);   // birthday 2x
});
