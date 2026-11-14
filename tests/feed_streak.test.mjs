import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

test("time-only activities read naturally", () => {
  assert.equal(C.cardioDurText("walk", "Walk", "Landon", 36 * 60), "Landon walked for 36 minutes!");
  assert.equal(C.cardioDurText("run", "Run", "Avery", 3900), "Avery ran for 1 hour 5 minutes!");
  assert.equal(C.cardioDurText("basketball", "Basketball", "Justin", 3600), "Justin played 1 hour of basketball!");
  assert.equal(C.fixEventText("Landon played 36m of walk!"), "Landon walked for 36 minutes!");
  assert.equal(C.fixEventText("Justin played 1h 5m of basketball!"), "Justin played 1 hour 5 minutes of basketball!");
  assert.equal(C.fixEventText("Landon ran 3 miles!"), "Landon ran 3 miles!");
});

test("restoring a backup keeps the streak going across the gap", () => {
  const r = C.streakAfterRestore({ count: 40, lastDay: "2026-11-01", best: 40 }, { count: 1, lastDay: "2026-11-14", best: 3 }, "2026-11-14");
  assert.deepEqual(r, { count: 53, lastDay: "2026-11-14", best: 53 });
  // a phone streak that's longer wins
  assert.equal(C.streakAfterRestore({ count: 2, lastDay: "2026-11-13" }, { count: 10, lastDay: "2026-11-14", best: 10 }, "2026-11-14").count, 10);
  assert.equal(C.streakAfterRestore(null, { count: 4, lastDay: "2026-11-14" }, "2026-11-14").count, 4);
});

test("streak rebuilt from the first logged day", () => {
  const d = { lifts: [{ date: "2026-08-03" }], cardio: [{ date: "2026-07-21" }], weights: [], settings: { xpStart: "2026-07-25" } };
  assert.equal(C.earliestLogDate(d), "2026-07-21");
  const s = C.streakFromStart("2026-07-21", "2026-11-14", { count: 2, lastDay: "2026-11-14", best: 5 });
  assert.deepEqual(s, { count: 117, lastDay: "2026-11-14", best: 117 });
  assert.equal(C.streakFromStart("2026-11-13", "2026-11-14", { count: 9, best: 9 }).count, 9);   // never lowers it
});
