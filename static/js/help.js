/*
  Per-screen help (SARAL G8/G9: short, plain, reachable from every screen)
  plus a small plain-word → legal-term glossary (G5: jargon stays out of the
  main UI and lives here instead).
*/
import { sheet, el } from "./ui.js";
import { getLang } from "./i18n.js";

const HELP = {
  home: {
    en: ["Each card is one dispute. The coloured tag shows the closest deadline — red means act now.",
         "Tap a case to see everything on one thread: what happened, your proof, your deadlines, your documents."],
    hi: ["हर कार्ड एक विवाद है। रंगीन टैग सबसे नज़दीकी समय-सीमा दिखाता है — लाल का मतलब अभी करें।",
         "पूरा मामला एक जगह देखने के लिए कार्ड पर टैप करें: क्या हुआ, आपके सबूत, समय-सीमाएँ, दस्तावेज़।"],
  },
  case: {
    en: ["The card at the top is the one thing to do next, and how long you have. Hisaab works this out from your dates — it never guesses.",
         "The ＋ button adds proof, asks a question, makes a document, or adds dates.",
         "Every proof you add is locked into a record. If the record ever stops matching, Hisaab tells you."],
    hi: ["ऊपर वाला कार्ड बताता है अब क्या करना है और कितना समय है। हिसाब यह आपकी तारीख़ों से निकालता है — अंदाज़ा नहीं लगाता।",
         "＋ बटन से सबूत जोड़ें, सवाल पूछें, दस्तावेज़ बनाएँ, या तारीख़ें जोड़ें।",
         "हर सबूत एक रिकॉर्ड में बंद हो जाता है। अगर रिकॉर्ड कभी मेल न खाए, हिसाब आपको बताएगा।"],
  },
  evidence: {
    en: ["Save proof before the app blocks you out — the deactivation message, an earnings screen, a support chat, a payslip.",
         "Hisaab reads the picture and picks out the date, the amount and the reason. Check what it found; you can talk it through to fix anything."],
    hi: ["ऐप के ब्लॉक करने से पहले सबूत सहेजें — बंद होने का संदेश, कमाई की स्क्रीन, सपोर्ट चैट, पे-स्लिप।",
         "हिसाब तस्वीर पढ़कर तारीख़, रक़म और कारण निकालता है। जाँचें कि क्या मिला; कुछ ग़लत हो तो बात करके ठीक करें।"],
  },
  draft: {
    en: ["Hisaab writes the wording, then checks it against a list — the parties, a dated account, the exact amount, a deadline.",
         "It will not say 'ready' if the amount in the draft doesn't match your case, or if the time limit to file has already passed."],
    hi: ["हिसाब शब्द लिखता है, फिर एक सूची से जाँचता है — पक्ष, तारीख़ वाला ब्यौरा, सही रक़म, समय-सीमा।",
         "अगर मसौदे की रक़म आपके मामले से मेल न खाए, या दाख़िल करने का समय बीत चुका हो, तो यह 'तैयार' नहीं कहेगा।"],
  },
  dates: {
    en: ["Fill in only the dates that have actually happened. Hisaab computes each deadline and shows the working it used.",
         "For a blocked ID, the appeal to the platform's committee is due in 7 working days — weekends and holidays don't count."],
    hi: ["सिर्फ़ वही तारीख़ें भरें जो सच में हो चुकी हैं। हिसाब हर समय-सीमा निकालता है और हिसाब-किताब दिखाता है।",
         "ब्लॉक आईडी के लिए, प्लेटफ़ॉर्म की समिति में अपील 7 कार्य-दिवस में करनी होती है — शनिवार-रविवार और छुट्टियाँ नहीं गिनी जातीं।"],
  },
};

const GLOSSARY = {
  en: [
    ["Complaint to the platform", "the platform's Internal Dispute Resolution Committee (IDRC)"],
    ["Legal notice", "a demand notice before legal proceedings"],
    ["Consumer complaint", "a complaint to the Consumer Disputes Redressal Commission"],
    ["Labour complaint", "a claim to the Labour Commissioner / labour court"],
    ["Time limit to file", "the limitation period"],
  ],
  hi: [
    ["प्लेटफ़ॉर्म को शिकायत", "प्लेटफ़ॉर्म की आंतरिक विवाद समाधान समिति (IDRC)"],
    ["लीगल नोटिस", "कानूनी कार्रवाई से पहले माँग-पत्र"],
    ["उपभोक्ता शिकायत", "उपभोक्ता विवाद निवारण आयोग में शिकायत"],
    ["श्रम शिकायत", "श्रम आयुक्त / श्रम न्यायालय में दावा"],
    ["दाख़िल करने की समय-सीमा", "परिसीमा अवधि (limitation period)"],
  ],
};

export function showHelp(screen) {
  const lang = HELP[screen] && HELP[screen][getLang()] ? getLang() : "en";
  const lines = (HELP[screen] || HELP.home)[lang];
  const gloss = GLOSSARY[GLOSSARY[getLang()] ? getLang() : "en"];
  sheet("?", (body) => {
    const wrap = el("div", { class: "help" });
    lines.forEach((p) => wrap.append(el("p", { text: p })));
    wrap.append(el("h3", { text: "In legal words", style: "margin:6px 0 10px" }));
    gloss.forEach(([plain, term]) =>
      wrap.append(el("div", { class: "term", style: "margin-bottom:8px",
        html: `<b>${plain}</b> — ${term}` })));
    body.append(wrap);
  });
}
