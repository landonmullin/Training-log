import { test } from "node:test";
import assert from "node:assert/strict";
import { core as C } from "./load-core.mjs";

const egg = { name: "Egg", per100g: { kcal: 143, protein: 12.6, carbs: 0.7, fat: 9.5, fiber: 0 },
  portions: [{ label: "1 large", grams: 50 }, { label: "1 cup", grams: 243 }], servingOnly: false };
const bar = { name: "Bar", per100g: { kcal: 210, protein: 20, carbs: 22, fat: 7, fiber: 3 },
  portions: [{ label: "1 bar", grams: 100 }], servingOnly: true };
let n = 0; const makeId = () => "id" + (++n);

test("unitOptions lists portions, then g and oz", () => {
  assert.deepEqual(C.unitOptions(egg).map(o => o.key), ["p0", "p1", "g", "oz"]);
});
test("serving-only foods offer only their serving", () => {
  assert.deepEqual(C.unitOptions(bar).map(o => o.key), ["p0"]);
});
test("gramsFor converts portions, grams and ounces", () => {
  assert.equal(C.gramsFor(egg, 2, "p0"), 100);
  assert.equal(C.gramsFor(egg, "1.5", "p1"), 364.5);
  assert.equal(C.gramsFor(egg, 180, "g"), 180);
  assert.equal(C.gramsFor(egg, 4, "oz"), 113.4);
});
test("gramsFor returns 0 for zero, negative, junk, unknown or hidden units", () => {
  for (const q of [0, -1, "", "abc", null]) assert.equal(C.gramsFor(egg, q, "g"), 0);
  assert.equal(C.gramsFor(egg, 1, "p9"), 0);
  assert.equal(C.gramsFor(bar, 100, "g"), 0);
});
test("macrosFor scales per-100g values", () => {
  assert.deepEqual(C.macrosFor(egg.per100g, 200), { kcal: 286, protein: 25.2, carbs: 1.4, fat: 19, fiber: 0 });
  assert.deepEqual(C.macrosFor(egg.per100g, 0), { kcal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0 });
});
test("amountLabel formats portions, grams and ounces", () => {
  assert.equal(C.amountLabel(egg, 1, "p0"), "1 large");
  assert.equal(C.amountLabel(egg, 2, "p0"), "2 × large");
  assert.equal(C.amountLabel(egg, 180, "g"), "180 g");
  assert.equal(C.amountLabel(egg, 4, "oz"), "4 oz");
  assert.equal(C.amountLabel(bar, 1.5, "p0"), "1.5 × bar");
  assert.equal(C.amountLabel(egg, 1, "zz"), "");
});
test("dayTotals sums and rounds to whole numbers", () => {
  const t = C.dayTotals([
    { kcal: 300, protein: 20.4, carbs: 30.3, fat: 10.2, fiber: 2.6 },
    { kcal: 150, protein: 10.4, carbs: 0, fat: 5.2, fiber: 0 },
  ]);
  assert.deepEqual(t, { kcal: 450, protein: 31, carbs: 30, fat: 15, fiber: 3 });
  assert.deepEqual(C.dayTotals([]), { kcal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0 });
});

const crono = (date) => ({ id: "c-" + date, date, kcal: 2000, protein: 150, carbs: 200, fat: 70, fiber: 30, source: "cronometer" });
const entry = (date, kcal) => ({ id: "e" + kcal, date, kcal, protein: 10, carbs: 10, fat: 5, fiber: 1 });

test("logged entries replace a Cronometer row for that date only", () => {
  const out = C.rebuildNutritionDay([crono("2026-09-29"), crono("2026-09-30")], [entry("2026-09-30", 500)], "2026-09-30", makeId);
  assert.equal(out.length, 2);
  assert.equal(out.find(r => r.date === "2026-09-29").source, "cronometer");
  const row = out.find(r => r.date === "2026-09-30");
  assert.equal(row.source, "log"); assert.equal(row.kcal, 500); assert.equal(row.protein, 10);
});
test("rebuilding keeps the existing log row id", () => {
  const prev = [{ id: "keep-me", date: "2026-09-30", kcal: 1, protein: 0, carbs: 0, fat: 0, fiber: 0, source: "log" }];
  const out = C.rebuildNutritionDay(prev, [entry("2026-09-30", 700)], "2026-09-30", makeId);
  assert.equal(out[0].id, "keep-me"); assert.equal(out[0].kcal, 700);
});
test("removing the last entry removes the log row", () => {
  const prev = [crono("2026-09-29"), { id: "x", date: "2026-09-30", kcal: 500, protein: 0, carbs: 0, fat: 0, fiber: 0, source: "log" }];
  const out = C.rebuildNutritionDay(prev, [], "2026-09-30", makeId);
  assert.deepEqual(out.map(r => r.date), ["2026-09-29"]);
});
test("a date with no entries keeps its Cronometer row", () => {
  const out = C.rebuildNutritionDay([crono("2026-09-30")], [], "2026-09-30", makeId);
  assert.equal(out.length, 1); assert.equal(out[0].source, "cronometer");
});
test("logging on a past day changes only that day's row", () => {
  const log = [entry("2026-09-28", 400), entry("2026-09-30", 900)];
  const out = C.rebuildNutritionDay([], log, "2026-09-28", makeId);
  assert.deepEqual(out.map(r => [r.date, r.kcal]), [["2026-09-28", 400]]);
});
test("skipLoggedDates drops dates that have log entries", () => {
  const rows = [{ date: "2026-09-27" }, { date: "2026-09-28" }];
  assert.deepEqual(C.skipLoggedDates(rows, [entry("2026-09-28", 1)]), { kept: [{ date: "2026-09-27" }], skipped: 1 });
});

