/* The two screens: Home (case list) and Case (the one-thread timeline). */
import { $, el, markdown, pill, urgency, fmtDate, rupees } from "./ui.js?v=20260906.3";
import { t } from "./i18n.js?v=20260906.3";
import { api } from "./api.js?v=20260906.3";
import { openAction } from "./actions.js?v=20260906.3";

/* ---------- deadline vocabulary (plain words first) ---------------- */
const DL = {
  idrc_appeal:      { icon: "⏰", act: ["draft", "platform_grievance"] },
  idrc_disposal:    { icon: "⏳", act: null },
  idrc_grievance:   { icon: "⏳", act: null },
  platform_sla:     { icon: "⏳", act: null },
  notice_period:    { icon: "⏳", act: null },
  consumer_limitation: { icon: "⚖️", act: ["draft", "consumer_complaint"] },
  wage_limitation:  { icon: "⚖️", act: ["draft", "legal_notice"] },
  board_escalation: { icon: "↑", act: ["chat", null] },
  custom:           { icon: "📅", act: null },
};
const plainDeadline = (d) => ({
  idrc_appeal: "Appeal the block to the platform",
  idrc_disposal: "Platform's committee should decide by now",
  idrc_grievance: "Platform should have replied by now",
  platform_sla: "Platform's promised time runs out",
  notice_period: "The other side's time to reply runs out",
  consumer_limitation: "Last day to file a consumer complaint",
  wage_limitation: "Last window to claim the money",
  board_escalation: "Escalate to the Welfare Board",
  custom: d.label,
}[d.kind] || d.label);

/* ---------- HOME -------------------------------------------------- */
export async function renderHome(mount) {
  mount.innerHTML = "";
  const { cases } = await api("/cases");
  const wrap = el("div", { class: "screen" }, [
    el("h1", { text: t("home.title") }),
    el("p", { class: "sub", text: t("home.sub") }),
    el("button", { class: "btn primary block lg", text: t("home.new"),
      onclick: () => openAction("newcase") }),
  ]);

  if (!cases.length) {
    wrap.append(el("p", { class: "empty", text: t("home.empty") }));
  } else {
    const list = el("div", { class: "caselist" });
    for (const c of cases) list.append(caseCard(c));
    wrap.append(list);
  }
  mount.append(wrap);

  // enrich each card with its most-urgent deadline (one call per case)
  for (const c of cases) hydrateCard(c.id);
}

function caseCard(c) {
  const card = el("button", { class: "casecard", dataset: { id: c.id },
    onclick: () => location.hash = "#/case/" + c.id }, [
    el("div", { class: "t", text: c.title }),
    el("div", { class: "meta", text:
      `${c.platform} · ${t("issue." + c.issue_type)}` +
      (c.amount_claimed_inr ? " · " + rupees(c.amount_claimed_inr) : "") }),
    el("div", { class: "slot" }),
  ]);
  return card;
}

async function hydrateCard(id) {
  try {
    const { deadlines = [] } = await api("/cases/" + id);
    const next = pickNextDeadline(deadlines);
    const card = $(`.casecard[data-id="${id}"]`);
    if (!card) return;
    const slot = card.querySelector(".slot");
    if (!next) { slot.textContent = ""; return; }
    const sev = urgency(next);
    if (sev === "now") card.classList.add("flag");
    slot.replaceWith(el("div", { class: "slot" }, [
      pill(deadlinePillText(next), sev),
    ]));
  } catch {}
}

/* ---------- CASE (timeline) ------------------------------------- */
export async function renderCase(mount, id) {
  mount.innerHTML = "";
  const loading = el("div", { class: "screen" }, [el("p", { class: "empty", text: "…" })]);
  mount.append(loading);

  const data = await api("/cases/" + id);
  window.__case = data;                 // actions.js reads this for context
  loading.remove();

  const screen = el("div", { class: "screen" });
  screen.append(el("h1", { text: data.case.title }));
  if (data.case.summary)
    screen.append(el("p", { class: "sub", text: data.case.summary }));

  screen.append(nextStepCard(data));

  if (data.lost_wages)
    screen.append(lostWagesCard(data.lost_wages));

  if (data.evidence?.length)
    screen.append(recordStrip(data.evidence, id));

  screen.append(timeline(data));
  mount.append(screen);
  lazyThumbs(id, data.evidence || []);
}

