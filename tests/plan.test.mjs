import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

const sample = {
  format: "training-log-plan", version: 1, name: "PPL",
  workouts: [
    { name: "Push", days: ["monday", "Thu"], exercises: [
      { name: "Bench Press", main: true, sets: 3, reps: 5, weight: 155, progression: { type: "linear", increment: 5 } },
      { name: "Lateral Raise", sets: 3, repRange: [12, 20], weight: 20, progression: "double" },
      { name: "Push-Up", bodyweight: true, sets: 2, reps: 15, progression: { type: "reps" } },
    ] },
    { name: "Legs", days: ["Tue", "Fri"], exercises: [{ name: "Squat", sets: 3, reps: "8-12", weight: 135 }] },
  ],
};

test("planNormalize fills defaults and infers weekdays schedule", () => {
  const { plan, errors, warnings } = C.planNormalize(sample);
  assert.deepEqual(errors, []);
  assert.equal(plan.schedule, "weekdays");
  assert.deepEqual(plan.workouts[0].days, ["Mon", "Thu"]);
  assert.equal(plan.workouts[0].id, "Push");
  const lat = plan.workouts[0].exercises[1];
  assert.deepEqual(lat.repRange, [12, 20]);
  assert.equal(lat.progression.type, "double");
  assert.equal(lat.progression.increment, 5);
  const sq = plan.workouts[1].exercises[0];
  assert.deepEqual(sq.repRange, [8, 12]);          // "8-12" string becomes a range
  assert.equal(sq.progression.type, "double");     // ranges default to double progression
  assert.equal(plan.workouts[0].exercises[0].progression.missesBeforeDeload, 2);
  assert.equal(warnings.length, 0);
});

test("planNormalize reads JSON pasted from a chat with code fences", () => {
  const text = "Here's your plan!\n```json\n" + JSON.stringify(sample) + "\n```\nHave fun.";
  assert.equal(C.planNormalize(text).plan.workouts.length, 2);
});

