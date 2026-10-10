# Upgrading from the previous version

## Which version is running?

| Where | New version (2.4.0) | Previous version |
|---|---|---|
| Server console at startup | `[SPIC MACAY] APR Assistant 2.4.0 (...): ACTIVE` | No such line |
| `<your address>/health` | Shows `"version"` and `"apr_assistant"` | Neither |
| `<your address>/assistant` | A calm screen greeting you with "नमस्कार" (spoken), with a speaker and a mic in the message box | The original screen |
| `<your address>/admin` | Admin console sign-in | Not Found |
| Home page footer | "APR Assistant 2.4.0" | Nothing |

From the server, `python e2e_check.py --url https://spicmacay.in/<sub-path>` reports which version the live site serves.

## Steps (Windows or Linux)

1. **Stop the app:** close the waitress window or stop the service.
2. **Back up the current folder by renaming it,** for example `spicmacay_ai_app` to `spicmacay_ai_app_previous`.
3. **Unzip the new package next to it, not inside it,** so a fresh `spicmacay_ai_app` folder appears in the same place. Check that there is **no** `spicmacay_ai_app\spicmacay_ai_app` inside: a nested copy is the most common reason the old screens keep appearing.
4. **Copy these from the previous folder into the new one:**
   - `.env`, including `URL_PREFIX` if you set it. Also add `ADMIN_PASSWORD=...`, or `ADMIN_EMAILS=...`, so you can open the admin console.
   - `knowledge_index\` (the Convention and Movement guides).
   - `credentials\` (Google sign-in for the guides), if present.
   - `app\static\event_photos\` and `app\static\artist_photos\`: photos the portal already links to.
   - `instance\`, only if you have run the new version before (templates, settings, history).
5. **Install this version's packages** in the same Python environment the server uses: `pip install -r requirements.txt`. On a Lilly-managed machine, install through Artifactory.
6. **Start the app.** The console must show `APR Assistant 2.4.0 ...: ACTIVE`. If it says **NOT ACTIVE**, the reason follows, usually a missing package: repeat step 5. The `/assistant` and `/admin` pages also show the reason.
7. **Open the site and press Ctrl+F5.** The assistant is at `/assistant`, the admin console at `/admin`, and the original screen at `/assistant/classic`.
8. **Run `python e2e_check.py --url <your address>` once** for a full check.

## Rolling back

Stop the app, rename the folders back, and start it again. Both versions use the same database tables, and the switch itself changes nothing in the database.
