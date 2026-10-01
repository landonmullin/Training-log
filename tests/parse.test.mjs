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
