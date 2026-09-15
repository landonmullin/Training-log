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
  return ` ${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")}${h >= 12 ? "pm" : "am"}`;
};
const line = it => `${it.title} (${it.cls})${fmtTime(it.time)}`;

const SEND_HOUR = 8;               // local time to deliver
const snap = await db.collection("push").get();
let sent = 0, skipped = 0, removed = 0;

for (const doc of snap.docs) {
  const u = doc.data();
  if (!u.sub || !u.sub.endpoint) { skipped++; continue; }
  const tz = u.tz || "America/Chicago";
  const today = localDate(tz, 0), tomorrow = localDate(tz, 1);
  const hour = localHour(tz);
  // only deliver in the target hour, once per day
  if (hour !== SEND_HOUR || u.lastSent === today) { skipped++; continue; }

  const items = Array.isArray(u.items) ? u.items : [];
  const dueToday = items.filter(i => i.date === today);
  const dueTomorrow = items.filter(i => i.date === tomorrow);
  if (!dueToday.length && !dueTomorrow.length) { await doc.ref.set({ lastSent: today }, { merge: true }); skipped++; continue; }

  const parts = [];
  if (dueToday.length) parts.push("Today: " + dueToday.map(line).join(" · "));
  if (dueTomorrow.length) parts.push("Tomorrow: " + dueTomorrow.map(line).join(" · "));
  const n = dueToday.length + dueTomorrow.length;
  const payload = JSON.stringify({
    title: `📚 ${n} thing${n > 1 ? "s" : ""} coming up`,
    body: parts.join("\n"),
    tag: "school-" + today,
    url: "./"
  });

  try {
    await webpush.sendNotification(u.sub, payload, { TTL: 6 * 3600 });
    await doc.ref.set({ lastSent: today }, { merge: true });
    sent++;
  } catch (err) {
    if (err.statusCode === 404 || err.statusCode === 410) { await doc.ref.delete(); removed++; } // subscription expired
    else { console.error("send failed for", doc.id, err.statusCode, err.body || err.message); skipped++; }
  }
}
console.log(`sent ${sent}, skipped ${skipped}, removed ${removed}`);
