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

def router(offline, gemini=None, wahoo=None):
    def handle(route):
        url = route.request.url
        if url.startswith("http://127.0.0.1"): return route.continue_()
        if offline: return route.abort()
        if "wahooligan.com" in url:
            if wahoo is None: return route.abort()
            out = wahoo(route.request)
            if out is None: return route.abort()
            status, body, ctype = out
            return route.fulfill(status=status, content_type=ctype, body=body, headers={**CORS, "Access-Control-Allow-Headers": "*"})
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
def app(pw, url, seed=None, offline=False, gemini=None, wahoo=None, path=""):
    b = pw.chromium.launch(executable_path=CHROME)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    if seed is not None:
        ctx.add_init_script(
            f"try{{if(!sessionStorage.getItem('seeded')){{localStorage.setItem({json.dumps(KEY)},{json.dumps(json.dumps(seed))});"
            "sessionStorage.setItem('seeded','1');}}catch(e){}")
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route("**/*", router(offline, gemini, wahoo))
    pg.goto(url + path); pg.evaluate("App.tab('food')")
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
        assert pg.locator(".cal .day .kbar.green").count() == 1
        assert pg.locator(".cal .day .kbar.red").count() == 1
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

@test
def goal_settings_set_bulk_mode_and_green_range(pw, url):
    ym = (_dt.date.today().replace(day=1) - _dt.timedelta(days=1)).isoformat()[:7]
    days = {f"{ym}-02": 2700, f"{ym}-03": 3050, f"{ym}-04": 3400}
    seed = base(nutrition=[{"id": d, "date": d, "kcal": k, "protein": 150, "carbs": 300, "fat": 90, "fiber": 30, "source": "health"} for d, k in days.items()])
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('weight')"); pg.evaluate("App.toggleTargets()")
        pg.click("#tMode button:has-text('Bulk')")
        pg.fill("#tKcal", "3000"); pg.fill("#tLow", "2900"); pg.fill("#tHigh", "3200")
        pg.click("#tSave")
        st = stored(pg)["settings"]
        assert st["kcalMode"] == "bulk" and st["kcalTarget"] == 3000 and st["kcalLow"] == 2900 and st["kcalHigh"] == 3200
        assert "2900" in pg.inner_text("#view") and "3200" in pg.inner_text("#view")
        pg.evaluate("App.tab('calendar')"); pg.evaluate("App.month(-1)")
        assert pg.locator(".cal .day .kbar.red").count() == 1      # 2700: under range while bulking
        assert pg.locator(".cal .day .kbar.green").count() == 1    # 3050
        assert pg.locator(".cal .day .kbar.yellow").count() == 1   # 3400: over range while bulking
        legend = pg.inner_text(".legend").lower()
        assert "in range" in legend and "over" in legend and "under" in legend
        pg.evaluate("App.tab('weight')"); pg.evaluate("ui.targetsOpen = true; render()")
        pg.fill("#tLow", ""); pg.fill("#tHigh", ""); pg.click("#tSave")
        st = stored(pg)["settings"]
        assert st["kcalLow"] is None and st["kcalHigh"] is None

@test
def food_tab_colors_follow_the_goal_mode(pw, url):
    d = base(nutrition=[{"id": "n", "date": iso_shift(0), "kcal": 1900, "protein": 150, "carbs": 200, "fat": 60, "fiber": 30, "source": "health"}])
    d["settings"].update({"kcalMode": "cut", "kcalTarget": 2300, "kcalLow": 2100, "kcalHigh": 2400})
    with app(pw, url, d) as pg:
        assert pg.get_attribute("#foodDay .kbig", "data-zone") == "yellow"   # 1900 is under the cutting range
        assert "2100–2400" in pg.inner_text("#foodGoalBtn")

@test
def food_tab_edits_the_calorie_goal_in_place(pw, url):
    d = base(nutrition=[{"id": "n", "date": iso_shift(0), "kcal": 2700, "protein": 150, "carbs": 300, "fat": 90, "fiber": 30, "source": "health"}])
    with app(pw, url, d) as pg:
        assert pg.get_attribute("#foodDay .kbig", "data-zone") == "red"      # 2700 over the 2400 cut goal
        assert "2400" in pg.inner_text("#foodGoalBtn")
        pg.click("#foodGoalBtn")
        pg.click("#tMode button:has-text('Bulk')")
        pg.fill("#tKcal", "2800"); pg.fill("#tLow", "2600"); pg.fill("#tHigh", "3000")
        pg.click("#tSave")
        st = stored(pg)["settings"]
        assert st["kcalMode"] == "bulk" and st["kcalTarget"] == 2800 and st["kcalLow"] == 2600 and st["kcalHigh"] == 3000
        assert pg.evaluate("ui.tab") == "food"
        assert pg.get_attribute("#foodDay .kbig", "data-zone") == "green"
        assert pg.locator("#tSave").count() == 0                               # editor closes after saving
        assert "bulk" in pg.inner_text("#foodGoalBtn").lower()


