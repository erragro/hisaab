/* DOM helpers, bottom sheet, toast, urgency helpers. No framework. */
import { t, applyStatic } from "./i18n.js?v=20260906.3";

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

export function el(tag, props = {}, kids = []) {
  const n = document.createElement(tag);
  for (const k in props) {
    const v = props[k];
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k === "text") n.textContent = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v != null && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of [].concat(kids)) if (c != null && c !== false)
    n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
}

/* Render the small, safe Markdown subset used in model replies. Never use
   innerHTML for model/user content: replies are untrusted text. */
export function markdown(text) {
  const out = document.createDocumentFragment();
  let list = null;

  const inline = (target, value) => {
    const re = /\*\*([^*\n]+)\*\*/g;
    let at = 0, match;
    while ((match = re.exec(value))) {
      if (match.index > at) target.append(document.createTextNode(value.slice(at, match.index)));
      target.append(el("strong", { text: match[1] }));
      at = re.lastIndex;
    }
    if (at < value.length) target.append(document.createTextNode(value.slice(at)));
  };

  for (const line of String(text || "").replace(/\r/g, "").split("\n")) {
    const ordered = line.match(/^(\d+)[.)]\s+(.+)$/);
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    if (ordered || unordered) {
      const tag = ordered ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        if (ordered && Number(ordered[1]) !== 1) list.start = Number(ordered[1]);
        out.append(list);
      }
      const item = document.createElement("li");
      inline(item, ordered ? ordered[2] : unordered[1]);
      list.append(item);
      continue;
    }

    list = null;
    if (!line.trim()) continue;
    const p = document.createElement("p");
    inline(p, line);
    out.append(p);
  }
  return out;
}

export function toast(msg) {
  const n = el("div", { class: "toast", text: msg });
  $("#toastRoot").append(n);
  setTimeout(() => n.remove(), 3400);
}

/* ---- bottom sheet ------------------------------------------------- */
let openSheet = null;

export function sheet(title, buildBody, { sub } = {}) {
  closeSheet();
  const scrim = el("div", { class: "sheet-scrim", onclick: closeSheet });
  const body = el("div", { class: "sheet-body" });
  const s = el("div", { class: "sheet", role: "dialog", "aria-modal": "true" }, [
    el("div", { class: "grip" }),
    el("h2", { text: title }),
    sub ? el("p", { class: "sheet-sub", text: sub }) : null,
    body,
  ]);
  $("#sheetRoot").append(scrim, s);
  requestAnimationFrame(() => { scrim.classList.add("in"); s.classList.add("in"); });
  openSheet = { scrim, s };
  buildBody(body, closeSheet);
  applyStatic(s);
  return closeSheet;
}

export function closeSheet() {
  if (!openSheet) return;
  const { scrim, s } = openSheet; openSheet = null;
  scrim.classList.remove("in"); s.classList.remove("in");
  setTimeout(() => { scrim.remove(); s.remove(); }, 240);
}

/* ---- urgency ----------------------------------------------------- */
// map a deadline (or a bare day count) -> a severity bucket the whole UI shares.
// working-day deadlines are judged on working days (a 3-working-day window is
// urgent even though it's ~5 calendar days).
export function urgency(dl) {
  const d = typeof dl === "number" || dl == null ? dl : dl.days_remaining;
  const w = (dl && typeof dl === "object") ? dl.working_days_remaining : null;
  if (d == null) return "idle";
  if (d < 0) return "now";
  if (w != null) return w <= 4 ? "now" : (w <= 8 ? "soon" : "ok");
  if (d <= 3) return "now";
  if (d <= 10) return "soon";
  return "ok";
}

export function pill(label, sev) {
  return el("span", { class: `pill ${sev}` }, [el("span", { class: "dot" }), label]);
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString(document.documentElement.lang || "en",
    { day: "numeric", month: "short", year: "numeric" });
}

export function rupees(n) {
  if (n == null) return "";
  return "₹" + Number(n).toLocaleString("en-IN");
}

export function spinner() { return el("span", { class: "spinner" }); }

/** a labelled field: returns {wrap, input} */
export function field(labelText, input) {
  const l = el("label", { text: labelText }, [input]);
  return l;
}
