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

def router(offline, gemini=None):
    def handle(route):
        url = route.request.url
        if url.startswith("http://127.0.0.1"): return route.continue_()
        if offline: return route.abort()
        if "generativelanguage.googleapis.com" in url:
            if gemini is None: return route.abort()
            status, body = gemini(route.request)
            return route.fulfill(status=status, content_type="application/json", body=body,
                                 headers={**CORS, "Access-Control-Allow-Headers": "*"})
        if "api.nal.usda.gov/fdc/v1/food/" in url:
            return route.fulfill(status=200, content_type="application/json", body=fixture("usda-food-details.json"), headers=CORS)
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
def app(pw, url, seed=None, offline=False, gemini=None):
    b = pw.chromium.launch(executable_path=CHROME)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    if seed is not None:
        ctx.add_init_script(
            f"if(!sessionStorage.getItem('seeded')){{localStorage.setItem({json.dumps(KEY)},{json.dumps(json.dumps(seed))});"
            "sessionStorage.setItem('seeded','1');}")
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route("**/*", router(offline, gemini))
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

@test
def food_tab_charts_calories_only(pw, url):
    seed = base(nutrition=[{"id": "n1", "date": "2026-09-27", "kcal": 2100, "protein": 150, "carbs": 200, "fat": 70, "fiber": 30, "source": "cronometer"},
                           {"id": "n2", "date": "2026-09-28", "kcal": 2300, "protein": 160, "carbs": 210, "fat": 75, "fiber": 32, "source": "cronometer"}])
    with app(pw, url, seed) as pg:
        segs = " ".join(pg.locator("#view .seg").all_inner_texts())
        assert "Protein" not in segs and "Carbs" not in segs
        assert pg.locator("#view svg").count() >= 1
        assert "recent days" in pg.inner_text("#view").lower()

@test
def search_input_stays_put_when_results_load(pw, url):
    seed = base(foods=[EGG]); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed) as pg:
        pg.click("#fdAdd")
        y0 = pg.locator("#fdQuery").bounding_box()["y"]
        pg.keyboard.type("yogurt")
        pg.wait_for_selector("#fdResults :text('Nutella')")
        box = pg.locator("#fdQuery").bounding_box()
        assert abs(box["y"] - y0) < 1, (y0, box["y"])
        assert box["y"] >= 0
        assert pg.locator("#fdQuickLink").bounding_box()["y"] < pg.locator("#fdResults").bounding_box()["y"]

@test
def usda_food_without_servings_loads_them(pw, url):
    seed = base(); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed) as pg:
        pg.click("#fdAdd"); pg.keyboard.type("chicken")
        pg.wait_for_selector("#fdResults :text('Chicken, breast')")
        pg.click("#fdResults .fd-res:has-text('Chicken, breast')")
        pg.wait_for_function("document.querySelectorAll('#faUnit option').length > 2")
        opts = pg.locator("#faUnit option").all_inner_texts()
        assert opts[:2] == ["1 breast, bone and skin removed", "1 cup"], opts
        assert pg.input_value("#faUnit") == "p0" and pg.input_value("#faQty") == "1"
        pg.click("#faSave")
        s = stored(pg)
        assert s["foodLog"][0]["kcal"] == 184 and len(s["foods"][0]["portions"]) == 2

@test
def push_sync_skips_unchanged_reminders(pw, url):
    seed = base(); seed["settings"]["pushEnabled"] = True; seed["crew"] = {"config": {"apiKey": "x", "projectId": "p", "appId": "a"}}
    with app(pw, url, seed) as pg:
        pg.evaluate("""() => { window.__writes = 0;
          fbInit = async () => ({ db: { collection: () => ({ doc: () => ({ set: async () => { window.__writes++; } }) }) } }); }""")
        pg.evaluate("pushSyncItems()"); pg.evaluate("pushSyncItems()")
        assert pg.evaluate("window.__writes") == 1
        pg.evaluate("data.school.tasks.push({id:'t1', text:'Lab report', due: todayISO(), done:false})")
        pg.evaluate("pushSyncItems()")
        assert pg.evaluate("window.__writes") == 2

