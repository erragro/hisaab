// Hisaab frontend. Vanilla JS. Firebase Auth (Google) via CDN compat SDK.
// The Firebase web config below is NOT a secret (it identifies the project,
// not a credential). Fill it from Firebase console -> Project settings.

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signOut,
  onAuthStateChanged, connectAuthEmulator,
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";

const firebaseConfig = {
  apiKey: "REPLACE_ME",
  authDomain: "REPLACE_ME.firebaseapp.com",
  projectId: "REPLACE_ME",
};

const fb = initializeApp(firebaseConfig);
const auth = getAuth(fb);
if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
  try { connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true }); } catch {}
}

const newId = () => (crypto.randomUUID ? crypto.randomUUID()
  : String(Date.now()) + Math.random().toString(16).slice(2));

// ---- api helper ---------------------------------------------------------
async function api(path, { method = "GET", body, idempotencyKey } = {}) {
  const token = await auth.currentUser.getIdToken();
  const res = await fetch("/api" + path, {
    method,
    headers: {
      "Authorization": "Bearer " + token,
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || res.statusText);
  return data;
}

const $ = (s) => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
function toast(msg) {
  const t = el("div", "toast", msg); document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

// ---- auth wiring ------------------------------------------------------
$("#signInBtn").onclick = () => signInWithPopup(auth, new GoogleAuthProvider()).catch(e => toast(e.message));
$("#signOutBtn").onclick = () => signOut(auth);
$("#menuBtn").onclick = () => $("#menu").toggleAttribute("hidden");
$("#exportBtn").onclick = async () => {
  const data = await api("/export");
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = "hisaab-export.json"; a.click();
};
$("#deleteBtn").onclick = async () => {
  if (prompt("This permanently deletes your account and every case. Type DELETE to confirm.") !== "DELETE") return;
  await api("/account", { method: "DELETE" });
  await signOut(auth);
  toast("Account deleted.");
};

onAuthStateChanged(auth, (user) => {
  const on = !!user;
  $("#landing").hidden = on;
  $("#app").hidden = !on;
  $("#whoami").hidden = !on;
  if (on) { $("#email").textContent = user.email || ""; loadCases(); }
});

// ---- cases list -----------------------------------------------------
$("#newCaseBtn").onclick = () => $("#newCaseDialog").showModal();
$("#newCaseForm").addEventListener("submit", async (e) => {
  if (e.submitter?.value !== "ok") return;
  const f = new FormData(e.target);
  const body = {
    title: f.get("title"), issue_type: f.get("issue_type"),
    platform: f.get("platform"),
    amount_claimed_inr: f.get("amount_claimed_inr") ? Number(f.get("amount_claimed_inr")) : null,
    incident_date: f.get("incident_date") || null,
  };
  const btn = e.submitter; if (btn) btn.disabled = true;
  try {
    const { id } = await api("/cases", { method: "POST", body, idempotencyKey: newId() });
    e.target.reset();
    await loadCases();
    openCase(id);
  } catch (err) { toast(err.message); }
  finally { if (btn) btn.disabled = false; }
});

async function loadCases() {
  const { cases } = await api("/cases");
  const ul = $("#caseList"); ul.innerHTML = "";
  if (!cases.length) ul.append(el("p", "fine", "No cases yet. Start one above."));
  for (const c of cases) {
    const li = el("li");
    li.append(el("div", "t", c.title));
    li.append(el("div", "m", `${c.platform} · ${c.issue_type.replace(/_/g, " ")}` +
      (c.amount_claimed_inr ? ` · ₹${c.amount_claimed_inr}` : "")));
    li.onclick = () => openCase(c.id);
    ul.append(li);
  }
}

// ---- one case -----------------------------------------------------
let CURRENT = null;

$("#backBtn").onclick = () => { $("#casePane").hidden = true; $("#caseListPane").hidden = false; CURRENT = null; };

document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabpane").forEach(p => p.hidden = p.id !== "tab-" + t.dataset.tab);
});

async function openCase(id) {
  CURRENT = id;
  $("#caseListPane").hidden = true;
  $("#casePane").hidden = false;
  const { case: c, messages, deadlines, drafts, evidence, lost_wages } =
    await api("/cases/" + id);
  $("#caseTitle").textContent = c.title;
  $("#caseSummary").textContent = c.summary || "You haven't talked this one through yet.";
  renderMessages(messages);
  renderDeadlines(deadlines);
  renderDrafts(drafts);
  renderEvidence(evidence, lost_wages);
}

// ---- evidence locker -------------------------------------------
const fileToB64 = (file) => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res(String(r.result).split(",", 2)[1] || "");
  r.onerror = rej;
  r.readAsDataURL(file);
});

