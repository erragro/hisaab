/* Bootstrap: auth, hash routing, topbar, FAB, offline bar, menu, PWA. */
import { $, el, sheet, toast } from "./ui.js?v=20260906.3";
import { t, setLang, getLang, applyStatic, LANGS } from "./i18n.js?v=20260906.3";
import { onUser, signInGoogle, startPhoneSignIn, resetVerifier, signOut, currentUser } from "./auth.js?v=20260906.3";
import { api, pendingCount, onSync, flushQueue } from "./api.js?v=20260906.3";
import { renderHome, renderCase } from "./screens.js?v=20260906.3";
import { openAction } from "./actions.js?v=20260906.3";
import { showHelp } from "./help.js?v=20260906.3";

const view = $("#view");
let currentScreen = "home";
let activeUid = null;
let signingOut = false;

/* ---- language + text size (persisted) ---------------------------- */
setLang(getLang());
document.body.dataset.step = localStorage.getItem("hisaab.step") || "s";
applyStatic();

/* ---- auth gate -------------------------------------------------- */
function resetSignedInView() {
  window.__case = null;
  view.replaceChildren();
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}

function setAuthStatus(text, show = true) {
  const status = $("#authStatus");
  if (!status) return;
  status.textContent = text;
  status.hidden = !show;
}

function applyAuthState(user) {
  const previousUid = activeUid;
  activeUid = user?.uid || null;
  const landing = $("#landing");
  if (landing) landing.hidden = !!user;
  $("#app").hidden = !user;
  setAuthStatus("", false);
  if (user) {
    route();
    flushQueue();
  } else if (previousUid) {
    resetSignedInView();
  }
}

Promise.resolve(onUser(applyAuthState)).catch(() => {
  $("#landing").hidden = false;
  $("#app").hidden = true;
  setAuthStatus("", false);
  toast("We couldn't check your sign-in. Refresh and try again.");
});

async function endSession(message = "") {
  if (signingOut) return;
  signingOut = true;
  try {
    resetSignedInView();
    await signOut();
    if (message) toast(message);
  } catch {
    toast("Couldn't sign out. Please try again.");
  } finally {
    signingOut = false;
  }
}

const phoneForm = $("#phoneForm");
if (phoneForm) phoneForm.addEventListener("submit", onSendCode);
const googleBtn = $("#googleBtn");
if (googleBtn) googleBtn.onclick = async () => {
  if (googleBtn.disabled) return;
  googleBtn.disabled = true;
  googleBtn.textContent = "Opening Google…";
  try { await signInGoogle(); }
  catch (e) { const m = mapAuthErr(e); if (m) toast(m); }
  finally { googleBtn.disabled = false; googleBtn.textContent = t("auth.google"); }
};

async function onSendCode(e) {
  e.preventDefault();
  const raw = ($("#phoneInput").value || "").replace(/\D/g, "");
  if (raw.length !== 10) { toast(t("auth.badphone")); return; }
  const e164 = "+91" + raw;
  const btn = $("#sendCodeBtn");
  btn.disabled = true; btn.textContent = t("common.saving");
  try {
    const conf = await startPhoneSignIn(e164);
    openOtpSheet(e164, conf);
  } catch (err) { toast(mapAuthErr(err) || t("auth.err")); }
  btn.disabled = false; btn.textContent = t("auth.phone.send");
}

function openOtpSheet(e164, conf) {
  sheet(t("auth.otp.title"), (body, close) => {
    const otp = el("input", { class: "otp-input", inputmode: "numeric", maxlength: 6,
      autocomplete: "one-time-code", "aria-label": "code", placeholder: "••••••" });
    const verify = el("button", { class: "btn primary block lg", text: t("auth.otp.verify") });
    const resend = el("button", { class: "btn ghost block", style: "margin-top:8px",
      text: t("auth.otp.resend") });
    const change = el("button", { class: "btn ghost block", text: t("auth.otp.change") });

    async function submit() {
      const code = otp.value.replace(/\D/g, "");
      if (code.length !== 6) { otp.focus(); return; }
      verify.disabled = true; verify.textContent = t("common.saving");
      try { await conf.confirm(code); verify.textContent = "Signing you in…"; close(); }
      catch (err) {
        verify.disabled = false; verify.textContent = t("auth.otp.verify");
        toast(mapOtpErr(err)); otp.select();
      }
    }
    verify.onclick = submit;
    otp.addEventListener("input", () => {
      if (otp.value.replace(/\D/g, "").length === 6) submit();
    });
    resend.onclick = () => { close(); resetVerifier(); $("#phoneForm").requestSubmit(); };
    change.onclick = () => { close(); resetVerifier(); $("#phoneInput").focus(); };

    body.append(
      el("p", { class: "sheet-sub", text: t("auth.otp.sent") + " " + prettyPhone(e164) }),
      otp, verify, resend, change,
    );
    setTimeout(() => otp.focus(), 120);
  });
}

const prettyPhone = (e164) => e164.replace(/^(\+91)(\d{5})(\d{5})$/, "$1 $2 $3");

function mapAuthErr(err) {
  const c = (err && err.code) || "";
  if (c.includes("invalid-phone")) return t("auth.badphone");
  if (c.includes("too-many-requests")) return t("auth.toomany");
  if (c.includes("quota-exceeded")) return "SMS limit reached. Please try again later.";
  if (c.includes("billing-not-enabled")) return "Phone sign-in needs Firebase billing to send SMS.";
  if (c.includes("captcha") || c.includes("app-credential"))
    return "Phone verification security check failed. Refresh the page and try again.";
  if (c.includes("operation-not-allowed")) return "Phone sign-in is not enabled in Firebase.";
  if (c.includes("unauthorized-domain")) return "This website is not authorized for phone sign-in.";
  if (c.includes("popup-closed") || c.includes("cancelled-popup")) return "";
  return c ? `${t("auth.err")} (${c.replace(/^auth\//, "")})` : t("auth.err");
}

function mapOtpErr(err) {
  const c = (err && err.code) || "";
  if (c.includes("invalid-verification-code")) return t("auth.otp.wrong");
  if (c.includes("code-expired") || c.includes("session-expired"))
    return "This code has expired. Send a new code and try again.";
  return c ? `Couldn't verify the code (${c.replace(/^auth\//, "")})` : t("auth.otp.wrong");
}

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
    if (e?.status === 401) await endSession("Your sign-in expired. Please sign in again.");
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
      (v) => {
        setLang(v);
        close();
        // Rebuild the current view without reloading. Reloading loses the
        // in-memory demo session and is unnecessary for Firebase sessions.
        view.replaceChildren();
        requestAnimationFrame(() => route(true));
      }));
    body.append(seg(t("menu.textsize"),
      [["s", t("menu.textsize.s")], ["m", t("menu.textsize.m")], ["l", t("menu.textsize.l")]],
      document.body.dataset.step,
      (v) => { document.body.dataset.step = v; localStorage.setItem("hisaab.step", v); }));

    body.append(el("hr", { style: "border:0;border-top:1px solid var(--line);margin:8px 0 16px" }));
    body.append(el("button", { class: "btn ghost block", text: t("menu.export"),
      style: "margin-bottom:10px", onclick: exportData }));
    body.append(el("button", { class: "btn ghost block", text: t("menu.signout"),
      style: "margin-bottom:10px", onclick: async () => { close(); await endSession(); } }));
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
  try { await api("/account", { method: "DELETE" }); await endSession("Account deleted."); }
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