@test
def usda_search_sends_forgiving_and_literal_queries(pw, url):
    seed = base(); seed["settings"]["usdaKey"] = "TESTKEY"
    with app(pw, url, seed) as pg:
        seen = []
        pg.on("request", lambda r: seen.append(r.url) if "foods/search" in r.url else None)
        pg.click("#fdAdd"); pg.keyboard.type("McDonalds McGriddle")
        pg.wait_for_selector("#fdResults :text('Nutella')")
        from urllib.parse import urlparse, parse_qs
        qs = sorted(parse_qs(urlparse(u).query)["query"][0] for u in seen)
        assert qs == ["+mcdonald* +mcgriddle*", "McDonalds McGriddle"], qs
        names = pg.locator("#fdResults .fd-res").all_inner_texts()
        assert sum("Egg, whole, raw" in n for n in names) == 1  # merged without duplicates

@test
def calendar_marks_calorie_goal_and_shows_food_first(pw, url):
    with app(pw, url, base()) as pg:
        ym = pg.evaluate("shiftISO(todayISO().slice(0,8) + '01', -1).slice(0,7)")  # last month: all days are in the past
    d1, d2, d3 = f"{ym}-02", f"{ym}-03", f"{ym}-04"
    seed = base(
        nutrition=[{"id": "n1", "date": d1, "kcal": 2200, "protein": 150, "carbs": 200, "fat": 70, "fiber": 30, "source": "log"},
                   {"id": "n2", "date": d2, "kcal": 2900, "protein": 150, "carbs": 300, "fat": 90, "fiber": 20, "source": "cronometer"}],
        foodLog=[{"id": "e1", "date": d1, "time": "07:30", "foodId": None, "name": "Overnight oats", "grams": None, "qty": None,
                  "unit": None, "label": "", "kcal": 600, "protein": 30, "carbs": 80, "fat": 15, "fiber": 10},
                 {"id": "e2", "date": d1, "time": "12:10", "foodId": None, "name": "Chicken bowl", "grams": None, "qty": None,
                  "unit": None, "label": "", "kcal": 1600, "protein": 120, "carbs": 120, "fat": 55, "fiber": 20}],
        lifts=[{"id": "l1", "date": d1, "split": "push", "exercises": [{"name": "Bench Press", "sets": [{"weight": 185, "reps": 5}]}], "notes": ""}],
        weights=[{"id": "w1", "date": d3, "lbs": 180}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('calendar')"); pg.evaluate("App.month(-1)")
        assert pg.locator(".cal .day .kbar.under").count() == 1
        assert pg.locator(".cal .day .kbar.over").count() == 1
        assert pg.locator(".cal .day .kbar").count() == 2  # weigh-in-only day gets no bar
        pg.evaluate(f"App.selDay('{d1}')")
        cards = pg.locator("#view .card").all_inner_texts()
        food_i = next(i for i, c in enumerate(cards) if "Overnight oats" in c)
        lift_i = next(i for i, c in enumerate(cards) if "PUSH DAY" in c.upper())
        assert food_i < lift_i, (food_i, lift_i)
        assert "Chicken bowl" in cards[food_i] and "2200" in cards[food_i]
        assert not any("NUTRITION" in c for c in cards)  # old totals-only card replaced
        pg.evaluate(f"App.selDay('{d2}')")
        assert any("2900" in c for c in pg.locator("#view .card").all_inner_texts())  # Cronometer day: totals only
        pg.evaluate(f"App.selDay('{d1}')")
        pg.click("#calFoodOpen")
        assert pg.evaluate("ui.tab") == "food" and pg.evaluate("ui.foodDay") == d1

import datetime as _dt
FUTURE = (_dt.date.today() + _dt.timedelta(days=10)).isoformat()
def gem_text(t): return 200, json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}}]})
def gem_call(name, args): return 200, json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}}]})
def scripted(*replies):
    """Gemini stand-in: returns replies in order and records each request body."""
    seen = []
    def respond(req):
        seen.append({"body": req.post_data_json, "headers": req.headers})
        return replies[min(len(seen), len(replies)) - 1]
    respond.seen = seen
    return respond
def school_seed(**over):
    d = base(**over)
    d["school"] = {"classes": [{"id": "c1", "name": "ENGR 3413 Materials Science"}, {"id": "c2", "name": "Modern Physics"}],
                   "tasks": [], "sessions": [], "assignments": [], "schedule": [],
                   "dates": [{"id": "d1", "title": "Exam 2", "kind": "exam", "date": FUTURE, "time": "10:00", "classId": "c1"},
                             {"id": "d2", "title": "Quiz 3", "kind": "quiz", "date": FUTURE, "classId": "c2"}]}
    d["settings"].update({"aiEnabled": True, "aiKey": "GEMKEY", "schoolEnabled": True})
    return d