$("#evidenceForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const file = f.get("file");
  if (!file || !file.size) return;
  if (file.size > 900_000) { toast("File is over 900 KB — crop or compress it."); return; }
  const btn = e.submitter; if (btn) btn.disabled = true;
  $("#evidenceChain").textContent = "Reading the file…";
  try {
    const body = {
      kind: f.get("kind"), filename: file.name, mime: file.type,
      data_b64: await fileToB64(file),
      captured_hint: f.get("captured_hint") || null,
    };
    const { degraded } = await api(`/cases/${CURRENT}/evidence`,
      { method: "POST", body, idempotencyKey: newId() });
    e.target.reset();
    if (degraded) toast("Saved. Couldn't auto-read the file — you can still use it.");
    await openCase(CURRENT);
  } catch (err) { toast(err.message); $("#evidenceChain").textContent = ""; }
  finally { if (btn) btn.disabled = false; }
});

function renderEvidence(items, lostWages) {
  items = items || [];
  const chain = $("#evidenceChain");
  chain.innerHTML = "";
  if (items.length) {
    const ok = items.every((x, i) =>
      x.seq === i + 1 && (i === 0 || x.prev_hash === items[i - 1].chain_hash));
    chain.append(el("span", null,
      `${items.length} item${items.length > 1 ? "s" : ""} · chain ${ok ? "intact ✓" : "BROKEN ✕"} · `));
    const a = el("button", "sm ghost", "Download appeal record");
    a.onclick = async () => {
      const m = await api(`/cases/${CURRENT}/appeal-record`);
      const blob = new Blob([JSON.stringify(m, null, 2)], { type: "application/json" });
      const u = URL.createObjectURL(blob);
      const link = el("a"); link.href = u; link.download = "appeal-record.json"; link.click();
    };
    chain.append(a);
  }

  const lw = $("#lostWages"); lw.innerHTML = "";
  if (lostWages) {
    const d = el("div", "dl soon");
    d.append(el("div", "lab", `Estimated lost earnings: ₹${lostWages.estimate_inr.toLocaleString("en-IN")}`));
    d.append(el("div", "due", lostWages.basis));
    lw.append(d);
  }

  const list = $("#evidenceList"); list.innerHTML = "";
  for (const it of items) {
    const card = el("div", "dl");
    const head = el("div", "lab",
      `#${it.seq} · ${it.kind.replace(/_/g, " ")} · ${it.filename}`);
    card.append(head);
    const ex = it.extracted || {};
    const bits = [];
    if (ex.observed_date) bits.push("date " + ex.observed_date);
    if (ex.amount_inr) bits.push("₹" + ex.amount_inr + (ex.period_days ? `/${ex.period_days}d` : ""));
    if (ex.rating) bits.push("rating " + ex.rating);
    if (ex.reason) bits.push("reason: " + ex.reason);
    (ex.refs || []).forEach(r => bits.push(r));
    if (ex.summary) card.append(el("div", "due", ex.summary));
    if (bits.length) card.append(el("div", "due", bits.join(" · ")));
    card.append(el("div", "fine",
      `saved ${new Date(it.captured_at).toLocaleString()} · sha256 ${it.sha256.slice(0, 16)}…`));
    list.append(card);
  }
}

