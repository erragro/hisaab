/*
  API client.
   - Bearer <Firebase ID token> on every call (uid is never sent in a body).
   - Idempotency-Key on every mutating call, so a retry from the offline
     queue can't act twice.
   - Writes made while offline are queued in localStorage and flushed on
     reconnect (optimistic-UI support). Reads while offline just throw.
*/
import { getToken } from "./auth.js?v=20260906.3";

export const newId = () =>
  (crypto.randomUUID ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2));

const QKEY = "hisaab.queue";
const queue = () => JSON.parse(localStorage.getItem(QKEY) || "[]");
const setQueue = (q) => localStorage.setItem(QKEY, JSON.stringify(q));
export const pendingCount = () => queue().length;

const listeners = new Set();
export const onSync = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const emit = () => listeners.forEach((f) => f());

export async function api(path, { method = "GET", body, idempotencyKey } = {}) {
  if (typeof window !== "undefined" && window.__mockApi)
    return window.__mockApi(path, { method, body });

  const token = await getToken();
  const headers = { Authorization: "Bearer " + token };
  if (body) headers["Content-Type"] = "application/json";
  const key = idempotencyKey || (method !== "GET" ? newId() : null);
  if (key) headers["Idempotency-Key"] = key;

  let res;
  try {
    res = await fetch("/api" + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
  } catch (netErr) {
    if (method !== "GET") { enqueue({ path, method, body, key }); throw new OfflineError(); }
    throw netErr;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || data.detail || res.statusText, res.status);
  return data;
}

export class ApiError extends Error { constructor(m, status) { super(m); this.status = status; } }
export class OfflineError extends Error { constructor() { super("offline"); this.offline = true; } }

function enqueue(item) { const q = queue(); q.push(item); setQueue(q); emit(); }

export async function flushQueue() {
  let q = queue();
  while (q.length) {
    const item = q[0];
    try {
      const token = await getToken();
      const headers = { Authorization: "Bearer " + token, "Idempotency-Key": item.key };
      if (item.body) headers["Content-Type"] = "application/json";
      const res = await fetch("/api" + item.path, {
        method: item.method, headers,
        body: item.body ? JSON.stringify(item.body) : undefined,
      });
      if (!res.ok && res.status >= 500) break;   // transient — retry later
    } catch { break; }                            // still offline
    q.shift(); setQueue(q); emit();
  }
}

window.addEventListener("online", flushQueue);