import struct
def make_fit(start_utc, seconds=600, power=150, cadence=86, hr0=125, sport=2):
    """Minimal cycling FIT: 1 Hz records (timestamp, HR, distance, power, cadence) + a session message."""
    FIT_EPOCH = 631065600
    t0 = int(start_utc.timestamp()) - FIT_EPOCH
    body = bytearray()
    def define(local, glob, fields):
        body.extend(bytes([0x40 | local, 0, 0]) + struct.pack("<H", glob) + bytes([len(fields)]))
        for num, size, base in fields: body.extend(bytes([num, size, base]))
    define(1, 20, [(253, 4, 0x86), (3, 1, 0x02), (5, 4, 0x86), (7, 2, 0x84), (4, 1, 0x02)])
    for i in range(seconds):
        hr = hr0 + (i * 25) // seconds
        body.extend(bytes([1]) + struct.pack("<IBIHB", t0 + i, hr, i * 700, power, cadence))
    define(2, 18, [(2, 4, 0x86), (5, 1, 0x00), (7, 4, 0x86), (8, 4, 0x86), (9, 4, 0x86), (16, 1, 0x02), (17, 1, 0x02), (20, 2, 0x84), (18, 1, 0x02)])
    body.extend(bytes([2]) + struct.pack("<IBIIIBBHB", t0, sport, seconds * 1000, seconds * 1000, seconds * 700, hr0 + 12, hr0 + 25, power, cadence))
    header = bytes([14, 0x10]) + struct.pack("<HI", 2132, len(body)) + b".FIT" + b"\x00\x00"
    return header + bytes(body) + b"\x00\x00"

REDIRECT = "/index.html"  # the page the harness serves
def wahoo_api(workouts, fit=None, details=None, token_log=None, summaries=None):
    """Fake Wahoo cloud: token endpoint, workouts list/detail, CDN FIT file."""
    def respond(req):
        u = req.url
        if "/oauth/token" in u:
            if token_log is not None: token_log.append(dict(x.split("=", 1) for x in (req.post_data or "").split("&")))
            return 200, json.dumps({"access_token": "ACC2", "refresh_token": "REF2", "expires_in": 7200, "token_type": "bearer"}), "application/json"
        if "/workout_summary" in u:
            wid = int(u.split("/v1/workouts/")[1].split("/")[0])
            return (200, json.dumps((summaries or {})[wid]), "application/json") if wid in (summaries or {}) else (404, "{}", "application/json")
        if "/v1/workouts/" in u:
            wid = int(u.split("/v1/workouts/")[1].split("?")[0])
            return 200, json.dumps((details or {})[wid]), "application/json"
        if "/v1/workouts" in u:
            return 200, json.dumps({"workouts": workouts, "total": len(workouts)}), "application/json"
        if u.endswith(".fit"):
            return (200, fit, "application/octet-stream") if fit is not None else None
        return None
    return respond
def ride(wid, start, summary=True, fit_url=None):
    w = {"id": wid, "starts": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "minutes": 10, "name": "KICKR ride", "workout_type_id": 12}
    if summary:
        w["workout_summary"] = {"duration_active_accum": "600.0", "distance_accum": "4200.0", "heart_rate_avg": "131.0",
            "power_avg": "152.0", "cadence_avg": "88.0", "calories_accum": "110.0", "file": {"url": fit_url} if fit_url else None}
    return w

@test
def wahoo_connect_starts_pkce_login(pw, url):
    with app(pw, url, base()) as pg:
        pg.evaluate("App.tab('settings')")
        pg.fill("#wahooClientId", "  MYCLIENTID ")
        with pg.expect_request(lambda r: "api.wahooligan.com/oauth/authorize" in r.url) as req:
            pg.click("#wahooConnect")
        from urllib.parse import urlparse, parse_qs
        q = {k: v[0] for k, v in parse_qs(urlparse(req.value.url).query).items()}
        assert q["client_id"] == "MYCLIENTID" and q["state"] == "wahoo" and q["code_challenge_method"] == "S256"
        assert q["scope"] == "user_read workouts_read offline_data" and q["redirect_uri"].endswith("/index.html")
        assert len(q["code_challenge"]) == 43

