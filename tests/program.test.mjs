import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

const L = (date, name, sets) => ({ id: date + name, date, exercises: [{ name, sets: sets.map(([weight, reps]) => ({ weight, reps })) }] });

test("progE1RM / progRound5", () => {
  assert.equal(Math.round(C.progE1RM(185, 5)), 216);
  assert.equal(C.progE1RM(200, 1), 200);
  assert.equal(C.progRound5(137.4), 135);
  assert.equal(C.progRound5(138), 140);
  assert.equal(C.progRound5(20), 45);       // never below the empty bar
});

test("progAnalyze finds best bench/squat/pull-ups and backs off for time away", () => {
  const lifts = [
    L("2026-03-01", "Bench Press", [[185, 5], [185, 5]]),
    L("2026-03-08", "Bench Press", [[175, 8]]),
    L("2026-03-01", "Squat", [[225, 5]]),
    L("2026-03-02", "Pull-Up", [[0, 3], [0, 2]]),
    L("2026-03-03", "Barbell Row", [[135, 10], [145, 8]]),
    L("2026-03-04", "Dumbbell Bench Press", [[80, 10]]),   // not barbell bench
    L("2026-11-01", "Bench Press", [[95, 5]]),
  ];
  const a = C.progAnalyze(lifts, "2026-11-12");
  assert.equal(a.workouts, 7);
  assert.equal(a.bench.best.weight, 175);          // 175x8 beats 185x5 on estimated max
  assert.equal(a.bench.best.reps, 8);
  assert.ok(a.bench.weeksSinceBest >= 35);
  assert.equal(a.bench.last, "2026-11-01");
  // e1RM ~222 -> 5RM ~190 -> 35 weeks since that strength -> x0.7 -> 135 (beats the light recent 95x5)
  assert.equal(a.bench.heavy, 135);
  assert.ok(a.bench.volume < a.bench.heavy);
  assert.equal(a.squat.best.weight, 225);
  assert.equal(a.pullup.bestReps, 3);
  assert.equal(a.acc["Barbell Row"], 145);
  assert.equal(C.progAnalyze([], "2026-11-12").bench, null);
});

test("recent training gets a smaller back-off", () => {
  const a = C.progAnalyze([L("2026-11-05", "Bench Press", [[185, 5]])], "2026-11-12");
  assert.equal(a.bench.heavy, 165);   // 0.9 x ~185
});

test("progNextMain: +inc on success, repeat on first miss, deload 10% on second", () => {
  let s = { w: 135, fails: 0, inc: 5 };
  s = C.progNextMain(s, [5, 5, 5], 5);
  assert.deepEqual(s, { w: 140, fails: 0, inc: 5 });
  s = C.progNextMain(s, [5, 5, 4], 5);
  assert.deepEqual(s, { w: 140, fails: 1, inc: 5 });
  s = C.progNextMain(s, [5, 3, 0], 5);
  assert.deepEqual(s, { w: 125, fails: 0, inc: 5 });
  // squat starts at +10 and drops to +5 after its first miss
  let q = { w: 185, fails: 0, inc: 10 };
  q = C.progNextMain(q, [5, 5, 5], 5); assert.equal(q.w, 195);
  q = C.progNextMain(q, [5, 5, 4], 5); assert.equal(q.inc, 5);
  q = C.progNextMain(q, [5, 5, 5], 5); assert.equal(q.w, 200);
});

test("progNextPull: adds a rep to the weakest set, then goes weighted", () => {
  let p = { reps: [2, 2, 2, 2, 2], added: 0 };
  p = C.progNextPull(p, [2, 2, 2, 2, 2]);
  assert.deepEqual(p.reps, [3, 2, 2, 2, 2]);
  p = C.progNextPull(p, [3, 2, 2, 2, 1]);           // missed: same targets
  assert.deepEqual(p.reps, [3, 2, 2, 2, 2]);
  p = C.progNextPull({ reps: [6, 6, 6, 6, 5], added: 0 }, [6, 6, 6, 6, 5]);
  assert.deepEqual(p, { reps: [5, 5, 5], added: 5 });  // 30 reps reached -> weighted
  p = C.progNextPull({ reps: [5, 5, 5], added: 5 }, [5, 5, 5]);
  assert.deepEqual(p, { reps: [5, 5, 5], added: 10 });
});

test("progNextAcc: double progression", () => {
  assert.equal(C.progNextAcc({ w: 50 }, [12, 12, 12], 8, 12, 5).w, 55);
  assert.equal(C.progNextAcc({ w: 50 }, [12, 11, 12], 8, 12, 5).w, 50);
  assert.equal(C.progNextAcc({ w: null }, [10, 10, 10], 8, 12, 5).w, null);
});

test("progSession builds the day's checklist", () => {
  const prog = {
    main: { benchH: { w: 135, fails: 0, inc: 5 }, benchV: { w: 115, fails: 0, inc: 5 }, squatH: { w: 185, fails: 0, inc: 10 }, squatV: { w: 155, fails: 0, inc: 5 } },
    pull: { reps: [2, 2, 2, 2, 2], added: 0 }, acc: { "Barbell Row": { w: 95 } },
  };
  const ua = C.progSession(prog, "UA");
  assert.equal(ua.split, "upper");
  assert.equal(ua.items[0].name, "Bench Press");
  assert.deepEqual(ua.items[0].sets.map(s => [s.w, s.r]), [[135, 5], [135, 5], [135, 5]]);
  assert.equal(ua.items[1].name, "Pull-Up");
  assert.equal(ua.items[1].sets.length, 5);
  assert.equal(ua.items.find(i => i.name === "Barbell Row").sets[0].w, 95);
  const lb = C.progSession(prog, "LB");
  assert.equal(lb.split, "lower");
  assert.deepEqual(lb.items[0].sets.map(s => [s.w, s.r]), [[155, 8], [155, 8], [155, 8]]);
  assert.ok(!lb.items.some(i => /dead/i.test(i.name)));
  // abs close out both lower days
  assert.equal(lb.items[lb.items.length - 1].name, "Ab Wheel");
  const la = C.progSession(prog, "LA");
  assert.equal(la.items[la.items.length - 1].name, "Cable Crunch");
});

test("progWarmup ramps to the work weight", () => {
  assert.deepEqual(C.progWarmup(185).map(x => x.w), [45, 95, 130, 155]);
  assert.deepEqual(C.progWarmup(65).map(x => x.w), [45, 55]);
});
