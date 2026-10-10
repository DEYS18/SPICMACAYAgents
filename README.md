# SPIC MACAY APR Assistant (v2)

A voice-first assistant for SPIC MACAY coordinators. In one conversation, typed, spoken (Hindi, English, Hinglish, Marathi and other Indian languages) or tapped, it can file an **Artist Payment Request**, make a **poster**, send **Requests for Payment** and **pre-event guidelines**, or just produce the **documents**: any one of them, or all together. Administrators govern every email, document layout and behaviour from an **admin console**.

The previous assistant is still at `/assistant/classic`. The dashboard and the Convention and Movement guides are unchanged.
See `docs/REVIEW_AND_CHANGES.md` for the review, the reviewer comments (DC1 to DC15) and everything that changed; `docs/screenshots/` shows the phone, laptop and admin screens (`v24_*` for this release).

## New in 2.4 (coordinators' feedback, 10 Oct 2026)

- **Emails look like the earlier app's again:** gold banner, "With Our Thanks" pill, red-edged fact cards, gold amount box; the APR confirmation keeps its red banner. Enhanced with bank particulars in the Request for Payment, an attachment line, and a clean APR subject. Unedited templates upgrade by themselves; edited ones are kept (use **Reset to default** to take the new design).
- **The poster goes with the APR.** Uploaded poster, or one made in the conversation, is attached; for a single program with the main artist's photo on file, filing makes one. A poster made after filing is kept with the program and offered as an email with the APR. Requests for Payment re-attach it. Calendar invite (.ics) for upcoming events, as before.
- **Laptop screen:** the assistant's face on the left (greets with folded hands, lips move while replies are read aloud), the program at a glance on the right. On phones the face appears on the welcome and while speaking, with a Stop button.
- **Steady "Working on it" indicator:** the chat no longer jumps while the assistant works.
- Admin > Settings: `apr.attach_poster`, `apr.auto_poster`, `apr.calendar_invite`, `assistant.show_face`.

## Quick start

You need Python 3.11 or newer, the portal's MySQL database, an OpenAI API key and SMTP credentials.

```bash
python -m venv venv
venv\Scripts\activate                 # Linux or macOS: source venv/bin/activate
pip install -r requirements.txt       # on a Lilly-managed machine, through Artifactory (see below)
copy .env.example .env                # Linux or macOS: cp .env.example .env, then fill it in
python run.py
```

Open `http://localhost:5000/assistant`; the admin console is `http://localhost:5000/admin`.

The first start creates `instance/`: the governance database (templates with their history, settings, approvals, activity, saved conversations), generated documents, and emails saved during dry runs. **Back this folder up.**

**Installing packages on a Lilly-managed machine:** public PyPI is not permitted there, so point pip at Lilly's Artifactory first (see "Artifactory | Developer Platform Front Door"), then run `pip install -r requirements.txt`. On SPIC MACAY's own server plain pip is fine.

## Hosting

| Where | How |
|---|---|
| Windows | `python run.py` (uses waitress when `DEBUG` is not `true`) |
| Linux | `gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 --timeout 120 run:app` |
| Docker | `docker compose up -d --build` (keeps `./instance` and `./logs` on the host) |
| Behind a proxy under a sub-path | Works without settings. The app takes the sub-path from `X-Forwarded-Prefix` or from IIS's `X-Original-URL`, and otherwise uses addresses relative to each page. Setting `URL_PREFIX=/spicmacay_ai_agent/New_AI_Portal` is still recommended, so links in emails are complete |

Use **one worker process**: the weekly-report scheduler and the classic assistant keep state per process. (The new assistant keeps its state in `instance/governance.db`, so it would be fine with more.)

**Serve the site over HTTPS.** Browsers only allow the microphone on `https://` or `localhost`; once on HTTPS also set `SESSION_COOKIE_SECURE=true`.

**Convention and Movement guides:** copy your existing `knowledge_index/` folder into the project root. It is not in this zip (142 MB).

## Troubleshooting

**The screens look exactly as before (no new assistant, no admin console).** The server is still running the previous version. The most common cause is the package unzipped *inside* the old folder, so the old files keep running.

1. Check the startup line `APR Assistant 2.4.0 ...: ACTIVE`, or open `<your address>/health`.
2. Follow `docs/UPGRADE.md`.
3. Run `python e2e_check.py --url <your address>` to confirm which version the live site serves.


