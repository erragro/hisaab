# Local UI end-to-end test plan

These five scenarios run against the self-contained demo fixture. They use
mock authentication and a local in-browser data store: no SMS, Firebase,
Firestore, Gemini, or Cloud Run data is touched. The screens and JavaScript
modules are the same ones used by the live app.

## Start the local demo

From the repository root, run:

```bash
python3 -m http.server 8800 --directory static
```

Then open [http://127.0.0.1:8800/demo.html](http://127.0.0.1:8800/demo.html).
Use a private/incognito window, or reload the page, before each scenario to
reset its local test data.

## 1. Google sign-in, home, and an existing case

1. Open `demo.html?demoSignedOut=1`.
2. Select **Continue with Google**.
3. Verify that **Your cases** appears once, with no login/landing screen
   flicker.
4. Open **Uber blocked my ID after a customer complaint**.
5. Verify the next-step card, estimated lost earnings, evidence record, and
   timeline appear. Select **Download appeal record** and confirm a JSON file
   is downloaded.

Expected: the user lands in the app exactly once and can view the evidence
chain and case modules without an authentication loop.

## 2. Phone OTP sign-in, create a case, and logout

1. Open `demo.html?demoSignedOut=1`.
2. Enter a ten-digit phone number and select **Send code**.
3. Enter any six digits and select **Verify**. (The demo deliberately accepts
   any six digits; it sends no real SMS.)
4. Select **Start a new case**, complete title, issue, platform, amount, and
   incident date, then select **Create case**.
5. Open the menu and select **Sign out**.

Expected: the new case opens, and sign-out returns to the landing screen with
no stale case content or hash route left behind.

## 3. Add proof and confirm the evidence record refreshes

1. Sign in through either demo method and open the Uber case.
2. Open the **+** action button, then **Add proof**.
3. Choose a small PNG/JPEG/PDF (under 900 KB), choose a proof type and date,
   then select **Add to record**.
4. Verify the preview appears before submission, followed by **Added to your
   record.** after submission.
5. Verify the timeline now includes the new proof and the proof-record count
   has increased.

Expected: file preview, base64 conversion, evidence action, record rendering,
and post-save case refresh all work together.

## 4. Ask a question, verify formatted reply, and create a draft

1. Open a case and choose **+** → **Ask a question**.
2. Enter `What should I save first?` and select **Send**.
3. Verify the response has a bold opening sentence and a numbered list; no
   literal `**` characters should appear.
4. Close the chat, choose **+** → **Make a document**, complete the required
   sender/recipient fields, and select **Write the draft**.
5. Verify the generated text, readiness result, and readiness checks appear.

Expected: chat messages, safe Markdown rendering, draft creation, and the
readiness UI all work in one continuous case flow.

## 5. Update dates, accessibility preferences, and clean session recovery

1. Open a case and choose **+** → **Add dates**.
2. Enter a platform-grievance date and SLA days, then select **Update
   deadlines**. Confirm the updated deadline appears after the case refresh.
3. Open the menu, change text size to **Largest**, then change language to
   **हिन्दी**. Confirm the screen rerenders and the preference remains after
   a reload.
4. Sign out, then use **Continue with Google** to sign in again.

Expected: deadline update, language and text-size persistence, logout cleanup,
and a fresh login all succeed without reload loops.

## Scope note

This is a UI end-to-end suite. Before release, separately run `make gate` for
the backend/unit-test gate, and test real Google and phone login once in the
Firebase staging project because external provider consent, reCAPTCHA, and SMS
delivery cannot be safely simulated in a local browser fixture.
