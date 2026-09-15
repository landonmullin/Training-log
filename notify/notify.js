// Sends the morning reminder to every subscribed user. Runs on a schedule via GitHub Actions.
import admin from "firebase-admin";
import webpush from "web-push";

const VAPID_PUBLIC = "BNAdUWt7aajWIowZt3k3vwiSVi9iQIhFs3JXXuuQZJyKs_-8RhvHU2U14XiIqeDuD3iwJgA82J7clLLK4-ISmE8";
const sa = JSON.parse(process.env.FIREBASE_SA);
admin.initializeApp({ credential: admin.credential.cert(sa) });
const db = admin.firestore();
webpush.setVapidDetails("mailto:noreply@example.com", VAPID_PUBLIC, process.env.VAPID_PRIVATE);

// local calendar date for a timezone, as YYYY-MM-DD
function localDate(tz, offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(d);
  const get = t => parts.find(p => p.type === t).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
function localHour(tz) {
  return +new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", hour12: false }).format(new Date());
}
const fmtTime = t => {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  const hh = h % 12 === 0 ? 12 : h % 12;
  return `${hh}${m ? ":" + String(m).padStart(2, "0") : ""}${h >= 12 ? "pm" : "am"}`;
};
// "Homework 1 - 10am"; timed items first in clock order, untimed after
const sortByTime = items => [...items].sort((a, b) => {
  if (!a.time && !b.time) return 0;
  if (!a.time) return 1;
  if (!b.time) return -1;
  return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
});
const line = it => it.time ? `${it.title} - ${fmtTime(it.time)}` : it.title;
const section = items => sortByTime(items).map(line).join("\n");

const SEND_HOUR = 8;               // local time to deliver
const FORCE = process.env.FORCE === "1";   // manual test run: ignore the hour + once-a-day guard, send to everyone
const snap = await db.collection("push").get();
let sent = 0, skipped = 0, removed = 0;

console.log(`FORCE=${FORCE} · ${snap.size} subscriber doc(s)`);
for (const doc of snap.docs) {
  const u = doc.data();
  const hasSub = !!(u.sub && u.sub.endpoint);
  console.log(`- ${doc.id}: name=${u.name||"?"} tz=${u.tz||"?"} sub=${hasSub?"yes":"MISSING"} items=${Array.isArray(u.items)?u.items.length:0} lastSent=${u.lastSent||"never"} keys=[${Object.keys(u).join(",")}]`);
  if (!hasSub) { console.log("  → skipped: no push subscription stored (enable reminders in the app)"); skipped++; continue; }
  const tz = u.tz || "America/Chicago";
  const today = localDate(tz, 0), tomorrow = localDate(tz, 1);
  const hour = localHour(tz);
  // only deliver in the target hour, once per day
  if (!FORCE && (hour !== SEND_HOUR || u.lastSent === today)) { console.log(`  → skipped: local hour ${hour} (sends at ${SEND_HOUR}), lastSent=${u.lastSent||"never"}`); skipped++; continue; }

  const items = Array.isArray(u.items) ? u.items : [];
  const dueToday = items.filter(i => i.date === today);
  const dueTomorrow = items.filter(i => i.date === tomorrow);
  if (!FORCE && !dueToday.length && !dueTomorrow.length) { await doc.ref.set({ lastSent: today }, { merge: true }); skipped++; continue; }

  // one notification per day that has something due, in the user's clean format
  const sends = [];
  if (dueToday.length)    sends.push({ title: "Due today:",    body: section(dueToday),    tag: "due-today-" + today });
  if (dueTomorrow.length) sends.push({ title: "Due tomorrow:", body: section(dueTomorrow), tag: "due-tomorrow-" + today });
  if (!sends.length) sends.push({ title: "Training Log", body: "Reminders are working. Nothing due today or tomorrow.", tag: "test-" + Date.now() });

  try {
    for (const n of sends) {
      await webpush.sendNotification(u.sub, JSON.stringify({ ...n, url: "./" }), { TTL: 6 * 3600 });
    }
    if (!FORCE) await doc.ref.set({ lastSent: today }, { merge: true });   // a test run never uses up the real 8am send
    console.log(`  → sent ✓ (${sends.map(x => x.title).join(" + ")})`); sent++;
  } catch (err) {
    if (err.statusCode === 404 || err.statusCode === 410) { await doc.ref.delete(); removed++; } // subscription expired
    else { console.error("  → send FAILED:", err.statusCode, err.body || err.message); skipped++; }
  }
}
console.log(`sent ${sent}, skipped ${skipped}, removed ${removed}`);
