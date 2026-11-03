import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

test("planMin: 4am day boundary pushes after-midnight times to the end of the day", () => {
  assert.equal(C.planMin("09:00"), 540);
  assert.equal(C.planMin("23:30"), 1410);
  assert.equal(C.planMin("01:00"), 1500);
  assert.equal(C.planMin("03:59"), 1679);
  assert.equal(C.planMin("04:00"), 240);
  assert.equal(C.planMin(""), null);
  assert.equal(C.planMin("junk"), null);
});

test("planDayISO: before 4am still counts as the previous day", () => {
  assert.equal(C.planDayISO(new Date(2026, 10, 3, 0, 30)), "2026-11-02");
  assert.equal(C.planDayISO(new Date(2026, 10, 3, 3, 59)), "2026-11-02");
  assert.equal(C.planDayISO(new Date(2026, 10, 3, 4, 0)), "2026-11-03");
  assert.equal(C.planNowMin(new Date(2026, 10, 3, 0, 30)), 1470);
  assert.equal(C.planNowMin(new Date(2026, 10, 3, 9, 5)), 545);
});

test("planSorted orders by day position, points before ranges at the same time", () => {
  const s = C.planSorted([
    { id: "a", start: "01:00", title: "bed" },
    { id: "b", start: "10:30", end: "12:00", title: "school" },
    { id: "c", start: "10:30", title: "breakfast done" },
    { id: "d", start: "09:00", title: "wake" },
  ]);
  assert.deepEqual(s.map(x => x.id), ["d", "c", "b", "a"]);
});

test("planResolve: date override > therapy alternate > weekday template", () => {
  const p = {
    templates: { MO: [{ id: "m", start: "09:00", title: "Wake" }], TU: [{ id: "t", start: "09:00", title: "Wake" }] },
    alt: { MO: [{ id: "x", start: "08:15", title: "Wake" }] },
    overrides: { "2026-11-10": [{ id: "o", start: "07:00", title: "Early" }] },
    flags: { "2026-11-16": { therapy: true }, "2026-11-10": { therapy: true } },
  };
  assert.equal(C.planResolve(p, "2026-11-02").source, "template");     // Monday, no flag
  assert.equal(C.planResolve(p, "2026-11-02").blocks[0].id, "m");
  assert.equal(C.planResolve(p, "2026-11-16").source, "therapy");
  assert.equal(C.planResolve(p, "2026-11-16").blocks[0].id, "x");
  assert.equal(C.planResolve(p, "2026-11-10").source, "override");
  assert.equal(C.planResolve(p, "2026-11-03").blocks[0].id, "t");      // Tuesday
  assert.equal(C.planResolve(p, "2026-11-04").blocks.length, 0);       // empty Wednesday
  assert.equal(C.planResolve({}, "2026-11-04").blocks.length, 0);
});

test("planTimeline marks past/current/next and places the now line", () => {
  const b = C.planSorted([
    { id: "w", start: "09:00", title: "Wake" },
    { id: "s", start: "10:30", end: "12:00", title: "School" },
    { id: "a", start: "12:00", end: "13:00", title: "Avery" },
    { id: "work", start: "15:30", end: "01:00", title: "Work" },
    { id: "bed", start: "01:00", title: "Bed" },
  ]);
  let t = C.planTimeline(b, 11 * 60);
  assert.deepEqual(t.rows.map(r => r.state), ["past", "now", "next", "later", "later"]);
  assert.equal(t.lineAt, 2);                         // line sits before "Avery"
  assert.equal(t.rows[1].pct, 33);
  t = C.planTimeline(b, 24 * 60 + 30);              // 12:30am, still at work
  assert.equal(t.rows[3].state, "now");
  assert.equal(t.rows[4].state, "next");
  t = C.planTimeline(b, 8 * 60);                    // before the day starts
  assert.equal(t.lineAt, 0);
  assert.equal(t.rows[0].state, "next");
  t = C.planTimeline(b, 9 * 60 + 30);               // between wake and school: wake is the current step
  assert.equal(t.rows[0].state, "now");
  assert.equal(t.rows[1].state, "next");
});