function nextStepCard(data) {
  const step = computeNextStep(data);
  const card = el("div", { class: `nextstep ${step.sev}` }, [
    el("div", { class: "kicker", text: t("next.kicker") }),
    el("div", { class: "headline", text: step.headline }),
  ]);
  if (step.count != null) {
    card.append(el("div", { class: "count" }, [
      el("b", { text: Math.abs(step.count) }),
      el("span", { text: step.countLabel }),
    ]));
    if (step.due) card.append(el("div", { class: "why", text: t("next.act") === "" ? "" : ("by " + fmtDate(step.due)) }));
  }
  if (step.why) card.append(el("div", { class: "why", text: step.why }));
  if (step.action)
    card.append(el("button", { class: "btn primary block", text: t("next.act"),
      onclick: () => openAction(step.action[0], step.action[1]) }));
  return card;
}

export function computeNextStep(data) {
  const dls = (data.deadlines || []).slice()
    .sort((a, b) => a.days_remaining - b.days_remaining);
  const live = dls.filter((d) => d.days_remaining >= -21);
  const top = live[0];

  if (top) {
    const sev = urgency(top);
    const working = top.working_days_remaining != null;
    const n = working ? top.working_days_remaining : top.days_remaining;
    let countLabel;
    if (top.days_remaining < 0) countLabel = t("next.overdue");
    else if (top.days_remaining === 0) countLabel = t("next.today");
    else countLabel = working ? t("next.daysworking") : t("next.daysleft");
    const meta = DL[top.kind] || DL.custom;
    return {
      sev, headline: plainDeadline(top),
      count: top.days_remaining <= 0 ? 0 : n,
      countLabel, due: top.due_date,
      why: top.basis,
      action: meta.act,
    };
  }

  const notReady = (data.drafts || []).find((d) => d.readiness && !d.readiness.ready);
  if (notReady) {
    return {
      sev: "soon",
      headline: `Finish your ${t("dk." + notReady.kind)}`,
      why: (notReady.readiness.missing || []).join(" · "),
      action: ["draft", notReady.kind],
    };
  }

  return { sev: "ok", headline: t("next.none"), why: t("next.none.why") };
}

function pickNextDeadline(dls) {
  const live = dls.filter((d) => d.days_remaining >= -21)
    .sort((a, b) => a.days_remaining - b.days_remaining);
  return live[0] || null;
}
function deadlinePillText(d) {
  if (d.days_remaining < 0) return t("next.overdue");
  if (d.days_remaining === 0) return t("next.today");
  const working = d.working_days_remaining != null;
  const n = working ? d.working_days_remaining : d.days_remaining;
  return `${n} ${working ? t("next.daysworking") : t("next.daysleft")}`;
}

function lostWagesCard(lw) {
  return el("div", { class: "infocard" }, [
    el("div", { class: "kicker", text: t("case.lostwages") }),
    el("div", { class: "bignum", text: rupees(lw.estimate_inr) }),
    el("div", { class: "why", text: lw.basis }),
  ]);
}

function recordStrip(evidence, id) {
  const ok = evidence.every((e, i) =>
    e.seq === i + 1 && (i === 0 || e.prev_hash === evidence[i - 1].chain_hash));
  const strip = el("div", { class: "record" + (ok ? "" : " broken") }, [
    el("span", { text: ok ? "🔒" : "⚠️" }),
    el("span", { text: `${evidence.length} ` + (ok ? t("case.record") : t("case.record.broken")) }),
  ]);
  if (ok)
    strip.append(el("button", { class: "tl-more", text: t("case.download"),
      onclick: () => downloadRecord(id) }));
  return strip;
}