@test
def wahoo_callback_imports_rides_with_fit_detail(pw, url):
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(hours=3)
    old = now - _dt.timedelta(days=60)
    log = []
    api = wahoo_api([ride(901, start, fit_url="https://cdn.wahooligan.com/901.fit"), ride(900, old)], fit=make_fit(start), token_log=log)
    seed = base(); seed["wahooApi"] = {"clientId": "CID", "pkceVerifier": "v" * 64}
    seed["settings"]["maxHr"] = 220
    with app(pw, url, seed, wahoo=api, path="?code=AUTHCODE&state=wahoo") as pg:
        pg.wait_for_function("data.cardio.some(c => c.wahooId === 901)")
        assert "code=" not in pg.evaluate("location.href")
        assert log[0]["grant_type"] == "authorization_code" and log[0]["code"] == "AUTHCODE" and log[0]["code_verifier"] == "v" * 64 and log[0]["client_id"] == "CID"
        st = stored(pg)
        c = [x for x in st["cardio"] if x.get("wahooId") == 901][0]
        assert c["type"] == "cycling" and c["avgPowerW"] == 150 and c["avgCadence"] == 86 and c["hrHist"] and c["maxHr"] >= 145  # ride file wins over summary
        assert not any(x.get("wahooId") == 900 for x in st["cardio"])          # older than the first-sync window
        assert st["wahooApi"]["refreshToken"] == "REF2" and "pkceVerifier" not in st["wahooApi"]
        pg.evaluate("App.tab('calendar')"); pg.evaluate(f"App.selDay('{start.astimezone().date().isoformat()}')")
        assert "150 W" in pg.inner_text("#view")

@test
def wahoo_uses_summary_when_fit_is_unreachable(pw, url):
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)
    api = wahoo_api([ride(902, start, fit_url="https://cdn.wahooligan.com/902.fit")], fit=None)
    seed = base(); seed["wahooApi"] = {"clientId": "CID", "accessToken": "ACC", "refreshToken": "REF", "expiresAt": 9999999999999}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 902][0]
        assert c["avgHr"] == 131 and c["durationSec"] == 600 and c["avgPowerW"] == 152 and not c.get("hrHist")

@test
def wahoo_refreshes_expired_token_and_skips_known_rides(pw, url):
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=5)
    log = []
    detail = {904: ride(904, start)}
    api = wahoo_api([ride(903, start), ride(904, start, summary=False)], details=detail, token_log=log)
    seed = base(cardio=[{"id": "x", "date": "2026-10-01", "type": "cycling", "name": "old", "distanceMi": 2.6, "durationSec": 600, "wahooId": 903}])
    seed["wahooApi"] = {"clientId": "CID", "accessToken": "OLD", "refreshToken": "REF", "expiresAt": 1}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        assert log and log[0]["grant_type"] == "refresh_token" and log[0]["refresh_token"] == "REF"
        ids = [x.get("wahooId") for x in stored(pg)["cardio"]]
        assert ids.count(903) == 1 and ids.count(904) == 1
        assert stored(pg)["wahooApi"]["accessToken"] == "ACC2"

@test
def wahoo_tokens_stay_out_of_backups(pw, url):
    seed = backup_seed(); seed["wahooApi"] = {"clientId": "CID", "clientSecret": "SECRET-WAHOO-SECRET", "accessToken": "SECRET-WAHOO-ACCESS", "refreshToken": "SECRET-WAHOO-REFRESH", "expiresAt": 5}
    with app(pw, url, seed) as pg:
        pg.evaluate(FAKE_FS); pg.evaluate("cloudBackup(true)")
        blob = json.dumps(pg.evaluate("__fs"))
        assert "SECRET-WAHOO" not in blob and "CID" in blob
        pg.evaluate("async () => { ui.pendingRestore = await cloudFetchBackup('ABC123', 'landon'); App.confirmRestore(); }")
        assert stored(pg)["wahooApi"]["refreshToken"] == "SECRET-WAHOO-REFRESH"

@test
def wahoo_uses_the_ride_file_sport_when_wahoo_type_is_unknown(pw, url):
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
    w = ride(950, start, fit_url="https://cdn.wahooligan.com/950.fit"); w["workout_type_id"] = 777; w["name"] = "Evening walk"
    api = wahoo_api([w], fit=make_fit(start, sport=11, power=0, cadence=0))
    seed = base(); seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 950][0]
        assert c["type"] == "walk", c["type"]
        assert not c.get("avgPowerW")

import gzip
@test
def wahoo_fills_in_earlier_imports_that_came_in_empty(pw, url):
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=20)
    w = ride(960, start, fit_url="https://cdn.wahooligan.com/960.fit"); w["workout_type_id"] = 6; w["name"] = "Afternoon Walk"
    api = wahoo_api([w], fit=gzip.compress(make_fit(start, sport=11, power=0, cadence=0)))   # forwarded file arrives gzipped
    d = start.astimezone().date().isoformat()
    seed = base(cardio=[{"id": "w1", "date": d, "type": "walk", "name": "Afternoon Walk", "distanceMi": 0, "durationSec": 2640,
                         "avgHr": None, "source": "wahoo", "wahooId": 960}])
    seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999, "lastSync": 1}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 960]
        assert len(c) == 1 and c[0]["id"] == "w1"
        assert c[0]["distanceMi"] > 2 and c[0]["hrHist"] and c[0]["avgHr"] and c[0]["type"] == "walk"