def last_tool_result(body):
    for c in reversed(body["contents"]):
        for part in c.get("parts", []):
            if "functionResponse" in part: return part["functionResponse"]["response"]["result"]
def ask(pg, text):
    pg.click("#aiBtn"); pg.fill("#aiInput", text); pg.click("#aiSend")
    pg.wait_for_function("!ui.aiBusy")

@test
def assistant_is_off_by_default(pw, url):
    with app(pw, url, base()) as pg:
        assert not pg.locator("#aiBtn").is_visible()
        assert pg.locator("#appTitle").is_visible()
        pg.evaluate("App.tab('settings')")
        pg.click("button.switch[aria-label='AI assistant']")
        assert pg.locator("#aiBtn").is_visible() and not pg.locator("#appTitle").is_visible()
        assert pg.locator("#aiKey").count() == 1
        assert stored(pg)["settings"]["aiEnabled"] is True

@test
def assistant_answers_next_exam_from_app_data(pw, url):
    g = scripted(gem_call("get_school", {"class_name": "materials"}), gem_text(f"Your next **Materials Science** exam is Exam 2 on {FUTURE} at 10:00."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "When is my next materials science exam?")
        assert "Exam 2" in pg.inner_text("#aiLog") and "<strong>" in pg.inner_html("#aiLog")
        assert len(g.seen) == 2 and g.seen[0]["headers"].get("x-goog-api-key") == "GEMKEY"
        first = g.seen[0]["body"]
        assert first["contents"][-1]["parts"][0]["text"] == "When is my next materials science exam?"
        assert any(f["name"] == "add_school_task" for f in first["tools"][0]["functionDeclarations"])
        assert "Materials Science" in first["systemInstruction"]["parts"][0]["text"]
        result = json.dumps(last_tool_result(g.seen[1]["body"]))
        assert "Exam 2" in result and "Quiz 3" not in result

@test
def assistant_adds_school_task(pw, url):
    g = scripted(gem_call("add_school_task", {"text": "Lab report", "class_name": "materials science", "due": FUTURE, "time": "23:59"}),
                 gem_text("Added Lab report for Materials Science."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "add lab report due in ten days for materials science")
        t = stored(pg)["school"]["tasks"]
        assert len(t) == 1 and t[0]["text"] == "Lab report" and t[0]["classId"] == "c1" and t[0]["due"] == FUTURE and t[0]["dueTime"] == "23:59"
        assert last_tool_result(g.seen[1]["body"])["ok"] is True

@test
def assistant_unknown_class_adds_nothing(pw, url):
    g = scripted(gem_call("add_school_task", {"text": "Homework 4", "class_name": "chemistry"}), gem_text("I don't see a chemistry class."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "add homework 4 for chemistry")
        assert stored(pg)["school"]["tasks"] == []
        r = last_tool_result(g.seen[1]["body"])
        assert "error" in r and "Modern Physics" in r["classes"]

@test
def assistant_reads_a_day_and_logs_food(pw, url):
    seed = school_seed(lifts=[{"id": "l1", "date": "2026-09-28", "split": "push", "exercises": [{"name": "Bench Press", "sets": [{"weight": 185, "reps": 5}]}], "notes": ""}],
                       nutrition=[{"id": "n1", "date": "2026-09-28", "kcal": 2350, "protein": 170, "carbs": 220, "fat": 75, "fiber": 30, "source": "cronometer"}])
    g = scripted(gem_call("get_day", {"date": "2026-09-28"}), gem_call("log_food", {"name": "Protein shake", "kcal": 160, "protein": 30}), gem_text("Done."))
    with app(pw, url, seed, gemini=g) as pg:
        ask(pg, "what did I eat and lift on 9/28, and log a protein shake")
        day = last_tool_result(g.seen[1]["body"])
        assert day["food"]["kcal"] == 2350 and day["lifting"][0]["exercises"][0]["sets"] == "185x5"
        s = stored(pg); e = s["foodLog"][0]
        assert e["name"] == "Protein shake" and e["kcal"] == 160 and e["date"] == pg.evaluate("todayISO()")
        assert any(r["date"] == e["date"] and r["source"] == "log" for r in s["nutrition"])

@test
def assistant_adds_todo(pw, url):
    g = scripted(gem_call("add_todo", {"text": "Call the dentist"}), gem_text("Added."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "remind me to call the dentist")
        assert stored(pg)["todos"][0]["text"] == "Call the dentist"

@test
def assistant_explains_bad_key_and_missing_key(pw, url):
    g = scripted((400, json.dumps({"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "hi")
        assert "key" in pg.inner_text("#aiLog").lower() and "settings" in pg.inner_text("#aiLog").lower()
    seed = school_seed(); seed["settings"]["aiKey"] = ""
    with app(pw, url, seed, gemini=scripted(gem_text("unused"))) as pg:
        ask(pg, "hi")
        assert "settings" in pg.inner_text("#aiLog").lower()

@test
def assistant_survives_rerender_and_tab_change(pw, url):
    g = scripted(gem_text("Hello there."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "hi")
        pg.evaluate("render()")
        assert "Hello there." in pg.inner_text("#aiLog")

@test
def assistant_switches_to_available_model_when_default_is_gone(pw, url):
    def g(req):
        if req.method == "GET":
            return 200, json.dumps({"models": [{"name": "models/gemini-9.0-flash", "supportedGenerationMethods": ["generateContent"]}]})
        if "gemini-9.0-flash:generateContent" in req.url: return gem_text("Hi from the new model.")
        return 404, json.dumps({"error": {"code": 404, "message": "models/gemini-3.5-flash is not found", "status": "NOT_FOUND"}})
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "hi")
        assert "Hi from the new model." in pg.inner_text("#aiLog")
        assert stored(pg)["settings"]["aiModel"] == "gemini-9.0-flash"

BUSY = (503, json.dumps({"error": {"code": 503, "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.", "status": "UNAVAILABLE"}}))

@test
def assistant_retries_then_uses_another_model_when_busy(pw, url):
    calls = []
    def g(req):
        calls.append((req.method, req.url))
        if req.method == "GET":
            return 200, json.dumps({"models": [{"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                                               {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]}]})
        if "gemini-3.6-flash:generateContent" in req.url: return gem_text("Answered by the backup model.")
        return BUSY
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "hi")
        assert "Answered by the backup model." in pg.inner_text("#aiLog")
        posts = [u for m, u in calls if m == "POST"]
        assert sum("gemini-3.5-flash:" in u for u in posts) == 2  # first try + one retry
        assert stored(pg)["settings"].get("aiModel") in (None, "gemini-3.5-flash")  # backup isn't saved as the default

@test
def assistant_explains_when_every_model_is_busy(pw, url):
    def g(req):
        if req.method == "GET":
            return 200, json.dumps({"models": [{"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]}]})
        return BUSY
    with app(pw, url, school_seed(), gemini=g) as pg:
        ask(pg, "hi")
        txt = pg.inner_text("#aiLog").lower()
        assert "busy" in txt and "try again" in txt

FAKE_FS = """() => {
  window.__fs = {};
  const mkDoc = path => ({
    set: async v => { __fs[path] = JSON.parse(JSON.stringify(v)); },
    get: async () => ({ exists: path in __fs, data: () => __fs[path], id: path.split("/").pop() }),
    delete: async () => { delete __fs[path]; },
    collection: n => mkCol(path + "/" + n),
  });
  const mkCol = path => ({
    doc: id => mkDoc(path + "/" + id),
    get: async () => ({ docs: Object.keys(__fs).filter(k => k.startsWith(path + "/") && !k.slice(path.length + 1).includes("/"))
      .map(k => ({ id: k.slice(path.length + 1), data: () => __fs[k] })) }),
  });
  fbInit = async () => ({ db: { collection: n => mkCol(n) } });
}"""
def backup_seed():
    d = base()
    d["crew"] = {"code": "ABC123", "name": "Landon", "config": {"apiKey": "x", "projectId": "p", "appId": "a"}}
    d["settings"].update({"aiKey": "SECRET-GEMINI-KEY-123", "usdaKey": "SECRET-USDA-KEY-456"})
    d["stravaApi"] = {"clientId": "777", "clientSecret": "SECRET-STRAVA-CLIENT", "refreshToken": "SECRET-STRAVA-REFRESH", "accessToken": "SECRET-STRAVA-ACCESS", "expiresAt": 1}
    return d
BIG_LOG = """n => { data.foodLog = Array.from({ length: n }, (_, i) => ({ id: "e" + i, date: "2026-01-01", time: "08:00", foodId: null,
  name: "Entry number " + i + " with a reasonably long descriptive food name", grams: 100, qty: 1, unit: "p0",
  label: "1 serving", kcal: 250, protein: 20.5, carbs: 30.5, fat: 8.5, fiber: 2.5 })); }"""

@test
def cloud_backup_handles_a_log_over_one_megabyte_and_strips_secrets(pw, url):
    with app(pw, url, backup_seed()) as pg:
        pg.evaluate(FAKE_FS); pg.evaluate(BIG_LOG, 9000)
        assert pg.evaluate("backupCore().length") > 1_000_000
        pg.evaluate("cloudBackup(true)")
        docs = pg.evaluate("__fs")
        sizes = {k: len(json.dumps(v)) for k, v in docs.items()}
        assert max(sizes.values()) < 900_000, sizes
        blob = json.dumps(docs)
        for secret in ["SECRET-GEMINI-KEY-123", "SECRET-USDA-KEY-456", "SECRET-STRAVA-CLIENT", "SECRET-STRAVA-REFRESH", "SECRET-STRAVA-ACCESS"]:
            assert secret not in blob, secret
        assert [b["name"] for b in pg.evaluate("cloudListBackups('ABC123')")] == ["Landon"]
        r = pg.evaluate("cloudFetchBackup('ABC123', 'landon')")
        assert len(r["foodLog"]) == 9000 and r["stravaApi"]["clientId"] == "777" and "aiKey" not in r["settings"]
        assert stored(pg)["settings"]["aiKey"] == "SECRET-GEMINI-KEY-123"  # the phone keeps its keys

@test
def cloud_backup_cleans_up_chunks_when_the_log_shrinks(pw, url):
    with app(pw, url, backup_seed()) as pg:
        pg.evaluate(FAKE_FS); pg.evaluate(BIG_LOG, 9000); pg.evaluate("cloudBackup(true)")
        assert any("__c" in k for k in pg.evaluate("Object.keys(__fs)"))
        pg.evaluate(BIG_LOG, 10); pg.evaluate("cloudBackup(true)")
        assert not any("__c" in k for k in pg.evaluate("Object.keys(__fs)"))
        assert len(pg.evaluate("cloudFetchBackup('ABC123', 'landon')")["foodLog"]) == 10

@test
def restoring_a_backup_keeps_this_phones_keys(pw, url):
    seed = backup_seed()
    seed["school"]["classes"] = [{"id": "c1", "name": "Materials Science"}]
    seed["school"]["dates"] = [{"id": "d1", "title": "Exam 2", "kind": "exam", "date": "2026-10-20", "classId": "c1"}]
    with app(pw, url, seed) as pg:
        pg.evaluate(FAKE_FS); pg.evaluate("cloudBackup(true)")
        pg.evaluate("async () => { ui.pendingRestore = await cloudFetchBackup('ABC123', 'landon'); App.confirmRestore(); }")
        st = stored(pg)
        assert st["settings"]["aiKey"] == "SECRET-GEMINI-KEY-123" and st["settings"]["usdaKey"] == "SECRET-USDA-KEY-456"
        assert st["stravaApi"]["refreshToken"] == "SECRET-STRAVA-REFRESH"
        assert st["school"]["classes"][0]["name"] == "Materials Science" and st["school"]["dates"][0]["title"] == "Exam 2"

@test
def calendar_banner_reflects_cloud_backup_health(pw, url):
    d = backup_seed(); d["weights"] = [{"id": "w1", "date": "2026-09-01", "lbs": 180}]
    d["settings"]["cloudBackup"] = {"at": 0}
    with app(pw, url, d) as pg:
        pg.evaluate("data.settings.cloudBackup = { at: Date.now() - 3600e3 }; App.tab('calendar')")
        assert "back up" not in pg.inner_text("#view").lower()  # healthy cloud backup: no nag
        pg.evaluate("data.settings.cloudBackup = { at: Date.now() - 4 * 86400e3 }; render()")
        txt = pg.inner_text("#view").lower()
        assert "cloud backup" in txt and "4 days" in txt
        assert pg.locator("#bkBannerBtn").count() == 1
    nocrew = base(); nocrew["weights"] = [{"id": "w1", "date": "2026-09-01", "lbs": 180}]
    with app(pw, url, nocrew) as pg:
        pg.evaluate("App.tab('calendar')")
        assert "export" in pg.inner_text("#view").lower()  # no crew: keep the export reminder

@test
def interrupted_backup_leaves_the_previous_one_restorable(pw, url):
    with app(pw, url, backup_seed()) as pg:
        pg.evaluate(FAKE_FS); pg.evaluate(BIG_LOG, 9000); pg.evaluate("cloudBackup(true)")
        pg.evaluate(BIG_LOG, 9100); pg.evaluate("data.foodLog[0].name = 'x'.repeat(5000)")  # shift every piece boundary
        pg.evaluate("""() => { const real = fbInit; fbInit = async () => { const fb = await real(); const col = fb.db.collection;
          fb.db = { collection: n => { const c = col(n); const wrap = c2 => ({ ...c2, doc: id => { const d = c2.doc(id);
            return { ...d, collection: m => wrap(d.collection(m)), set: async v => { if (/__c.*1$/.test(id)) throw new Error("signal lost"); return d.set(v); } }; } });
            return wrap(c); } }; return fb; }; }""")
        pg.evaluate("cloudBackup(false)")
        r = pg.evaluate("cloudFetchBackup('ABC123', 'landon')")
        assert len(r["foodLog"]) == 9000 and r["foodLog"][0]["name"].startswith("Entry number 0")  # the last complete backup is intact

@test
def voice_transcript_is_sent_when_speech_ends(pw, url):
    g = scripted(gem_text("Got it."))
    with app(pw, url, school_seed(), gemini=g) as pg:
        pg.evaluate("""() => { window.SpeechRecognition = window.webkitSpeechRecognition = class { start(){ window.__rec = this; } stop(){ this.onend && this.onend(); } }; }""")
        pg.click("#aiBtn"); pg.click("#aiMic")
        pg.evaluate("""() => { __rec.onresult({ results: [[{ transcript: "when is my next exam" }]] }); __rec.onend(); }""")
        pg.wait_for_function("!ui.aiBusy && ui.aiMsgs.length >= 2")
        assert pg.evaluate("ui.aiMsgs[0].text") == "when is my next exam"
        assert len(g.seen) == 1

@test
def background_render_keeps_half_filled_forms(pw, url):
    with app(pw, url, base()) as pg:
        pg.click("#fdAdd"); pg.click("#fdQuickLink")
        pg.fill("#fqName", "Tacos"); pg.fill("#fqKcal", "450")
        pg.evaluate("render()")
        assert pg.input_value("#fqName") == "Tacos" and pg.input_value("#fqKcal") == "450"
        pg.evaluate("App.foodOpen('search')"); pg.click("#fdCreateLink")
        pg.fill("#fcName", "Mom's chili"); pg.fill("#fcKcal", "520"); pg.fill("#fcGrams", "300")
        pg.evaluate("render()")
        assert pg.input_value("#fcName") == "Mom's chili" and pg.input_value("#fcKcal") == "520" and pg.input_value("#fcGrams") == "300"

@test
def scanner_restarts_on_the_new_video_after_a_rerender(pw, url):
    with app(pw, url, base()) as pg:
        pg.evaluate("""() => { window.__starts = 0; window.__stops = 0;
          window.ZXingBrowser = { BrowserMultiFormatOneDReader: class { async decodeFromConstraints(c, video){ window.__starts++; window.__video = video; return { stop(){ window.__stops++; } }; } } }; }""")
        pg.click("#fdScan"); pg.wait_for_function("window.__starts === 1")
        pg.evaluate("render()"); pg.wait_for_function("window.__starts === 2")
        assert pg.evaluate("window.__stops") == 1
        assert pg.evaluate("window.__video === document.querySelector('#fdScanVideo')")
        pg.click("#fdSheet .fd-x")
        assert pg.evaluate("window.__stops") == 2

@test
def assistant_sheet_fits_above_the_keyboard(pw, url):
    with app(pw, url, school_seed()) as pg:
        pg.click("#aiBtn")
        pg.evaluate("""() => { Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => 420 });
          window.visualViewport.dispatchEvent(new Event('resize')); }""")
        box = pg.locator("#aiInput").bounding_box()
        assert box["y"] + box["height"] <= 420, box

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
