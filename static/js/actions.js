/* Bottom-sheet actions. Each is one task, one screen (SARAL G3/G7). */
import { sheet, closeSheet, el, $, toast, rupees, fmtDate } from "./ui.js";
import { t } from "./i18n.js";
import { api, newId, OfflineError, ApiError } from "./api.js";
import { showHelp } from "./help.js";

const caseId = () => (location.hash.match(/#\/case\/([^/]+)/) || [])[1];
const ctx = () => window.__case || {};
const reload = () => document.dispatchEvent(new Event("hisaab:reload"));

export function openAction(kind, arg) {
  ({
    newcase: sheetNewCase,
    evidence: sheetEvidence,
    chat: sheetChat,
    draft: () => sheetDraft(arg),
    viewdraft: () => sheetViewDraft(arg),
    deadlines: sheetDeadlines,
  }[kind] || (() => {}))();
}

/* ---- new case -------------------------------------------------- */
const ISSUES = ["unpaid_wages", "wrong_deduction", "deactivation",
  "incentive_dispute", "accident_claim", "other"];

function sheetNewCase() {
  sheet(t("new.title"), (body, close) => {
    const f = el("form");
    const title = el("input", { required: true, minlength: 3, maxlength: 140,
      placeholder: t("new.t.ph") });
    const issue = el("select", {}, ISSUES.map((i) =>
      el("option", { value: i, text: t("issue." + i) })));
    const platform = el("input", { required: true, maxlength: 60, placeholder: t("new.platform.ph") });
    const amount = el("input", { type: "number", min: 0, inputmode: "numeric" });
    const date = el("input", { type: "date" });
    f.append(
      el("label", { text: t("new.t") }, [title]),
      el("label", { text: t("new.issue") }, [issue]),
      el("label", { text: t("new.platform") }, [platform]),
      el("label", { text: t("new.amount") }, [amount]),
      el("label", { text: t("new.date") }, [date]),
      el("button", { class: "btn primary block lg", text: t("new.create") }),
    );
    f.onsubmit = async (e) => {
      e.preventDefault();
      const btn = f.querySelector("button"); btn.disabled = true;
      try {
        const { id } = await api("/cases", { method: "POST", idempotencyKey: newId(), body: {
          title: title.value.trim(), issue_type: issue.value,
          platform: platform.value.trim(),
          amount_claimed_inr: amount.value ? Number(amount.value) : null,
          incident_date: date.value || null,
        }});
        close();
        location.hash = "#/case/" + id;
      } catch (err) { btn.disabled = false; toast(errMsg(err)); }
    };
    body.append(f);
  }, { sub: t("new.sub") });
}

/* ---- evidence ------------------------------------------------- */
const EV_KINDS = ["deactivation_notice", "earnings_screen", "ratings_screen",
  "support_chat", "payslip", "other"];

function sheetEvidence() {
  const id = caseId();
  sheet(t("ev.title"), (body, close) => {
    const f = el("form");
    const kind = el("select", {}, EV_KINDS.map((k) =>
      el("option", { value: k, text: t("evk." + k) })));
    const date = el("input", { type: "date" });
    const file = el("input", { type: "file", required: true,
      accept: "image/png,image/jpeg,image/webp,application/pdf", capture: "environment" });
    const preview = el("div", { class: "preview", hidden: true });
    const status = el("div", { class: "sub", style: "min-height:1.4em" });

    file.onchange = () => {
      preview.innerHTML = ""; preview.hidden = true;
      const fl = file.files[0]; if (!fl) return;
      if (fl.size > 900_000) { toast("Over 900 KB — crop or compress it."); file.value = ""; return; }
      if (fl.type.startsWith("image/")) {
        const img = el("img", { alt: "" });
        img.src = URL.createObjectURL(fl); preview.append(img);
      } else preview.append(el("span", { class: "big", text: "🧾" }));
      preview.append(el("span", { text: fl.name })); preview.hidden = false;
    };

    f.append(
      el("label", { text: t("ev.kind") }, [kind]),
      el("label", { text: t("ev.date") }, [date]),
      el("label", { class: "dropzone", html: `<span class="big">📷</span><span>${t("ev.pick")}</span><span class="sub">${t("ev.hint")}</span>` }, [file]),
      preview, status,
      el("button", { class: "btn primary block lg", text: t("ev.add") }),
    );
    f.onsubmit = async (e) => {
      e.preventDefault();
      const fl = file.files[0]; if (!fl) return;
      const btn = f.querySelector("button.btn"); btn.disabled = true;
      status.textContent = t("ev.reading");
      try {
        const data_b64 = await toB64(fl);
        await api(`/cases/${id}/evidence`, { method: "POST", idempotencyKey: newId(), body: {
          kind: kind.value, filename: fl.name, mime: fl.type, data_b64,
          captured_hint: date.value || null,
        }});
        close(); reload(); toast("Added to your record.");
      } catch (err) {
        btn.disabled = false; status.textContent = "";
        if (err instanceof OfflineError) { close(); toast(t("err.offline_sent")); }
        else toast(errMsg(err));
      }
    };
    body.append(f);
  }, { sub: t("ev.sub") });
}

/* ---- chat --------------------------------------------------- */
function sheetChat() {
  const id = caseId();
  sheet(t("chat.title"), (body, close) => {
    const log = el("div", { class: "chat-log" });
    for (const m of (ctx().messages || []))
      log.append(el("div", { class: "msg " + (m.role === "user" ? "user" : "model"), text: m.text }));

    const ta = el("textarea", { rows: 2, placeholder: t("chat.ph"), maxlength: 4000 });
    const mic = el("button", { class: "btn mic", type: "button", text: "🎤", "aria-label": t("chat.mic") });
    const send = el("button", { class: "btn primary", type: "submit", text: t("chat.send") });
    wireMic(mic, ta);

    const form = el("form", { class: "chat-input" }, [ta, mic, send]);
    form.onsubmit = async (e) => {
      e.preventDefault();
      const text = ta.value.trim(); if (!text) return;
      ta.value = ""; ta.disabled = send.disabled = true;
      log.append(el("div", { class: "msg user", text }));
      log.scrollTop = log.scrollHeight;
      try {
        const { reply, degraded } = await api(`/cases/${id}/chat`,
          { method: "POST", idempotencyKey: newId(), body: { message: text } });
        log.append(el("div", { class: "msg model" + (degraded ? " degraded" : ""), text: reply }));
        reload();
      } catch (err) {
        if (err instanceof OfflineError) toast(t("err.offline_sent"));
        else { toast(errMsg(err)); log.append(el("div", { class: "msg model degraded", text: errMsg(err) })); }
      }
      ta.disabled = send.disabled = false; log.scrollTop = log.scrollHeight; ta.focus();
    };
    body.append(log, form);
    log.scrollTop = log.scrollHeight;
  }, { sub: t("chat.sub") });
}

function wireMic(btn, ta) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { btn.hidden = true; return; }
  const rec = new SR();
  rec.lang = { en: "en-IN", hi: "hi-IN", kn: "kn-IN", ta: "ta-IN", bn: "bn-IN" }[document.documentElement.lang] || "en-IN";
  rec.interimResults = false;
  let on = false;
  btn.onclick = () => { on ? rec.stop() : rec.start(); };
  rec.onstart = () => { on = true; btn.classList.add("rec"); };
  rec.onend = () => { on = false; btn.classList.remove("rec"); };
  rec.onresult = (e) => {
    const s = [...e.results].map((r) => r[0].transcript).join(" ");
    ta.value = (ta.value ? ta.value + " " : "") + s;
  };
}

/* ---- draft ------------------------------------------------- */
const DRAFT_KINDS = ["legal_notice", "platform_grievance", "consumer_complaint", "labour_complaint"];

function sheetDraft(preKind) {
  const id = caseId();
  sheet(t("draft.title"), (body, close) => {
    const f = el("form");
    const kind = el("select", {}, DRAFT_KINDS.map((k) =>
      el("option", { value: k, text: t("dk." + k), selected: k === preKind || null })));
    const you = el("input", { required: true, maxlength: 120 });
    const youAddr = el("input", { maxlength: 400 });
    const workerId = el("input", { maxlength: 80 });
    const to = el("input", { required: true, maxlength: 160 });
    const toAddr = el("input", { maxlength: 400 });
    const out = el("div");
    f.append(
      el("label", { text: t("draft.kind") }, [kind]),
      el("div", { class: "field-row two" }, [
        el("label", { text: t("draft.you") }, [you]),
        el("label", { text: t("draft.workerid") }, [workerId])]),
      el("label", { text: t("draft.youraddr") }, [youAddr]),
      el("div", { class: "field-row two" }, [
        el("label", { text: t("draft.to") }, [to]),
        el("label", { text: t("draft.toaddr") }, [toAddr])]),
      el("button", { class: "btn primary block lg", text: t("draft.make") }),
      out,
    );
    f.onsubmit = async (e) => {
      e.preventDefault();
      const btn = f.querySelector("button.btn"); btn.disabled = true;
      out.innerHTML = `<p class="sub">${t("common.saving")}</p>`;
      try {
        const { draft, readiness, degraded } = await api(`/cases/${id}/draft`,
          { method: "POST", idempotencyKey: newId(), body: {
            kind: kind.value, sender_name: you.value, sender_address: youAddr.value,
            sender_worker_id: workerId.value, recipient_name: to.value,
            recipient_address: toAddr.value,
          }});
        out.innerHTML = ""; out.append(draftView(draft, readiness, degraded));
        reload();
      } catch (err) { out.innerHTML = ""; toast(errMsg(err)); }
      btn.disabled = false;
    };
    body.append(f);
  }, { sub: t("draft.sub") });
}

function sheetViewDraft(draftId) {
  const d = (ctx().drafts || []).find((x) => x.id === draftId);
  if (!d) return;
  sheet(t("dk." + d.kind), (body) => body.append(draftView(d, d.readiness, false)));
}

function draftView(draft, r, degraded) {
  const wrap = el("div");
  if (degraded)
    wrap.append(el("p", { class: "sub", text: "The assistant was offline — this is a template. Fill the [brackets]." }));
  wrap.append(el("pre", { class: "draftbody", text: draft.body }));
  wrap.append(el("button", { class: "btn ghost block", text: t("draft.copy"),
    onclick: () => { navigator.clipboard.writeText(draft.body); toast("Copied"); } }));
  if (r) {
    wrap.append(el("div", { class: "ready-head " + (r.ready ? "yes" : "no"), style: "margin-top:16px" },
      [r.ready ? "✓ " + t("draft.ready") : "✕ " + t("draft.notready")]));
    const passed = r.checks.filter((c) => c.ok).length;
    wrap.append(el("div", { class: "sub", text: `${passed} ${t("draft.checkspassed", { n: r.checks.length })}` }));
    const checks = el("div", { class: "checks" });
    for (const c of r.checks)
      checks.append(el("div", { class: "check " + (c.ok ? "ok" : "no") },
        [c.label, c.note ? el("span", { class: "note", text: " — " + c.note }) : null]));
    wrap.append(checks);
  }
  return wrap;
}

/* ---- dates -------------------------------------------------- */
function sheetDeadlines() {
  const id = caseId();
  sheet(t("dates.title"), (body, close) => {
    const f = el("form");
    const noticeSent = el("input", { type: "date" });
    const noticeDays = el("input", { type: "number", min: 1, max: 90, value: 15, inputmode: "numeric" });
    const grievance = el("input", { type: "date" });
    const sla = el("input", { type: "number", min: 1, max: 180, inputmode: "numeric" });
    const idrc = el("input", { type: "date" });
    f.append(
      el("div", { class: "field-row two" }, [
        el("label", { text: t("dates.notice_sent") }, [noticeSent]),
        el("label", { text: t("dates.notice_days") }, [noticeDays])]),
      el("div", { class: "field-row two" }, [
        el("label", { text: t("dates.grievance_filed") }, [grievance]),
        el("label", { text: t("dates.sla_days") }, [sla])]),
      el("label", { text: t("dates.idrc_filed") }, [idrc]),
      el("button", { class: "btn primary block lg", text: t("dates.recompute") }),
    );
    f.onsubmit = async (e) => {
      e.preventDefault();
      const btn = f.querySelector("button"); btn.disabled = true;
      try {
        await api(`/cases/${id}/deadlines`, { method: "POST", idempotencyKey: newId(), body: {
          notice_sent: noticeSent.value || null,
          notice_days: Number(noticeDays.value || 15),
          grievance_filed: grievance.value || null,
          platform_sla_days: sla.value ? Number(sla.value) : null,
          idrc_appeal_filed: idrc.value || null,
        }});
        closeSheet(); reload();
      } catch (err) { btn.disabled = false; toast(errMsg(err)); }
    };
    body.append(f);
  }, { sub: t("dates.sub") });
}

/* ---- helpers ---------------------------------------------- */
function toB64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",", 2)[1] || "");
    r.onerror = rej; r.readAsDataURL(file);
  });
}
function errMsg(err) {
  if (err instanceof OfflineError) return t("err.offline_sent");
  if (err instanceof ApiError) return err.message;
  return t("err.generic");
}
