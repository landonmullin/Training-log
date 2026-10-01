# Food Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Cronometer with in-app food logging (search, barcode scan, manual entry) whose daily totals feed the existing nutrition charts unchanged.

**Architecture:** All pure logic (unit math, totals, API parsers, ranking) lives in one marked block inside `index.html` (`// @food-core-start` … `// @food-core-end`), which Node tests extract and run. App-level code (state, rendering, network, scanner) sits next to the existing food code and calls the core. Every change to a day's `data.foodLog` re-derives that day's row in the existing `data.nutrition` array, so no existing reader changes.

**Tech Stack:** Vanilla JS in a single `index.html` (GitHub Pages PWA), localStorage, USDA FoodData Central API, Open Food Facts API, `@zxing/browser@0.2.1` (UMD, loaded on first scan), Node 20+ `node --test`, Python Playwright with local Chromium for UI smoke tests.

**Spec:** `docs/superpowers/specs/2026-09-30-food-logging-design.md`

## Global Constraints

- The app stays a single `index.html`; no build step. The only new runtime dependency is `https://cdn.jsdelivr.net/npm/@zxing/browser@0.2.1/umd/zxing-browser.min.js`, loaded only when Scan is first tapped.
- Nutrients tracked: calories, protein, carbs, fat, fiber only.
- One list per day, sorted by time. No meal groups.
- `data.nutrition` row shape stays `{id, date, kcal, protein, carbs, fat, fiber, source}`; derived rows use `source: "log"`.
- If a date has log entries, the log wins over `manual`/`cronometer` rows for that date. The Cronometer import skips any date with log entries.
- Remote search: 3+ characters, 500 ms debounce, USDA and OFF in parallel, 8-second timeout per call, stale requests aborted.
- Ranking: saved → USDA Foundation/SR Legacy → USDA Survey (FNDDS) → USDA Branded + OFF (de-duplicated by normalized barcode, USDA wins).
- Food data stays on the device and in the existing backup (same `data` object, localStorage key `ftrack-data-v2`). Nothing is written to Firebase.
- Phone-only layout: everything must work at 390 px wide.
- Ships as `APP_VERSION = 72`. `sw.js` does no caching; do not touch it. No feature toggle.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf
  ```

**Small additions beyond the spec (recorded here so reviewers don't flag them):**
- Log entries also store `qty` and `unit` (the amount as typed and the unit key) so the edit screen can re-open with the same amount.
- `@zxing/browser` does not export decode hints, so the scanner uses `BrowserMultiFormatOneDReader` with defaults (all 1-D formats). Codes are normalized to digits, so EAN/UPC behave as specified.
- The USDA key and Cronometer import live in a new **Nutrition** card in Settings.

## Review Focus

1. **Zero-calorie foods** (black coffee, diet soda): `kcal: 0` must be accepted by the manual form, Quick add, and OFF parsing, never treated as "missing". Pinned in Task 2 (`customFood` zero test), Task 3 (OFF `0` kcal test), Task 5 (Quick add 0 kcal smoke), Task 7 (scanned Diet Coke smoke).
2. **Deleting a logged day from "Recent days"**: the day must not reappear. Deleting a `source:"log"` row also removes that date's food entries. Pinned in Task 4.
3. **Fast typing / out-of-order responses**: an older search finishing late must not overwrite newer results. Pinned in Task 6 (stale-guard smoke).
4. **Barcode zero-padding** (UPC-A `012345678905` vs EAN-13 `0012345678905`): must match the same saved food. Pinned in Task 3 (`normBarcode`) and Task 7 (re-scan with different padding).
5. **Logging on a past day**: entries and the derived total land on the selected day, not today. Pinned in Task 2 (`rebuildNutritionDay` past-day test) and Task 5 (yesterday smoke).

---

## File Structure

| File | Responsibility |
|---|---|
| `index.html` | Everything shipped: core block (pure), app-level food code, CSS, Settings card. |
| `tests/load-core.mjs` | Extracts the `@food-core` block from `index.html` and returns its functions. |
| `tests/food.test.mjs` | Unit tests: units, macros, totals, precedence, custom foods, saved search, time helpers, prefill. |
| `tests/parse.test.mjs` | Unit tests: USDA/OFF parsers, merge/ranking, barcode normalization, URL builders. |
| `tests/fixtures/*.json` | Representative USDA and OFF responses (documented response shapes). |
| `tests/ui_smoke.py` | Headless Chromium smoke tests against a local server with mocked APIs. Local use only. |
| `probe.html` | Temporary CORS check page for Landon's phone. Deleted in Task 9. |

---

### Task 1: CORS probe (human-gated)

The sandbox cannot reach the food APIs, so browser access must be checked from Landon's phone. Tasks 2–5 do not depend on the result and continue while he runs it. **Task 6 does not start until the result is in.**

**Files:**
- Create: `probe.html`

**Interfaces:**
- Consumes: nothing.
- Produces: a pass/fail report from Landon for three endpoints, used as the gate for Task 6.

- [ ] **Step 1: Create the probe page**

```html
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>API check</title>
<style>
  body{font:16px -apple-system,sans-serif;padding:20px;max-width:520px;margin:auto}
  input,button{font-size:16px;padding:12px;width:100%;margin:8px 0;box-sizing:border-box}
  pre{white-space:pre-wrap;background:#f3f3f3;padding:10px;border-radius:8px;font-size:13px}
</style>
<h2>Food API check</h2>
<input id="key" placeholder="USDA key (leave blank to use DEMO_KEY)" autocomplete="off">
<button onclick="run()">Run checks</button>
<pre id="out">Not run yet.</pre>
<script>
async function check(name, url, pick){
  try { const r = await fetch(url); const j = await r.json(); return `${name}: OK (HTTP ${r.status}) — ${pick(j)}`; }
  catch(e){ return `${name}: FAILED — ${e.name}: ${e.message}`; }
}
async function run(){
  const key = document.getElementById("key").value.trim() || "DEMO_KEY";
  const out = document.getElementById("out"); out.textContent = "Running…";
  const types = encodeURIComponent("Foundation,SR Legacy,Survey (FNDDS),Branded");
  const lines = await Promise.all([
    check("USDA search", `https://api.nal.usda.gov/fdc/v1/foods/search?api_key=${encodeURIComponent(key)}&query=egg&pageSize=3&dataType=${types}`,
      j => `${j.totalHits} hits, first: ${j.foods?.[0]?.description} (${j.foods?.[0]?.dataType})`),
    check("OFF search", "https://world.openfoodfacts.org/cgi/search.pl?search_terms=greek%20yogurt&search_simple=1&action=process&json=1&page_size=3&fields=code,product_name",
      j => `${j.count} hits, first: ${j.products?.[0]?.product_name}`),
    check("OFF barcode", "https://world.openfoodfacts.org/api/v2/product/3017620422003.json?fields=code,product_name",
      j => `status ${j.status}, ${j.product?.product_name}`),
  ]);
  out.textContent = lines.join("\n\n");
}
</script>
```

- [ ] **Step 2: Commit and push** (Pages serves from `main`)

```bash
git add probe.html
git commit -m "Add temporary food API CORS probe" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
git push origin HEAD:main
```

- [ ] **Step 3: Ask Landon to run it**

Send: "Open `https://landonmullin.github.io/Training-log/probe.html` on your phone (Pages can take a minute to update), paste your USDA key or leave it blank, tap **Run checks**, and send me the three lines." A line reading `FAILED — TypeError: Load failed` (Safari) or `Failed to fetch` means the API blocks browser requests. Continue with Task 2 while waiting.

---

### Task 2: Food core block and Node test harness

**Files:**
- Modify: `index.html` — insert the core block directly after the line `// ----- food / nutrition -----` (currently line 1939).
- Create: `tests/load-core.mjs`, `tests/food.test.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces (all top-level function declarations in `index.html`, also returned by `core` in tests):
  - `FOOD_OZ` (const, 28.3495)
  - `fNum(v) → number` (non-finite → 0), `r1(n) → number` (1 decimal)
  - `normBarcode(s) → string` (digits only, leading zeros stripped)
  - `tidyName(s) → string` (Title Case only if input is ALL CAPS)
  - `unitOptions(food) → [{key, label, grams}]` (`"p0".."pN"`, then `"g"`, `"oz"` unless `servingOnly`)
  - `gramsFor(food, qty, unitKey) → number` (0 when invalid)
  - `amountLabel(food, qty, unitKey) → string`
  - `macrosFor(per100g, grams) → {kcal:int, protein, carbs, fat, fiber}` (1 decimal)
  - `dayTotals(entries) → {kcal, protein, carbs, fat, fiber}` (ints)
  - `rebuildNutritionDay(nutrition, foodLog, date, makeId) → nutrition[]` (new array)
  - `skipLoggedDates(rows, foodLog) → {kept, skipped}`
  - `customFood(values) → food` (throws `Error("Enter a name")` / `Error("Enter calories")`)
  - `toSavedFood(food, makeId) → savedFood` (adds `id, uses:0, lastUsed:0`; drops transient fields)
  - `searchSaved(foods, q) → foods[]`, `recentFoods(foods, mode) → foods[]`
  - `fmtTime("HH:MM") → "7:42a"`, `hhmmOf(Date) → "HH:MM"`, `shiftISO(iso, days) → iso`

- [ ] **Step 1: Write the test loader**

`tests/load-core.mjs`:
```js
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const m = html.match(/\/\/ @food-core-start([\s\S]*?)\/\/ @food-core-end/);
if (!m) throw new Error("food core block not found in index.html");
const body = m[1];
const names = [...body.matchAll(/^(?:function|const)\s+(\w+)/gm)].map(x => x[1]);
export const core = new Function(`"use strict";\n${body}\nreturn { ${names.join(", ")} };`)();
```

- [ ] **Step 2: Write the failing tests**

`tests/food.test.mjs`:
```js
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
  assert.equal(C.fmtTime("07:42"), "7:42a"); assert.equal(C.fmtTime("00:05"), "12:05a");
  assert.equal(C.fmtTime("12:30"), "12:30p"); assert.equal(C.fmtTime("23:59"), "11:59p");
  assert.equal(C.fmtTime("bad"), "");
  assert.equal(C.hhmmOf(new Date(2026, 0, 1, 7, 5)), "07:05");
  assert.equal(C.shiftISO("2026-03-01", -1), "2026-02-28");
  assert.equal(C.shiftISO("2026-12-31", 1), "2027-01-01");
});
test("tidyName only changes ALL CAPS names", () => {
  assert.equal(C.tidyName("GREEK NONFAT YOGURT, PLAIN"), "Greek Nonfat Yogurt, Plain");
  assert.equal(C.tidyName("Egg, whole, raw"), "Egg, whole, raw");
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test tests/food.test.mjs`
Expected: FAIL with `food core block not found in index.html`.

- [ ] **Step 4: Check for name collisions before inserting**

Run:
```bash
grep -n -E "^(function|const|let) (FOOD_OZ|fNum|r1|normBarcode|tidyName|unitOptions|gramsFor|amountLabel|macrosFor|dayTotals|rebuildNutritionDay|skipLoggedDates|customFood|toSavedFood|searchSaved|recentFoods|fmtTime|hhmmOf|shiftISO)\b" index.html
```
Expected: no output. If anything matches, rename the core function (prefix `fd`) everywhere in this plan's code before continuing.

- [ ] **Step 5: Insert the core block** directly after `// ----- food / nutrition -----`

```js
// @food-core-start
// Pure food-logging helpers: no DOM, no `data`, no network. Tested by tests/*.test.mjs.
const FOOD_OZ = 28.3495;
function fNum(v){ const n = typeof v === "string" ? parseFloat(v) : v; return Number.isFinite(n) ? n : 0; }
function r1(n){ return Math.round(n * 10) / 10; }
function normBarcode(s){ return String(s ?? "").replace(/\D/g, "").replace(/^0+/, ""); }
function tidyName(s){
  const t = String(s ?? "").trim();
  if (!t || t !== t.toUpperCase()) return t;
  return t.toLowerCase().replace(/(^|[\s,(\/-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
}
function unitOptions(food){
  const opts = (food.portions || []).map((p, i) => ({ key: "p" + i, label: p.label, grams: p.grams }));
  if (!food.servingOnly) opts.push({ key: "g", label: "g", grams: 1 }, { key: "oz", label: "oz", grams: FOOD_OZ });
  return opts;
}
function gramsFor(food, qty, unitKey){
  const q = fNum(qty);
  const u = unitOptions(food).find(o => o.key === unitKey);
  return (q > 0 && u) ? r1(q * u.grams) : 0;
}
function amountLabel(food, qty, unitKey){
  const u = unitOptions(food).find(o => o.key === unitKey);
  if (!u) return "";
  const q = r1(fNum(qty));
  if (unitKey === "g" || unitKey === "oz") return `${q} ${u.label}`;
  if (q === 1) return u.label;
  return `${q} × ${u.label.replace(/^1\s+/, "")}`;
}
function macrosFor(per100g, grams){
  const f = fNum(grams) / 100;
  return { kcal: Math.round(fNum(per100g.kcal) * f), protein: r1(fNum(per100g.protein) * f),
    carbs: r1(fNum(per100g.carbs) * f), fat: r1(fNum(per100g.fat) * f), fiber: r1(fNum(per100g.fiber) * f) };
}
function dayTotals(entries){
  const t = { kcal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0 };
  for (const e of entries) for (const k of Object.keys(t)) t[k] += fNum(e[k]);
  for (const k of Object.keys(t)) t[k] = Math.round(t[k]);
  return t;
}
function rebuildNutritionDay(nutrition, foodLog, date, makeId){
  const entries = foodLog.filter(e => e.date === date);
  const others = nutrition.filter(n => n.date !== date);
  if (!entries.length) return others.concat(nutrition.filter(n => n.date === date && n.source !== "log"));
  const prev = nutrition.find(n => n.date === date && n.source === "log");
  return others.concat([{ id: prev ? prev.id : makeId(), date, ...dayTotals(entries), source: "log" }]);
}
function skipLoggedDates(rows, foodLog){
  const logged = new Set(foodLog.map(e => e.date));
  return { kept: rows.filter(r => !logged.has(r.date)), skipped: rows.filter(r => logged.has(r.date)).length };
}
function customFood(v){
  const name = String(v.name ?? "").trim();
  if (!name) throw new Error("Enter a name");
  const kcalRaw = String(v.kcal ?? "").trim();
  if (kcalRaw === "" || !(parseFloat(kcalRaw) >= 0)) throw new Error("Enter calories");
  const grams = fNum(v.servingGrams);
  const servingOnly = !(grams > 0);
  const scale = servingOnly ? 1 : 100 / grams;
  const per100g = {};
  for (const k of ["kcal", "protein", "carbs", "fat", "fiber"]) per100g[k] = r1(Math.max(0, fNum(v[k])) * scale);
  return { name, brand: String(v.brand ?? "").trim(), barcode: normBarcode(v.barcode), per100g,
    portions: [{ label: String(v.servingLabel ?? "").trim() || "1 serving", grams: servingOnly ? 100 : r1(grams) }],
    servingOnly, source: "custom", sourceId: "" };
}
function toSavedFood(f, makeId){
  return { id: makeId(), name: f.name, brand: f.brand || "", barcode: f.barcode || "",
    per100g: { ...f.per100g }, portions: (f.portions || []).map(p => ({ label: p.label, grams: p.grams })),
    servingOnly: !!f.servingOnly, source: f.source, sourceId: f.sourceId || "", uses: 0, lastUsed: 0 };
}
function searchSaved(foods, q){
  const toks = String(q ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!toks.length) return [];
  return foods.filter(f => { const hay = (f.name + " " + (f.brand || "")).toLowerCase(); return toks.every(t => hay.includes(t)); })
    .sort((a, b) => (b.uses - a.uses) || (b.lastUsed - a.lastUsed)).slice(0, 20);
}
function recentFoods(foods, mode){
  const key = mode === "frequent" ? (f => f.uses) : (f => f.lastUsed);
  return foods.filter(f => f.uses > 0).sort((a, b) => key(b) - key(a)).slice(0, 15);
}
function fmtTime(hhmm){
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ""));
  if (!m) return "";
  const h = +m[1];
  return `${h % 12 || 12}:${m[2]}${h < 12 ? "a" : "p"}`;
}
function hhmmOf(d){ return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; }
function shiftISO(iso, days){
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + days);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}
// @food-core-end
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `node --test tests/food.test.mjs`
Expected: all tests PASS.

- [ ] **Step 7: Confirm the app still boots** (no duplicate-declaration errors)

Run a quick headless load (the full harness arrives in Task 4):
```bash
python3 - <<'EOF'
import subprocess, time
from playwright.sync_api import sync_playwright
srv = subprocess.Popen(["python3","-m","http.server","8765"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg = b.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/*", lambda r: r.continue_() if "localhost" in r.request.url else r.abort())
        pg.goto("http://localhost:8765/index.html"); pg.evaluate("App.tab('food')")
        print("errors:", errs); assert not errs
finally: srv.terminate()
EOF
```
Expected: `errors: []`.

- [ ] **Step 8: Commit**

```bash
git add index.html tests/load-core.mjs tests/food.test.mjs
git commit -m "Add pure food-logging core with unit tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 3: API parsers, ranking and URL builders

**Files:**
- Modify: `index.html` — add to the core block, just above `// @food-core-end`.
- Create: `tests/parse.test.mjs`, `tests/fixtures/usda-search.json`, `tests/fixtures/off-search.json`, `tests/fixtures/off-product.json`, `tests/fixtures/off-product-missing.json`

**Interfaces:**
- Consumes: `fNum`, `r1`, `normBarcode`, `tidyName` (Task 2).
- Produces:
  - `USDA_TIER` (const map: `Foundation`/`SR Legacy` → 1, `Survey (FNDDS)` → 2, `Branded` → 3)
  - `OFF_FIELDS` (const string)
  - `parseUsdaFood(apiFood) → food | null` (food has transient `tier`)
  - `parseOffProduct(apiProduct) → food | null` (transient `tier: 3`, `incomplete: boolean`; `per100g.kcal` may be `null`)
  - `mergeResults(savedHits, usdaFoods, offFoods) → foods[]` (saved first with `saved: true`)
  - `usdaSearchURL(q, key)`, `offSearchURL(q)`, `offProductURL(code)` → strings

- [ ] **Step 1: Write the fixtures** (shapes match the documented API responses; values are realistic)

`tests/fixtures/usda-search.json`:
```json
{"totalHits":4,"foods":[
 {"fdcId":171287,"description":"Egg, whole, raw, fresh","dataType":"SR Legacy",
  "foodNutrients":[{"nutrientId":1003,"nutrientName":"Protein","unitName":"G","value":12.6},
   {"nutrientId":1004,"nutrientName":"Total lipid (fat)","unitName":"G","value":9.51},
   {"nutrientId":1005,"nutrientName":"Carbohydrate, by difference","unitName":"G","value":0.72},
   {"nutrientId":1008,"nutrientName":"Energy","unitName":"KCAL","value":143},
   {"nutrientId":1079,"nutrientName":"Fiber, total dietary","unitName":"G","value":0}],
  "foodMeasures":[{"disseminationText":"1 large","gramWeight":50,"rank":2},
   {"disseminationText":"1 cup (4.86 large eggs)","gramWeight":243,"rank":1},
   {"disseminationText":"Quantity not specified","gramWeight":50,"rank":9}]},
 {"fdcId":2646170,"description":"Chicken, breast, boneless, skinless, raw","dataType":"Foundation",
  "foodNutrients":[{"nutrientId":1003,"unitName":"G","value":22.5},{"nutrientId":1004,"unitName":"G","value":1.93},
   {"nutrientId":1005,"unitName":"G","value":0},{"nutrientId":1062,"unitName":"KJ","value":444},
   {"nutrientId":2047,"unitName":"KCAL","value":106}],
  "foodMeasures":[]},
 {"fdcId":2345678,"description":"GREEK NONFAT YOGURT, PLAIN","dataType":"Branded","brandOwner":"Fage USA Dairy Industry, Inc.","brandName":"FAGE",
  "gtinUpc":"00689544080350","servingSize":170,"servingSizeUnit":"g","householdServingFullText":"1 container",
  "foodNutrients":[{"nutrientId":1003,"unitName":"G","value":10.0},{"nutrientId":1004,"unitName":"G","value":0},
   {"nutrientId":1005,"unitName":"G","value":3.53},{"nutrientId":1008,"unitName":"KCAL","value":53},{"nutrientId":1079,"unitName":"G","value":0}],
  "foodMeasures":[]},
 {"fdcId":999,"description":"NO ENERGY ROW","dataType":"Branded","foodNutrients":[{"nutrientId":1003,"unitName":"G","value":5}]}
]}
```

`tests/fixtures/off-search.json`:
```json
{"count":3,"page":1,"products":[
 {"code":"0689544080350","product_name":"Total 0% Greek Yogurt","brands":"Fage","serving_size":"170 g","serving_quantity":170,
  "nutriments":{"energy-kcal_100g":54,"proteins_100g":10.3,"carbohydrates_100g":3.6,"fat_100g":0,"fiber_100g":0}},
 {"code":"3017620422003","product_name":"Nutella","brands":"Ferrero,Nutella","serving_size":"15 g","serving_quantity":15,
  "nutriments":{"energy-kj_100g":2252,"proteins_100g":6.3,"carbohydrates_100g":57.5,"fat_100g":30.9}},
 {"code":"111","product_name":"Mystery bar","brands":"","nutriments":{"proteins_100g":20}}
]}
```

`tests/fixtures/off-product.json`:
```json
{"code":"0049000028911","status":1,"product":{"code":"0049000028911","product_name":"Diet Coke","brands":"Coca-Cola",
 "serving_size":"1 can (355 ml)","serving_quantity":355,
 "nutriments":{"energy-kcal_100g":0,"proteins_100g":0,"carbohydrates_100g":0,"fat_100g":0}}}
```

`tests/fixtures/off-product-missing.json`:
```json
{"code":"0000000000017","status":0,"status_verbose":"product not found"}
```

- [ ] **Step 2: Write the failing tests**

`tests/parse.test.mjs`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { core as C } from "./load-core.mjs";

const fx = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const usda = fx("usda-search.json").foods;
const off = fx("off-search.json").products;

test("USDA generic food: kcal, macros, portions by rank, junk portion dropped", () => {
  const f = C.parseUsdaFood(usda[0]);
  assert.equal(f.name, "Egg, whole, raw, fresh"); assert.equal(f.source, "usda"); assert.equal(f.sourceId, "171287");
  assert.equal(f.tier, 1);
  assert.deepEqual(f.per100g, { kcal: 143, protein: 12.6, carbs: 0.7, fat: 9.5, fiber: 0 });
  assert.deepEqual(f.portions, [{ label: "1 cup (4.86 large eggs)", grams: 243 }, { label: "1 large", grams: 50 }]);
});
test("USDA Foundation food falls back to Atwater energy (2047) and ignores kJ", () => {
  const f = C.parseUsdaFood(usda[1]);
  assert.equal(f.per100g.kcal, 106); assert.equal(f.per100g.fiber, 0); assert.deepEqual(f.portions, []);
});
test("USDA branded food: tidy name, brand, serving portion, normalized barcode", () => {
  const f = C.parseUsdaFood(usda[2]);
  assert.equal(f.name, "Greek Nonfat Yogurt, Plain"); assert.equal(f.brand, "FAGE");
  assert.equal(f.barcode, "689544080350"); assert.equal(f.tier, 3);
  assert.deepEqual(f.portions, [{ label: "1 serving (1 container)", grams: 170 }]);
});
test("USDA food with no energy value is dropped", () => {
  assert.equal(C.parseUsdaFood(usda[3]), null);
  assert.equal(C.parseUsdaFood(null), null);
});
test("OFF product: kcal, first brand, serving portion", () => {
  const f = C.parseOffProduct(off[0]);
  assert.equal(f.name, "Total 0% Greek Yogurt"); assert.equal(f.brand, "Fage"); assert.equal(f.source, "off");
  assert.equal(f.per100g.kcal, 54); assert.equal(f.incomplete, false);
  assert.deepEqual(f.portions, [{ label: "1 serving (170 g)", grams: 170 }]);
});
test("OFF product with only kJ converts to kcal", () => {
  const f = C.parseOffProduct(off[1]);
  assert.equal(f.per100g.kcal, 538.2); assert.equal(f.brand, "Ferrero"); assert.equal(f.per100g.fiber, 0);
});
test("OFF product without energy is marked incomplete", () => {
  const f = C.parseOffProduct(off[2]);
  assert.equal(f.incomplete, true); assert.equal(f.per100g.kcal, null); assert.deepEqual(f.portions, []);
});
test("OFF zero-calorie product is complete, not missing", () => {
  const f = C.parseOffProduct(fx("off-product.json").product);
  assert.equal(f.per100g.kcal, 0); assert.equal(f.incomplete, false); assert.equal(f.barcode, "49000028911");
});
test("normBarcode makes UPC-A and EAN-13 forms of one product equal", () => {
  assert.equal(C.normBarcode("012345678905"), C.normBarcode("0012345678905"));
  assert.equal(C.normBarcode(" 0049 0000-28911 "), "49000028911");
  assert.equal(C.normBarcode(""), ""); assert.equal(C.normBarcode(null), "");
});
test("mergeResults ranks tiers, de-duplicates by barcode (USDA wins), drops incomplete", () => {
  const u = usda.map(C.parseUsdaFood).filter(Boolean);
  const o = off.map(C.parseOffProduct).filter(Boolean);
  const out = C.mergeResults([], u, o);
  assert.deepEqual(out.map(f => f.name), ["Egg, whole, raw, fresh", "Chicken, breast, boneless, skinless, raw", "Greek Nonfat Yogurt, Plain", "Nutella"]);
});
test("mergeResults puts saved foods first and hides remote copies of them", () => {
  const u = usda.map(C.parseUsdaFood).filter(Boolean);
  const saved = [{ id: "s1", name: "Egg, whole, raw, fresh", source: "usda", sourceId: "171287", barcode: "", per100g: {}, portions: [] },
                 { id: "s2", name: "Nutella (mine)", source: "custom", sourceId: "", barcode: "3017620422003", per100g: {}, portions: [] }];
  const out = C.mergeResults(saved, u, off.map(C.parseOffProduct).filter(Boolean));
  assert.deepEqual(out.map(f => f.name), ["Egg, whole, raw, fresh", "Nutella (mine)", "Chicken, breast, boneless, skinless, raw", "Greek Nonfat Yogurt, Plain"]);
  assert.equal(out[0].saved, true); assert.equal(out[2].saved, undefined);
});
test("URL builders encode the query and key", () => {
  const u = C.usdaSearchURL("mac & cheese", "k/1");
  assert.ok(u.startsWith("https://api.nal.usda.gov/fdc/v1/foods/search?"));
  assert.ok(u.includes("query=mac%20%26%20cheese")); assert.ok(u.includes("api_key=k%2F1"));
  assert.ok(u.includes("pageSize=25")); assert.ok(u.includes("dataType=Foundation%2CSR%20Legacy%2CSurvey%20(FNDDS)%2CBranded"));
  assert.ok(C.offSearchURL("greek yogurt").includes("search_terms=greek%20yogurt"));
  assert.equal(C.offProductURL("0049000028911"), `https://world.openfoodfacts.org/api/v2/product/0049000028911.json?fields=${C.OFF_FIELDS}`);
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `node --test tests/parse.test.mjs`
Expected: FAIL (`C.parseUsdaFood is not a function`).

- [ ] **Step 4: Implement** — paste above `// @food-core-end`:

```js
const USDA_TIER = { "Foundation": 1, "SR Legacy": 1, "Survey (FNDDS)": 2, "Branded": 3 };
const OFF_FIELDS = "code,product_name,brands,nutriments,serving_size,serving_quantity";
function parseUsdaFood(f){
  if (!f || !f.fdcId) return null;
  const ns = f.foodNutrients || [];
  const pick = (id, kcalOnly) => {
    const n = ns.find(x => x.nutrientId === id && (!kcalOnly || String(x.unitName || "").toUpperCase() === "KCAL"));
    return n && Number.isFinite(n.value) ? n.value : null;
  };
  const kcal = pick(1008, true) ?? pick(2047, true) ?? pick(2048, true);
  if (kcal == null) return null;
  const portions = [];
  if (f.dataType === "Branded"){
    const sz = fNum(f.servingSize), unit = String(f.servingSizeUnit || "").toLowerCase();
    if (sz > 0 && (unit === "g" || unit === "grm"))
      portions.push({ label: `1 serving (${f.householdServingFullText ? String(f.householdServingFullText).trim() : r1(sz) + " g"})`, grams: r1(sz) });
  }
  for (const m of [...(f.foodMeasures || [])].sort((a, b) => (a.rank || 0) - (b.rank || 0))){
    const g = fNum(m.gramWeight), t = String(m.disseminationText || "").trim();
    if (g > 0 && t && t.toLowerCase() !== "quantity not specified" && portions.length < 6) portions.push({ label: t, grams: r1(g) });
  }
  return { name: tidyName(f.description), brand: String(f.brandName || f.brandOwner || "").trim(), barcode: normBarcode(f.gtinUpc),
    per100g: { kcal: r1(kcal), protein: r1(fNum(pick(1003))), carbs: r1(fNum(pick(1005))), fat: r1(fNum(pick(1004))), fiber: r1(fNum(pick(1079))) },
    portions, servingOnly: false, source: "usda", sourceId: String(f.fdcId), tier: USDA_TIER[f.dataType] || 3 };
}
function parseOffProduct(p){
  if (!p || !p.code) return null;
  const n = p.nutriments || {};
  const kcal = n["energy-kcal_100g"] != null ? fNum(n["energy-kcal_100g"])
    : n["energy-kj_100g"] != null ? fNum(n["energy-kj_100g"]) / 4.184 : null;
  const sq = fNum(p.serving_quantity);
  const portions = sq > 0 ? [{ label: `1 serving (${p.serving_size ? String(p.serving_size).trim() : r1(sq) + " g"})`, grams: r1(sq) }] : [];
  return { name: String(p.product_name || "").trim() || "Unnamed product", brand: String(p.brands || "").split(",")[0].trim(),
    barcode: normBarcode(p.code),
    per100g: { kcal: kcal == null ? null : r1(kcal), protein: r1(fNum(n.proteins_100g)), carbs: r1(fNum(n.carbohydrates_100g)),
      fat: r1(fNum(n.fat_100g)), fiber: r1(fNum(n.fiber_100g)) },
    portions, servingOnly: false, source: "off", sourceId: String(p.code), tier: 3, incomplete: kcal == null };
}
function mergeResults(savedHits, usdaFoods, offFoods){
  const keys = new Set(savedHits.map(f => f.source + ":" + f.sourceId));
  const codes = new Set(savedHits.map(f => f.barcode).filter(Boolean));
  const out = [];
  const remote = [...usdaFoods, ...offFoods].filter(f => f && !f.incomplete).sort((a, b) => a.tier - b.tier);
  for (const f of remote){
    const key = f.source + ":" + f.sourceId;
    if (keys.has(key) || (f.barcode && codes.has(f.barcode))) continue;
    keys.add(key); if (f.barcode) codes.add(f.barcode);
    out.push(f);
  }
  return savedHits.map(f => ({ ...f, saved: true })).concat(out);
}
function usdaSearchURL(q, key){
  return `https://api.nal.usda.gov/fdc/v1/foods/search?api_key=${encodeURIComponent(key)}&query=${encodeURIComponent(q)}`
    + `&pageSize=25&dataType=${encodeURIComponent("Foundation,SR Legacy,Survey (FNDDS),Branded")}`;
}
function offSearchURL(q){
  return `https://world.openfoodfacts.org/cgi/search.pl?search_terms=${encodeURIComponent(q)}`
    + `&search_simple=1&action=process&json=1&page_size=20&fields=${OFF_FIELDS}`;
}
function offProductURL(code){
  return `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(String(code).replace(/\D/g, ""))}.json?fields=${OFF_FIELDS}`;
}
```

Note: `encodeURIComponent` leaves `(` and `)` unencoded, which is why the test expects `Survey%20(FNDDS)`.

- [ ] **Step 5: Add the collision names to the check and run it**

```bash
grep -n -E "^(function|const|let) (USDA_TIER|OFF_FIELDS|parseUsdaFood|parseOffProduct|mergeResults|usdaSearchURL|offSearchURL|offProductURL)\b" index.html
```
Expected: exactly one line per name (the ones you just added).

- [ ] **Step 6: Run all unit tests**

Run: `node --test tests/*.test.mjs`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add index.html tests/parse.test.mjs tests/fixtures
git commit -m "Add USDA and Open Food Facts parsers with ranking" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 4: Data layer, Cronometer import rules, and UI smoke harness

**Files:**
- Modify: `index.html`
  - `EMPTY` (line ~163)
  - `ui` object (line ~1500)
  - after the `// @food-core-end` line: app-level food helpers
  - `App.delFood` (line ~3500)
  - `#csvFile` change handler (line ~4126)
  - end of `renderSettings()` (line ~2750)
- Create: `tests/ui_smoke.py`

**Interfaces:**
- Consumes: `rebuildNutritionDay`, `skipLoggedDates`, `toSavedFood`, `fNum` (Task 2).
- Produces:
  - `data.foods: SavedFood[]`, `data.foodLog: LogEntry[]` where `LogEntry = {id, date, time, foodId|null, name, grams|null, qty|null, unit|null, label, kcal, protein, carbs, fat, fiber}`
  - `refreshFoodDay(date) → void` (re-derives that date's `data.nutrition` row)
  - `upsertFood(food) → SavedFood` (finds by id, then `source+sourceId`, then barcode; else saves a copy)
  - `foodForEntry(entry) → food` (library food, or a stand-in rebuilt from the entry's snapshot)
  - `nutritionSettingsHTML() → string` with insertion markers `<!-- usda-key -->` and `<!-- my-foods -->`
  - `ui` fields: `foodDay, foodSheet, foodQuery, foodFocus, foodListMode, foodResults, foodRemote, foodPick, foodAmt, foodEdit, foodQuickPrefill, foodPrefill, foodEditFoodId, scanStatus`
  - `tests/ui_smoke.py` with helpers `app(pw, url, seed, offline=False)`, `stored(pg)`, `base(**over)`, `@test`, and the marker line `# --- tests above this line ---`

- [ ] **Step 1: Write the smoke harness with the first two failing tests**

`tests/ui_smoke.py`:
```python
"""Headless smoke tests for the food logger. Run: python3 tests/ui_smoke.py
Serves the repo locally, mocks the food APIs from tests/fixtures, blocks every other network request."""
import contextlib, http.server, json, os, socketserver, sys, threading, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
CHROME = os.environ.get("CHROME_PATH", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
KEY = "ftrack-data-v2"
CORS = {"Access-Control-Allow-Origin": "*"}

class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(ROOT), **k)
    def log_message(self, *a): pass

def start_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html"

def fixture(name): return (FIX / name).read_text()

def router(offline):
    def handle(route):
        url = route.request.url
        if url.startswith("http://127.0.0.1"): return route.continue_()
        if offline: return route.abort()
        if "api.nal.usda.gov" in url:
            return route.fulfill(status=200, content_type="application/json", body=fixture("usda-search.json"), headers=CORS)
        if "openfoodfacts.org/cgi/search.pl" in url:
            return route.fulfill(status=200, content_type="application/json", body=fixture("off-search.json"), headers=CORS)
        if "openfoodfacts.org/api/v2/product/" in url:
            name = "off-product.json" if "49000028911" in url else "off-product-missing.json"
            return route.fulfill(status=200, content_type="application/json", body=fixture(name), headers=CORS)
        return route.abort()
    return handle

def base(**over):
    d = {"lifts": [], "cardio": [], "weights": [], "nutrition": [], "todos": [], "shifts": [], "events": [],
         "customExercises": [], "foods": [], "foodLog": [],
         "school": {"classes": [], "tasks": [], "dates": [], "sessions": [], "assignments": [], "schedule": []},
         "settings": {"kcalTarget": 2400, "proteinTarget": 180}}
    d.update(over); return d

EGG = {"id": "f-egg", "name": "Egg, whole", "brand": "", "barcode": "",
       "per100g": {"kcal": 143, "protein": 12.6, "carbs": 0.7, "fat": 9.5, "fiber": 0},
       "portions": [{"label": "1 large", "grams": 50}], "servingOnly": False,
       "source": "usda", "sourceId": "171287", "uses": 3, "lastUsed": 1}

@contextlib.contextmanager
def app(pw, url, seed=None, offline=False):
    b = pw.chromium.launch(executable_path=CHROME)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    if seed is not None:
        ctx.add_init_script(
            f"if(!sessionStorage.getItem('seeded')){{localStorage.setItem({json.dumps(KEY)},{json.dumps(json.dumps(seed))});"
            "sessionStorage.setItem('seeded','1');}")
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route("**/*", router(offline))
    pg.goto(url); pg.evaluate("App.tab('food')")
    try:
        yield pg
        assert not errors, f"page errors: {errors}"
    finally:
        b.close()

