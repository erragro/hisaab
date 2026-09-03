/*
  Firebase Auth (Google sign-in), loaded lazily so a blocked CDN (or the
  /demo.html preview) never breaks the rest of the app.
  The web config below is NOT a secret — it identifies the project, not a
  credential. Fill it from Firebase console → Project settings.
*/
const firebaseConfig = {
  apiKey: "REPLACE_ME",
  authDomain: "REPLACE_ME.firebaseapp.com",
  projectId: "REPLACE_ME",
};

// dev seam: /demo.html sets window.__mockUser to preview the UI without Firebase
const MU = () => (typeof window !== "undefined" ? window.__mockUser : null);

let _auth = null, _fb = null;

async function fb() {
  if (_auth) return _fb;
  const [{ initializeApp }, m] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js"),
  ]);
  const app = initializeApp(firebaseConfig);
  _auth = m.getAuth(app);
  if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
    try { m.connectAuthEmulator(_auth, "http://localhost:9099", { disableWarnings: true }); } catch {}
  }
  _fb = m;
  return m;
}

export async function onUser(cb) {
  if (MU()) { queueMicrotask(() => cb(MU())); return () => {}; }
  const m = await fb();
  return m.onAuthStateChanged(_auth, cb);
}
export async function signIn() {
  const m = await fb();
  return m.signInWithPopup(_auth, new m.GoogleAuthProvider());
}
export async function signOut() {
  if (MU()) { window.__mockUser = null; location.reload(); return; }
  const m = await fb();
  return m.signOut(_auth);
}
export function currentUser() { return MU() || (_auth && _auth.currentUser); }
export async function getToken() {
  if (MU()) return "mock-token";
  await fb();
  if (!_auth.currentUser) throw new Error("not signed in");
  return _auth.currentUser.getIdToken();
}