async function downloadRecord(id) {
  const m = await api("/cases/" + id + "/appeal-record");
  const blob = new Blob([JSON.stringify(m, null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: "appeal-record.json" });
  a.click();
}

/* ---- the timeline itself ---- */
function timeline(data) {
  const items = [];
  const { case: c, evidence = [], drafts = [], deadlines = [], messages = [] } = data;

  if (c.incident_date)
    items.push({ date: c.incident_date, node: "⚑", sev: "done",
      title: c.title, sub: t("issue." + c.issue_type) });
  else
    items.push({ date: c.createdAt, node: "•", sev: "done", title: "Case started" });

  for (const e of evidence) {
    const ex = e.extracted || {};
    const chips = [];
    if (ex.observed_date) chips.push(fmtDate(ex.observed_date));
    if (ex.amount_inr) chips.push(rupees(ex.amount_inr) + (ex.period_days ? `/${ex.period_days}d` : ""));
    if (ex.rating) chips.push("★ " + ex.rating);
    if (ex.reason) chips.push(ex.reason);
    (ex.refs || []).forEach((r) => chips.push(r));
    items.push({
      date: e.captured_at, node: evIcon(e.kind), sev: "done",
      title: t("evk." + e.kind), sub: ex.summary, chips,
      thumbFor: e.mime && e.mime.startsWith("image/") ? e.id : null,
    });
  }

  for (const d of drafts)
    items.push({
      date: d.createdAt, node: "📄", sev: "done",
      title: t("dk." + d.kind),
      right: d.readiness
        ? pill(d.readiness.ready ? t("draft.ready") : t("draft.notready"),
               d.readiness.ready ? "ok" : "now")
        : null,
      onclick: () => openAction("viewdraft", d.id),
    });

  if (messages.length)
    items.push({
      date: messages[messages.length - 1].ts, node: "💬", sev: "done",
      title: `${t("case.talked")} — ${messages.length} ${t("case.messages")}`,
      expand: messages,
    });

  for (const d of deadlines) {
    const sev = urgency(d);
    const future = d.days_remaining > 0;
    items.push({
      date: d.due_date, node: (DL[d.kind] || DL.custom).icon,
      sev, future,
      title: plainDeadline(d),
      sub: deadlinePillText(d) + (future ? "" : ` · ${fmtDate(d.due_date)}`),
    });
  }

  items.sort((a, b) => new Date(a.date) - new Date(b.date));

  const tl = el("div", { class: "timeline" });
  for (const it of items) tl.append(tlItem(it));
  return tl;
}

function tlItem(it) {
  const cls = ["tl-item", it.future ? "fut" : "", it.sev].filter(Boolean).join(" ");
  const row = el("div", { class: cls, onclick: it.onclick });
  row.append(el("div", { class: "node", text: it.node }));
  row.append(el("div", { class: "when", text: fmtDate(it.date) }));
  const what = el("div", { class: "what" });
  what.append(el("b", { text: it.title }));
  if (it.right) { what.style.display = "flex"; what.style.justifyContent = "space-between";
    what.style.gap = "10px"; what.append(it.right); }
  row.append(what);
  if (it.sub) row.append(el("div", { class: "when", text: it.sub }));
  if (it.chips?.length) {
    const ex = el("div", { class: "extra" });
    it.chips.forEach((ch) => ex.append(el("span", { class: "chip", text: ch })));
    row.append(ex);
  }
  if (it.thumbFor)
    row.append(el("img", { class: "tl-thumb", dataset: { thumb: it.thumbFor }, alt: "" }));
  if (it.expand) {
    let open = false;
    const box = el("div", { class: "tl-expand", hidden: true });
    it.expand.forEach((m) => {
      const msg = el("div", { class: "msg " + (m.role === "user" ? "user" : "model") });
      if (m.role === "user") msg.textContent = m.text;
      else msg.append(markdown(m.text));
      box.append(msg);
    });
    const btn = el("button", { class: "tl-more", text: "▾ show",
      onclick: (e) => { e.stopPropagation(); open = !open; box.hidden = !open;
        btn.textContent = open ? "▴ hide" : "▾ show"; } });
    row.append(btn, box);
  }
  return row;
}

const evIcon = (k) => ({
  deactivation_notice: "🚫", earnings_screen: "₹", ratings_screen: "★",
  support_chat: "💬", payslip: "🧾", other: "📎",
}[k] || "📎");

async function lazyThumbs(caseId, evidence) {
  const imgs = document.querySelectorAll("img[data-thumb]");
  for (const img of imgs) {
    try {
      const { evidence: e } = await api(`/cases/${caseId}/evidence/${img.dataset.thumb}`);
      if (e?.data_b64) img.src = `data:${e.mime};base64,${e.data_b64}`;
    } catch {}
  }
}