def stored(pg): return pg.evaluate(f"JSON.parse(localStorage.getItem({json.dumps(KEY)}))")
def today(pg): return pg.evaluate("todayISO()")

TESTS = []
def test(fn): TESTS.append(fn); return fn

@test
def cronometer_import_skips_logged_dates(pw, url):
    seed = base(foodLog=[{"id": "e1", "date": "2026-09-28", "time": "08:00", "foodId": None, "name": "Quick add",
                          "grams": None, "qty": None, "unit": None, "label": "", "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}],
                nutrition=[{"id": "n1", "date": "2026-09-28", "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "source": "log"}])
    csv = "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n2026-09-27,2100,150,200,70,30\n2026-09-28,2300,160,210,75,32\n"
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        assert pg.locator("#nutritionSettings").count() == 1
        pg.set_input_files("#csvFile", files=[{"name": "c.csv", "mimeType": "text/csv", "buffer": csv.encode()}])
        pg.wait_for_function("JSON.parse(localStorage.getItem('ftrack-data-v2')).nutrition.length === 2")
        rows = {r["date"]: r for r in stored(pg)["nutrition"]}
        assert rows["2026-09-27"]["source"] == "cronometer"
        assert rows["2026-09-28"]["source"] == "log" and rows["2026-09-28"]["kcal"] == 500

@test
def deleting_a_logged_day_clears_its_entries(pw, url):
    d = "2026-09-28"
    seed = base(foodLog=[{"id": "e1", "date": d, "time": "08:00", "foodId": None, "name": "Quick add", "grams": None,
                          "qty": None, "unit": None, "label": "", "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}],
                nutrition=[{"id": "n1", "date": d, "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "source": "log"}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.delFood('n1')"); pg.evaluate("App.delFood('n1')")
        s = stored(pg)
        assert s["nutrition"] == [] and s["foodLog"] == []
        pg.evaluate("refreshFoodDay('2026-09-28')")
        assert stored(pg)["nutrition"] == []

# --- tests above this line ---

def main():
    srv, url = start_server(); failed = 0
    only = sys.argv[1:]
    with sync_playwright() as pw:
        for t in TESTS:
            if only and t.__name__ not in only: continue
            try: t(pw, url); print("ok  ", t.__name__)
            except Exception: failed += 1; print("FAIL", t.__name__); traceback.print_exc()
    srv.shutdown()
    print(f"{failed} failed"); sys.exit(1 if failed else 0)

if __name__ == "__main__": main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/ui_smoke.py`
Expected: both FAIL (`#nutritionSettings` count is 0; `refreshFoodDay is not defined` or the entries remain).

- [ ] **Step 3: Add the new arrays to `EMPTY`**

Replace:
```js
const EMPTY = { lifts:[], cardio:[], weights:[], nutrition:[], todos:[], shifts:[], events:[], customExercises:[],
```
with:
```js
const EMPTY = { lifts:[], cardio:[], weights:[], nutrition:[], todos:[], shifts:[], events:[], customExercises:[], foods:[], foodLog:[],
```
(The existing loop right after loading `data` fills any missing array from `EMPTY`, and backup restore spreads `EMPTY`, so old data and old backups pick these up automatically.)

- [ ] **Step 4: Add the UI state fields**

Replace:
```js
  foodMetric: "kcal", foodManualOpen: false, cardioList: "recent", targetsOpen: false,
```
with:
```js
  foodMetric: "kcal", foodManualOpen: false, cardioList: "recent", targetsOpen: false,
  foodDay: todayISO(), foodSheet: null, foodQuery: "", foodFocus: false, foodListMode: "recent", foodResults: [],
  foodRemote: { q: "", usda: [], off: [], status: "" }, foodPick: null, foodAmt: null, foodEdit: null,
  foodQuickPrefill: null, foodPrefill: null, foodEditFoodId: null, scanStatus: "",
```

- [ ] **Step 5: Add the app-level helpers** directly after the `// @food-core-end` line

```js
// ----- food log: app-level (reads/writes `data`) -----
function refreshFoodDay(date){ data.nutrition = rebuildNutritionDay(data.nutrition, data.foodLog, date, uid); }
function upsertFood(food){
  let f = food.id ? data.foods.find(x => x.id === food.id) : null;
  if (!f && food.source !== "custom" && food.sourceId) f = data.foods.find(x => x.source === food.source && x.sourceId === food.sourceId);
  if (!f && food.barcode) f = data.foods.find(x => x.barcode && x.barcode === food.barcode);
  if (!f){ f = toSavedFood(food, uid); data.foods.push(f); }
  return f;
}
function foodForEntry(e){
  const lib = data.foods.find(f => f.id === e.foodId);
  if (lib) return lib;
  const g = fNum(e.grams) || 100, k = 100 / g;
  return { name: e.name, brand: "", barcode: "", portions: [], servingOnly: false, source: "custom", sourceId: "",
    per100g: { kcal: e.kcal * k, protein: e.protein * k, carbs: e.carbs * k, fat: e.fat * k, fiber: e.fiber * k } };
}
function nutritionSettingsHTML(){
  return `<div class="card" id="nutritionSettings">
    <div class="lbl" style="margin-bottom:8px">Nutrition</div>
    <!-- usda-key -->
    <div style="font-size:14px;font-weight:600;margin-bottom:4px">Import from Cronometer</div>
    <div style="font-size:13px;color:var(--sub);margin-bottom:10px;line-height:1.45">Back-fill past days from a Cronometer <b>Daily Nutrition</b> export (website: Account → Export Data). Days that already have foods logged here are skipped.</div>
    <button class="btn" style="background:transparent;border:1px solid var(--pull);color:var(--pull)" onclick="document.getElementById('csvFile').click()">Upload Cronometer CSV</button>
    <!-- my-foods -->
  </div>`;
}
```

- [ ] **Step 6: Show the card in Settings**

At the end of `renderSettings()`, replace:
```js
    <div style="font-size:12px;color:var(--sub);margin-top:8px">Turning one off hides it from the logging menus — activities you already logged stay visible everywhere.</div>
  </div>`;
  return html;
}
```
with:
```js
    <div style="font-size:12px;color:var(--sub);margin-top:8px">Turning one off hides it from the logging menus — activities you already logged stay visible everywhere.</div>
  </div>`;
  html += nutritionSettingsHTML();
  return html;
}
```

- [ ] **Step 7: Make the Cronometer import skip logged dates**

In the `$("#csvFile").addEventListener("change", …)` handler, replace:
```js
    const parsed = parseCronometerCSV(await f.text());
    if (!parsed.length) throw new Error("No daily rows found in file");
```
with:
```js
    const parsedAll = parseCronometerCSV(await f.text());
    if (!parsedAll.length) throw new Error("No daily rows found in file");
    const { kept: parsed, skipped } = skipLoggedDates(parsedAll, data.foodLog);
    if (!parsed.length) throw new Error(`All ${skipped} day${skipped>1?"s":""} already have foods logged here — nothing imported`);
```
and replace the success toast line:
```js
    toast(`Imported ${parsed.length} day${parsed.length>1?"s":""} (${shortDate(ds[0])}–${shortDate(ds[ds.length-1])}) ✓`);
```
with:
```js
    toast(`Imported ${parsed.length} day${parsed.length>1?"s":""} (${shortDate(ds[0])}–${shortDate(ds[ds.length-1])})${skipped?` · ${skipped} logged day${skipped>1?"s":""} kept`:""} ✓`);
```

- [ ] **Step 8: Make deleting a logged day also clear its entries**

Replace `App.delFood`:
```js
  delFood(key){
    if(!confirmDel("F"+key))return;
    data.nutrition = data.nutrition.filter(d=>d.id!==key && d.date!==key);
    save(); toast("Day deleted"); render();
  },
```
with:
```js
  delFood(key){
    if(!confirmDel("F"+key))return;
    const row = data.nutrition.find(d=>d.id===key || d.date===key);
    data.nutrition = data.nutrition.filter(d=>d.id!==key && d.date!==key);
    if (row) data.foodLog = data.foodLog.filter(e=>e.date!==row.date); // or the day would rebuild from its entries
    save(); toast("Day deleted"); render();
  },
```

- [ ] **Step 9: Run the smoke tests and unit tests**

Run: `python3 tests/ui_smoke.py && node --test tests/*.test.mjs`
Expected: `0 failed`, unit tests all PASS.

- [ ] **Step 10: Commit**

```bash
git add index.html tests/ui_smoke.py
git commit -m "Add food log data layer; Cronometer import skips logged days" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 5: Food tab day card, add sheet, amount screen, Quick add, edit/delete

**Files:**
- Modify: `index.html`
  - `<style>`: add sheet and row CSS
  - `renderFood()`: replace the Cronometer card and manual form with the day card; append the sheet
  - after `nutritionSettingsHTML()`: rendering functions
  - `App`: replace `toggleFoodManual` and `saveFood`; add food actions
  - `App.tab`: close any open sheet
  - `afterRender()`: focus the search box
  - `ui`: remove `foodManualOpen: false, `
- Modify: `tests/ui_smoke.py` (append tests above the marker)

**Interfaces:**
- Consumes: Task 2 core, `refreshFoodDay`, `upsertFood`, `foodForEntry` (Task 4).
- Produces:
  - `foodSheetHTML() → string` (dispatches on `ui.foodSheet` ∈ `"search" | "amount" | "quick" | "create" | "scan"`; unknown → `""`)
  - `foodResultsHTML() → string` (also sets `ui.foodResults`), `updateFoodResults() → void`
  - `foodSheetBodies` object that later tasks extend: `foodSheetBodies.create = …`, `foodSheetBodies.scan = …`
  - App actions: `foodOpen(kind)`, `foodClose()`, `foodQuery(v)`, `foodListMode(m)`, `foodPickResult(i)`, `foodPickFood(food)`, `foodAmt(field, value)`, `foodLogSave()`, `foodQuickSave()`, `foodEditEntry(id)`, `foodDelEntry(id)`, `foodDayShift(n)`, `foodDayToday()`, `foodScan()` (stub until Task 7)
  - Element ids: `#fdPrev #fdNext #fdAdd #fdScan #fdSheet #fdQuery #fdResults #fdQuickLink #faQty #faUnit #faTime #faPreview #faSave #fqName #fqKcal #fqProt #fqCarb #fqFat #fqFib #fqTime #fqSave`

- [ ] **Step 1: Write the failing smoke tests** (insert above `# --- tests above this line ---`)

```python
@test
def log_recent_food_on_today(pw, url):
    with app(pw, url, base(foods=[EGG])) as pg:
        pg.click("#fdAdd")
        pg.click("#fdResults .fd-res >> nth=0")
        pg.fill("#faQty", "2"); pg.select_option("#faUnit", "p0")
        assert "143" in pg.inner_text("#faPreview")
        pg.click("#faSave")
        s = stored(pg); e = s["foodLog"][0]
        assert e["date"] == today(pg) and e["kcal"] == 143 and e["label"] == "2 × large" and e["grams"] == 100
        assert e["qty"] == 2 and e["unit"] == "p0"
        row = [r for r in s["nutrition"] if r["date"] == today(pg)][0]
        assert row["source"] == "log" and row["kcal"] == 143
        assert s["foods"][0]["uses"] == 4
        assert pg.locator("#fdSheet").count() == 0
        assert "Egg, whole" in pg.inner_text("#view")

@test
def search_box_keeps_focus_while_typing(pw, url):
    with app(pw, url, base(foods=[EGG])) as pg:
        pg.click("#fdAdd")
        pg.keyboard.type("egg", delay=50)
        assert pg.input_value("#fdQuery") == "egg"
        assert pg.evaluate("document.activeElement.id") == "fdQuery"
        assert "Egg, whole" in pg.inner_text("#fdResults")

@test
def quick_add_on_yesterday_including_zero_calories(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdPrev")
        y = pg.evaluate("shiftISO(todayISO(), -1)")
        pg.click("#fdAdd"); pg.click("#fdQuickLink")
        pg.fill("#fqName", "Black coffee"); pg.fill("#fqKcal", "0"); pg.click("#fqSave")
        pg.click("#fdAdd"); pg.click("#fdQuickLink")
        pg.fill("#fqKcal", "500"); pg.fill("#fqProt", "30"); pg.click("#fqSave")
        s = stored(pg)
        assert [e["date"] for e in s["foodLog"]] == [y, y]
        assert s["foodLog"][0]["kcal"] == 0 and s["foodLog"][0]["name"] == "Black coffee"
        assert s["foodLog"][1]["name"] == "Quick add"
        assert [(r["date"], r["kcal"]) for r in s["nutrition"]] == [(y, 500)]
        pg.click("#fdNext")
        assert pg.evaluate("ui.foodDay") == today(pg)
        assert pg.locator("#fdNext").is_disabled()  # cannot go past today
        pg.evaluate("App.foodDayShift(1)")
        assert pg.evaluate("ui.foodDay") == today(pg)

@test
def quick_add_requires_calories(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdAdd"); pg.click("#fdQuickLink"); pg.click("#fqSave")
        assert stored(pg)["foodLog"] == [] and pg.locator("#fdSheet").count() == 1

@test
def edit_then_delete_entry(pw, url):
    with app(pw, url, base(foods=[EGG])) as pg:
        pg.click("#fdAdd"); pg.click("#fdResults .fd-res >> nth=0")
        pg.fill("#faQty", "1"); pg.select_option("#faUnit", "p0"); pg.click("#faSave")
        eid = stored(pg)["foodLog"][0]["id"]
        pg.click(".fd-row >> nth=0")
        assert pg.input_value("#faQty") == "1" and pg.input_value("#faUnit") == "p0"
        pg.fill("#faQty", "3"); pg.click("#faSave")
        s = stored(pg)
        assert len(s["foodLog"]) == 1 and s["foodLog"][0]["id"] == eid and s["foodLog"][0]["kcal"] == 215
        assert s["foods"][0]["uses"] == 4  # editing doesn't count as a new use
        pg.click(".fd-row >> nth=0")
        pg.click("#fdSheet button.del"); pg.click("#fdSheet button.del")
        s = stored(pg)
        assert s["foodLog"] == [] and s["nutrition"] == []

@test
def edit_quick_add_entry(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdAdd"); pg.click("#fdQuickLink"); pg.fill("#fqKcal", "400"); pg.click("#fqSave")
        pg.click(".fd-row >> nth=0")
        assert pg.input_value("#fqKcal") == "400"
        pg.fill("#fqKcal", "450"); pg.click("#fqSave")
        s = stored(pg)
        assert len(s["foodLog"]) == 1 and s["foodLog"][0]["kcal"] == 450 and s["nutrition"][0]["kcal"] == 450
```

Note: 3 large eggs = 150 g → 143 × 1.5 = 214.5 → `Math.round` → 215.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/ui_smoke.py`
Expected: the six new tests FAIL (`#fdAdd` not found); the Task 4 tests still pass.

- [ ] **Step 3: Add CSS** — paste inside `<style>`, just before `</style>`:

```css
  .fsheet{position:fixed;inset:0;z-index:20;background:rgba(0,0,0,0.45);display:flex;align-items:flex-end}
  .fsheet .panel{background:var(--paper);width:100%;max-width:560px;margin:0 auto;max-height:88vh;overflow-y:auto;border-radius:16px 16px 0 0;padding:10px 14px calc(18px + env(safe-area-inset-bottom))}
  .fd-x{background:none;border:none;color:var(--sub);font-size:18px;padding:4px 8px;cursor:pointer}
  .fd-nav{background:none;border:1px solid var(--line);border-radius:8px;width:40px;height:34px;font-size:20px;line-height:1;color:var(--ink);cursor:pointer}
  .fd-nav:disabled{opacity:.3}
  .fd-date{background:none;border:none;font-weight:700;font-size:15px;color:var(--ink);cursor:pointer}
  .fd-row{display:grid;grid-template-columns:48px 1fr auto;gap:8px;align-items:baseline;width:100%;text-align:left;padding:9px 0;background:none;border:none;border-bottom:1px solid var(--grid);color:var(--ink);cursor:pointer;font-size:14px;font-family:var(--body)}
  .fd-row .t,.fd-row .k{font-family:var(--mono);font-size:12px;color:var(--sub)}
  .fd-row .a{color:var(--sub);font-size:12px}
  .fd-res .meta{display:block;font-family:var(--mono);font-size:11px;color:var(--sub);margin-top:2px}
  .fd-tag{display:inline-block;font-family:var(--mono);font-size:9px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:6px;color:var(--sub);vertical-align:middle}
  .linkbtn{background:none;border:none;color:var(--pull);font-weight:600;font-size:14px;cursor:pointer;padding:6px}
```

- [ ] **Step 4: Add the rendering functions** directly after `nutritionSettingsHTML()`

```js
function foodEntriesFor(date){
  return data.foodLog.filter(e => e.date === date).sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
}
function foodDayCardHTML(){
  const date = ui.foodDay, s = data.settings, today = todayISO();
  const entries = foodEntriesFor(date);
  const t = dayTotals(entries);
  const label = date === today ? "Today" : date === shiftISO(today, -1) ? "Yesterday" : prettyDate(date);
  const remain = s.kcalTarget ? s.kcalTarget - t.kcal : null;
  return `<div class="card" style="border-left:4px solid var(--pull)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <button class="fd-nav" id="fdPrev" onclick="App.foodDayShift(-1)" aria-label="Previous day">‹</button>
      <button class="fd-date" onclick="App.foodDayToday()">${esc(label)}</button>
      <button class="fd-nav" id="fdNext" onclick="App.foodDayShift(1)" aria-label="Next day" ${date >= today ? "disabled" : ""}>›</button>
    </div>
    <div class="stats" style="margin-bottom:6px">
      <div class="stat"><div class="k">eaten</div><div class="v" style="color:${kcalColor(t.kcal)}">${t.kcal}</div></div>
      ${remain != null ? `<div class="stat"><div class="k">${remain >= 0 ? "left" : "over"}</div><div class="v" style="color:${remain >= 0 ? "#2B8A3E" : "var(--danger)"}">${Math.abs(remain)}</div></div>` : ""}
      <div class="stat"><div class="k">protein</div><div class="v">${t.protein}${s.proteinTarget ? `<span style="color:var(--sub);font-size:12px">/${s.proteinTarget}</span>` : ""}g</div></div>
    </div>
    <div style="font-family:var(--mono);font-size:11px;color:var(--sub);margin-bottom:6px">C${t.carbs} · F${t.fat} · fiber ${t.fiber}</div>
    ${entries.length ? entries.map(e => `<button class="fd-row" onclick="App.foodEditEntry('${e.id}')">
        <span class="t">${fmtTime(e.time)}</span>
        <span class="n">${esc(e.name)}${e.label ? ` <span class="a">${esc(e.label)}</span>` : ""}</span>
        <span class="k">${e.kcal} kcal · P${Math.round(e.protein)}</span></button>`).join("")
      : `<div class="muted" style="padding:8px 0">Nothing logged ${date === today ? "yet today" : "this day"}.</div>`}
    <div style="display:grid;grid-template-columns:2fr 1fr;gap:8px;margin-top:12px">
      <button class="btn" id="fdAdd" style="background:var(--pull);color:#fff" onclick="App.foodOpen('search')">+ Add food</button>
      <button class="btn" id="fdScan" style="background:transparent;border:1px solid var(--pull);color:var(--pull)" onclick="App.foodScan()">Scan</button>
    </div>
  </div>`;
}
function foodDefaultServing(f){
  const p = (f.portions || [])[0];
  const grams = p ? p.grams : 100;
  return { label: p ? p.label : "100 g", kcal: macrosFor(f.per100g, grams).kcal };
}
function foodResultRowHTML(f, i){
  const d = foodDefaultServing(f);
  const tag = f.saved ? "saved" : f.source === "usda" ? "USDA" : f.source === "off" ? "OFF" : "custom";
  return `<button class="pick fd-res" onclick="App.foodPickResult(${i})">${esc(f.name)}<span class="fd-tag">${tag}</span>
    <span class="meta">${f.brand ? esc(f.brand) + " · " : ""}${d.kcal} kcal / ${esc(d.label)}</span></button>`;
}
function foodRemoteStatusHTML(){
  const st = ui.foodRemote.q === ui.foodQuery.trim() ? ui.foodRemote.status : "";
  if (st === "loading") return `<div class="note" style="margin:10px 0">Searching USDA and Open Food Facts…</div>`;
  if (st === "offline") return `<div class="note" style="margin:10px 0">Offline — showing saved foods</div>`;
  if (st === "partial") return `<div class="note" style="margin:10px 0">One database didn't respond — showing what came back</div>`;
  if (st === "nokey") return `<div class="note" style="margin:10px 0">USDA search is off — <button class="linkbtn" style="font-size:11px;padding:0" onclick="App.foodGoUsdaKey()">add your free key in Settings</button></div>`;
  return "";
}
function foodResultsHTML(){
  const q = ui.foodQuery.trim();
  if (!q){
    ui.foodResults = recentFoods(data.foods, ui.foodListMode).map(f => ({ ...f, saved: true }));
    return `<div class="seg" style="margin:10px 0 4px">
        <button class="${ui.foodListMode === "recent" ? "on" : ""}" onclick="App.foodListMode('recent')">Recent</button>
        <button class="${ui.foodListMode === "frequent" ? "on" : ""}" onclick="App.foodListMode('frequent')">Frequent</button>
      </div>` + (ui.foodResults.length ? ui.foodResults.map(foodResultRowHTML).join("")
        : `<div class="muted" style="padding:12px 0">Foods you log show up here.</div>`);
  }
  const r = ui.foodRemote.q === q ? ui.foodRemote : { usda: [], off: [] };
  ui.foodResults = mergeResults(searchSaved(data.foods, q), r.usda, r.off);
  return (ui.foodResults.length ? ui.foodResults.map(foodResultRowHTML).join("")
      : (q.length < 3 ? `<div class="muted" style="padding:12px 0">Keep typing to search the databases…</div>` : ""))
    + foodRemoteStatusHTML();
}
function updateFoodResults(){ const el = $("#fdResults"); if (el) el.innerHTML = foodResultsHTML(); }
function foodPreviewHTML(){
  const f = ui.foodPick, a = ui.foodAmt;
  const g = gramsFor(f, a.qty, a.unit);
  if (!g) return `<div class="note">Enter an amount</div>`;
  const m = macrosFor(f.per100g, g);
  return `<div class="stats">${stat("kcal", m.kcal)}${stat("protein", m.protein + "g")}${stat("carbs", m.carbs + "g")}${stat("fat", m.fat + "g")}</div>
    <div class="note" style="text-align:left;margin-top:6px">${g} g · fiber ${m.fiber} g</div>`;
}
const foodSheetBodies = {
  search(){
    return `<div class="lbl">Add food · ${ui.foodDay === todayISO() ? "today" : esc(shortDate(ui.foodDay))}</div>
      <input id="fdQuery" value="${esc(ui.foodQuery)}" placeholder="Search foods…" autocomplete="off" autocorrect="off" oninput="App.foodQuery(this.value)">
      <div id="fdResults">${foodResultsHTML()}</div>
      <div id="fdLinks" style="display:flex;gap:16px;justify-content:center;margin-top:12px">
        <button class="linkbtn" id="fdQuickLink" onclick="App.foodOpen('quick')">Quick add</button>
      </div>`;
  },
  amount(){
    const f = ui.foodPick, a = ui.foodAmt;
    return `<div class="lbl">${ui.foodEdit ? "Edit entry" : "Log food"}</div>
      <div style="font-weight:700;font-size:16px">${esc(f.name)}</div>
      ${f.brand ? `<div style="font-size:13px;color:var(--sub)">${esc(f.brand)}</div>` : ""}
      <div style="display:grid;grid-template-columns:1fr 1.6fr;gap:8px;margin:12px 0">
        <input class="mono" id="faQty" type="number" inputmode="decimal" step="any" value="${esc(a.qty)}" oninput="App.foodAmt('qty', this.value)">
        <select id="faUnit" onchange="App.foodAmt('unit', this.value)">${unitOptions(f).map(o =>
          `<option value="${o.key}" ${o.key === a.unit ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>
      </div>
      <div class="lbl">Time</div>
      <input id="faTime" type="time" value="${esc(a.time)}" onchange="App.foodAmt('time', this.value)" style="margin-bottom:12px">
      <div id="faPreview">${foodPreviewHTML()}</div>
      <button class="btn" id="faSave" style="background:var(--pull);color:#fff;margin-top:14px" onclick="App.foodLogSave()">${ui.foodEdit ? "Save" : "Log"}</button>
      ${ui.foodEdit ? `<div style="text-align:center;margin-top:12px">${delBtn("FL" + ui.foodEdit, `App.foodDelEntry('${ui.foodEdit}')`, "delete entry")}</div>` : ""}`;
  },
  quick(){
    const p = ui.foodQuickPrefill || {};
    const v = k => p[k] == null ? "" : esc(p[k]);
    const num = (id, label, k) => `<div><div class="lbl">${label}</div><input class="mono" id="${id}" type="number" inputmode="decimal" step="any" value="${v(k)}"></div>`;
    return `<div class="lbl">${ui.foodEdit ? "Edit quick add" : "Quick add"}</div>
      <div class="lbl" style="margin-top:8px">Name</div>
      <input id="fqName" value="${p.name && p.name !== "Quick add" ? esc(p.name) : ""}" placeholder="Quick add" autocomplete="off" style="margin-bottom:8px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
        ${num("fqKcal", "Calories", "kcal")}${num("fqProt", "Protein (g)", "protein")}
        ${num("fqCarb", "Carbs (g)", "carbs")}${num("fqFat", "Fat (g)", "fat")}${num("fqFib", "Fiber (g)", "fiber")}
      </div>
      <div class="lbl">Time</div>
      <input id="fqTime" type="time" value="${esc(p.time || hhmmOf(new Date()))}" style="margin-bottom:12px">
      <button class="btn" id="fqSave" style="background:var(--pull);color:#fff" onclick="App.foodQuickSave()">${ui.foodEdit ? "Save" : "Log"}</button>
      ${ui.foodEdit ? `<div style="text-align:center;margin-top:12px">${delBtn("FL" + ui.foodEdit, `App.foodDelEntry('${ui.foodEdit}')`, "delete entry")}</div>` : ""}`;
  },
};
function foodSheetHTML(){
  const body = ui.foodSheet && foodSheetBodies[ui.foodSheet];
  if (!body) return "";
  return `<div class="fsheet" onclick="if(event.target===this)App.foodClose()"><div class="panel" id="fdSheet">
    <div style="display:flex;justify-content:flex-end"><button class="fd-x" onclick="App.foodClose()" aria-label="Close">✕</button></div>
    ${body()}</div></div>`;
}
```

- [ ] **Step 5: Replace the top of `renderFood()`**

Replace everything from `let html = \`<div class="card" style="border-left:4px solid var(--pull)">` (the "Import from Cronometer" card) through the closing `}` of the `if (ui.foodManualOpen){ … }` block with:
```js
  let html = foodDayCardHTML();
```
Change the chart's empty message from `"Import a Cronometer export or log two days to draw a trend. Chart shows the last 30 logged days."` to `"Log foods on two days to draw a trend. Chart shows the last 30 logged days."`.

Replace the final `return html;` of `renderFood()` with:
```js
  return html + foodSheetHTML();
```

- [ ] **Step 6: Replace the old food actions in `App`**

Delete `toggleFoodManual(){…},` and the whole `saveFood(){…},` method. Remove `foodManualOpen: false, ` from the `ui` object. Then add these methods in the `// food` section of `App`:

```js
  foodOpen(kind){
    ui.foodSheet = kind; ui.confirmKey = null;
    if (kind === "search"){ ui.foodQuery = ""; ui.foodFocus = true; ui.foodEdit = null; }
    if (kind === "quick"){ ui.foodQuickPrefill = null; ui.foodEdit = null; }
    render();
  },
  foodClose(){ ui.foodSheet = null; ui.foodEdit = null; ui.foodPrefill = null; ui.foodEditFoodId = null; ui.confirmKey = null; render(); },
  foodQuery(v){ ui.foodQuery = v; updateFoodResults(); },
  foodListMode(m){ ui.foodListMode = m; updateFoodResults(); },
  foodPickResult(i){ const f = ui.foodResults[i]; if (f) App.foodPickFood(f); },
  foodPickFood(f){
    const first = unitOptions(f)[0];
    ui.foodPick = f; ui.foodEdit = null;
    ui.foodAmt = { qty: first.key === "g" ? "100" : "1", unit: first.key, time: hhmmOf(new Date()) };
    ui.foodSheet = "amount"; render();
  },
  foodAmt(field, value){
    ui.foodAmt[field] = value;
    if (field !== "time"){ const el = $("#faPreview"); if (el) el.innerHTML = foodPreviewHTML(); }
  },
  foodLogSave(){
    const a = ui.foodAmt, picked = ui.foodPick;
    const grams = gramsFor(picked, a.qty, a.unit);
    if (!(grams > 0)){ toast("Enter an amount", true); return; }
    if (!/^\d{2}:\d{2}$/.test(a.time || "")){ toast("Enter a time", true); return; }
    const editing = ui.foodEdit ? data.foodLog.find(e => e.id === ui.foodEdit) : null;
    const food = editing ? picked : upsertFood(picked);
    const fields = { time: a.time, name: food.name, grams, qty: r1(fNum(a.qty)), unit: a.unit,
      label: amountLabel(food, a.qty, a.unit), ...macrosFor(food.per100g, grams) };
    let date;
    if (editing){ Object.assign(editing, fields); date = editing.date; }
    else {
      date = ui.foodDay;
      data.foodLog.push({ id: uid(), date, foodId: food.id, ...fields });
      food.uses = (food.uses || 0) + 1; food.lastUsed = Date.now();
    }
    refreshFoodDay(date); save();
    ui.foodSheet = null; ui.foodEdit = null; ui.foodPick = null;
    toast(editing ? "Entry updated ✓" : `Logged ${fields.kcal} kcal ✓`); render();
  },
  foodQuickSave(){
    const val = id => ($(id)?.value ?? "").trim();
    const kcalStr = val("#fqKcal");
    if (kcalStr === "" || !(parseFloat(kcalStr) >= 0)){ toast("Enter calories", true); return; }
    const time = val("#fqTime");
    if (!/^\d{2}:\d{2}$/.test(time)){ toast("Enter a time", true); return; }
    const m = id => r1(Math.max(0, fNum(val(id))));
    const fields = { time, foodId: null, name: val("#fqName") || "Quick add", grams: null, qty: null, unit: null, label: "",
      kcal: Math.round(parseFloat(kcalStr)), protein: m("#fqProt"), carbs: m("#fqCarb"), fat: m("#fqFat"), fiber: m("#fqFib") };
    const editing = ui.foodEdit ? data.foodLog.find(e => e.id === ui.foodEdit) : null;
    let date;
    if (editing){ Object.assign(editing, fields); date = editing.date; }
    else { date = ui.foodDay; data.foodLog.push({ id: uid(), date, ...fields }); }
    refreshFoodDay(date); save();
    ui.foodSheet = null; ui.foodEdit = null; ui.foodQuickPrefill = null;
    toast(editing ? "Entry updated ✓" : `Logged ${fields.kcal} kcal ✓`); render();
  },
  foodEditEntry(id){
    const e = data.foodLog.find(x => x.id === id); if (!e) return;
    ui.foodEdit = id; ui.confirmKey = null;
    if (e.grams == null){ ui.foodQuickPrefill = { ...e }; ui.foodSheet = "quick"; render(); return; }
    const food = foodForEntry(e);
    const ok = unitOptions(food).some(o => o.key === e.unit) && e.qty != null;
    ui.foodPick = food;
    ui.foodAmt = { qty: String(ok ? e.qty : e.grams), unit: ok ? e.unit : "g", time: e.time };
    ui.foodSheet = "amount"; render();
  },
  foodDelEntry(id){
    if (!confirmDel("FL" + id)) return;
    const e = data.foodLog.find(x => x.id === id); if (!e) return;
    data.foodLog = data.foodLog.filter(x => x.id !== id);
    refreshFoodDay(e.date); save();
    ui.foodSheet = null; ui.foodEdit = null; toast("Entry deleted"); render();
  },
  foodDayShift(n){ const d = shiftISO(ui.foodDay, n); if (d > todayISO()) return; ui.foodDay = d; render(); },
  foodDayToday(){ ui.foodDay = todayISO(); render(); },
  foodScan(){ toast("Barcode scanning arrives in the next step", true); },
```

`foodForEntry` can return a stand-in with no portions; `unitOptions` then still offers `g`/`oz`, so the `ok` fallback to grams always has a valid unit.

- [ ] **Step 7: Close the sheet on tab change, and focus the search box**

At the start of `App.tab(t){`, insert:
```js
    if (ui.foodSheet){ ui.foodSheet = null; ui.foodEdit = null; }
```
In `afterRender()`, add after the `#clsSearch` focus lines:
```js
  const fq = $("#fdQuery");
  if (fq && ui.foodFocus){ fq.focus(); ui.foodFocus = false; }
```

- [ ] **Step 8: Run the smoke tests and unit tests**

Run: `python3 tests/ui_smoke.py && node --test tests/*.test.mjs`
Expected: `0 failed`; unit tests PASS.

- [ ] **Step 9: Take screenshots and check them by eye**

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, "tests")
from ui_smoke import *
srv, url = start_server()
with sync_playwright() as pw:
    with app(pw, url, base(foods=[EGG])) as pg:
        pg.screenshot(path="/tmp/food-day.png")
        pg.click("#fdAdd"); pg.screenshot(path="/tmp/food-search.png")
        pg.click("#fdResults .fd-res >> nth=0"); pg.screenshot(path="/tmp/food-amount.png")
srv.shutdown()
EOF
```
Open each PNG with the Read tool. Check: nothing overflows 390 px, the sheet covers the nav bar, and text is readable. Fix any layout problem before committing.

- [ ] **Step 10: Commit**

```bash
git add index.html tests/ui_smoke.py
git commit -m "Food tab: day log, add sheet, amounts, quick add, edit and delete" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 6: Remote search and USDA key setting

**Gate:** Do not start until Landon has reported the Task 1 probe result.
- All three lines OK: continue.
- Any line FAILED: **stop**. Tell Landon which API is blocked and propose a small proxy (for example a free Cloudflare Worker). Wait for his decision before writing anything.

**Files:**
- Modify: `index.html` — the app-level food section (after `foodSheetHTML`), `nutritionSettingsHTML()` (`<!-- usda-key -->` marker), `App`
- Modify: `tests/ui_smoke.py`

**Interfaces:**
- Consumes: `usdaSearchURL`, `offSearchURL`, `parseUsdaFood`, `parseOffProduct` (Task 3); `updateFoodResults`, `foodRemoteStatusHTML` (Task 5).
- Produces:
  - `fetchJSON(url, signal?) → Promise<object>` (8-second timeout, throws on non-2xx)
  - `scheduleRemoteSearch(q) → void`, `runRemoteSearch(q) → Promise<void>`
  - `data.settings.usdaKey: string`
  - App actions: `setUsdaKey(v)`, `foodGoUsdaKey()`; `App.foodQuery` now also schedules the remote search
  - Element id: `#usdaKey`

- [ ] **Step 1: Write the failing smoke tests** (above the marker)

```python
@test
def remote_search_merges_and_ranks(pw, url):
    seed = base(foods=[EGG]); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed) as pg:
        pg.click("#fdAdd"); pg.keyboard.type("yogurt")
        pg.wait_for_selector("#fdResults :text('Nutella')")
        names = pg.locator("#fdResults .fd-res").all_inner_texts()
        joined = "\n".join(names)
        assert "Greek Nonfat Yogurt, Plain" in joined and "Total 0% Greek Yogurt" not in joined
        assert "Mystery bar" not in joined
        assert names[0].startswith("Chicken") or names[0].startswith("Egg, whole, raw")
        pg.click("#fdResults .fd-res:has-text('Nutella')")
        pg.select_option("#faUnit", "p0"); pg.click("#faSave")
        s = stored(pg)
        assert s["foodLog"][0]["kcal"] == 81 and any(f["name"] == "Nutella" for f in s["foods"])

@test
def search_without_key_uses_off_and_explains(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdAdd"); pg.keyboard.type("nutella")
        pg.wait_for_selector("#fdResults :text('Nutella')")
        assert "add your free key in Settings" in pg.inner_text("#fdResults")
        assert "Greek Nonfat Yogurt" not in pg.inner_text("#fdResults")
        pg.click("#fdResults .linkbtn")
        assert pg.evaluate("ui.tab") == "settings" and pg.locator("#usdaKey").count() == 1
        pg.fill("#usdaKey", "  KEY123 "); pg.dispatch_event("#usdaKey", "change")
        assert stored(pg)["settings"]["usdaKey"] == "KEY123"

@test
def offline_search_shows_saved_foods(pw, url):
    seed = base(foods=[EGG]); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed, offline=True) as pg:
        pg.click("#fdAdd"); pg.keyboard.type("egg")
        pg.wait_for_selector("#fdResults :text('Offline')")
        assert "Egg, whole" in pg.inner_text("#fdResults")

@test
def stale_search_result_is_ignored(pw, url):
    seed = base(); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed) as pg:
        pg.click("#fdAdd")
        pg.evaluate("ui.foodQuery = 'chicken'")
        pg.evaluate("runRemoteSearch('egg')")  # finishes after the user has moved on
        assert pg.evaluate("ui.foodRemote.q") != "egg"
```

Nutella: 15 g × 538.2 kcal/100 g = 80.7 → 81.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/ui_smoke.py remote_search_merges_and_ranks search_without_key_uses_off_and_explains offline_search_shows_saved_foods stale_search_result_is_ignored`
Expected: all four FAIL.

- [ ] **Step 3: Add the network code** after `foodSheetHTML()`

```js
async function fetchJSON(url, signal){
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  const relay = () => ctl.abort();
  signal?.addEventListener("abort", relay);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", relay); }
}
let foodSearchTimer = null, foodSearchCtl = null;
function scheduleRemoteSearch(q){
  clearTimeout(foodSearchTimer);
  if (foodSearchCtl){ foodSearchCtl.abort(); foodSearchCtl = null; }
  q = q.trim();
  if (q.length < 3){ ui.foodRemote = { q: "", usda: [], off: [], status: "" }; return; }
  foodSearchTimer = setTimeout(() => runRemoteSearch(q), 500);
}
async function runRemoteSearch(q){
  if (!navigator.onLine){ ui.foodRemote = { q, usda: [], off: [], status: "offline" }; updateFoodResults(); return; }
  const ctl = new AbortController(); foodSearchCtl = ctl;
  const key = (data.settings.usdaKey || "").trim();
  if (ui.foodQuery.trim() === q){ ui.foodRemote = { q, usda: [], off: [], status: "loading" }; updateFoodResults(); }
  const usdaP = key
    ? fetchJSON(usdaSearchURL(q, key), ctl.signal).then(j => (j.foods || []).map(parseUsdaFood).filter(Boolean))
    : Promise.resolve(null);
  const offP = fetchJSON(offSearchURL(q), ctl.signal).then(j => (j.products || []).map(parseOffProduct).filter(Boolean));
  const [u, o] = await Promise.allSettled([usdaP, offP]);
  if (ctl.signal.aborted || ui.foodQuery.trim() !== q) return; // a newer search replaced this one
  if (foodSearchCtl === ctl) foodSearchCtl = null;
  const usda = u.status === "fulfilled" && u.value ? u.value : [];
  const off = o.status === "fulfilled" ? o.value : [];
  const usdaFailed = u.status === "rejected", offFailed = o.status === "rejected";
  const status = (offFailed && (usdaFailed || !key)) ? "offline"
    : !key ? "nokey"
    : (usdaFailed || offFailed) ? "partial" : "done";
  ui.foodRemote = { q, usda, off, status };
  updateFoodResults();
}
```

- [ ] **Step 4: Trigger the search from typing**

Replace `foodQuery(v){ ui.foodQuery = v; updateFoodResults(); },` in `App` with:
```js
  foodQuery(v){ ui.foodQuery = v; scheduleRemoteSearch(v); updateFoodResults(); },
```

- [ ] **Step 5: Add the key field and its actions**

In `nutritionSettingsHTML()`, replace `<!-- usda-key -->` with:
```js
    <div style="font-size:14px;font-weight:600;margin-bottom:4px">USDA food database key</div>
    <div style="font-size:13px;color:var(--sub);margin-bottom:8px;line-height:1.45">Free key that turns on USDA results in food search. Open Food Facts works without one.</div>
    <input id="usdaKey" class="mono" value="${esc(data.settings.usdaKey || "")}" placeholder="paste your key" autocomplete="off" autocapitalize="off" spellcheck="false" onchange="App.setUsdaKey(this.value)">
    <a class="weblink pull" href="https://api.data.gov/signup/" target="_blank" rel="noopener">Get a free key <span class="ext">↗</span></a>
    <div style="height:1px;background:var(--grid);margin:14px 0"></div>
```
Add to `App`:
```js
  setUsdaKey(v){ data.settings.usdaKey = String(v || "").trim(); save(); toast(data.settings.usdaKey ? "USDA key saved ✓" : "USDA key removed"); },
  foodGoUsdaKey(){
    ui.foodSheet = null; ui.tab = "settings"; render();
    const el = $("#usdaKey"); if (el){ el.scrollIntoView({ block: "center" }); el.focus(); }
  },
```

- [ ] **Step 6: Run all tests**

Run: `python3 tests/ui_smoke.py && node --test tests/*.test.mjs`
Expected: `0 failed`; unit tests PASS.

- [ ] **Step 7: Commit**

```bash
git add index.html tests/ui_smoke.py
git commit -m "Food search: USDA and Open Food Facts with stale-request guard" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 7: Barcode scanning and manual food creation

**Files:**
- Modify: `index.html` — core block (`prefillFrom`), app-level food section, `foodSheetBodies`, CSS, `App`, `App.tab`
- Modify: `tests/food.test.mjs`, `tests/ui_smoke.py`

**Interfaces:**
- Consumes: Task 2/3 core, `fetchJSON` (Task 6), `foodSheetBodies`, `App.foodPickFood` (Task 5).
- Produces:
  - Core: `prefillFrom(food, barcode) → {name, brand, barcode, servingLabel, servingGrams, kcal, protein, carbs, fat, fiber}` (`kcal` is `""` when unknown; `servingGrams` is `""` for serving-only foods)
  - `loadZxing() → Promise`, `startScan() → Promise`, `stopScan() → void`, `handleBarcode(raw) → Promise`
  - `foodSheetBodies.scan`, `foodSheetBodies.create`
  - App actions: `foodScan()` (real), `foodCreateSave()`
  - Element ids: `#fdScanVideo #fdCreateLink #fcName #fcBrand #fcServing #fcGrams #fcKcal #fcProt #fcCarb #fcFat #fcFib #fcSave`

- [ ] **Step 1: Write the failing unit test** (append to `tests/food.test.mjs`)

```js
test("prefillFrom gives per-serving values for the first portion", () => {
  const p = C.prefillFrom({ name: "Bar", brand: "B", per100g: { kcal: 400, protein: 30, carbs: 40, fat: 10, fiber: 5 },
    portions: [{ label: "1 bar", grams: 60 }], servingOnly: false }, "0123");
  assert.deepEqual(p, { name: "Bar", brand: "B", barcode: "123", servingLabel: "1 bar", servingGrams: 60,
    kcal: 240, protein: 18, carbs: 24, fat: 6, fiber: 3 });
});
test("prefillFrom falls back to 100 g, leaves unknown calories blank, blanks grams for serving-only", () => {
  const p = C.prefillFrom({ name: "X", brand: "", per100g: { kcal: null, protein: 20, carbs: 0, fat: 0, fiber: 0 }, portions: [] }, "");
  assert.equal(p.servingLabel, "100 g"); assert.equal(p.servingGrams, 100); assert.equal(p.kcal, ""); assert.equal(p.protein, 20);
  const s = C.prefillFrom({ name: "W", per100g: { kcal: 900, protein: 60, carbs: 0, fat: 0, fiber: 0 },
    portions: [{ label: "1 plate", grams: 100 }], servingOnly: true }, "");
  assert.equal(s.servingGrams, ""); assert.equal(s.kcal, 900);
});
```

- [ ] **Step 2: Write the failing smoke tests** (above the marker)

```python
@test
def scanned_known_product_logs_directly(pw, url):
    with app(pw, url, base()) as pg:
        pg.evaluate("handleBarcode('0049000028911')")
        assert pg.evaluate("ui.foodSheet") == "amount"
        assert "Diet Coke" in pg.inner_text("#fdSheet")
        pg.click("#faSave")
        e = stored(pg)["foodLog"][0]
        assert e["kcal"] == 0 and e["name"] == "Diet Coke"
        pg.evaluate("handleBarcode('049000028911')")  # same product, UPC-A padding
        assert pg.evaluate("ui.foodSheet") == "amount" and pg.evaluate("ui.foodPick.id") == stored(pg)["foods"][0]["id"]

@test
def unknown_barcode_creates_food_and_rescans_offline(pw, url):
    with app(pw, url, base()) as pg:
        pg.evaluate("handleBarcode('0000000000017')")
        assert pg.evaluate("ui.foodSheet") == "create"
        assert "17" in pg.inner_text("#fdSheet")
        pg.click("#fcSave")  # blank name
        assert pg.evaluate("ui.foodSheet") == "create"
        pg.fill("#fcName", "Gas station bar"); pg.fill("#fcServing", "1 bar"); pg.fill("#fcGrams", "60")
        pg.fill("#fcKcal", "250"); pg.fill("#fcProt", "20"); pg.click("#fcSave")
        assert pg.evaluate("ui.foodSheet") == "amount"
        pg.click("#faSave")
        s = stored(pg)
        assert s["foodLog"][0]["kcal"] == 250 and s["foods"][0]["barcode"] == "17"
        pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith("http://127.0.0.1") else r.abort())
        pg.evaluate("handleBarcode('17')")
        assert pg.evaluate("ui.foodSheet") == "amount" and "Gas station bar" in pg.inner_text("#fdSheet")

@test
def create_food_from_search_link(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdAdd"); pg.click("#fdCreateLink")
        pg.fill("#fcName", "Mom's lasagna"); pg.fill("#fcKcal", "700"); pg.click("#fcSave")
        opts = pg.locator("#faUnit option").all_inner_texts()
        assert opts == ["1 serving"]
        pg.fill("#faQty", "1.5"); pg.click("#faSave")
        assert stored(pg)["foodLog"][0]["kcal"] == 1050

@test
def scanner_load_failure_returns_to_search(pw, url):
    with app(pw, url, base(), offline=True) as pg:
        pg.click("#fdScan")
        pg.wait_for_function("ui.foodSheet === 'search'")
        assert pg.locator("#fdQuery").count() == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `node --test tests/food.test.mjs; python3 tests/ui_smoke.py scanned_known_product_logs_directly unknown_barcode_creates_food_and_rescans_offline create_food_from_search_link scanner_load_failure_returns_to_search`
Expected: the two new unit tests and four smoke tests FAIL.

- [ ] **Step 4: Add `prefillFrom` to the core** (above `// @food-core-end`)

```js
function prefillFrom(food, barcode){
  const p = (food.portions || [])[0];
  const grams = p ? p.grams : 100;
  const m = macrosFor(food.per100g, grams);
  return { name: food.name || "", brand: food.brand || "", barcode: normBarcode(barcode || food.barcode),
    servingLabel: p ? p.label : "100 g", servingGrams: food.servingOnly ? "" : grams,
    kcal: food.per100g.kcal == null ? "" : m.kcal, protein: m.protein, carbs: m.carbs, fat: m.fat, fiber: m.fiber };
}
```
Run the collision check for `prefillFrom` (`grep -n -E "^(function|const|let) prefillFrom\b" index.html` → exactly one line).

- [ ] **Step 5: Add scanner CSS** (inside `<style>`)

```css
  .fd-scan{position:relative;width:100%;aspect-ratio:4/3;background:#000;border-radius:10px;overflow:hidden;margin:8px 0}
  .fd-scan video{width:100%;height:100%;object-fit:cover;display:block}
  .fd-scan .aim{position:absolute;left:12%;right:12%;top:42%;height:16%;border:2px solid rgba(255,255,255,.85);border-radius:8px}
```

- [ ] **Step 6: Add the scanner and lookup code** after `runRemoteSearch`

```js
const ZXING_URL = "https://cdn.jsdelivr.net/npm/@zxing/browser@0.2.1/umd/zxing-browser.min.js";
let zxingPromise = null, scanCtl = null;
function loadZxing(){
  if (window.ZXingBrowser) return Promise.resolve();
  if (zxingPromise) return zxingPromise;
  zxingPromise = new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = ZXING_URL; s.onload = () => res();
    s.onerror = () => { zxingPromise = null; rej(new Error("Couldn't load the scanner — check your signal")); };
    document.head.appendChild(s);
  });
  return zxingPromise;
}
function stopScan(){ try { scanCtl?.stop(); } catch (_) {} scanCtl = null; }
async function startScan(){
  try {
    await loadZxing();
    const video = $("#fdScanVideo");
    if (ui.foodSheet !== "scan" || !video) return;
    const reader = new ZXingBrowser.BrowserMultiFormatOneDReader();
    let done = false;
    scanCtl = await reader.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (result) => {
      if (!result || done) return;
      done = true; stopScan(); handleBarcode(result.getText());
    });
    if (ui.foodSheet !== "scan" || done) stopScan(); // sheet closed while the camera was starting
  } catch (err) {
    stopScan();
    const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
    ui.foodSheet = "search"; ui.foodQuery = ""; render();
    toast(denied ? "Camera access was blocked for this app" : (err.message || "Scanner failed"), true);
  }
}
async function handleBarcode(raw){
  const code = normBarcode(raw);
  if (!code){ ui.foodSheet = "search"; ui.foodQuery = ""; render(); toast("Couldn't read that barcode", true); return; }
  const saved = data.foods.find(f => f.barcode && f.barcode === code);
  if (saved){ App.foodPickFood(saved); return; }
  ui.foodSheet = "scan"; ui.scanStatus = `Looking up ${String(raw).trim()}…`; render();
  const complete = f => f && !f.incomplete && f.portions.length > 0;
  let off = null, usda = null;
  try { const j = await fetchJSON(offProductURL(raw)); if (j && j.status === 1 && j.product) off = parseOffProduct({ code: String(raw), ...j.product }); } catch (_) {}
  if (!complete(off) && (data.settings.usdaKey || "").trim()){
    try {
      const j = await fetchJSON(usdaSearchURL(code, data.settings.usdaKey.trim()));
      const hit = (j.foods || []).find(x => normBarcode(x.gtinUpc) === code);
      usda = hit ? parseUsdaFood(hit) : null;
    } catch (_) {}
  }
  if (ui.foodSheet !== "scan") return; // closed while looking up
  ui.scanStatus = "";
  const pick = complete(off) ? off : complete(usda) ? usda : null;
  if (pick){ App.foodPickFood(pick); return; }
  const partial = off || usda;
  ui.foodPrefill = partial ? prefillFrom(partial, code) : { barcode: code };
  ui.foodSheet = "create"; render();
  toast(partial ? "Found it, but some info is missing — check and save" : "Not found — enter it once and it'll scan next time");
}
```

- [ ] **Step 7: Add the scan and create sheets**

After the `foodSheetBodies` object literal, add:
```js
foodSheetBodies.scan = function(){
  return `<div class="lbl">Scan barcode</div>
    <div class="fd-scan"><video id="fdScanVideo" playsinline muted autoplay></video><div class="aim"></div></div>
    <div class="note">${esc(ui.scanStatus || "Point the camera at the barcode")}</div>
    <div style="text-align:center;margin-top:8px"><button class="linkbtn" onclick="App.foodOpen('search')">Search instead</button></div>`;
};
foodSheetBodies.create = function(){
  const p = ui.foodPrefill || {};
  const v = k => p[k] == null ? "" : esc(p[k]);
  const txt = (id, label, k, ph = "") => `<div><div class="lbl">${label}</div><input id="${id}" value="${v(k)}" placeholder="${ph}" autocomplete="off"></div>`;
  const num = (id, label, k) => `<div><div class="lbl">${label}</div><input class="mono" id="${id}" type="number" inputmode="decimal" step="any" value="${v(k)}"></div>`;
  return `<div class="lbl">${ui.foodEditFoodId ? "Edit food" : "Create food"}</div>
    <div style="display:grid;gap:8px;margin:8px 0">
      ${txt("fcName", "Name", "name")}
      ${txt("fcBrand", "Brand (optional)", "brand")}
      <div style="display:grid;grid-template-columns:1.4fr 1fr;gap:8px">
        ${txt("fcServing", "Serving", "servingLabel", "1 serving")}
        ${num("fcGrams", "Grams (optional)", "servingGrams")}
      </div>
      <div class="lbl" style="margin-top:4px">Per serving</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        ${num("fcKcal", "Calories", "kcal")}${num("fcProt", "Protein (g)", "protein")}
        ${num("fcCarb", "Carbs (g)", "carbs")}${num("fcFat", "Fat (g)", "fat")}${num("fcFib", "Fiber (g)", "fiber")}
      </div>
    </div>
    ${p.barcode ? `<div class="note">barcode ${esc(p.barcode)}</div>` : ""}
    <button class="btn" id="fcSave" style="background:var(--pull);color:#fff;margin-top:10px" onclick="App.foodCreateSave()">${ui.foodEditFoodId ? "Save food" : "Save & log"}</button>`;
};
```
In `foodSheetBodies.search`, add the Create link after the Quick add button inside `#fdLinks`:
```js
        <button class="linkbtn" id="fdCreateLink" onclick="App.foodOpen('create')">Create food</button>
```

- [ ] **Step 8: Wire the actions**

Replace the stub `foodScan(){ … },` in `App` with:
```js
  foodScan(){ ui.foodSheet = "scan"; ui.scanStatus = ""; ui.foodEdit = null; render(); startScan(); },
  foodCreateSave(){
    const val = id => $(id)?.value ?? "";
    let food;
    try {
      food = customFood({ name: val("#fcName"), brand: val("#fcBrand"), servingLabel: val("#fcServing"), servingGrams: val("#fcGrams"),
        kcal: val("#fcKcal"), protein: val("#fcProt"), carbs: val("#fcCarb"), fat: val("#fcFat"), fiber: val("#fcFib"),
        barcode: ui.foodPrefill?.barcode || "" });
    } catch (err) { toast(err.message, true); return; }
    const saved = toSavedFood(food, uid);
    data.foods.push(saved); save();
    ui.foodPrefill = null;
    App.foodPickFood(saved);
  },
```
In `App.foodOpen(kind)`, add:
```js
    if (kind === "create" && !ui.foodPrefill) ui.foodPrefill = {};
    if (kind !== "scan") stopScan();
```
In `App.foodClose()`, call `stopScan();` first. In `App.tab`, change the inserted line from Task 5 to:
```js
    if (ui.foodSheet){ stopScan(); ui.foodSheet = null; ui.foodEdit = null; }
```

- [ ] **Step 9: Run all tests**

Run: `node --test tests/*.test.mjs && python3 tests/ui_smoke.py`
Expected: all PASS, `0 failed`.

- [ ] **Step 10: Commit**

```bash
git add index.html tests/food.test.mjs tests/ui_smoke.py
git commit -m "Add barcode scanning and manual food creation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 8: My foods (edit and delete saved foods)

**Files:**
- Modify: `index.html` — `nutritionSettingsHTML()` (`<!-- my-foods -->` marker), `renderSettings()` (append sheet), `App.foodCreateSave`, `App`
- Modify: `tests/ui_smoke.py`

**Interfaces:**
- Consumes: `prefillFrom`, `customFood`, `foodSheetBodies.create`, `foodSheetHTML`, `foodForEntry`.
- Produces: App actions `foodEditSaved(id)`, `foodDelSaved(id)`; `App.foodCreateSave` handles `ui.foodEditFoodId`; element `#myFoods`.

- [ ] **Step 1: Write the failing smoke tests** (above the marker)

```python
@test
def edit_saved_food_keeps_history(pw, url):
    seed = base(foods=[EGG], foodLog=[{"id": "e1", "date": "2026-09-28", "time": "08:00", "foodId": "f-egg", "name": "Egg, whole",
        "grams": 50, "qty": 1, "unit": "p0", "label": "1 large", "kcal": 72, "protein": 6.3, "carbs": 0.4, "fat": 4.8, "fiber": 0}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        assert "Egg, whole" in pg.inner_text("#myFoods")
        pg.click("#myFoods .linkbtn >> nth=0")
        assert pg.input_value("#fcName") == "Egg, whole" and pg.input_value("#fcGrams") == "50"
        pg.fill("#fcName", "Egg (large)"); pg.fill("#fcKcal", "80"); pg.click("#fcSave")
        s = stored(pg); f = s["foods"][0]
        assert f["id"] == "f-egg" and f["name"] == "Egg (large)" and f["per100g"]["kcal"] == 160 and f["uses"] == 3
        assert s["foodLog"][0]["kcal"] == 72  # history keeps its snapshot
        assert pg.evaluate("ui.foodSheet") is None and pg.evaluate("ui.tab") == "settings"

@test
def deleted_food_entries_stay_editable(pw, url):
    seed = base(foods=[EGG], foodLog=[{"id": "e1", "date": "2026-09-28", "time": "08:00", "foodId": "f-egg", "name": "Egg, whole",
        "grams": 50, "qty": 1, "unit": "p0", "label": "1 large", "kcal": 72, "protein": 6.3, "carbs": 0.4, "fat": 4.8, "fiber": 0}],
        nutrition=[{"id": "n1", "date": "2026-09-28", "kcal": 72, "protein": 6, "carbs": 0, "fat": 5, "fiber": 0, "source": "log"}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        pg.click("#myFoods button.del"); pg.click("#myFoods button.del")
        assert stored(pg)["foods"] == []
        pg.evaluate("App.tab('food'); ui.foodDay = '2026-09-28'; render()")
        pg.click(".fd-row >> nth=0")
        assert pg.input_value("#faUnit") == "g" and pg.input_value("#faQty") == "50"
        pg.fill("#faQty", "100"); pg.click("#faSave")
        s = stored(pg)
        assert s["foodLog"][0]["kcal"] == 144 and s["foods"] == []
```

Stand-in food: 72 kcal per 50 g → 144 kcal per 100 g.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/ui_smoke.py edit_saved_food_keeps_history deleted_food_entries_stay_editable`
Expected: both FAIL (`#myFoods` missing).

- [ ] **Step 3: Render the list** — in `nutritionSettingsHTML()`, replace `<!-- my-foods -->` with:

```js
    <div style="height:1px;background:var(--grid);margin:14px 0"></div>
    <div style="font-size:14px;font-weight:600;margin-bottom:6px">My foods (${data.foods.length})</div>
    <div id="myFoods">${data.foods.length ? [...data.foods].sort((a, b) => a.name.localeCompare(b.name)).map(f => {
        const d = foodDefaultServing(f);
        return `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--grid)">
          <div style="flex:1;min-width:0"><div style="font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.name)}</div>
            <div style="font-family:var(--mono);font-size:11px;color:var(--sub)">${f.brand ? esc(f.brand) + " · " : ""}${d.kcal} kcal / ${esc(d.label)}</div></div>
          <button class="linkbtn" onclick="App.foodEditSaved('${f.id}')">edit</button>
          ${delBtn("MF" + f.id, `App.foodDelSaved('${f.id}')`)}
        </div>`; }).join("")
      : `<div class="muted" style="text-align:left">Foods you log or create are saved here.</div>`}</div>
```

In `renderSettings()`, change `html += nutritionSettingsHTML();` to:
```js
  html += nutritionSettingsHTML() + foodSheetHTML();
```

- [ ] **Step 4: Add the actions, and the edit branch in `foodCreateSave`**

Add to `App`:
```js
  foodEditSaved(id){
    const f = data.foods.find(x => x.id === id); if (!f) return;
    ui.foodEditFoodId = id; ui.foodPrefill = prefillFrom(f, f.barcode); ui.foodSheet = "create"; render();
  },
  foodDelSaved(id){
    if (!confirmDel("MF" + id)) return;
    data.foods = data.foods.filter(f => f.id !== id); save(); toast("Food removed — past entries keep their numbers"); render();
  },
```
In `App.foodCreateSave`, replace:
```js
    const saved = toSavedFood(food, uid);
    data.foods.push(saved); save();
    ui.foodPrefill = null;
    App.foodPickFood(saved);
```
with:
```js
    if (ui.foodEditFoodId){
      const f = data.foods.find(x => x.id === ui.foodEditFoodId);
      if (f){
        const keepExtra = !food.servingOnly && !f.servingOnly ? f.portions.slice(1) : [];
        Object.assign(f, { name: food.name, brand: food.brand, per100g: food.per100g,
          portions: [...food.portions, ...keepExtra], servingOnly: food.servingOnly });
        save();
      }
      ui.foodEditFoodId = null; ui.foodPrefill = null; ui.foodSheet = null;
      toast("Food updated ✓"); render(); return;
    }
    const saved = toSavedFood(food, uid);
    data.foods.push(saved); save();
    ui.foodPrefill = null;
    App.foodPickFood(saved);
```

Editing keeps the food's `id`, `source`, `sourceId`, `barcode`, `uses` and `lastUsed`, and keeps any extra USDA portions after the first.

- [ ] **Step 5: Run all tests**

Run: `node --test tests/*.test.mjs && python3 tests/ui_smoke.py`
Expected: all PASS, `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add index.html tests/ui_smoke.py
git commit -m "Settings: My foods list with edit and delete" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
```

---

### Task 9: Version bump, cleanup, verification, ship

**Files:**
- Modify: `index.html` (`APP_VERSION`)
- Delete: `probe.html`

- [ ] **Step 1: Bump the version**

Replace `const APP_VERSION = 71;` with `const APP_VERSION = 72;`.

- [ ] **Step 2: Remove the probe**

Run: `git rm probe.html`

- [ ] **Step 3: Confirm the old manual-day code is gone**

Run: `grep -n -E "foodManualOpen|toggleFoodManual|saveFood\(|fKcal" index.html`
Expected: no output.

- [ ] **Step 4: Run the whole suite**

Run: `node --test tests/*.test.mjs && python3 tests/ui_smoke.py`
Expected: all PASS, `0 failed`.

- [ ] **Step 5: Final screenshots in light and dark mode**

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, "tests")
from ui_smoke import *
srv, url = start_server()
with sync_playwright() as pw:
    for dark in (False, True):
        seed = base(foods=[EGG]); seed["settings"]["darkMode"] = dark
        with app(pw, url, seed) as pg:
            pg.click("#fdAdd"); pg.click("#fdResults .fd-res >> nth=0"); pg.click("#faSave")
            tag = "dark" if dark else "light"
            pg.screenshot(path=f"/tmp/final-food-{tag}.png", full_page=True)
            pg.evaluate("App.tab('settings')"); pg.locator("#nutritionSettings").scroll_into_view_if_needed()
            pg.screenshot(path=f"/tmp/final-settings-{tag}.png")
srv.shutdown()
EOF
```
Open all four PNGs with the Read tool and check contrast and layout in both themes.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "v72: in-app food logging replaces Cronometer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01P6NbzDRgT17pkvKf93CYJf"
git fetch origin main && git rebase origin/main
git push origin HEAD:main
```

- [ ] **Step 7: Hand Landon the phone checklist**

Send him this list to run on his iPhone after Pages updates (about a minute):
1. Settings → Nutrition: paste the USDA key.
2. Food tab: search "chicken breast", log 6 oz; search "rice", log 1 cup.
3. Scan a packaged item you have; scan something obscure (store brand) and create it; scan it again.
4. Quick add a restaurant meal; edit it; delete it.
5. Log something on yesterday with ‹.
6. Turn on airplane mode with the app open: search a food you've logged before; Quick add still works.
7. Calendar → today and the Food tab chart show the new total.
8. For 2–3 days, log in both apps and compare daily calories (within about 3–5% passes).
