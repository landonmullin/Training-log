import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

test("time helpers", () => {
  assert.equal(C.fdTime("07:42"), "7:42a"); assert.equal(C.fdTime("00:05"), "12:05a");
  assert.equal(C.fdTime("12:30"), "12:30p"); assert.equal(C.fdTime("23:59"), "11:59p");
  assert.equal(C.fdTime("bad"), "");
  assert.equal(C.shiftISO("2026-03-01", -1), "2026-02-28");
  assert.equal(C.shiftISO("2026-12-31", 1), "2027-01-01");
});
test("kcalZone: cutting — under range yellow, in range green, over range red", () => {
  const cut = { kcalMode: "cut", kcalTarget: 2300, kcalLow: 2100, kcalHigh: 2400 };
  assert.equal(C.kcalZone(1900, cut), "yellow");
  assert.equal(C.kcalZone(2100, cut), "green");
  assert.equal(C.kcalZone(2400, cut), "green");
  assert.equal(C.kcalZone(2401, cut), "red");
});
test("kcalZone: bulking — under range red, in range green, over range yellow", () => {
  const bulk = { kcalMode: "bulk", kcalTarget: 3000, kcalLow: 2900, kcalHigh: 3200 };
  assert.equal(C.kcalZone(2800, bulk), "red");
  assert.equal(C.kcalZone(3000, bulk), "green");
  assert.equal(C.kcalZone(3300, bulk), "yellow");
});
test("kcalZone: without a range the goal is the line (old behavior for cutting)", () => {
  assert.equal(C.kcalZone(2300, { kcalTarget: 2400 }), "green");   // no mode = cutting
  assert.equal(C.kcalZone(2500, { kcalTarget: 2400 }), "red");
  assert.equal(C.kcalZone(2500, { kcalMode: "bulk", kcalTarget: 2400 }), "green");
  assert.equal(C.kcalZone(2300, { kcalMode: "bulk", kcalTarget: 2400 }), "red");
  assert.equal(C.kcalZone(2300, {}), null);
  assert.equal(C.kcalZone(2300, { kcalTarget: null }), null);
});
test("kcalZone: one-sided range falls back to the goal; reversed limits are swapped", () => {
  assert.equal(C.kcalZone(2450, { kcalMode: "cut", kcalTarget: 2400, kcalLow: 2100 }), "red");
  assert.equal(C.kcalZone(2000, { kcalMode: "cut", kcalTarget: 2400, kcalLow: 2100 }), "yellow");
  assert.equal(C.kcalZone(2200, { kcalMode: "cut", kcalLow: 2400, kcalHigh: 2100 }), "green");
  assert.equal(C.kcalZone(2000, { kcalMode: "cut", kcalLow: 2100, kcalHigh: 2400 }), "yellow"); // range alone works
});
const classes = [{ id: "c1", name: "ENGR 3413 Materials Science" }, { id: "c2", name: "Modern Physics" }, { id: "c3", name: "Physics Lab" }];
test("matchClass finds a class from loose spoken names", () => {
  assert.equal(C.matchClass(classes, "materials science").id, "c1");
  assert.equal(C.matchClass(classes, "Materials").id, "c1");
  assert.equal(C.matchClass(classes, "mat sci").id, "c1");
  assert.equal(C.matchClass(classes, "engr 3413").id, "c1");
  assert.equal(C.matchClass(classes, "modern physics").id, "c2");
  assert.equal(C.matchClass(classes, "physics lab").id, "c3");
  assert.equal(C.matchClass(classes, "chemistry"), null);
  assert.equal(C.matchClass(classes, ""), null);
  assert.equal(C.matchClass([], "materials"), null);
});
test("aiTextHTML escapes and keeps line breaks and bold", () => {
  assert.equal(C.aiTextHTML("Hi <b>\n**Exam 2** on Fri"), "Hi &lt;b&gt;<br><strong>Exam 2</strong> on Fri");
});
test("pickFlashModel prefers the newest free Flash model that can generate content", () => {
  const list = { models: [
    { name: "models/gemini-2.5-pro", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.5-flash", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.8-flash", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.8-flash-tts", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.8-flash-lite", supportedGenerationMethods: ["generateContent"] },
    { name: "models/embedding-001", supportedGenerationMethods: ["embedContent"] }] };
  assert.equal(C.pickFlashModel(list), "gemini-3.8-flash");
  assert.equal(C.pickFlashModel({ models: [] }), null);
});
test("pickFlashModel can skip busy models and fall back to Flash-Lite", () => {
  const list = { models: [
    { name: "models/gemini-3.5-flash", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.8-flash", supportedGenerationMethods: ["generateContent"] },
    { name: "models/gemini-3.5-flash-lite", supportedGenerationMethods: ["generateContent"] }] };
  assert.equal(C.pickFlashModel(list, ["gemini-3.8-flash"]), "gemini-3.5-flash");
  assert.equal(C.pickFlashModel(list, ["gemini-3.8-flash", "gemini-3.5-flash"]), "gemini-3.5-flash-lite");
  assert.equal(C.pickFlashModel(list, ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]), null);
});
test("parseHealthInbox reads per-day fields, tolerates formatted numbers, skips empty and future days", () => {
  const doc = {
    d20261003: { kcal: "2,345.6", protein: "180.24", carbs: "250", fat: "70.5", fiber: "31" },
    d20261004: { kcal: 2100, protein: 150 },
    d20261005: { kcal: "0", protein: "0" },
    d20261006: { kcal: "1500" },
    junk: { kcal: "999" }, d2026100: { kcal: "1" }, d20261002: "not a map",
  };
  assert.deepEqual(C.parseHealthInbox(doc, "2026-10-05"), [
    { date: "2026-10-03", kcal: 2346, protein: 180, carbs: 250, fat: 71, fiber: 31 },
    { date: "2026-10-04", kcal: 2100, protein: 150, carbs: 0, fat: 0, fiber: 0 },
  ]);
  assert.deepEqual(C.parseHealthInbox(null, "2026-10-05"), []);
});
test("mergeHealthDays makes Cronometer's synced totals the day's only row", () => {
  const nutrition = [
    { id: "a", date: "2026-10-03", kcal: 1000, protein: 0, carbs: 0, fat: 0, fiber: 0, source: "log", replaced: { id: "z" } },
    { id: "b", date: "2026-10-02", kcal: 1800, protein: 120, carbs: 0, fat: 0, fiber: 0, source: "cronometer" },
  ];
  const day = { date: "2026-10-03", kcal: 2346, protein: 180, carbs: 250, fat: 71, fiber: 31 };
  const r = C.mergeHealthDays(nutrition, [day], () => "new");
  assert.deepEqual(r.changed, ["2026-10-03"]);
  assert.deepEqual(r.nutrition.find(n => n.date === "2026-10-03"), { id: "new", ...day, source: "health" });
  assert.equal(r.nutrition.find(n => n.date === "2026-10-02").kcal, 1800);
  assert.equal(r.nutrition.length, 2);
  const again = C.mergeHealthDays(r.nutrition, [day], () => "other");
  assert.deepEqual(again.changed, []);
  assert.equal(again.nutrition, r.nutrition);
  const updated = C.mergeHealthDays(r.nutrition, [{ ...day, kcal: 2500 }], () => "other");
  assert.equal(updated.nutrition.find(n => n.date === "2026-10-03").id, "new");
});
test("healthToken-style ids: makeHealthToken is 32 url-safe characters", () => {
  const t = C.makeHealthToken(new Uint8Array(24).fill(255));
  assert.equal(t.length, 32); assert.match(t, /^[A-Za-z0-9_-]+$/);
});
