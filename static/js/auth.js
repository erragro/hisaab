/*
  Firebase Auth, loaded lazily so a blocked CDN (or the /demo.html preview)
  never breaks the rest of the app.

  Primary sign-in is phone number + OTP (the auth Indian users know from
  UPI / Aadhaar / every govt portal). "Continue with Google" is the
  one-tap secondary option. The backend does not care which was used —
  `verify_id_token` yields the same uid either way.

  The web config below is NOT a secret — it identifies the project, not a
  credential. Fill it from Firebase console → Project settings.
*/
const firebaseConfig = {
  apiKey: "AIzaSyBnlCSYL8F_cqnz3vpJjibwagOJd92NJiQ",
  authDomain: "gen-lang-client-0368265372.firebaseapp.com",
  projectId: "gen-lang-client-0368265372",
};

// dev seam: /demo.html explicitly enables mock auth, without Firebase or a
// real phone number.
const MU = () => (typeof window !== "undefined" ? window.__mockUser : null);
const isDemo = () => (typeof window !== "undefined" && window.__hisaabDemo === true);
const demoNavigate = (signedOut) => {
  const next = new URL(location.href);
  if (signedOut) next.searchParams.set("demoSignedOut", "1");
  else next.searchParams.delete("demoSignedOut");
  location.replace(next);
};

let _auth = null, _fb = null, _recaptcha = null;

async function fb() {
  if (_fb) return _fb;
  const [{ initializeApp }, m] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js"),
  ]);
  const app = initializeApp(firebaseConfig);
  _auth = m.getAuth(app);
  _auth.useDeviceLanguage();
  if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
    try { m.connectAuthEmulator(_auth, "http://localhost:9099", { disableWarnings: true }); } catch {}
  }
  _fb = m;
  return m;
}

async function verifier() {
  const m = await fb();
  if (!_recaptcha) {
    _recaptcha = new m.RecaptchaVerifier(_auth, "recaptcha-container", { size: "invisible" });
  }
  return _recaptcha;
}

export function resetVerifier() {
  try { _recaptcha && _recaptcha.clear(); } catch {}
  _recaptcha = null;
}

/* ---- state ---- */
export async function onUser(cb) {
  if (isDemo()) { queueMicrotask(() => cb(MU())); return () => {}; }
  const m = await fb();
  return m.onAuthStateChanged(_auth, cb);
}
export function currentUser() { return isDemo() ? MU() : (_auth && _auth.currentUser); }
export async function getToken() {
  if (isDemo()) return "demo:token";
  await fb();
  if (!_auth.currentUser) throw new Error("not signed in");
  return _auth.currentUser.getIdToken();
}
export async function signOut() {
  if (isDemo()) {
    window.__mockUser = null;
    demoNavigate(true);
    return;
  }
  const m = await fb();
  return m.signOut(_auth);
}

/* ---- phone (primary) ---- */
// returns a confirmation object; caller collects the code and calls .confirm(code)
export async function startPhoneSignIn(e164) {
  if (isDemo()) return { confirm: async () => {
    window.__mockUser = { uid: "demo", phone: e164 };
    demoNavigate(false);
  } };
  const m = await fb();
  const v = await verifier();
  try {
    return await m.signInWithPhoneNumber(_auth, e164, v);
  } catch (err) {
    resetVerifier();
    throw err;
  }
}

/* ---- google (secondary) ---- */
export async function signInGoogle() {
  if (isDemo()) {
    window.__mockUser = { uid: "demo", email: "demo@worker.in" };
    demoNavigate(false);
    return;
  }
  const m = await fb();
  return m.signInWithPopup(_auth, new m.GoogleAuthProvider());
}
