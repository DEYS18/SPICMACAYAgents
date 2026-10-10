# Database compatibility: regression test against the production dump

**What was tested.** The latest app ran against the dump you shared, a phpMyAdmin export dated 7 March 2026. It was loaded into **MariaDB 10.11.14**, the same server version the dump came from, in its default **strict** SQL mode: 233 tables, 6,902 events, 1,217 artists, 5,318 institutions and 151 APRs.

The run started the full app (classic parts and the new assistant) and drove it through the HTTP API, covering:
- directory search on real names;
- filing a single event, a circuit and a Virasat, including Hindi text, the ₹ sign and accented letters;
- one row per day for a three-day workshop;
- adding provisional artists and institutions;
- Requests for Payment for portal-created events;
- the ten-poster batch;
- every page and API.

After the fixes, **16 of 16 checks pass** on a freshly loaded copy. A repeatable version is in `tests/test_mariadb_integration.py` (4 tests, all passing; it deletes what it creates).

## Do you need to change your database?

**No.** The assistant uses only existing tables and columns: no new tables, no new columns, no altered types. Everything new (templates, settings, history, co-coordinator lists, AI usage) lives in the app's own `instance/governance.db`.

**One data addition, as you agreed.** If **Workshops** or **Yoga & Meditation** is missing from `event_module`, the app adds it: one row each, with the next id, recorded in the activity log. Your March 2026 dump already has both (ids 9 and 11), so nothing is added there.

Names that mean the same module count as present: "Workshop" or "Workshops", "&" or "and". A module switched off in the portal is left alone. More can be listed under Admin > Settings > APR > "Modules to add to the portal if missing", for example Baithak, the one module coordinators mention that the portal lacks.

Verified on MariaDB: with the two modules removed from a copy, they were re-created (ids 14 and 15) and a workshop was filed against the new id.

Two optional improvements:
- **A dedicated MySQL user.** Grant it SELECT, INSERT and UPDATE on the portal tables and use it instead of root.
- **An index on `institution_list.institution_name`.** This speeds up the classic lookups that match institutions by name. It is not needed for correctness.

The classic code's existing behaviour of creating `payment_notification_log` on its first payment reminder is unchanged. The new assistant does not use that table.

## What the test found, and the fixes

| Found | Effect before the fix | Fix |
|---|---|---|
| **The portal's APR is a `custom_apr` record.** Its id is the APR number (newest 207), and it holds the event ids, coordinators' user ids, program type and group. `apr_payment_request`, which the assistant wrote, has **0 rows** in production | APRs filed by the assistant would not appear in the portal's APR list or its approval and finance workflow, and would be numbered from `apr_payment_request2`, whose highest number is 16 | The assistant now writes a `custom_apr` record exactly like the portal's own (APR **208** onwards in the test). It still writes the old `apr_payment_request` rows for the previous AI app's dashboard (a setting) |
| **Program types are taxonomy terms:** Circuit 288, Single Event 289, Viraasat Series 291 | `event_series.event_type` was left empty | Read from `taxonomy_term_field_data` (vid `events`) |
| **Institutions are stored by name in `event_list.institution`** (all 6,902 rows) | The assistant wrote directory ids, which the portal would display as numbers | Names are written. The classic code's 9 institution lookups, which joined on `e.institution = i.sid` and so found nothing for portal events, now match by id or by name, preferring the same city |
| **Events in a program point to it through `added_from`** | Events were not linked to their program | Linked |
| **The real modules:** Full Concert (13), Workshops (9), Workshop Demonstration (8), Yoga & Meditation (11) and others; there is no plain "Concert", and no Baithak | Modules were matched loosely, and an unknown one would have been stored as text | Mapped to the portal's names ("Concert" becomes Full Concert, "Workshop" becomes Workshops, "Yoga" becomes Yoga & Meditation). Workshops and Yoga & Meditation are added if missing. An unknown module is caught at review, and the AI is given the portal's list |
| **The portal tables are latin1, and the server is in strict mode** | Any Devanagari, ₹ or "ā" in a title, note or name would make MariaDB reject the whole filing | Text for latin1 tables is made latin1-safe (Indian scripts romanised, ₹ written as Rs). The same guard covers every classic write |
| **The tables use AUTO_INCREMENT** | Ids were generated as MAX(id)+1, which can collide with the portal's own inserts | Ids come from AUTO_INCREMENT |
| **The directory data is untidy:** 29 artist names and 60 institution names are duplicated, and the city field often holds the last word of the name ("AIIMS" in city "AIIMS", "Quadrangle, St. Mary's ICSE School" in city "School") | The exact record "AIIMS Delhi" was demoted into a campus question; TISS was matched to TIFR; VNIT was matched to "B.V.M. Civil Lines" through its initials | An exact name wins unless another record has the same name or is a more specific campus. Generic words (institute, school, national) cannot carry a match alone. Initials match people, not institutions. A match whose city disagrees gets a visible "check this" note |