test("customFood with serving grams scales to per 100 g", () => {
  const f = C.customFood({ name: " Burrito ", servingLabel: "1 burrito", servingGrams: "250", kcal: "650", protein: "30", carbs: "", fat: "20", fiber: "8" });
  assert.equal(f.name, "Burrito");
  assert.deepEqual(f.per100g, { kcal: 260, protein: 12, carbs: 0, fat: 8, fiber: 3.2 });
  assert.deepEqual(f.portions, [{ label: "1 burrito", grams: 250 }]);
  assert.equal(f.servingOnly, false); assert.equal(f.source, "custom");
  assert.equal(C.macrosFor(f.per100g, C.gramsFor(f, 1, "p0")).kcal, 650);
});
test("customFood without grams is serving-only", () => {
  const f = C.customFood({ name: "Wings", servingLabel: "", servingGrams: "", kcal: "900", protein: "60" });
  assert.equal(f.servingOnly, true);
  assert.deepEqual(f.portions, [{ label: "1 serving", grams: 100 }]);
  assert.equal(f.per100g.kcal, 900);
  assert.equal(C.macrosFor(f.per100g, C.gramsFor(f, 2, "p0")).kcal, 1800);
});
test("customFood accepts zero calories", () => {
  assert.equal(C.customFood({ name: "Black coffee", kcal: "0" }).per100g.kcal, 0);
});
test("customFood rejects blank name, blank or negative calories; clamps negative macros", () => {
  assert.throws(() => C.customFood({ name: " ", kcal: "100" }), /Enter a name/);
  assert.throws(() => C.customFood({ name: "X", kcal: "" }), /Enter calories/);
  assert.throws(() => C.customFood({ name: "X", kcal: "-5" }), /Enter calories/);
  assert.equal(C.customFood({ name: "X", kcal: "10", protein: "-3" }).per100g.protein, 0);
});
test("customFood keeps a normalized barcode", () => {
  assert.equal(C.customFood({ name: "X", kcal: "1", barcode: "0012 345" }).barcode, "12345");
});
test("toSavedFood adds bookkeeping and drops transient fields", () => {
  const s = C.toSavedFood({ ...egg, source: "usda", sourceId: "171287", tier: 1, saved: true, incomplete: false }, () => "f1");
  assert.equal(s.id, "f1"); assert.equal(s.uses, 0); assert.equal(s.lastUsed, 0);
  assert.equal("tier" in s, false); assert.equal("saved" in s, false); assert.equal("incomplete" in s, false);
  s.portions[0].grams = 999; assert.equal(egg.portions[0].grams, 50);
});

const lib = [
  { id: "a", name: "Egg, whole", brand: "", uses: 1, lastUsed: 300 },
  { id: "b", name: "Greek yogurt", brand: "Fage", uses: 9, lastUsed: 100 },
  { id: "c", name: "Egg whites", brand: "Kirkland", uses: 5, lastUsed: 200 },
  { id: "d", name: "Never used", brand: "", uses: 0, lastUsed: 0 },
];
test("searchSaved matches every word across name and brand, most-used first", () => {
  assert.deepEqual(C.searchSaved(lib, "egg").map(f => f.id), ["c", "a"]);
  assert.deepEqual(C.searchSaved(lib, "fage yog").map(f => f.id), ["b"]);
  assert.deepEqual(C.searchSaved(lib, "  "), []);
});
test("recentFoods sorts by last use or by count and skips unused foods", () => {
  assert.deepEqual(C.recentFoods(lib, "recent").map(f => f.id), ["a", "c", "b"]);
  assert.deepEqual(C.recentFoods(lib, "frequent").map(f => f.id), ["b", "c", "a"]);
});
test("time helpers", () => {
  assert.equal(C.fdTime("07:42"), "7:42a"); assert.equal(C.fdTime("00:05"), "12:05a");
  assert.equal(C.fdTime("12:30"), "12:30p"); assert.equal(C.fdTime("23:59"), "11:59p");
  assert.equal(C.fdTime("bad"), "");
  assert.equal(C.hhmmOf(new Date(2026, 0, 1, 7, 5)), "07:05");
  assert.equal(C.shiftISO("2026-03-01", -1), "2026-02-28");
  assert.equal(C.shiftISO("2026-12-31", 1), "2027-01-01");
});
test("tidyName only changes ALL CAPS names", () => {
  assert.equal(C.tidyName("GREEK NONFAT YOGURT, PLAIN"), "Greek Nonfat Yogurt, Plain");
  assert.equal(C.tidyName("Egg, whole, raw"), "Egg, whole, raw");
});
