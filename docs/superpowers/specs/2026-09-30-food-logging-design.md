# Food Logging — Design Spec

Date: 2026-09-30
Status: Approved in brainstorming, pending written-spec review
Target version: v72

## Goal

Replace Cronometer with in-app food logging in Training Log. Search a food database, scan barcodes, and add foods manually, with daily totals feeding the existing nutrition charts, 7-day averages, and goal colors.

**Success criteria**
- Logging a typical day takes no longer than it does in Cronometer.
- Daily calorie totals land within about 3–5% of Cronometer's for the same foods.
- Every existing nutrition reader (calendar day view, Food tab charts and averages, dashboard, backup preview) keeps working unchanged.

## Decisions

| Topic | Decision |
|---|---|
| Nutrients tracked | Calories, protein, carbs, fat, fiber only. No micronutrients. |
| Barcode scanning | Included in v1. |
| Day structure | One list per day, sorted by time. No meal groups. |
| Data source | Live search of USDA FoodData Central and Open Food Facts from the phone. Logged foods are saved locally. |
| Sharing | Food data stays on the device and in the existing personal backup. Not shared with the crew. |
| Cronometer | Its past daily totals are kept as history. CSV import moves to Settings as a back-fill tool. |

**Out of scope:** micronutrients, meal groups, a shared crew food library, a bundled offline USDA dataset, recipes, and the Claude assistant (a separate sub-project).

## 1. Data model

`data.nutrition` stays exactly as it is: one row per date, `{id, date, kcal, protein, carbs, fat, fiber, source}`. Two new top-level arrays are added to `EMPTY` and default to `[]`.

### `data.foods` — saved food library

```
{ id, name, brand, barcode,
  per100g: { kcal, protein, carbs, fat, fiber },
  portions: [ { label: "1 large egg", grams: 50 }, ... ],
  servingOnly: false,
  source: "usda" | "off" | "custom", sourceId,
  uses, lastUsed }
```

- Macros are stored per 100 g. Each portion converts to grams.
- A food is added the first time it is logged, whether it came from search, a scan, or manual entry. `uses` and `lastUsed` are updated on every log.
- **Serving-only foods:** a custom food entered without serving grams is stored with `servingOnly: true`, one portion `{label, grams: 100}`, and `per100g` set to its per-serving values. For these foods the unit picker shows only the serving portion; `g` and `oz` are hidden.

### `data.foodLog` — what was eaten

```
{ id, date, time, foodId, name, grams, label,
  kcal, protein, carbs, fat, fiber }
```

- `date` is `YYYY-MM-DD`; `time` is `HH:MM` in 24-hour format.
- Macros are snapshotted at log time. Editing or deleting a saved food never changes past entries.
- `label` is the amount as entered, for display (e.g. "2 large eggs").
- **Quick add** entries have `foodId: null`, a user-supplied `name` (default "Quick add"), and `grams: null`.

### Derived daily totals

Whenever a date's `foodLog` entries change, the app recomputes that date's row:

- If the date has one or more log entries, the date's existing `data.nutrition` row is replaced with `{id, date, ...summed and rounded macros, source: "log"}`. This replaces any `manual` or `cronometer` row for that date.
- If the date's last entry is deleted, its `source: "log"` row is removed.
- The Cronometer CSV import skips any date that has `foodLog` entries.

Storage estimate: about 150 bytes per entry, or roughly 0.8 MB per year at 15 entries a day. Saved through the existing `save()` into the same localStorage key, so the existing cloud backup includes it.

## 2. Logging screens (Food tab)

The top of the Food tab is replaced. The existing charts and averages below it stay.

### Day card
- Date switcher `‹ Today ›`. The arrows move by one day; tapping the label returns to today.
- Totals strip: calories eaten and remaining against `kcalTarget` using the existing `kcalColor()` green/red, protein against `proteinTarget`, and C/F/fiber in small mono text. When no goal is set, show totals only.
- Entry list sorted by `time`: `7:42a  2 large eggs  143 kcal · P13`.
- Buttons: **+ Add food** and **Scan**.

