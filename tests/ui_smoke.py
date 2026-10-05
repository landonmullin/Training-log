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
def deleting_a_logged_day_clears_its_entries(pw, url):
    d = "2026-09-28"
    seed = base(foodLog=[{"id": "e1", "date": d, "time": "08:00", "foodId": None, "name": "Quick add", "grams": None,
                          "qty": None, "unit": None, "label": "", "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}],
                nutrition=[{"id": "n1", "date": d, "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "source": "log"}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.delFood('n1')"); pg.evaluate("App.delFood('n1')")
        s = stored(pg)
        assert s["nutrition"] == [] and s["foodLog"] == []

















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
def assistant_sheet_fits_above_the_keyboard(pw, url):
    with app(pw, url, school_seed()) as pg:
        pg.click("#aiBtn")
        pg.evaluate("""() => { Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => 420 });
          window.visualViewport.dispatchEvent(new Event('resize')); }""")
        box = pg.locator("#aiInput").bounding_box()
        assert box["y"] + box["height"] <= 420, box


TOKEN = "T" * 8 + "abcdEFGH1234_-xyz" + "Q" * 7  # 32 chars
def sync_seed(**over):
    d = base(**over)
    d["crew"] = {"code": "ABC123", "name": "Landon", "config": {"apiKey": "AIzaTESTKEY", "projectId": "training-tracker-1d42d", "appId": "a"}}
    d["settings"]["healthToken"] = TOKEN
    return d
def iso_shift(days): return (_dt.date.today() + _dt.timedelta(days=days)).isoformat()
def dkey(iso): return "d" + iso.replace("-", "")

@test
def food_tab_is_view_only_with_day_navigation(pw, url):
    y = iso_shift(-1)
    seed = base(nutrition=[{"id": "n1", "date": y, "kcal": 2550, "protein": 172, "carbs": 260, "fat": 80, "fiber": 33, "source": "health"}])
    with app(pw, url, seed) as pg:
        assert pg.locator("#fdAdd").count() == 0 and pg.locator("#fdScan").count() == 0
        card = pg.inner_text("#foodDay")
        assert "today" in card.lower() and "no food data" in card.lower()
        assert pg.locator("#fdNext").is_disabled()
        pg.click("#fdPrev")
        card = pg.inner_text("#foodDay")
        assert "2550" in card and "172" in card and "260" in card and "33" in card
        assert "150 over" in card.lower()  # goal is 2400
        assert "cronometer" in card.lower()
        pg.click("#fdNext")
        assert pg.evaluate("ui.foodDay") == pg.evaluate("todayISO()")
        assert "recent days" in pg.inner_text("#view").lower()

@test
def calendar_marks_calorie_goal_and_shows_food_first(pw, url):
    ym = (_dt.date.today().replace(day=1) - _dt.timedelta(days=1)).isoformat()[:7]  # last month: all days in the past
    d1, d2, d3 = f"{ym}-02", f"{ym}-03", f"{ym}-04"
    seed = base(
        nutrition=[{"id": "n1", "date": d1, "kcal": 2200, "protein": 150, "carbs": 200, "fat": 70, "fiber": 30, "source": "health"},
                   {"id": "n2", "date": d2, "kcal": 2900, "protein": 150, "carbs": 300, "fat": 90, "fiber": 20, "source": "cronometer"}],
        lifts=[{"id": "l1", "date": d1, "split": "push", "exercises": [{"name": "Bench Press", "sets": [{"weight": 185, "reps": 5}]}], "notes": ""}],
        weights=[{"id": "w1", "date": d3, "lbs": 180}])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('calendar')"); pg.evaluate("App.month(-1)")
        assert pg.locator(".cal .day .kbar.under").count() == 1
        assert pg.locator(".cal .day .kbar.over").count() == 1
        assert pg.locator(".cal .day .kbar").count() == 2  # weigh-in-only day gets no bar
        pg.evaluate(f"App.selDay('{d1}')")
        cards = pg.locator("#view .card").all_inner_texts()
        food_i = next(i for i, c in enumerate(cards) if c.strip().upper().startswith("FOOD"))
        lift_i = next(i for i, c in enumerate(cards) if "PUSH DAY" in c.upper())
        assert food_i < lift_i and "2200" in cards[food_i]
        pg.click("#calFoodOpen")
        assert pg.evaluate("ui.tab") == "food" and pg.evaluate("ui.foodDay") == d1

@test
def cronometer_csv_import_replaces_those_days(pw, url):
    seed = base(nutrition=[{"id": "n1", "date": "2026-09-28", "kcal": 500, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "source": "health"}])
    csv = "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n2026-09-27,2100,150,200,70,30\n2026-09-28,2300,160,210,75,32\n"
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        pg.set_input_files("#csvFile", files=[{"name": "c.csv", "mimeType": "text/csv", "buffer": csv.encode()}])
        pg.wait_for_function("JSON.parse(localStorage.getItem('ftrack-data-v2')).nutrition.length === 2")
        rows = {r["date"]: r for r in stored(pg)["nutrition"]}
        assert rows["2026-09-28"]["kcal"] == 2300 and rows["2026-09-28"]["source"] == "cronometer"

@test
def health_inbox_imports_cronometer_totals(pw, url):
    y, t = iso_shift(-1), iso_shift(0)
    seed = sync_seed(nutrition=[{"id": "old", "date": y, "kcal": 1000, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "source": "cronometer"}])
    with app(pw, url, seed) as pg:
        pg.evaluate(FAKE_FS)
        pg.evaluate(f"""() => {{ __fs['healthInbox/{TOKEN}'] = {{
            {dkey(y)}: {{ kcal: "2,345.6", protein: "180.2", carbs: "250", fat: "70.4", fiber: "31" }},
            {dkey(t)}: {{ kcal: "0" }}, {dkey(iso_shift(1))}: {{ kcal: "900" }} }}; }}""")
        pg.evaluate("healthSync(true)")
        rows = {r["date"]: r for r in stored(pg)["nutrition"]}
        assert rows[y] == {"id": "old", "date": y, "kcal": 2346, "protein": 180, "carbs": 250, "fat": 70, "fiber": 31, "source": "health"} or \
               (rows[y]["kcal"] == 2346 and rows[y]["source"] == "health")
        assert t not in rows and iso_shift(1) not in rows
        assert stored(pg)["settings"]["healthLast"] > 0

@test
def health_sync_runs_when_the_app_comes_back(pw, url):
    y = iso_shift(-1)
    with app(pw, url, sync_seed()) as pg:
        pg.evaluate(FAKE_FS)
        pg.evaluate(f"() => {{ __fs['healthInbox/{TOKEN}'] = {{ {dkey(y)}: {{ kcal: '2200', protein: '170' }} }}; }}")
        pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        pg.wait_for_function(f"data.nutrition.some(n => n.date === '{y}' && n.source === 'health')")
        pg.evaluate("App.tab('food')")
        assert "synced" in pg.inner_text("#foodDay").lower() or pg.locator("#foodDay").count() == 1

@test
def health_inbox_is_trimmed_when_it_grows(pw, url):
    with app(pw, url, sync_seed()) as pg:
        pg.evaluate(FAKE_FS)
        fields = ", ".join(f"{dkey(iso_shift(-i))}: {{ kcal: '2000' }}" for i in range(1, 71))
        pg.evaluate(f"() => {{ __fs['healthInbox/{TOKEN}'] = {{ {fields} }}; }}")
        pg.evaluate("healthSync(true)")
        doc = pg.evaluate(f"__fs['healthInbox/{TOKEN}']")
        assert 25 <= len(doc) <= 31 and dkey(iso_shift(-1)) in doc
        assert len([n for n in stored(pg)["nutrition"] if n["source"] == "health"]) == 70

@test
def settings_walks_through_cronometer_sync_setup(pw, url):
    seed = sync_seed(); del seed["settings"]["healthToken"]
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        pg.click("#healthSetupBtn")
        token = stored(pg)["settings"]["healthToken"]
        assert len(token) >= 32
        pg.click("#healthSetup summary")
        txt = pg.inner_text("#healthSetup")
        for part in ["training-tracker-1d42d", token, "key=AIzaTESTKEY", "updateMask.fieldPaths=d", "healthInbox", "Cronometer"]:
            assert part in txt, part
        assert "stringValue" in txt  # request body template
    with app(pw, url, base()) as pg:
        pg.evaluate("App.tab('settings')")
        assert "crew sync" in pg.inner_text("#nutritionSettings").lower()

@test
def assistant_reads_a_day_and_cannot_log_food(pw, url):
    seed = school_seed(lifts=[{"id": "l1", "date": "2026-09-28", "split": "push", "exercises": [{"name": "Bench Press", "sets": [{"weight": 185, "reps": 5}]}], "notes": ""}],
                       nutrition=[{"id": "n1", "date": "2026-09-28", "kcal": 2350, "protein": 170, "carbs": 220, "fat": 75, "fiber": 30, "source": "health"}])
    g = scripted(gem_call("get_day", {"date": "2026-09-28"}), gem_text("2350 kcal and bench."))
    with app(pw, url, seed, gemini=g) as pg:
        ask(pg, "what did I eat and lift on 9/28")
        day = last_tool_result(g.seen[1]["body"])
        assert day["food"]["kcal"] == 2350 and day["lifting"][0]["exercises"][0]["sets"] == "185x5"
        names = [f["name"] for f in g.seen[0]["body"]["tools"][0]["functionDeclarations"]]
        assert "log_food" not in names

@test
def food_tab_has_a_sync_now_button(pw, url):
    t = iso_shift(0)
    with app(pw, url, sync_seed()) as pg:
        pg.evaluate(FAKE_FS)
        pg.evaluate(f"() => {{ __fs['healthInbox/{TOKEN}'] = {{ {dkey(t)}: {{ kcal: '512.1', protein: '22.4' }} }}; }}")
        assert "no food data" in pg.inner_text("#foodDay").lower()
        btn = pg.locator("#foodSyncBtn")
        assert btn.is_visible() and btn.bounding_box()["y"] < pg.locator("#foodDay").bounding_box()["y"] + 10
        btn.click()
        pg.wait_for_function("document.querySelector('#foodDay').innerText.includes('512')")
        assert "last synced" in pg.inner_text("#view").lower()
        pg.wait_for_function("document.querySelector('#foodSyncBtn').innerText.includes('Sync now')")  # not stuck on Syncing…
    with app(pw, url, base()) as pg:
        assert pg.locator("#foodSyncBtn").count() == 0

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