**"Refused to execute script ... MIME type ('text/html')" and "startWithMessage is not defined".** The page asked for its scripts at the site root (`https://spicmacay.in/static/...`) instead of under the app's sub-path, and the main website answered with an HTML page.

- **This version:** works under a sub-path without any setting.
- **Previous version, or an immediate fix:** set `URL_PREFIX` in `.env` to the part of the address before `/assistant` (for example `URL_PREFIX=/spicmacay_ai_agent/New_AI_Portal`), then restart. The startup line `[SPIC MACAY] URL_PREFIX resolved to: ...` shows what the app picked up.

**"Your API key has been invalidated" (`token_invalidated`, error 401).** OpenAI no longer accepts the key in `.env`: it was revoked, by someone in the OpenAI account or automatically by OpenAI.

1. Create a new secret key at platform.openai.com > API keys.
2. Put it in `OPENAI_API_KEY` in the server's `.env` and restart the app.
3. Confirm it with Admin > Overview > "Check the AI key now", or with `python e2e_check.py`.

The same check reports other problems: an empty balance, a model the key may not use, or a network block. Both assistants now say which problem it is instead of showing the raw error.

After upgrading, reload once with Ctrl+F5. Static files carry a version from then on, so browsers never keep stale scripts. If a file still fails to load, a red banner at the bottom of the page names it.

## Configuration

Everything is in `.env.example` with comments. The important ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the session cookie. Must be long and random. |
| `OPENAI_API_KEY` | AI conversation, poster and cheque reading, speech recognition and spoken replies. Without it, the draft can still be filled in by tapping. |
| `OPENAI_MODEL` | The conversation model (default for Admin > Settings > Assistant); `OPENAI_VISION_MODEL` for posters and cheques. GPT-4o, GPT-5.x and GPT-6 all work; see `docs/MODEL_AND_CONFIG.md`. |
| `DB_*` | The portal's MySQL database. |
| `SMTP_*`, `FROM_EMAIL` | Outgoing email. Without SMTP, emails are saved as files in `instance/outbox`. |
| `AUTH_MODE` | `open` (as before) or `email_otp`: coordinators sign in with a code emailed to an address in the coordinator directory, and are then recognised on every program. |
| `ADMIN_PASSWORD`, `ADMIN_EMAILS` | Who may open the admin console. |
| `GOOGLE_API_KEY` | Optional: Google Places for institutions and Knowledge Graph for artists. Wikipedia, Wikidata and OpenStreetMap work without it. |

Behaviour (default audience, finance CC list, bank details, signatory, photo rules, which skills are on, AI model, voice) lives in **Admin > Settings**, not in `.env`.

## Using the assistant

**The assistant (`/assistant`) combines the calm, conversation-first screen with the original assistant's know-how.**

**Its brain is the original SPIC MACAY assistant's playbook,** read word for word from `app/models/agent.py`:
- terminology, language and the conversation flow;
- the 300-attendee default, city and state best guesses, and coordinator email lookups;
- new artists and institutions, accompanying artists, photos, bank details;
- payment reminders, posters, and single, circuit and Virasat programs.

It drives this version's tools: better search, any date format, review cards, email previews, the batch flow, web look-ups, cheque reading and the portal's own APR records. A short section after the playbook explains how to carry it out with these tools. Questions about SPIC MACAY itself go to the original information agent, which reads the movement's own documents.

**Nothing is asked up front.** The welcome (in Hindi first, as before) is spoken as the screen opens; if the browser keeps the page silent, a *सुनिए · Tap to hear the welcome* button appears. Then the coordinator speaks, types or uploads a poster, and the assistant works out what they need:
- the APR, the Request for Payment, the pre-event guidelines or a poster;
- one at a time or together;
- for a new program or one already filed.

The next step appears as a small button only once it applies: after filing, *Make a poster · Send Request for Payment · Send pre-event guidelines*.

**Around the conversation:**
- **Quiet starters** under the message box: Upload a poster, Several posters at once, Pending payments, Upcoming programs, About SPIC MACAY.
- **The message box:** attach (+), the **speaker** (gold when replies are read aloud) and the mic.
- **The Details pill:** a progress ring and drawer.
- **Cards for choices:** tappable choices when names are close, the summary card with **File APR** and **Preview PDF**, a preview of every email with tick boxes.

**Several posters at once** reads up to 20 posters and files their APRs together (see `docs/REAL_POSTER_TEST.md`). The original screen stays available at `/assistant/classic`; it uses the same improved services underneath (`app/services/classic_bridge.py`).

## Admin console

