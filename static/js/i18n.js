/*
  i18n — SARAL G11 (culturally responsive: local-language support).
  English and Hindi are filled; the switcher lists the others so the
  intent and the mechanism are visible. Unfilled keys fall back to English.
  Strings are plain-word first; the legal term lives in help.js.
*/

export const LANGS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "ta", label: "தமிழ்" },
  { code: "bn", label: "বাংলা" },
];

const STR = {
  en: {
    "landing.h1": "Your case, on one thread.",
    "landing.p": "A payment or deactivation dispute plays out over weeks. Hisaab keeps the whole thing in one place — talk it through, save your proof, see exactly what to do next and how long you have.",
    "landing.trust": "Private to you. Export or delete it any time.",
    "landing.disclaimer": "General information about process and drafting. Not legal advice.",

    "auth.phone.ph": "Your mobile number",
    "auth.phone.send": "Send code",
    "auth.google": "Continue with Google",
    "auth.badphone": "Enter your 10-digit mobile number",
    "auth.err": "Couldn't send the code. Check the number and try again.",
    "auth.toomany": "Too many attempts. Wait a while and try again.",
    "auth.otp.title": "Enter the code",
    "auth.otp.sent": "We sent a 6-digit code by SMS to",
    "auth.otp.verify": "Verify",
    "auth.otp.resend": "Send the code again",
    "auth.otp.change": "Change number",
    "auth.otp.wrong": "That code didn't match. Try again.",

    "home.title": "Your cases",
    "home.sub": "One thread per dispute.",
    "home.new": "＋ Start a new case",
    "home.empty": "No cases yet. Start one above.",
    "home.allclear": "Nothing needs you right now.",

    "fab.evidence": "Add proof",
    "fab.chat": "Ask a question",
    "fab.draft": "Make a document",
    "fab.deadlines": "Add dates",

    "next.kicker": "Your next step",
    "next.none": "You're on track",
    "next.none.why": "Nothing is due. Add proof or ask a question when something changes.",
    "next.daysleft": "days left",
    "next.daysworking": "working days left",
    "next.overdue": "overdue",
    "next.today": "due today",
    "next.act": "Do this now",

    "case.record": "proof · record intact",
    "case.record.broken": "record does not match — do not rely on it",
    "case.talked": "You talked this through",
    "case.messages": "messages",
    "case.download": "Download appeal record",
    "case.lostwages": "Estimated lost earnings",

    "new.title": "Start a case",
    "new.sub": "Just the basics. You can fill the rest by talking it through.",
    "new.t": "Short title",
    "new.t.ph": "e.g. Zomato withheld ₹2,400 — March",
    "new.issue": "What went wrong",
    "new.platform": "Which app / company",
    "new.platform.ph": "Zomato, Uber, Urban Company…",
    "new.amount": "Amount involved (₹)",
    "new.date": "When did it happen",
    "new.create": "Create case",
    "issue.unpaid_wages": "Payment not made",
    "issue.wrong_deduction": "Wrong deduction",
    "issue.deactivation": "ID blocked / deactivated",
    "issue.incentive_dispute": "Incentive not paid",
    "issue.accident_claim": "Accident / injury",
    "issue.other": "Something else",

    "ev.title": "Add proof",
    "ev.sub": "Save what you have before you lose app access. The screenshot, the message, the payslip.",
    "ev.kind": "What is this",
    "ev.date": "Date on it (if shown)",
    "ev.pick": "Take a photo or choose a file",
    "ev.hint": "Photo, screenshot or PDF · under 900 KB",
    "ev.add": "Add to record",
    "ev.reading": "Reading the file…",
    "evk.deactivation_notice": "The block / deactivation message",
    "evk.earnings_screen": "In-app earnings screen",
    "evk.ratings_screen": "Ratings / performance screen",
    "evk.support_chat": "Chat or email with support",
    "evk.payslip": "Payslip / payout statement",
    "evk.other": "Something else",

    "chat.title": "Talk it through",
    "chat.sub": "Say what happened, or ask what to do next. One step at a time.",
    "chat.ph": "Type here, or tap the mic to speak",
    "chat.send": "Send",
    "chat.mic": "Speak",

    "draft.title": "Make a document",
    "draft.sub": "Hisaab drafts the wording. It also checks the draft is actually ready before you send it.",
    "draft.kind": "Which document",
    "draft.you": "Your name",
    "draft.youraddr": "Your address",
    "draft.workerid": "Your worker / partner ID",
    "draft.to": "Send it to (name)",
    "draft.toaddr": "Their address",
    "draft.make": "Write the draft",
    "draft.copy": "Copy the text",
    "draft.ready": "Ready to send",
    "draft.notready": "Not ready yet",
    "draft.missing": "still missing",
    "draft.checkspassed": "of {n} checks passed",
    "dk.legal_notice": "Legal notice",
    "dk.platform_grievance": "Complaint to the platform",
    "dk.consumer_complaint": "Consumer complaint",
    "dk.labour_complaint": "Labour complaint",

    "dates.title": "Add dates",
    "dates.sub": "Hisaab works out your deadlines from these. It never guesses a date.",
    "dates.notice_sent": "Notice sent on",
    "dates.notice_days": "Days you gave them",
    "dates.grievance_filed": "Complaint to platform filed on",
    "dates.sla_days": "Days the platform promised",
    "dates.idrc_filed": "Appeal to platform's committee filed on",
    "dates.recompute": "Update deadlines",

    "menu.language": "Language",
    "menu.textsize": "Text size",
    "menu.textsize.s": "Normal", "menu.textsize.m": "Large", "menu.textsize.l": "Largest",
    "menu.export": "Download my data",
    "menu.delete": "Delete my account",
    "menu.signout": "Sign out",
    "menu.delete.confirm": "This permanently deletes your account and every case. Type DELETE to confirm.",

    "err.offline_sent": "Saved. It will send when you're back online.",
    "err.generic": "Something went wrong. Try again.",
    "common.close": "Close",
    "common.saving": "Saving…",
  },

  hi: {
    "landing.h1": "आपका मामला, एक ही जगह।",
    "landing.p": "पैसे या आईडी ब्लॉक का मामला हफ़्तों चलता है। हिसाब सब कुछ एक जगह रखता है — बात करें, सबूत सहेजें, और देखें कि अब क्या करना है और कितना समय बचा है।",
    "landing.trust": "सिर्फ़ आपके लिए। कभी भी डाउनलोड या डिलीट करें।",
    "landing.disclaimer": "प्रक्रिया और मसौदे की सामान्य जानकारी। यह कानूनी सलाह नहीं है।",

    "auth.phone.ph": "आपका मोबाइल नंबर",
    "auth.phone.send": "कोड भेजें",
    "auth.google": "Google से जारी रखें",
    "auth.badphone": "अपना 10 अंकों का मोबाइल नंबर डालें",
    "auth.err": "कोड नहीं भेजा जा सका। नंबर जाँचकर फिर कोशिश करें।",
    "auth.toomany": "बहुत ज़्यादा कोशिशें। थोड़ी देर बाद फिर कोशिश करें।",
    "auth.otp.title": "कोड डालें",
    "auth.otp.sent": "हमने SMS से 6 अंकों का कोड भेजा है",
    "auth.otp.verify": "सत्यापित करें",
    "auth.otp.resend": "कोड फिर भेजें",
    "auth.otp.change": "नंबर बदलें",
    "auth.otp.wrong": "कोड मेल नहीं खाया। फिर कोशिश करें।",

    "home.title": "आपके मामले",
    "home.sub": "हर विवाद के लिए एक धागा।",
    "home.new": "＋ नया मामला शुरू करें",
    "home.empty": "अभी कोई मामला नहीं। ऊपर से एक शुरू करें।",
    "home.allclear": "अभी कुछ ज़रूरी नहीं है।",

    "fab.evidence": "सबूत जोड़ें",
    "fab.chat": "सवाल पूछें",
    "fab.draft": "दस्तावेज़ बनाएँ",
    "fab.deadlines": "तारीख़ें जोड़ें",

    "next.kicker": "आपका अगला कदम",
    "next.none": "सब ठीक है",
    "next.none.why": "कुछ भी बाक़ी नहीं। बदलाव होने पर सबूत जोड़ें या सवाल पूछें।",
    "next.daysleft": "दिन बचे",
    "next.daysworking": "कार्य-दिवस बचे",
    "next.overdue": "समय बीत चुका",
    "next.today": "आज की समय-सीमा",
    "next.act": "अभी यह करें",

    "case.record": "सबूत · रिकॉर्ड सुरक्षित",
    "case.record.broken": "रिकॉर्ड मेल नहीं खाता — इस पर भरोसा न करें",
    "case.talked": "आपने इस पर बात की",
    "case.messages": "संदेश",
    "case.download": "अपील रिकॉर्ड डाउनलोड करें",
    "case.lostwages": "अनुमानित नुक़सान",

    "new.title": "मामला शुरू करें",
    "new.sub": "बस मूल बातें। बाक़ी बात करके भर सकते हैं।",
    "new.t": "छोटा शीर्षक",
    "new.t.ph": "जैसे: ज़ोमैटो ने ₹2,400 रोके — मार्च",
    "new.issue": "क्या ग़लत हुआ",
    "new.platform": "कौन सा ऐप / कंपनी",
    "new.platform.ph": "ज़ोमैटो, उबर, अर्बन कंपनी…",
    "new.amount": "जुड़ी हुई रक़म (₹)",
    "new.date": "यह कब हुआ",
    "new.create": "मामला बनाएँ",
    "issue.unpaid_wages": "भुगतान नहीं हुआ",
    "issue.wrong_deduction": "ग़लत कटौती",
    "issue.deactivation": "आईडी ब्लॉक / बंद",
    "issue.incentive_dispute": "इंसेंटिव नहीं मिला",
    "issue.accident_claim": "दुर्घटना / चोट",
    "issue.other": "कुछ और",

    "ev.title": "सबूत जोड़ें",
    "ev.sub": "ऐप का एक्सेस जाने से पहले जो है सहेज लें। स्क्रीनशॉट, संदेश, पे-स्लिप।",
    "ev.kind": "यह क्या है",
    "ev.date": "उस पर दिख रही तारीख़ (अगर हो)",
    "ev.pick": "फ़ोटो लें या फ़ाइल चुनें",
    "ev.hint": "फ़ोटो, स्क्रीनशॉट या PDF · 900 KB से कम",
    "ev.add": "रिकॉर्ड में जोड़ें",
    "ev.reading": "फ़ाइल पढ़ी जा रही है…",
    "evk.deactivation_notice": "ब्लॉक / बंद होने का संदेश",
    "evk.earnings_screen": "ऐप की कमाई की स्क्रीन",
    "evk.ratings_screen": "रेटिंग / प्रदर्शन स्क्रीन",
    "evk.support_chat": "सपोर्ट से चैट या ईमेल",
    "evk.payslip": "पे-स्लिप / भुगतान विवरण",
    "evk.other": "कुछ और",

    "chat.title": "बात करें",
    "chat.sub": "बताएँ क्या हुआ, या पूछें अब क्या करना है। एक बार में एक कदम।",
    "chat.ph": "यहाँ लिखें, या बोलने के लिए माइक दबाएँ",
    "chat.send": "भेजें",
    "chat.mic": "बोलें",

    "draft.title": "दस्तावेज़ बनाएँ",
    "draft.sub": "हिसाब शब्द लिखता है। भेजने से पहले जाँचता भी है कि मसौदा तैयार है या नहीं।",
    "draft.kind": "कौन सा दस्तावेज़",
    "draft.you": "आपका नाम",
    "draft.youraddr": "आपका पता",
    "draft.workerid": "आपकी वर्कर / पार्टनर आईडी",
    "draft.to": "किसे भेजना है (नाम)",
    "draft.toaddr": "उनका पता",
    "draft.make": "मसौदा लिखें",
    "draft.copy": "टेक्स्ट कॉपी करें",
    "draft.ready": "भेजने के लिए तैयार",
    "draft.notready": "अभी तैयार नहीं",
    "draft.missing": "अब भी बाक़ी",
    "draft.checkspassed": "में से {n} जाँच पास",
    "dk.legal_notice": "लीगल नोटिस",
    "dk.platform_grievance": "प्लेटफ़ॉर्म को शिकायत",
    "dk.consumer_complaint": "उपभोक्ता शिकायत",
    "dk.labour_complaint": "श्रम शिकायत",

    "dates.title": "तारीख़ें जोड़ें",
    "dates.sub": "हिसाब इन्हीं से आपकी समय-सीमाएँ निकालता है। तारीख़ का अंदाज़ा कभी नहीं लगाता।",
    "dates.notice_sent": "नोटिस भेजा गया",
    "dates.notice_days": "आपने कितने दिन दिए",
    "dates.grievance_filed": "प्लेटफ़ॉर्म को शिकायत की तारीख़",
    "dates.sla_days": "प्लेटफ़ॉर्म ने कितने दिन का वादा किया",
    "dates.idrc_filed": "प्लेटफ़ॉर्म की समिति में अपील की तारीख़",
    "dates.recompute": "समय-सीमाएँ अपडेट करें",

    "menu.language": "भाषा",
    "menu.textsize": "टेक्स्ट का आकार",
    "menu.textsize.s": "सामान्य", "menu.textsize.m": "बड़ा", "menu.textsize.l": "सबसे बड़ा",
    "menu.export": "मेरा डेटा डाउनलोड करें",
    "menu.delete": "मेरा खाता डिलीट करें",
    "menu.signout": "साइन आउट",
    "menu.delete.confirm": "यह आपका खाता और सभी मामले हमेशा के लिए मिटा देगा। पुष्टि के लिए DELETE लिखें।",

    "err.offline_sent": "सहेज लिया। ऑनलाइन होने पर भेज दिया जाएगा।",
    "err.generic": "कुछ ग़लत हुआ। फिर कोशिश करें।",
    "common.close": "बंद करें",
    "common.saving": "सहेजा जा रहा है…",
  },
};

let cur = localStorage.getItem("hisaab.lang") || "en";

export function setLang(code) {
  cur = STR[code] ? code : "en";
  localStorage.setItem("hisaab.lang", cur);
  document.documentElement.lang = cur;
  applyStatic();
}
export function getLang() { return cur; }

export function t(key, vars) {
  let s = (STR[cur] && STR[cur][key]) || STR.en[key] || key;
  if (vars) for (const k in vars) s = s.replace("{" + k + "}", vars[k]);
  return s;
}

/** translate every [data-t] node currently in the DOM */
export function applyStatic(root = document) {
  root.querySelectorAll("[data-t]").forEach((n) => { n.textContent = t(n.dataset.t); });
  root.querySelectorAll("[data-t-ph]").forEach((n) => { n.placeholder = t(n.dataset.tPh); });
}
