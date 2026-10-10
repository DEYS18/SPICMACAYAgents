# APR Assistant v2: review, changes and hand-over notes

October 2026. Scope: the APR assistant (other tabs unchanged), the reviewer comments by Dinesh Chand dated 4 October 2026 (DC1 to DC15), circuits and Requests for Payment, governance, interface and voice.

## 1. What was wrong before

| Finding | Effect | What changed |
|---|---|---|
| After the first round of tool calls, the model was asked to reply **without its tools** | One step per message: it could find an artist, then had to stop and ask. This is why it asked so many questions, worst of all for circuits. | A proper agent loop (`app/agents/orchestrator.py`): the model chains tool rounds in one message (tested: three rounds, tools on every call). |
| Virasat went through the single-event validator, which demanded a top-level artist and date that the prompt told the model not to collect | Virasat APRs failed | Separate rules per program type; the classic assistant was patched too. |
| Circuits never reported success to the interface | No success card or PDF button | Unified results; classic assistant patched. |
| The weekly reports were emailed on **every** APR (a testing aid left on) | Inbox noise | Off by default; an admin setting. |
| The module **name** was written to `event_list.event_category`, where the portal stores the `event_module` id (`4` = Lecture Demonstration) | Module likely missing in the portal for AI-created programs | The id is written; reads accept both, so older rows still display. |
| IDs by `MAX(id)+1` with separate commits per row; a failing circuit stop still produced an APR | Collisions between coordinators; half-created circuits | One transaction for all rows of a program, under a MySQL named lock; tested rollback. |
| PDFs used Helvetica, which cannot print curly quotes, dashes or the rupee sign, and failures returned an empty PDF | APR emailed without its attachment | reportlab with bundled DejaVu fonts; tested with St. Xavier’s, D’Souza, Sāchala and the rupee sign. |
| Artist search used whole-string LIKE and SOUNDEX | Misses on small spelling differences, titles, Indian scripts and abbreviations | New in-memory search (section 5). |
| Speech recognition was forced to English with no vocabulary | Hindi garbled; names misheard | Section 6. |
| Posters looked for fonts only in `C:\Windows\Fonts` | Tiny fallback font on a Linux server | Bundled fonts, searched across platforms. |
| `main_agent.py` used `traceback` without importing it | Every error path crashed instead of replying | Fixed. |
| No sign-in; CORS open to all origins; generated APRs (with phone numbers and emails) in `/static` | Anyone with the link could file APRs and read documents | Optional email sign-in, admin roles, same-origin by default, documents served only to the session that created them. |
| Email wording hard-coded in Python | Every wording change needed a developer | All wording in versioned templates (section 7). |
| The zip contained a `.rdp` file with a server address and user name | Infrastructure details in source | Left out; keep such files out of the repository. |

## 2. Reviewer comments

| | Comment | How it is handled | Where | Test |
|---|---|---|---|---|
| DC1 | Date format | Any format accepted (15-10-2026, 15/10/26, 15 Oct 2026, October 15th, next Friday, kal, १५ अक्टूबर). Numbers read day-first. Every date is read back unambiguously, e.g. "15 Oct 2026 (Thu)", and ambiguous ones are flagged. Documents print dd-MMM-yyyy (editable). | `app/core/dates.py` | `DateTests` |
| DC2, DC5 | Program and event hierarchy | A program holds events: single (one), Virasat (several at one institution), circuit (one artist, several institutions). The type is asked first. Virasat and circuits also create the portal's `event_series` record. | `app/agents/draft.py`, `program_writer.py` | `CircuitTests`, `VirasatTests` |
| DC3 | Deceased artists; similar names | Deceased flags (31 pre-loaded, editable, art-form aware) and the date of death from Wikidata in web lookups. Selecting a flagged artist needs confirmation. Similar names lead to an art-form question. | `app/search/resolver.py`, Admin > Directory flags | `test_deceased_*_dc3` |
| DC4 | City and state; multiple campuses | City and state come from the directory record. Campuses are detected and offered as choices; a city narrows them. | `resolver.py` | `test_campuses_dc4` |
| DC6, DC14 | Several coordinators; controlled access | With `AUTH_MODE=email_otp` the filer is known from sign-in. Co-coordinators can be added; only directory coordinators, others become an admin request. All print on the APR, are copied on its email, and are stored per APR. | `app/core/auth.py`, `CoordinatorsSkill` | `test_coordinators_dc6`, `test_email_sign_in_dc6` |
| DC7, DC9 | Main or accompanying when adding an artist | The role is required when adding an artist. | `ArtistsSkill.add_artist` | `test_new_artist_is_provisional_dc7_dc8` |
| DC8 | New artists provisional; Artist Care Group informed | Saved as provisional, queued in Admin > Approvals, the Artist Care Group emailed, the coordinator told. Approve or reject in the console. | same, `app/routes/admin.py` | same |
| DC10 | Several art forms | Recognised; the assistant asks which applies and that one is printed. | `text_utils.split_multi`, `select_artist` | `test_several_art_forms_dc10` |
| DC11 | Main and accompanying photos; main photo required for posters | Photos are requested per artist and role; posters need the main artist's photo (admin switch). | `PostersSkill` | `test_main_artist_photo_is_required_dc11` |
| DC12, DC15 | Cancelled cheque | Photo, then read with the vision model, then shown masked for confirmation, then saved. The cheque image is kept privately and its path written to `cancelled_cheque`. IFSC checked by format and against the public IFSC directory. | `BankSkill`, `read_cheque` | `test_cheque_details_are_confirmed_before_saving_dc12` |
| DC13 | Different artists at one circuit stop | After the stops are in, the assistant asks once about differences and changes only those stops. | `EventsSkill.set_event_artists`, `update_event` | `test_different_accompanist_at_one_stop_dc13` |