### Add flow (bottom sheet)
1. A search box is focused immediately. While it's empty it lists **Recent** foods (by `lastUsed`), with a toggle to **Frequent** (by `uses`). Tapping one goes to step 3.
2. Typing runs a search (Section 3). Tapping a result goes to step 3.
3. **Amount screen:** number field, unit picker (the food's portions, then `g` and `oz`), a live macro preview, and time (defaults to now, editable). **Log** saves the entry.

- A **Quick add** link opens a form for name, kcal, and optional P/C/F/fiber.
- A **Create food** link opens the manual food form (Section 3).

### Editing
Tapping an entry opens the amount screen pre-filled, with **Save** and **Delete**.

### Removed or moved
- The manual whole-day totals form is removed; Quick add replaces it.
- The Cronometer CSV import moves into Settings, with its existing instructions.

## 3. Search, scanning, and manual entry

### Search
- Each keystroke filters saved foods locally by name and brand.
- Remote search runs once the query has 3+ characters and typing has paused for 500 ms. USDA and Open Food Facts are queried in parallel. Any in-flight requests are cancelled with `AbortController` when a new search starts.
- **USDA:** `GET https://api.nal.usda.gov/fdc/v1/foods/search` with `query`, `pageSize=25`, `dataType=Foundation,SR Legacy,Survey (FNDDS),Branded`, and `api_key` read from Settings.
  - Nutrient numbers: energy 1008 (fall back to 2047, then 2048 when 1008 is missing), protein 1003, fat 1004, carbs 1005, fiber 1079.
  - Portions come from `foodMeasures` (generic foods) or from `servingSize` and `servingSizeUnit` when the unit is grams (branded foods).
- **Open Food Facts:** product search by name, requesting only these fields: `code, product_name, brands, nutriments, serving_size, serving_quantity`.
  - Nutrients: `energy-kcal_100g`, `proteins_100g`, `carbohydrates_100g`, `fat_100g`, `fiber_100g`.
  - Portion comes from `serving_quantity` (grams), labelled with `serving_size`.
  - Products with no calorie value are dropped from results.
- **Ranking:**
  1. Saved foods, sorted by `uses`.
  2. USDA Foundation and SR Legacy results.
  3. USDA Survey (FNDDS) results.
  4. USDA Branded and Open Food Facts results, merged, de-duplicated by barcode (USDA `gtinUpc` against OFF `code`, comparing leading-zero-normalized digits). USDA wins a duplicate.
  - Results already saved locally show only as saved results.
- **Result row:** name, brand, kcal for the default portion (the first portion, or 100 g if there are none), and a source tag: `saved`, `USDA`, or `OFF`.
- **Request settings:** each remote call has an 8-second timeout. One source failing does not block the other.

### Barcode scan
1. **Scan** opens a full-screen camera view. The scanning library (ZXing browser build, about 100 KB) loads from an allowed CDN the first time it's used.
2. Supported formats: EAN-13, EAN-8, UPC-A, UPC-E.
3. Lookup order:
   1. Saved foods by `barcode`.
   2. Open Food Facts product by code.
   3. USDA search using the code as the query, matching `gtinUpc`.
4. Outcomes:
   - **Found with calories:** go to the amount screen.
   - **Found but missing calories or serving size:** open the manual form, pre-filled with what was found.
   - **Not found:** open an empty manual form with the barcode attached.
5. Cancel and camera-permission-denied states return to the add sheet with a short message.

### Manual food form
- Fields: name (required), brand, serving label (default "1 serving"), serving grams (optional), and kcal (required), protein, carbs, fat, fiber **per serving**.
- With serving grams provided: `per100g = perServing × 100 / grams`, and the portion is `{label, grams}`.
- Without serving grams: the food is stored as serving-only (Section 1).
- Saving creates the food with `source: "custom"` and continues to the amount screen.

### Settings additions
- **USDA API key** field, with a link to request a free key at api.data.gov. Stored in `data.settings.usdaKey`.
- **My foods**: a list of saved foods with edit and delete.
- **Import from Cronometer**: the moved CSV import.

### Errors and offline
- When `navigator.onLine` is false or both remote sources fail, saved foods and Quick add stay available, with a note: "Offline — showing saved foods". This covers losing signal while the app is already open; `sw.js` does no caching, so a cold launch with no signal is unchanged from today and out of scope.
- When no USDA key is set, USDA is skipped and a one-line hint links to the Settings field.
- **Risk to verify first:** whether both APIs accept browser requests (CORS). If either one doesn't, stop and confirm a fallback with Landon before adding a proxy.

## 4. Testing and rollout

### Automated tests
- The new logic lives in pure functions with no DOM access:
  - portion and unit to grams conversion
  - macro calculation
  - daily total recompute
  - mixed-source precedence rules
  - USDA and OFF response parsers
  - result merge, de-duplication, and ranking
- `tests/food.test.mjs` runs them with `node --test`, using saved real API responses in `tests/fixtures/` as inputs.
- The tests load the functions by extracting a marked block from `index.html`, so the app stays a single file.
- No new dependencies.

### Manual phone checklist
- Text search, scanning a known product, scanning an unknown product.
- Log, edit, and delete an entry; log on a past day.
- Quick add; creating a custom food.
- Airplane mode, enabled after the app is open: saved foods and Quick add still work.
- The calendar day view, Food tab charts, and averages reflect the logged totals.
- A Cronometer import skips logged dates.

### Accuracy validation
For 2 or 3 days, log the same foods in both apps. A daily calorie difference within about 3–5% passes. Anything larger is treated as a bug to fix before dropping Cronometer.

### Rollout
- Set `APP_VERSION` to 72. `sw.js` does no caching (push only), so no cache bump is needed; updates load on the next app open.
- No data migration.
- No feature toggle.
