/* Bootstrap: auth, hash routing, topbar, FAB, offline bar, menu, PWA. */
import { $, el, sheet, toast } from "./ui.js";
import { t, setLang, getLang, applyStatic, LANGS } from "./i18n.js";
import { onUser, signIn, signOut, currentUser } from "./auth.js";
import { api, pendingCount, onSync, flushQueue } from "./api.js";
import { renderHome, renderCase } from "./screens.js";
import { openAction } from "./actions.js";
import { showHelp } from "./help.js";

const view = $("#view");
let currentScreen = "home";

/* ---- language + text size (persisted) ---------------------------- */
setLang(getLang());
document.body.dataset.step = localStorage.getItem("hisaab.step") || "s";
applyStatic();

/* ---- auth gate -------------------------------------------------- */
const signInBtn = $("#signInBtn");
if (signInBtn) signInBtn.onclick = () => signIn().catch((e) => toast(e.message));

onUser((user) => {
  const landing = $("#landing");
  if (landing) landing.hidden = !!user;
  $("#app").hidden = !user;
  if (user) { route(); flushQueue(); }
});

/* ---- routing (hash) ------------------------------------------- */
window.addEventListener("hashchange", route);
document.addEventListener("hisaab:reload", () => route(true));

async function route(force) {
  if (!currentUser()) return;
  const m = location.hash.match(/#\/case\/([^/]+)/);
  const back = $("#backBtn"), fab = $("#fabWrap");
  try {
    if (m) {
      currentScreen = "case";
      back.hidden = false; fab.hidden = false;
      $("#topTitle").textContent = "Hisaab";
      await renderCase(view, m[1]);
    } else {
      currentScreen = "home";
      back.hidden = true; fab.hidden = true; closeFab();
      $("#topTitle").innerHTML = 'Hisaab <span class="dev">हिसाब</span>';
      await renderHome(view);
    }
  } catch (e) {
    console.error("route failed", e);
    view.innerHTML = `<div class="screen"><p class="empty">${t("err.generic")}</p></div>`;
    if (e?.status === 401) location.reload();
  }
}

$("#backBtn").onclick = () => location.hash = "#/";
$("#helpBtn").onclick = () => showHelp(currentScreen);

/* ---- FAB speed-dial ----------------------------------------- */
const fab = $("#fab"), fabActions = $("#fabActions");
let fabOpen = false;
function closeFab() { fabOpen = false; fab.classList.remove("open"); fabActions.classList.add("closed"); }
fab.onclick = () => {
  fabOpen = !fabOpen;
  fab.classList.toggle("open", fabOpen);
  fabActions.classList.toggle("closed", !fabOpen);
};
fabActions.querySelectorAll("[data-act]").forEach((b) =>
  b.onclick = () => { closeFab(); openAction(b.dataset.act); });

/* ---- menu -------------------------------------------------- */
$("#menuBtn").onclick = openMenu;
function openMenu() {
  sheet("☰", (body, close) => {
    const seg = (label, opts, cur, on) => {
      const s = el("div", { class: "seg" });
      const btns = opts.map(([v, txt]) => el("button", { text: txt,
        "aria-pressed": String(v === cur),
        onclick: () => { btns.forEach((b) => b.setAttribute("aria-pressed", "false"));
          btns[opts.findIndex((o) => o[0] === v)].setAttribute("aria-pressed", "true"); on(v); } }));
      btns.forEach((b) => s.append(b));
      return el("div", { style: "margin-bottom:18px" },
        [el("label", { text: label, style: "margin-bottom:8px" }), s]);
    };
    body.append(seg(t("menu.language"),
      LANGS.map((l) => [l.code, l.label]), getLang(),
      (v) => { setLang(v); close(); route(true); }));
    body.append(seg(t("menu.textsize"),
      [["s", t("menu.textsize.s")], ["m", t("menu.textsize.m")], ["l", t("menu.textsize.l")]],
      document.body.dataset.step,
      (v) => { document.body.dataset.step = v; localStorage.setItem("hisaab.step", v); }));

    body.append(el("hr", { style: "border:0;border-top:1px solid var(--line);margin:8px 0 16px" }));
    body.append(el("button", { class: "btn ghost block", text: t("menu.export"),
      style: "margin-bottom:10px", onclick: exportData }));
    body.append(el("button", { class: "btn ghost block", text: t("menu.signout"),
      style: "margin-bottom:10px", onclick: () => signOut() }));
    body.append(el("button", { class: "btn danger block", text: t("menu.delete"),
      onclick: deleteAccount }));
  });
}

async function exportData() {
  try {
    const data = await api("/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = el("a", { href: URL.createObjectURL(blob), download: "hisaab-export.json" });
    a.click();
  } catch (e) { toast(e.message); }
}
async function deleteAccount() {
  if (prompt(t("menu.delete.confirm")) !== "DELETE") return;
  try { await api("/account", { method: "DELETE" }); await signOut(); toast("Account deleted."); }
  catch (e) { toast(e.message); }
}

/* ---- offline bar ------------------------------------------ */
const bar = $("#offlineBar");
function syncBar() {
  const off = !navigator.onLine, pend = pendingCount();
  bar.hidden = !(off || pend);
  bar.textContent = off
    ? t("err.offline_sent")
    : (pend ? `Syncing ${pend}…` : "");
}
window.addEventListener("online", () => { syncBar(); });
window.addEventListener("offline", syncBar);
onSync(syncBar);
syncBar();

/* ---- PWA ------------------------------------------------- */
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/sw.js").catch(() => {});