## How the assistant writes a program now

| Table | Values |
|---|---|
| `event_series` (circuit or Virasat) | `event_type` from taxonomy; title, dates, times; `event_id` holds the event ids; `status` 1; `event_status` is Completed once all its events have taken place, otherwise Pending; `added_by` is the filer's user id |
| `event_list` (one row per event, and per day of a multi-day workshop) | `institution` holds the name; `artist` and `accompanying_artist` hold ids; `event_category` holds the module id; `event_time` and `end_time` as HH:MM; `attendees`; `budget` holds the contribution; `added_from` holds the program id (0 for a single event); `added_by` is the user id; `fy`; `poww` 0 |
| `custom_apr` (the APR) | `coordinators_id` holds the user ids; `event_series` holds the program type; `eventgroup` holds the program id, or the event id for a single event; `event_id` holds the ids; `created_by`; `dt_created`; `del` 0; `final_submit` 1; `added_by` 'event_list'; `apr_status` stays empty for the portal's approval |
| `apr_payment_request` (always, alongside `custom_apr`) | Exactly the rows the previous version writes: one per event, sharing a `request_id` in its format (`REQ-<timestamp>-<code>`) and the APR reference (now the portal's number), the start time in `time_duration`, the institution name, the filer in `created_by` and `updated_by`, `del` 0 |

## Compatibility with the previous version

As agreed, every APR is recorded **both** ways: the portal's records (`custom_apr`, plus `event_series` for programs) and the previous version's `apr_payment_request` rows. Each has its own switch in Admin > Settings > APR, both on by default, and the app refuses to file if both are off.

**Verified with the previous version's own code.** Its `event_service.py` and `database.py`, from the zip you sent and loaded on their own with nothing from the new version, read APRs filed by the new version on the MariaDB copy:
- **Lookups:** for every event, its details, payment reminder, guidelines and resend lookups all found it.
- **References:** every event carried its APR reference.
- **Screens and errors:** its listings and dashboards ran without errors.
- **Its own filing:** afterwards it filed an APR of its own (`APR-<event>-<date>`) with no id collisions.

**One limit of the previous code:** it finds an event's institution only by id. Events stored by name, as the portal stores them, therefore show no institution email in the previous version's reminders. The new version's lookups handle both. If the previous version must keep running alongside the new one for a while, set Admin > Settings > APR > "Store the institution in event_list.institution as" to **id** for that period. The portal will then show a number for those events, so switch back to **name** once the previous version is retired.

**To repeat the check** with the exact previous version running in production, on a database copy:

    python tools/old_code_compat_check.py --old-app /path/to/previous/app --db "user:password@host:3306/drupal" --this-is-a-copy

It files four test programs with the new version, reads them through the previous version's code, files an APR with the previous version, prints the results and deletes everything both created. On the copy, the counts were the same before and after.

## Questions for you

1. **What does `event_list.poww` mean?** It is 1 on some 2026 events. The assistant writes 0. If it means "payment required by the Delhi account", it can be set from that field.
2. **Should filed events be marked "Completed"?** The assistant marks events Completed once they have taken place and Pending before, which matches the 2026 events behind the newest APRs. The portal also uses "Ready for APR".
3. **The old `apr_payment_request` rows: decided.** They continue alongside `custom_apr`, so nothing that reads them breaks.
