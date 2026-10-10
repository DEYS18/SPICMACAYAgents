# OpenAI models and configuration (October 2026)

## Is GPT-5.5 a good choice?

**Yes, it works, after the fixes in this release.**

GPT-5.5 was released on 23 April 2026 and is fully supported in the API, including the Chat Completions endpoint this app uses. It covers everything the app needs:
- function calling;
- image input (posters and cheques);
- structured (JSON) output;
- a 1M-token context.

Per OpenAI's model page, it costs **$5 per million input tokens and $30 per million output tokens**, or $0.50 for cached input. Its reasoning effort can be none, low, medium (the default), high or xhigh.

**Three things were wrong before this release:**

1. **The new assistant ignored your `OPENAI_MODEL`.** It used GPT-4o unless an administrator changed the model. It now takes `OPENAI_MODEL` as its default; a value saved in Admin > Settings still wins.
2. **The calls would have been rejected.** OpenAI's guidance is that reasoning models accept `temperature` and `top_p` only with reasoning effort "none". Both assistants always sent `temperature`. All calls now go through one layer (`app/agents/llm.py`) that:
   - sends a reasoning effort instead of `temperature` where needed;
   - renames `max_tokens` where the model requires it;
   - drops and remembers any optional parameter a model rejects.
   A compatibility layer applies the same rules to the classic assistant and the guides.
3. **It was slower and dearer than needed.** The default "medium" reasoning is more than a chat turn needs. The conversation now uses **low** effort (Admin > Settings > Assistant); poster and cheque reading uses **medium**, because accuracy matters most there.

## Newer models

OpenAI has since released two newer families:
- **GPT-5.6:** `gpt-5.6-sol`, plus the cheaper `-terra` and `-luna`.
- **GPT-6:** Astra, 6.1 Sol and Luna.

Their documentation says GPT-6 Astra and GPT-6.1 Sol need the **Responses API** for tool calling, and that GPT-6 Sol and Luna allow tools in Chat Completions only with reasoning effort "none". The app now switches to the Responses API automatically for GPT-6 models (Admin > Settings > Assistant > OpenAI API = auto). That path has been tested here only against a stand-in, so run the comparison below before switching.

## Recommendation

| Use | Model | Why |
|---|---|---|
| Reading posters and cheques | **gpt-5.5**, medium effort (`OPENAI_VISION_MODEL=gpt-5.5`) | Accuracy on dense posters matters most, and these calls are few |
| The conversation | Try **gpt-5.4-mini** at low effort; keep **gpt-5.5** if it misses steps | Many short tool-calling turns. GPT-5.4 Mini's input price ($0.75 per million) is a fraction of GPT-5.5's ($5) |
| Speech to text | **gpt-4o-transcribe** for Hindi and regional languages | More accurate than gpt-4o-mini-transcribe for Indian languages, at about twice the price per audio minute |
| Spoken replies | gpt-4o-mini-tts (unchanged) | |

**Decide with your own data.** Run this on your server:

    python e2e_check.py --compare-models gpt-5.5,gpt-5.4-mini --voice

It runs the same three-message circuit conversation on each model against a copy of your directory, and reports:
- seconds taken;
- whether the draft was completed;
- the tool calls made;
- the tokens used.

The voice check runs a Hindi sentence with artist names through both speech models. Add `gpt-5.6-terra` or `gpt-5.6-luna` to the comparison if your OpenAI organisation has access to them.

**Watching costs.** Admin > Overview now shows calls and input, cached and output tokens per model per day.

## Your `.env`: what to change

**Rotate first:** the OpenAI key, the SMTP (GMass) password, the MySQL root password for the server, the Aiven password and the ZeptoMail token. They were shared in a chat transcript. Delete the commented-out credentials too: a commented line is still a readable secret.

| Item | What happens now | Change |
|---|---|---|
| `SECRET_KEY` | A placeholder, so session cookies and the admin console can be forged | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Each defined twice; the last wins, so the app uses root/root on 127.0.0.1/drupal | Keep one block. Create a dedicated MySQL user with SELECT, INSERT and UPDATE on the portal tables |
| `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` | Not read by the app. `MYSQL_DB` holds the password, probably a copy-paste slip | Delete them |
| `SEND_WEEKLY_REPORTS_ON_APR_CREATE=true` | The classic assistant emails both weekly reports on every APR | `false` (the new assistant has its own switch, off by default) |
| `ALLOWED_ORIGINS` | Includes the placeholder `https://yourdomain.com` | List your real origins, or remove it: same-origin needs nothing |
| `AUTH_MODE`, `ADMIN_PASSWORD`, `ADMIN_EMAILS` | Not set: anyone with the link can use the assistant, and the admin console is locked | `AUTH_MODE=email_otp`, plus one or both admin settings |
| `SESSION_COOKIE_SECURE` | Not set | `true` once the site runs on HTTPS |
| `OPENAI_MODEL=gpt-5.5` | Now used by both assistants | Optionally add `OPENAI_VISION_MODEL`, `OPENAI_STT_MODEL` and `OPENAI_TTS_MODEL` |
| `FLASK_ENV` | Ignored by current Flask | Remove; `DEBUG` controls debug mode |

`e2e_check.py` checks these automatically every time it runs.

## Running the end-to-end check

Run these from the project folder, on the machine with your `.env`:

    python e2e_check.py                                     # configuration, OpenAI, database (read-only), email login
    python e2e_check.py --posters poster1.jpg poster2.jpg   # read real posters and show the batch plan
    python e2e_check.py --posters *.jpg --file              # file them into an in-memory copy; APR PDFs in e2e_output/apr_pdfs
    python e2e_check.py --voice                             # Hindi voice round trip
    python e2e_check.py --send-test-email you@spicmacay.com # one real email

It also checks the portal assumptions against your real data:
- that `event_category` holds module ids;
- the newest APR numbers and the next one the assistant would use;
- which `event_series.event_type` values are in use;
- how many institutions share a name across cities.

**It never writes to your database:** the session is opened READ ONLY, and filing happens in an in-memory copy of your directory and recent events. It emails no one unless you name an address, and never prints secrets. The full results go to `e2e_output/e2e_report.json`. Send me that file, which contains no secrets, and I can go through it with you.
