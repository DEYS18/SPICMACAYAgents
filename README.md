# SPIC MACAY APR Assistant (v2)

A voice-first assistant for SPIC MACAY coordinators. In one conversation, typed, spoken (Hindi, English, Hinglish, Marathi and other Indian languages) or tapped, it can file an **Artist Payment Request**, make a **poster**, send **Requests for Payment** and **pre-event guidelines**, or just produce the **documents**: any one of them, or all together. Administrators govern every email, document layout and behaviour from an **admin console**.

The previous assistant is still at `/assistant/classic`. The dashboard and the Convention and Movement guides are unchanged.
See `docs/REVIEW_AND_CHANGES.md` for the review, the reviewer comments (DC1 to DC15) and everything that changed; `docs/screenshots/` shows the phone, laptop and admin screens.

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
| Behind a proxy under a sub-path | set `URL_PREFIX=/spicmacay_ai_agent/New_AI_Portal`, or have the proxy send `X-Forwarded-Prefix` |

Use **one worker process**: the weekly-report scheduler and the classic assistant keep state per process. (The new assistant keeps its state in `instance/governance.db`, so it would be fine with more.)

**Serve the site over HTTPS.** Browsers only allow the microphone on `https://` or `localhost`; once on HTTPS also set `SESSION_COOKIE_SECURE=true`.

**Convention and Movement guides:** copy your existing `knowledge_index/` folder into the project root. It is not in this zip (142 MB).

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

- **Speak:** tap the mic and talk; it stops by itself when you pause. Hold it for push-to-talk, or press Alt+V on a keyboard. Pick the language at the top. The menu has: read replies aloud, hands-free (it listens again after each reply; say "bas" or "stop" to end), and check voice text before sending.
- **Tap to confirm:** when a name could mean several artists, institutions or campuses, cards appear; tap the right one.
- **The draft:** on a laptop it is on the right; on a phone tap "Details". Everything collected so far is there; tap any value to change it.
- **Attach (+):** a program poster (all its details are read into the draft), the main artist's photo, a circuit list (CSV or Excel), a cancelled cheque, program photos. On a laptop you can drag files onto the page.
- **Share:** APRs, invoices and posters have Share (WhatsApp and the like) and Download buttons.
- **Several posters at once:** for APRs you didn't file after each program, choose **+ > Several posters at once** (or drag up to 20 posters onto the page). The assistant:
  - reads them all;
  - merges events that appear on two posters;
  - groups the events into programs (Virasat, circuit or single);
  - leaves out what is already in the portal or needs no APR (such as a film screening);
  - shows one plan to check, where you tick what to file and fix anything marked by tapping.

  **File** then files every ticked program and emails each APR to the coordinators, or all of them in one email. Finally you choose which institutions get a Request for Payment, and how much. See `docs/REAL_POSTER_TEST.md` for a run with ten real posters.

## Admin console

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

75 tests (including the ten real posters in `tests/test_real_posters.py`) run against an in-memory copy of the portal schema with a scripted AI, so no database, API key or network is needed.

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