@test
def wahoo_records_what_each_import_got(pw, url):
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)
    w = ride(970, start, fit_url="https://cdn.wahooligan.com/970.fit"); w["workout_summary"]["heart_rate_avg"] = None
    api = wahoo_api([w], fit=None)   # file download fails
    seed = base(); seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        dbg = stored(pg)["wahooApi"]["debug"]
        assert dbg[0]["id"] == 970 and dbg[0]["typeId"] == 12 and "failed" in dbg[0]["file"].lower()
        assert "distance_accum" in dbg[0]["summary"] and "heart_rate_avg" not in dbg[0]["summary"]
        pg.evaluate("App.tab('settings')"); pg.click("#wahooDebug summary")
        assert "970" in pg.inner_text("#wahooDebug")
        # a workout that keeps failing is retried at most 3 times
        for _ in range(4): pg.evaluate("wahooSync(true)")
        assert [x for x in stored(pg)["cardio"] if x.get("wahooId") == 970][0]["wahooTries"] == 3

@test
def wahoo_rechecks_empty_imports_from_weeks_ago_and_explains_skips(pw, url):
    now = _dt.datetime.now(_dt.timezone.utc)
    old = now - _dt.timedelta(days=10)
    w = ride(980, old, fit_url="https://cdn.wahooligan.com/980.fit"); w["workout_type_id"] = 6
    done = ride(981, now - _dt.timedelta(days=1))
    api = wahoo_api([done, w], fit=make_fit(old, sport=11, power=0, cadence=0))
    seed = base(cardio=[
        {"id": "a", "date": old.astimezone().date().isoformat(), "type": "walk", "name": "Walk", "distanceMi": 0, "durationSec": 2640, "avgHr": None, "source": "wahoo", "wahooId": 980},
        {"id": "b", "date": "2026-10-05", "type": "cycling", "name": "Ride", "distanceMi": 9, "durationSec": 2700, "avgHr": 140, "hrHist": {"140": 2700}, "source": "wahoo", "wahooId": 981}])
    seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999, "lastSync": int(now.timestamp() * 1000)}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 980][0]
        assert c["distanceMi"] > 2 and c["hrHist"]
        dbg = {d["id"]: d for d in stored(pg)["wahooApi"]["debug"]}
        assert dbg[980]["file"] == "ok" and "already" in dbg[981]["file"]

@test
def wahoo_uses_the_summary_endpoint_and_a_30_day_window(pw, url):
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(days=4)              # older than lastSync - 3 days, arrived late from Strava
    bare = {"id": 990, "starts": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "minutes": 44, "name": "Afternoon Walk", "workout_type_id": 6}
    summ = {"distance_accum": "3500.0", "heart_rate_avg": "112.0", "duration_active_accum": "2640.0", "file": {"url": "https://cdn.wahooligan.com/990.fit"}}
    api = wahoo_api([bare], details={990: bare}, summaries={990: summ}, fit=make_fit(start, seconds=2640, sport=11, power=0, cadence=0))
    seed = base(); seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999, "lastSync": int(now.timestamp() * 1000)}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 990]
        assert len(c) == 1 and c[0]["type"] == "walk" and c[0]["distanceMi"] > 1 and c[0]["hrHist"]

@test
def wahoo_gives_exhausted_empty_imports_one_fresh_round(pw, url):
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(days=8)
    bare = {"id": 991, "starts": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "minutes": 44, "name": "Morning Walk", "workout_type_id": 6}
    summ = {"distance_accum": "3500.0", "heart_rate_avg": "110.0", "duration_active_accum": "2640.0", "file": None}
    api = wahoo_api([bare], details={991: bare}, summaries={991: summ})
    seed = base(cardio=[{"id": "m", "date": start.astimezone().date().isoformat(), "type": "walk", "name": "Morning Walk", "distanceMi": 0,
                         "durationSec": 2640, "avgHr": None, "source": "wahoo", "wahooId": 991, "wahooTries": 3}])
    seed["wahooApi"] = {"clientId": "CID", "accessToken": "A", "refreshToken": "R", "expiresAt": 9999999999999, "lastSync": int(now.timestamp() * 1000)}
    with app(pw, url, seed, wahoo=api) as pg:
        pg.evaluate("wahooSync(true)")
        c = [x for x in stored(pg)["cardio"] if x.get("wahooId") == 991][0]
        assert c["distanceMi"] > 2 and c["avgHr"] == 110


@test
def schedule_is_off_by_default_and_hidden(pw, url):
    with app(pw, url, base()) as pg:
        pg.evaluate("App.tab('calendar')")
        assert pg.locator("#planCard").count() == 0
        assert stored(pg) is None or not (stored(pg).get("settings") or {}).get("scheduleEnabled")