## 3. Circuits and Requests for Payment

A circuit used to be a long interview: each stop's date, institution, city and state asked one at a time, one tool round per message. Now:

- **All stops in one go.** Say or paste them, upload the poster, or attach a CSV/Excel list (Date, Institution, City, Time, Contribution). Every institution is matched at once; only real questions remain, such as which BITS campus.
- **Program-level defaults.** Module, time, artists and the default audience apply to every stop; per-stop differences are asked once (DC13).
- **Contribution per stop**, as on the portal's own APRs, so Requests for Payment can be prepared for the whole circuit in one step: one invoice and email per institution, with missing emails or amounts flagged, a preview with tick boxes, and one confirmation. NIL contributions are skipped.
- **The APR document** follows the portal's format: coordinator rows, time ranges, student and other audience, contribution per event, institution contact, additional notes.

## 4. Skills: use any, all or none

Each skill is independent, and the interface buttons call the same tools as the AI. Optional skills can be switched off in Admin > Settings > Skills.

| Skill | What it does | Optional |
|---|---|---|
| Program details, Dates and stops, Artists, Institutions, Coordinators | Build the draft | Core |
| Artist Payment Request | File in the portal database, PDF, emails | Yes |
| Documents only | APR preview and Request for Payment PDFs without filing or emailing | Yes |
| Request for Payment | Invoice emails, one per institution | Yes |
| Pre-event guidelines | SOP email for upcoming events | Yes |
| Posters | Poster from the draft or an existing program | Yes |
| Bank details | Cheque reading, IFSC checks | Yes |
| Program lookups | Existing programs and APRs | Yes |

Every email goes through a preview and is sent only after a clear yes. An admin setting can require the Send button, so a spoken or typed yes is not enough. Filing works the same way: a confirmation token from the review is required, and it is void if the draft changes afterwards.

## 4b. Several posters at once

