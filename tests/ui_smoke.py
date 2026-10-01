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