@test
def schedule_seeds_for_landon_and_sits_first_on_calendar(pw, url):
    seed = base(); seed["crew"] = {"name": "Landon"}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        pg.click("button[aria-label='Daily schedule']")
        p = stored(pg)["planner"]
        assert len(p["templates"]["SU"]) > 10 and len(p["alt"]["MO"]) > 5
        assert any(b["title"] == "Therapy" for b in p["alt"]["MO"])
        pg.evaluate("App.tab('calendar')")
        first = pg.evaluate("document.querySelector('#view').firstElementChild.id")
        assert first == "planCard", first
        assert pg.locator("#planCard .plrow").count() > 5

@test
def schedule_for_other_users_starts_empty(pw, url):
    seed = base(); seed["crew"] = {"name": "Avery"}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('settings')")
        pg.click("button[aria-label='Daily schedule']")
        assert not stored(pg)["planner"]["templates"]
        pg.evaluate("App.tab('planner')")
        assert pg.locator("text=Start from Landon's week").count() == 1

@test
def schedule_now_line_and_current_slot(pw, url):
    seed = base(settings={"kcalTarget": 2400, "proteinTarget": 180, "scheduleEnabled": True})
    blocks = [{"id": "a", "start": "04:00", "end": "23:59", "title": "All day thing", "note": ""},
              {"id": "b", "start": "03:59", "end": "", "title": "Bed", "note": ""}]
    seed["planner"] = {"templates": {d: blocks for d in ["SU","MO","TU","WE","TH","FR","SA"]}, "alt": {}, "overrides": {}, "flags": {}, "seeded": True}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('calendar')")
        assert pg.locator("#planCard .plnow").count() == 1
        hr = pg.evaluate("new Date().getHours()")
        if 4 <= hr < 23:
            assert pg.locator("#planCard .plcur").inner_text().find("All day thing") >= 0

@test
def schedule_day_edit_creates_override_and_resets(pw, url):
    seed = base(settings={"kcalTarget": 2400, "proteinTarget": 180, "scheduleEnabled": True})
    seed["planner"] = {"templates": {"WE": [{"id": "w", "start": "09:00", "end": "", "title": "Wake up", "note": ""}]},
                       "alt": {}, "overrides": {}, "flags": {}, "seeded": True}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('calendar')")
        pg.evaluate("App.selDay('2026-11-04')")  # a Wednesday, not today
        card = pg.locator("#planCard").last
        assert "Wake up" in card.inner_text()
        card.locator("#planEditBtn").click()
        pg.fill("#plStart", "11:00"); pg.fill("#plTitle", "Dentist"); pg.click("#plSave")
        ov = stored(pg)["planner"]["overrides"]["2026-11-04"]
        assert [b["title"] for b in ov] == ["Wake up", "Dentist"]
        assert stored(pg)["planner"]["templates"]["WE"][0]["title"] == "Wake up" and len(stored(pg)["planner"]["templates"]["WE"]) == 1
        pg.locator("text=Reset this day").click()
        assert "2026-11-04" not in stored(pg)["planner"]["overrides"]

@test
def schedule_therapy_checkbox_swaps_monday(pw, url):
    seed = base(settings={"kcalTarget": 2400, "proteinTarget": 180, "scheduleEnabled": True})
    seed["crew"] = {"name": "Landon"}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.planLoadSample(); App.tab('calendar'); App.selDay('2026-11-09')")
        card = pg.locator("#planCard").last
        assert "Therapy" not in card.locator(".plrow").all_inner_texts()[3]
        card.locator("#planTherapy").check()
        assert stored(pg)["planner"]["flags"]["2026-11-09"]["therapy"] is True
        txt = pg.locator("#planCard").last.inner_text()
        assert "8:15am" in txt and "Therapy" in txt and "therapy week" in txt

@test
def schedule_builder_edits_weekday_template(pw, url):
    seed = base(settings={"kcalTarget": 2400, "proteinTarget": 180, "scheduleEnabled": True})
    seed["planner"] = {"templates": {}, "alt": {}, "overrides": {}, "flags": {}, "seeded": True}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('planner'); App.planPickDow('TU')")
        pg.fill("#plStart", "09:00"); pg.fill("#plTitle", "Wake up"); pg.click("#plSave")
        pg.fill("#plStart", "08:00"); pg.fill("#plEnd", "08:30"); pg.fill("#plTitle", "Coffee"); pg.click("#plSave")
        assert [b["title"] for b in stored(pg)["planner"]["templates"]["TU"]] == ["Coffee", "Wake up"]
        pg.evaluate("App.planCopyDow('TU','TH')")
        assert len(stored(pg)["planner"]["templates"]["TH"]) == 2
        pg.click("button[aria-label='edit'] >> nth=0")
        pg.fill("#plTitle", "Coffee & soda"); pg.click("#plSave")
        assert stored(pg)["planner"]["templates"]["TU"][0]["title"] == "Coffee & soda"
        pg.click("button.del >> nth=0"); pg.click("button.del >> nth=0")
        assert len(stored(pg)["planner"]["templates"]["TU"]) == 1