function renderMessages(msgs) {
  const box = $("#messages"); box.innerHTML = "";
  for (const m of msgs) box.append(el("div", "msg " + m.role, m.text));
  box.scrollTop = box.scrollHeight;
}

$("#chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chatInput"); const text = input.value.trim();
  if (!text) return;
  input.value = ""; input.disabled = true;
  $("#messages").append(el("div", "msg user", text));
  try {
    const { reply, degraded } = await api(`/cases/${CURRENT}/chat`,
      { method: "POST", body: { message: text }, idempotencyKey: newId() });
    const m = el("div", "msg model" + (degraded ? " degraded" : ""), reply);
    $("#messages").append(m);
    // refresh summary
    const { case: c } = await api("/cases/" + CURRENT);
    $("#caseSummary").textContent = c.summary || "";
  } catch (err) { toast(err.message); }
  input.disabled = false; input.focus();
});

// ---- deadlines --------------------------------------------------
$("#deadlineForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    notice_sent: f.get("notice_sent") || null,
    notice_days: Number(f.get("notice_days") || 15),
    grievance_filed: f.get("grievance_filed") || null,
    platform_sla_days: f.get("platform_sla_days") ? Number(f.get("platform_sla_days")) : null,
  };
  try {
    const { deadlines } = await api(`/cases/${CURRENT}/deadlines`, { method: "POST", body });
    renderDeadlines(deadlines);
  } catch (err) { toast(err.message); }
});

function renderDeadlines(items) {
  const ul = $("#deadlineList"); ul.innerHTML = "";
  if (!items.length) { ul.append(el("p", "fine", "Add the dates above to compute your deadlines.")); return; }
  for (const d of items) {
    const cls = d.passed ? "dl passed" : (d.days_remaining <= 5 ? "dl soon" : "dl");
    const li = el("div", cls);
    li.append(el("div", "lab", d.label));
    li.append(el("div", "due",
      `${d.due_date} · ${d.passed ? Math.abs(d.days_remaining) + " days ago" : d.days_remaining + " days left"} · ${d.basis}`));
    ul.append(li);
  }
}

// ---- drafts + readiness ---------------------------------------
$("#draftForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = Object.fromEntries(f.entries());
  $("#draftOut").innerHTML = "<p class='fine'>Drafting…</p>";
  try {
    const { draft, readiness, degraded } = await api(`/cases/${CURRENT}/draft`,
      { method: "POST", body, idempotencyKey: newId() });
    renderDraft(draft, readiness, degraded);
  } catch (err) { toast(err.message); $("#draftOut").innerHTML = ""; }
});

function renderDraft(draft, r, degraded) {
  const out = $("#draftOut"); out.innerHTML = "";
  const box = el("div", "draft");
  if (degraded) box.append(el("p", "fine", "The assistant was unavailable — this is a template. Fill the [brackets]."));
  box.append(el("pre", null, draft.body));

  const rd = el("div", "readiness");
  rd.append(el("div", "bar " + (r.ready ? "ready" : "notready"),
    r.ready ? "Ready to send"
            : `Not ready — ${r.missing.length} required item(s) missing`));
  const passed = r.checks.filter(c => c.ok).length;
  rd.append(el("div", "fine", `${passed} of ${r.checks.length} checks passed`));
  for (const c of r.checks) {
    rd.append(el("div", "check " + (c.ok ? "ok" : "no"),
      c.label + (c.note ? " — " + c.note : "")));
  }
  box.append(rd);

  const copy = el("button", "sm", "Copy text");
  copy.onclick = () => { navigator.clipboard.writeText(draft.body); toast("Copied"); };
  box.append(copy);
  out.append(box);
}

function renderDrafts(list) {
  const out = $("#draftOut"); out.innerHTML = "";
  for (const d of list) renderDraft(d, d.readiness, false);
}