For coordinators who file APRs after a season of programs, the batch flow reads up to 20 posters together, checks them against the directory and the portal, and shows one plan to approve. It merges events that appear on two posters (a festival poster and a concert's own poster, or two versions of one), noting any disagreement such as different start times. It then groups events into programs: a Virasat when the poster says so, a circuit when one artist visits several institutions within a week, several days at one institution as one program, otherwise a single program. Events already in the portal are left out, so nothing is filed twice, and screenings without a performing artist need no APR.

Everything marked in the plan is fixed by tapping. You can pick the right match, add a person or institution as provisional (with the usual approval), untick an event or program, or change a program's type. **File** files every ticked program, one transaction each, and emails each APR to the coordinators, or all of them in one governed email (`email.apr_batch_summary`). A picker then lists every institution of the filed programs, so you choose which get a Request for Payment, with the amount and email. The usual preview and confirmation follow. The batch is also available to the AI (`batch_summary`, `batch_update`, `batch_file`, `batch_payment_requests`), so it can be driven by voice. See `docs/REAL_POSTER_TEST.md`.

## 5. Search

The directory (about 1,200 artists and 5,300 institutions) is indexed in memory and refreshed every ten minutes, and straight after anything is added.

- **Names:** titles are removed (Pt., Ustad, Vidushi, Padma Shri and others) without harming names like Padma Talwalkar. Indian spelling variants are normalised (z/j, w/v, aa/a, oo/u, sh/s, -iya/-ia). Initials work ("L K Pandit"). Hindi and eight other Indian scripts are transliterated, so "रोनू मजूमदार" finds Ronu Majumdar.
- **Institutions:** abbreviations are expanded (IIT, NIT, IIM, KV, JNV, DPS, APS, DAV, ZP, GSSS and more), old city names map to new (Bombay to Mumbai, Madras to Chennai), and "KV No. 1" is never confused with "No. 2". Campuses are detected.
- **Beyond the directory:** web lookups suggest details for confirmation, never written silently. Artists use Wikipedia and Wikidata (art form, Padma and Sangeet Natak Akademi awards, date of death), plus Google Knowledge Graph when `GOOGLE_API_KEY` is set. Institutions use Google Places with a key, otherwise OpenStreetMap, with city, state and PIN code. Results are cached for 30 days.

## 6. Voice

Speech recognition is no longer forced to English. With Auto it detects the language, or you choose one (हिन्दी, Hinglish, मराठी, বাংলা, தமிழ், తెలుగు, ಕನ್ನಡ, മലയാളം, ગુજરાતી, ਪੰਜਾਬੀ, ଓଡ଼ିଆ, অসমীয়া, اردو, English).

Each recording is sent with a vocabulary: the names already in the draft, the 15 most-booked artists, art forms and honorifics. This is the biggest gain for names. Whatever is heard then goes through the name search above.

The mic stops by itself when you pause, or can be held down for push-to-talk. Hands-free mode listens again after each spoken reply. Replies can be read aloud with the server voice (clearer Hindi) or the browser voice. Without a server key, the browser's own recogniser is used where available (Chrome).

Limits: Odia has no language hint in the speech model and falls back to auto-detect. Mixed Hindi-English is best-effort. Noisy halls reduce accuracy. The microphone needs HTTPS.

## 7. Governance

All wording and layouts are in `instance/governance.db` and edited in Admin > Templates. Each email has a subject, an HTML body inside a shared frame, and an optional plain-text version. The approved wording of the Request for Payment, guidelines and thank-you emails is carried over unchanged.

Every save is a new version and any earlier version can be switched back on. Edits are checked before saving: syntax errors are reported with the line number, and templates run in a sandbox so they cannot reach the server. Previews use sample data based on APR 1777, and test sends are available.

The APR layouts (single, circuit, Virasat), the Request for Payment document, the poster wording and the assistant's house rules are edited the same way, with widgets for columns, headings, widths and order. Safety rules (preview before sending, confirmation before filing) are built into the code, not the editable text.

## 8. Assumptions to confirm with the tech lead

| Item | What the app does now | Where to change |
|---|---|---|
| Module storage | `event_list.event_category` holds the `event_module` id (all 6,902 rows in the dump do); names are matched to the portal's own modules, e.g. Concert to Full Concert | Settings > APR > "Store the module as" |
| APR number | The `custom_apr` id, exactly as the portal numbers APRs | Settings > APR > "APR number" (portal; the old schemes remain selectable) |
| `event_series.event_type` | The program-type term from taxonomy (288, 289, 291 in production) | Settings > APR > program-type ids, if they ever differ |
| `event_list.institution` | The institution name, as every portal row does (all 6,902 rows in the March 2026 dump) | Code |
| Provisional artists | `artists_list.added_by = 'AI-PROV'` (the column holds 10 characters); approval sets `AI`, rejection sets `status = 0` | Code |
| Co-coordinators | Stored per APR in `instance/governance.db`, printed on the APR and copied on its email; the schema snapshot has no portal table for them | Tell me the portal table and they can be written there too |
| Default password hash | Artists and institutions added by the assistant get the same default hash the portal uses for its own records | A portal-wide decision |

## 8b. Decisions since the first review

| Question | Decision | What the app does |
|---|---|---|
| A workshop running several days | One portal row per day | A 9 to 11 Sep workshop is one item in the draft and the batch plan, and is filed as three rows in `event_list` and three APR lines. Ranges over 14 days are stopped as probable typos |
| Contribution amounts typed for Requests for Payment | No new tables or columns for now | Amounts stay in the Request for Payment only; nothing is written back to the filed APR |
| The previous version's `apr_payment_request` rows | Keep writing them alongside `custom_apr` | Both record types on every APR, the old rows exactly in the previous format; verified by running the previous version's own code against them |
| A concert that also appears in a Virasat | Filed with the Virasat | Untick it, or change the program type in the batch card, when a chapter files it separately |

The new code adds no tables to the portal database. Everything new lives in the app's own `instance/governance.db`: templates, settings, history, approvals, co-coordinators and AI usage counters. The classic code's existing `payment_notification_log` table is unchanged.

OpenAI calls now go through one model-aware layer. For the model assessment and recommendations, see `docs/MODEL_AND_CONFIG.md`.

## 8c. Aligned with the portal's own data model

A regression test against a production dump (MariaDB 10.11.14, March 2026) showed how the portal itself records an APR, and the assistant now does the same. The APR is a `custom_apr` record, and its id is the APR number the portal shows (the next after 207 in that dump). It carries the event ids, the coordinators' user ids, the program type (Circuit 288, Single Event 289, Viraasat Series 291) and the program group. Multi-event programs are `event_series` records. Events store institutions by name and are linked to their program through `added_from`. Previously the assistant wrote only the earlier AI app's `apr_payment_request` rows, which the portal never reads, and numbered APRs from a table whose highest number was 16. No database changes are needed. See `docs/DATABASE_COMPATIBILITY.md`.

## 8d. Conversation first (after the first deployment)

The first version of the new screen had a left panel of start buttons and a permanent right-hand form, and the AI's instructions read like a procedure ("ask one short question per reply, in this order"). Together they made the assistant feel like a web form. The coordinators' feedback was that the chat is the point, and both have changed:
- **The screen:** one centred conversation with a personal greeting and five quiet suggestions under the message box. Details sit behind a small pill and open as a drawer.
- **No duplicates:** suggestions never repeat a card's own buttons, and the microphone's ring appears only while listening.
- **The instructions:** they describe a warm, knowledgeable colleague, who takes the story in any order, asks only what is missing (naturally, never as a list), answers questions and offers at most one next step.
- **Unchanged:** every rule about confirmation, filing and sending, and every capability. All 13 abilities of the previous assistant have counterparts among the 41 tools.

The administrators' house rules default moved to "warm, respectful and patient"; the stored default is upgraded only if nobody has edited it.

## 8e. The original assistant is the main assistant again

Coordinators preferred the original conversational agent: its flow, its Hindi welcome spoken as the screen opens, and its screen. It is the main assistant again, at `/assistant`, and its conversation logic and instructions are unchanged.

The improvements sit underneath, at the two services it calls (`app/services/classic_bridge.py`):
- better directory search, returning the same fields with notes for the reviewer's points;
- any date format;
- the portal's own APR and program records, alongside the old rows;
- provisional new artists;
- a short addendum after its instructions.

Each falls back to the original behaviour if anything goes wrong. Verified end to end on the production copy, through the HTTP chat and the original agent:
- a single program filed as APR 208, with a Hindi title and the ₹ sign stored safely and the date given as "15 Nov 2026";
- a circuit filed as APR 209, with its program record and both stops linked.

The screen keeps all its features and takes the SPIC MACAY colours. The spoken welcome falls back to a "Tap to hear" button when a browser blocks autoplay, and the voice status no longer sticks on "Generating speech" when speech fails. The newer interface remains at `/assistant/new` as a preview.

## 8f. Each output on its own or together (original assistant)

Verified on the production copy, through the original agent, with every email captured:
- a Request for Payment on its own for a program already filed;
- the APR, its Request for Payment and the guidelines in one conversation;
- a poster on its own for a filed program;
- the guidelines on their own in a fresh conversation.

Fixed on the way:
- **Empty PDFs.** The Request for Payment invoice and the APR PDF came out empty, and emails went without attachments, whenever a name had a curly apostrophe ("St. Xavier’s"), a dash, an accent or the rupee sign. fpdf's Helvetica cannot print them; `app/core/pdf_text.py` makes such text printable, so the documents keep their look.
- **Posters for a filed program** looked the artist up by name, so a namesake's photo could be used (the directory has two "Ronu Majumdar" records). They now use the program's own artist, and a shared name never counts as a confident match.
- **"Send the pre-event guidelines" opening a conversation** went to the information agent. The router now knows guideline, pre-event, SOP, checklist and invoice.

The welcome screen gains **What do you need today?**, which starts one conversation for any combination of outputs, plus a Guidelines quick action and a link to the step-by-step view.

## 8g. One assistant: the calm screen, the original playbook, the newer tools

The assistant at `/assistant` is now one merged assistant:
- **Screen and tools:** the conversation-first screen and this version's tools, cards and buttons.
- **Instructions:** the original assistant's playbook, read word for word from `agent.py` at start-up (setting `assistant.original_playbook`). It is followed by a short section on carrying it out here: intent first, then a mapping of the 13 original tools to their newer equivalents.
- **Welcome:** in the original's Hindi-first style, spoken as the screen opens, asking nothing.
- **Follow-ups:** program-type and next-output buttons appear only once they apply.
- **Knowledge:** a new skill, `ask_spicmacay_guide`, connects the original information agent (WorkflowAgent) for questions about SPIC MACAY.
- **Speaker:** a speaker toggle sits next to the mic.

The original screen remains at `/assistant/classic`. If the merged assistant cannot start, `/assistant` sends coordinators there.

## 8h. Template governance

Admin > Templates now groups the templates by purpose (APR, Request for Payment, Event guidelines, Posters, Other emails, Assistant) and adds two things:
- **The pre-event guidelines document** is governed like the templates: a revised PDF is uploaded as a new version, every version is kept, any can be switched back on, and the original ships with the app. Both assistants attach the active version.
- **Edits that drop a placeholder the original relies on** (the APR number, an amount, the institution's name) are stopped with a list of what is missing, unless confirmed. Wording changes save straight away.

Everything else was already in place:
- the visual editors for the APR and Request for Payment layouts;
- the live previews, test emails and history;
- reset to default, and the sandboxed test render before every save.

## 8i. 2.4: emails, the poster, the laptop screen and the face

| Feedback | Cause | What changed |
|---|---|---|
| The earlier app's APR and Request for Payment emails looked better | 2.0 replaced them with a plain red-banner frame | The earlier designs are back as governed templates (gold banner, pills, fact cards, amount box; red banner for the APR), plus bank particulars, an attachment line and a calendar note. `email.shell`, `email.apr_confirmation`, `email.payment_request` and the others upgrade on start-up only if nobody edited them (`app/core/template_history.py`) |
| The poster no longer came with the APR | Only an *uploaded* poster was attached; the usual "Make a poster" step ran after the APR email had gone | Uploaded or made-here posters are attached; filing a single program makes one when the main artist's photo is on file (the review card says so first); a poster made after filing is linked to every event of the program and offered as a prepared email (`email.apr_poster`) with the APR. Requests for Payment re-attach it |
| — | APR subject included the institution's contact details and a line break | Subject is now "SPIC MACAY APR 208 Confirmation – artist at institution" |
| Sides of a laptop screen look empty | One 760 px column | From 1180 px: the assistant's face, status and examples on the left; the program at a glance (read-only) on the right, opening the Details drawer to edit |
| Chat text jumps while "Working on it" shows | The dots animated their width and, inheriting `overflow-wrap: anywhere`, wrapped one per line: the bubble's height cycled 27, 54, 82 px | A fixed-height indicator animated with transforms only (measured steady at 30 px) |
| A human face with folded hands, speaking | — | `app/static/js/avatar.js`: SVG figure (namaste), idle / listening / thinking / speaking states; lips follow the loudness of the server voice (decoded separately, playback untouched) or a speech rhythm for the browser voice. Admin switch `assistant.show_face`. Hindi and Marathi greetings and self-references are now feminine, to match |

The previous assistant at `/assistant/classic` is unchanged.

## 9. Testing: what was and was not verified

**Verified here:**
- 116 automated tests, plus a MariaDB integration test and a check with the previous version's own code run against the production dump: batch filing with ten real posters, one row per day, the OpenAI layer for GPT-4o, GPT-5.x and GPT-6 (Responses API), and the end-to-end script offline against an in-memory copy of the portal schema with a scripted AI.
- The real application factory booting with all legacy parts: 72 routes and every page returning 200.
- Chromium screenshots on a phone (390×844) and a laptop (1440×900) through a full circuit conversation, plus the admin console. These found and fixed three interface issues.

**Not verified live, because the sandbox's network blocks them (run `e2e_check.py` on your server):**
- OpenAI (chat, vision, transcription, speech)
- Google, Wikipedia, OpenStreetMap and IFSC lookups
- SMTP
- Your MySQL database

**Suggested first run:**
1. Start with Settings > Emails > Dry run switched on.
2. File one single-event APR and one small circuit.
3. Check the rows in the portal and the saved emails in `instance/outbox`.
4. Then switch dry run off.