import datetime as _dt
def _ago(days): return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
def _prog_seed(**settings):
    d = base(settings={"kcalTarget": 2400, "proteinTarget": 180, **settings})
    d["lifts"] = [
        {"id": "h1", "date": _ago(200), "split": "push", "notes": "", "exercises": [
            {"name": "Bench Press", "sets": [{"weight": 185, "reps": 5}, {"weight": 185, "reps": 5}]},
            {"name": "Barbell Row", "sets": [{"weight": 115, "reps": 10}]}]},
        {"id": "h2", "date": _ago(190), "split": "legs", "notes": "", "exercises": [
            {"name": "Squat", "sets": [{"weight": 225, "reps": 5}]},
            {"name": "Pull-Up", "sets": [{"weight": 0, "reps": 3}]}]},
    ]
    return d

@test
def program_off_by_default(pw, url):
    with app(pw, url, _prog_seed()) as pg:
        pg.evaluate("App.tab('lift')")
        assert pg.locator("text=Log freely").count() == 0
        assert pg.locator("text=+ Add movement").count() == 1
        pg.evaluate("App.tab('calendar')")
        assert pg.locator("text=Next lift").count() == 0

@test
def program_setup_reads_history(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')")
        pg.click("text=Bench · Squat · Pull-ups")
        txt = pg.inner_text("#view")
        assert "best 185×5" in txt and "best 225×5" in txt and "best 3 bodyweight reps" in txt, txt[:600]
        assert pg.input_value("#pgBenchH") == "130"      # 185x5 -> 5RM ~185, 28 wk away -> x0.7
        assert pg.input_value("#pgSquatH") == "160"
        assert pg.input_value("#pgPull") == "3"
        pg.click("text=Start the program")
        st = stored(pg)
        assert st["program"]["next"] == "UA" and st["settings"]["splitStyle"] == "ul"
        assert st["program"]["state"]["benchH"]["w"] == 130 and st["program"]["state"]["squatH"]["inc"] == 10
        assert st["program"]["state"]["pull"]["reps"] == [2, 2, 2, 2, 2]
        assert st["program"]["state"]["Barbell Row"]["w"] == 115
        assert "Start Upper A" in pg.inner_text("#view")

def _close_celebrate(pg):
    if pg.locator("#celebrate").count(): pg.click("#celebrate >> text=Nice")

def _start_program(pg):
    pg.evaluate("App.tab('lift')")
    pg.click("text=Bench · Squat · Pull-ups")
    pg.click("text=Start the program")
    pg.click("text=Start Upper A")

@test
def program_full_session_progresses(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        _start_program(pg)
        n_before = len(stored(pg)["lifts"])
        for i in range(3): pg.click(f"button[aria-label='Bench Press set {i+1}']")
        assert pg.locator("#restBar").count() == 1
        pg.wait_for_function("document.getElementById('restBar').style.display === 'flex'", timeout=3000)
        for i in range(5): pg.click(f"button[aria-label='Pull-Up set {i+1}']")
        # row: change set 1 weight to 120 and it carries to later sets
        row = pg.locator(".card", has_text="Barbell Row").locator("input[inputmode=decimal]")
        row.nth(0).fill("120")
        assert row.nth(2).input_value() == "120"
        for i in range(3):
            pg.locator(".card", has_text="Barbell Row").locator("input[inputmode=numeric]").nth(i).fill("12")
            pg.click(f"button[aria-label='Barbell Row set {i+1}']")
        pg.click("text=Finish workout")
        st = stored(pg)
        assert len(st["lifts"]) == n_before + 1
        w = st["lifts"][-1]
        assert w["split"] == "upper" and w["program"] == "UA"
        assert [e["name"] for e in w["exercises"]] == ["Bench Press", "Pull-Up", "Barbell Row"]
        assert [s["weight"] for s in w["exercises"][0]["sets"]] == [130, 130, 130]
        p = st["program"]
        assert p["state"]["benchH"]["w"] == 135
        assert p["state"]["pull"]["reps"] == [3, 2, 2, 2, 2]
        assert p["state"]["Barbell Row"]["w"] == 125
        assert p["next"] == "LA" and p["live"] is None
        assert "lb" in pg.inner_text("#celebrate") and "That's about" in pg.inner_text("#celebrate")
        _close_celebrate(pg)
        txt = pg.inner_text("#view")
        assert "Lower A" in txt and "130 → 135" in txt

@test
def program_missed_set_repeats_then_deloads(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        _start_program(pg)
        for k in range(2):
            if k: pg.evaluate("data.program.next='UA'; save(); render();"); pg.click("text=Start Upper A")
            pg.click("button[aria-label='Bench Press set 1']")
            pg.click("button[aria-label='Bench Press set 2']")
            pg.click("text=Finish workout")
            _close_celebrate(pg)
        m = stored(pg)["program"]["state"]["benchH"]
        assert m["w"] == 115 and m["fails"] == 0, m   # 130 -> miss -> miss -> 0.9 x 130 = 117 -> 115

@test
def program_calendar_card_and_resume(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        _start_program(pg)
        pg.click("button[aria-label='Bench Press set 1']")
        pg.evaluate("App.tab('calendar')")
        card = pg.locator(".card", has_text="Workout in progress")
        assert "1/" in card.inner_text()
        card.locator("text=Resume").click()
        assert pg.locator("button[aria-label='Bench Press set 1'][data-done='1']").count() == 1

@test
def program_free_logging_still_works(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')")
        pg.click("text=Log freely")
        assert pg.locator("text=+ Add movement").count() == 1
        pg.evaluate("App.addExercise('Dips')")
        pg.fill(".setgrid input >> nth=0", "0"); pg.fill(".setgrid input >> nth=1", "10")
        pg.click("text=Save workout")
        assert stored(pg)["lifts"][-1]["exercises"][0]["name"] == "Dips"

@test
def program_edit_plan_changes_weights(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')"); pg.click("text=Bench \u00B7 Squat \u00B7 Pull-ups"); pg.click("text=Start the program")
        pg.click("text=Edit plan")
        pg.click(".seg >> text=Lower A")
        pg.click("button[aria-label='edit Squat']")
        pg.fill(".pbedit input[placeholder='blank = set later']", "185")
        pg.click("text=Save plan")
        p = stored(pg)["program"]
        assert p["state"]["squatH"]["w"] == 185 and p["next"] == "UA"
        assert p["state"]["benchH"]["w"] == 130          # untouched exercises keep their weights

@test
def program_awake_toggle_and_abs(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        _start_program(pg)
        assert pg.is_checked("#pgAwake")
        pg.uncheck("#pgAwake")
        assert stored(pg)["settings"]["progAwake"] is False
        pg.evaluate("data.program.live=null; data.program.next='LA'; save(); render();")
        assert "Cable Crunch" in pg.inner_text("#view")


SAMPLE_PLAN = {"format": "training-log-plan", "version": 1, "name": "Push Legs", "schedule": "weekdays",
  "workouts": [
    {"name": "Push", "split": "push", "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "exercises": [
      {"name": "Bench Press", "main": True, "sets": 3, "reps": 5, "weight": 135, "progression": {"type": "linear", "increment": 5}},
      {"name": "Push-Up", "bodyweight": True, "sets": 2, "reps": 10, "progression": {"type": "reps"}}]},
    {"name": "Legs", "days": [], "exercises": [{"name": "Squat", "sets": 3, "repRange": [8, 12], "weight": None, "progression": {"type": "double", "increment": 5}}]}]}

@test
def plan_import_from_claude_reply(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')")
        pg.click("text=Import a plan from Claude")
        reply = "Here you go!\n```json\n" + json.dumps(SAMPLE_PLAN) + "\n```\nEnjoy"
        pg.fill("#pfText", reply)
        pg.click("text=Check plan")
        assert "push legs" in pg.inner_text("#view").lower()
        pg.click("text=Use this plan")
        p = stored(pg)["program"]
        assert p["plan"]["name"] == "Push Legs" and p["plan"]["schedule"] == "weekdays"
        assert p["state"]["Legs:Squat"]["w"] == 225      # filled from last logged squat
        assert "Start Push" in pg.inner_text("#view")    # Push runs every day → today
        pg.click("text=Start Push")
        for i in range(3): pg.click(f"button[aria-label='Bench Press set {i+1}']")
        pg.click("text=Finish workout")
        assert stored(pg)["lifts"][-1]["split"] == "push"
        assert stored(pg)["program"]["state"]["Push:Bench Press"]["w"] == 140

@test
def plan_import_shows_errors(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')"); pg.click("text=Import a plan from Claude")
        pg.fill("#pfText", '{"workouts":[{"name":"A","exercises":[{"name":"Row","sets":3}]}]}')
        pg.click("text=Check plan")
        txt = pg.inner_text("#view")
        assert "can't be imported" in txt and "reps must be" in txt
        assert pg.locator("text=Use this plan").count() == 0

@test
def plan_builder_build_drag_and_save(pw, url):
    with app(pw, url, _prog_seed(programEnabled=True)) as pg:
        pg.evaluate("App.tab('lift')"); pg.click("text=Build your own")
        pg.fill("#pbName", "My Split"); pg.fill("#pbWName", "Chest Day")
        pg.click("button.pbday >> text=Mon"); pg.click("button.pbday >> text=Thu")
        for n in ["Bench Press", "Dumbbell Fly", "Pull-Up"]:
            pg.fill("#pbNewEx", n); pg.click("button:text-is('Add')")
        names = lambda: [x["name"] for x in pg.evaluate("ui.planDraft.workouts[0].exercises")]
        assert names() == ["Bench Press", "Dumbbell Fly", "Pull-Up"]
        assert pg.evaluate("ui.planDraft.workouts[0].exercises[2].bodyweight") is True
        # drag Pull-Up to the top
        pg.evaluate("App.pbToggle(2)")
        h = pg.locator(".pbhandle").nth(2).bounding_box(); t = pg.locator(".pbhandle").nth(0).bounding_box()
        pg.mouse.move(h["x"] + 5, h["y"] + 5); pg.mouse.down()
        pg.mouse.move(t["x"] + 5, t["y"] + 2, steps=8); pg.mouse.move(t["x"] + 5, t["y"] - 10, steps=4); pg.mouse.up()
        assert names() == ["Pull-Up", "Bench Press", "Dumbbell Fly"], names()
        pg.click("button[aria-label='edit Bench Press']")
        pg.click(".pbedit >> text=Fixed reps")
        pg.select_option(".pbedit select", "linear")
        pg.fill(".pbedit input[placeholder='blank = set later']", "155")
        pg.click("text=Save plan")
        p = stored(pg)["program"]
        assert p["plan"]["name"] == "My Split" and p["plan"]["workouts"][0]["days"] == ["Mon", "Thu"]
        b = p["plan"]["workouts"][0]["exercises"][1]
        assert b["progression"]["type"] == "linear" and b["reps"] == 8
        assert p["state"]["W1:Bench Press"]["w"] == 155

@test
def plan_migrates_old_program(pw, url):
    seed = _prog_seed(programEnabled=True)
    seed["program"] = {"startedAt": "2026-11-12", "next": "UB", "log": [], "live": None,
        "main": {"benchH": {"w": 160, "fails": 0, "inc": 5}, "benchV": {"w": 140, "fails": 0, "inc": 5}, "squatH": {"w": 145, "fails": 0, "inc": 10}, "squatV": {"w": 115, "fails": 0, "inc": 5}},
        "pull": {"reps": [3, 3, 2, 2, 2], "added": 0}, "acc": {"Lat Pulldown": {"w": 120}}}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('lift')")
        txt = pg.inner_text("#view")
        assert "Upper B" in txt and "140 lb" in txt and "3·3·2·2·2" in txt, txt[:500]
        pg.click("text=Start Upper B")
        assert pg.input_value("#pgw-0-0") == "140"
        assert stored(pg)["program"]["state"]["Lat Pulldown"]["w"] == 120

@test
def trivia_counts_bodyweight_and_shows_on_level(pw, url):
    seed = _prog_seed()
    seed["weights"] = [{"id": "w1", "date": _ago(3), "lbs": 180}]
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('lift')")
        pg.evaluate("App.addExercise('Pull-Up')")
        pg.fill(".setgrid input >> nth=0", "0"); pg.fill(".setgrid input >> nth=1", "3")
        pg.click("text=Save workout")
        txt = pg.inner_text("#celebrate")
        assert "540 lb" in txt and "180 lb" in txt, txt
        _close_celebrate(pg)
        pg.evaluate("App.tab('progress')")
        assert "lifetime weight moved" in pg.inner_text("#view").lower()


@test
def plan_fix_swaps_ab_wheel_keeps_week(pw, url):
    seed = _prog_seed(programEnabled=True)
    seed["program"] = {"startedAt": _ago(1), "next": "LA", "live": None,
        "log": [{"date": _ago(1), "day": "UA", "changes": []}],
        "main": {"benchH": {"w": 160, "fails": 0, "inc": 5}, "benchV": {"w": 135, "fails": 0, "inc": 5}, "squatH": {"w": 135, "fails": 0, "inc": 10}, "squatV": {"w": 115, "fails": 0, "inc": 5}},
        "pull": {"reps": [3, 2, 2, 2, 2], "added": 0}, "acc": {"Ab Wheel": {"w": 0}}}
    with app(pw, url, seed) as pg:
        pg.evaluate("App.tab('lift')")
        txt = pg.inner_text("#view")
        assert "Lower A" in txt and "1/4 this week" in txt and "Upper A" in txt, txt[:600]
        assert "Ab Wheel" not in txt
        st = stored(pg)["program"]
        lb = [w for w in st["plan"]["workouts"] if w["id"] == "LB"][0]
        assert lb["exercises"][-1]["name"] == "Cable Crunch" and "cableCrunch" in st["fixes"]

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