### Governing the templates (Admin > Templates)

Reach the console from the portal's home page (**Management > Admin Console**), from the assistant's menu, or at `<your address>/admin`. It opens once `ADMIN_PASSWORD` or `ADMIN_EMAILS` is set in `.env`.

Every document and email the assistant produces is a governed template, grouped by what it is for:

| Group | Templates |
|---|---|
| **APR** | the APR PDF layouts for a single program, a circuit and a Virasat; the "APR filed" email; the several-APRs summary |
| **Request for Payment** | the email to the institution and the invoice document |
| **Event guidelines** | the guidelines email, and the guidelines document itself (the SOP and checklist PDF) |
| **Posters** | wording and options |
| **Other emails** | the email frame, the artist's thank-you, the Artist Care Group notice, coordinator requests, sign-in codes |
| **Assistant** | the house rules |

How editing works:
- **Every save is a new version.** Earlier versions stay in History and can be switched back on in one click; **Reset to default** brings back the original.
- **Edits are checked first.** Emails and layouts are previewed with sample data and test-rendered before saving, and **Send me a test** emails the saved version.
- **The major parts are protected.** If an edit leaves out something the original relies on (the APR number, an amount, the institution's name), saving stops and lists it: put it back, or confirm deliberately. Wording changes save straight away.
- **The guidelines document is versioned.** Upload a revised PDF as a new version; both assistants attach whichever version is active, and the original stays one click away. Uploaded versions are kept in `instance/documents/`: back it up with the rest of `instance/`.


Sign in at `/admin` with `ADMIN_PASSWORD`, or as a coordinator listed in `ADMIN_EMAILS`.

- **Templates:** every email, the APR layouts (single, circuit, Virasat), the Request for Payment document, poster wording and the assistant's house rules. Edit with widgets or directly, preview with sample data, send yourself a test, and switch back to any earlier version.
- **Settings:** organisation and bank details, APR defaults, email recipients, directory rules, web lookups, photo policy, AI model, voice, and an on/off switch for each optional skill.
- **Approvals:** provisional artists and institutions added by coordinators, and requests to add coordinators.
- **Directory flags:** artists who have passed away or should not be booked (31 well-known names are pre-loaded).
- **Activity:** every APR filed, email sent or saved, and change made in the console.

## End-to-end check on your server

`python e2e_check.py` checks the configuration, every configured OpenAI model, tool calling, the database (read-only) and the email login. Add `--posters`, `--file`, `--voice` or `--compare-models` for more; see `docs/MODEL_AND_CONFIG.md`. It never writes to the portal database and emails no one unless asked.

## Compatibility with the previous version

Every APR is written for the portal (`custom_apr`) and as the previous version wrote it (`apr_payment_request`). `python tools/old_code_compat_check.py --old-app <previous app folder> --db <copy> --this-is-a-copy` proves the previous version still reads them; see `docs/DATABASE_COMPATIBILITY.md`.

## Tests

```bash
python -m unittest discover -s tests -v     # or: pytest tests
# against a COPY of the portal database (MariaDB/MySQL); cleans up after itself:
SPICMACAY_TEST_DB="user:password@127.0.0.1:3306/drupal" SPICMACAY_TEST_DB_IS_A_COPY=yes python -m unittest tests.test_mariadb_integration -v
```

117 tests (including the ten real posters in `tests/test_real_posters.py`) run against an in-memory copy of the portal schema with a scripted AI, so no database, API key or network is needed.

## Where things are

| Path | What |
|---|---|
| `app/agents/` | The agent loop (`orchestrator.py`), prompts, the program draft and conversation state |
| `app/skills/` | The 14 skills and their 41 tools (`core_skills.py`, `output_skills.py`, `batch.py` for several posters at once) |
| `app/search/` | Directory search (artists, institutions, coordinators) and web lookups |
| `app/core/` | Dates, Indian-name handling, governance store, default templates, rendering, email, sign-in |
| `app/services/program_writer.py` | Writes a program the way the portal records it (custom_apr, event_series, event_list) in one transaction; see `docs/DATABASE_COMPATIBILITY.md` |
| `app/routes/assistant_api.py`, `app/routes/admin.py` | The assistant and admin APIs |
| `app/templates/assistant.html`, `admin.html`, `login.html` | The new pages; `assistant_classic.html` is the previous one |
| `app/static/js/assistant.js`, `voice.js`, `admin.js` | Interface, voice, admin console |
| `instance/` | Created at runtime; back it up |