test("planNormalize reports clear errors", () => {
  assert.match(C.planNormalize("no json here").errors[0], /Couldn't find a plan/);
  assert.match(C.planNormalize("{ bad json").errors[0], /Couldn't find a plan|valid JSON/);
  const r = C.planNormalize({ workouts: [{ name: "A", exercises: [{ sets: 3, reps: 5 }, { name: "Row", sets: 40, reps: 5 }] }] });
  assert.equal(r.plan, null);
  assert.equal(r.errors.length, 2);
  assert.match(C.planNormalize({ workouts: [] }).errors[0], /at least one workout/);
});

test("planSession + planApply drive linear, double, and reps progressions", () => {
  const { plan } = C.planNormalize(sample);
  const state = C.planEnsureState(plan, {}, {});
  const s = C.planSession(plan, state, "Push");
  const [bench, lat, push] = s.items;
  assert.deepEqual(bench.sets.map(x => [x.w, x.r]), [[155, 5], [155, 5], [155, 5]]);
  assert.equal(bench.rest, 180);
  assert.deepEqual(lat.sets.map(x => x.r), [12, 12, 12]);
  assert.deepEqual(push.sets.map(x => x.r), [15, 15]);
  bench.sets.forEach(x => x.done = true);
  let r = C.planApply(bench, state[bench.key]);
  assert.equal(r.next.w, 160); assert.match(r.change, /155 → 160/);
  lat.sets.forEach(x => { x.done = true; x.r = 20; });
  r = C.planApply(lat, state[lat.key]); assert.equal(r.next.w, 25);
  push.sets.forEach(x => x.done = true);
  r = C.planApply(push, state[push.key]); assert.deepEqual(r.next.reps, [16, 15]);
});

test("planNextUp: weekdays picks today's workout, rotation follows next", () => {
  const { plan } = C.planNormalize(sample);
  const p = { plan, log: [] };
  assert.deepEqual(C.planNextUp(p, "2026-11-16"), { id: "Push", when: "today", today: true });   // Monday
  assert.equal(C.planNextUp(p, "2026-11-18").id, "Push");                                       // Wed → Thu
  assert.equal(C.planNextUp(p, "2026-11-18").when, "tomorrow");
  p.log = [{ date: "2026-11-16" }];
  assert.equal(C.planNextUp(p, "2026-11-16").id, "Legs");                                       // done Monday → Tue
  const rot = { plan: { ...plan, schedule: "rotation" }, next: "Legs", log: [] };
  assert.equal(C.planNextUp(rot, "2026-11-16").id, "Legs");
  assert.equal(C.planAfter(plan, "Legs"), "Push");
});

test("progMigrate keeps every working weight from the old program", () => {
  const old = { startedAt: "2026-11-12", next: "LA", log: [{ date: "2026-11-12", day: "UA", changes: [] }],
    main: { benchH: { w: 160, fails: 1, inc: 5 }, benchV: { w: 135, fails: 0, inc: 5 }, squatH: { w: 145, fails: 0, inc: 10 }, squatV: { w: 115, fails: 0, inc: 5 } },
    pull: { reps: [3, 2, 2, 2, 2], added: 0 }, acc: { "Barbell Row": { w: 115 }, "Ab Wheel": { w: 0 } }, live: null };
  const m = C.progMigrate(old);
  assert.equal(m.plan.workouts.length, 4);
  assert.equal(m.next, "LA");
  const ua = C.planSession(m.plan, m.state, "UA");
  assert.equal(ua.items[0].sets[0].w, 160);
  assert.deepEqual(ua.items[1].sets.map(s => s.r), [3, 2, 2, 2, 2]);
  assert.equal(ua.items.find(i => i.name === "Barbell Row").sets[0].w, 115);
  assert.equal(C.planSession(m.plan, m.state, "LA").items[0].sets[0].w, 145);
  assert.equal(m.state.squatH.inc, 10);
  assert.equal(C.progMigrate(m), m);            // already migrated → untouched
});

test("built-in plan round-trips through planNormalize", () => {
  const { plan, errors } = C.planNormalize(C.planBuiltin());
  assert.deepEqual(errors, []);
  assert.equal(plan.schedule, "rotation");
  assert.equal(plan.workouts[1].exercises[0].progression.firstIncrement, 10);
  assert.equal(plan.workouts[0].exercises[0].key, "benchH");
});

test("exVolume counts bodyweight for bodyweight movements", () => {
  assert.equal(C.exVolume({ name: "Bench Press", sets: [{ weight: 135, reps: 5 }, { weight: 135, reps: 5 }] }, 180), 1350);
  assert.equal(C.exVolume({ name: "Pull-Up", sets: [{ weight: 0, reps: 3 }] }, 180), 540);
  assert.equal(C.exVolume({ name: "Pull-Up", sets: [{ weight: 25, reps: 2 }] }, 180), 410);
  assert.equal(C.exVolume({ name: "Assisted Pull-Up", sets: [{ weight: 50, reps: 5 }] }, 180), 650);
  assert.equal(Math.round(C.exVolume({ name: "Push-Up", sets: [{ weight: 0, reps: 10 }] }, 200)), 1280);
  assert.equal(C.exVolume({ name: "Pull-Up", sets: [{ weight: 0, reps: 3 }] }, null), 0);   // no weigh-ins
});

test("bwOn uses the latest weigh-in on or before the date", () => {
  const ws = [{ date: "2026-10-01", lbs: 175 }, { date: "2026-11-01", lbs: 180 }];
  assert.equal(C.bwOn(ws, "2026-10-15"), 175);
  assert.equal(C.bwOn(ws, "2026-12-01"), 180);
  assert.equal(C.bwOn(ws, "2026-01-01"), 180);   // nothing before → latest
  assert.equal(C.bwOn([], "2026-01-01"), null);
});

test("triviaSeason and triviaPick favor the holiday", () => {
  assert.equal(C.triviaSeason("2026-12-10").name, "christmas");
  assert.equal(C.triviaSeason("2026-11-27").name, "christmas");
  assert.equal(C.triviaSeason("2026-11-13").tags.thanksgiving, 6);
  assert.equal(C.triviaSeason("2026-07-02").tags.july4, 7);
  // over many seeds, December picks are mostly Christmas-y
  const xmas = new Set(["\u{1F384}", "\u{1F98C}", "\u{1F385}", "\u{1F381}", "\u{1F36C}", "\u{1F36A}", "\u{1F6F7}", "☕", "⛄", "\u{1F9E6}"]);
  let hits = 0, total = 0;
  for (let i = 0; i < 50; i++) for (const p of C.triviaPick(12000, "2026-12-15", "s" + i, 3)){ total++; if (xmas.has(p.emoji)) hits++; }
  assert.ok(hits / total > 0.6, `${hits}/${total}`);
  // no summer items in December
  for (let i = 0; i < 30; i++) assert.ok(!C.triviaPick(12000, "2026-12-15", "x" + i, 3).some(p => p.emoji === "\u{1F349}"));
  const a = C.triviaPick(12000, "2026-12-15", "same", 3), b = C.triviaPick(12000, "2026-12-15", "same", 3);
  assert.deepEqual(a, b);                         // stable per workout
  assert.equal(new Set(a.map(x => x.name)).size, 3);
  for (const x of a) assert.ok(x.count >= 1);
  assert.deepEqual(C.triviaPick(0, "2026-12-15", "z"), []);
});
