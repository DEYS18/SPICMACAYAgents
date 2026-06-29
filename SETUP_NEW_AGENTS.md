# Setup Guide — New Convention & Movement Guide Agents

This explains everything added to your app and the exact steps to make the two
new document-grounded agents work. Read the "Honest caveats" section too.

---

## What was added

**New agents (cards on the landing page):**
- **Convention Guide** — `/guide/convention`
- **Movement Programme Guide** — `/guide/movement`

**New / changed files:**
- `app/services/drive_rag_service.py` — Google Drive fetch + chunk + embed + retrieve (the RAG engine). *New.*
- `app/models/knowledge_agent.py` — the agent class + registry of the two agents and their personas. *New.*
- `app/routes/knowledge.py` — API endpoints for the new agents. *New.*
- `app/templates/index.html` — now a **card landing page** (choose an agent). *Replaced.*
- `app/templates/assistant.html` — your **original** event/voice chat, moved here, unchanged. *New (copy).*
- `app/templates/knowledge_chat.html` — interactive chat UI for the guides. *New.*
- `app/__init__.py` — initializes the agents + registers routes (additive edits). *Edited.*
- `requirements.txt` — added Drive + embedding dependencies. *Edited.*
- `knowledge_docs/convention/`, `knowledge_docs/movement/` — drop local docs here for testing. *New.*

**New page routes:** `/` (landing), `/assistant` (original chat), `/guide/<convention|movement>`
**New API routes:** under `/api/knowledge/` — `GET /agents`, `POST /<key>/start`, `/<key>/chat`, `/<key>/reset`, `/<key>/reindex`

Your existing event agent, voice, dashboard, and database code were **not** changed.

---

## Step 1 — Install the new dependencies

```bash
pip install -r requirements.txt
```

(Adds: google-api-python-client, google-auth*, pypdf, numpy.)

## Step 2 — Give each agent its documents

You have two options. **Option A is the fastest way to see it work today.**

### Option A — Local folder (no Google setup, good for testing)
1. Put public-safe `.txt`, `.md`, or `.pdf` files into:
   - `knowledge_docs/convention/`
   - `knowledge_docs/movement/`
2. Build the indexes (see Step 4). Done — the agents will answer from those files.

### Option B — Google Drive (for the real, auto-updatable setup)
1. In Google Cloud Console, create a **service account** and **enable the Google Drive API**.
2. Download the service account **JSON key file**.
3. In Google Drive, **share each curated folder** with the service account's email
   address (it looks like `name@project.iam.gserviceaccount.com`), as Viewer.
   *Sharing the specific folder is the simplest approach and avoids domain-wide
   delegation.*
4. Copy each folder's **ID** from its URL: `drive.google.com/drive/folders/THIS_PART`.

## Step 3 — Set environment variables (add to your `.env`)

```
# Knowledge agents (only needed for Option B / Google Drive)
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/service-account.json
CONVENTION_DRIVE_FOLDER_ID=your_convention_folder_id
MOVEMENT_DRIVE_FOLDER_ID=your_movement_folder_id

# Optional overrides (defaults shown)
EMBEDDING_MODEL=text-embedding-3-small
KNOWLEDGE_INDEX_DIR=knowledge_index
```

## Step 4 — Build (index) the documents

Indexes are built on demand, not on every query. After starting the app, trigger a build:

```bash
curl -X POST http://localhost:5000/api/knowledge/convention/reindex
curl -X POST http://localhost:5000/api/knowledge/movement/reindex
```

Re-run these whenever you add or change documents. (You could later wire this to
a button or a schedule.)

## Step 5 — Use it
Open `http://localhost:5000/` → pick a guide card → ask questions. Each answer
lists the source documents it used.

---

## Honest caveats — please read

- **I could not run your full app end-to-end.** I don't have your database,
  OpenAI key, Google credentials, or your real documents. I syntax-checked every
  file and smoke-tested the RAG build/retrieve logic in isolation with a mock —
  but the first real run is on your machine, so expect to iron out environment
  details (DB connection, paths, etc.).
- **Rotate your secrets.** Your uploaded zip contained a live `.env` with your
  OpenAI key and DB/SMTP passwords. Treat them as exposed and regenerate them.
- **"MCP server" was intentionally not used.** For a self-hosted app, calling the
  Google Drive API directly (what this does) is simpler and more reliable and
  achieves the same goal. If you specifically need an MCP server for some other
  reason, that's a separate, larger piece of work.
- **Google Workspace nuance (verify).** Because `sabyasachi@spicmacay.com` is a
  Workspace account, your Workspace admin settings *may* affect service-account
  access. Sharing the specific folder with the service account email usually works
  without extra admin steps, but I can't verify your domain's policy — confirm it
  on your side. If sharing doesn't grant access, the alternative is OAuth (user
  consent) or domain-wide delegation, which need more setup.
- **Costs.** Building an index and answering questions both call the OpenAI API
  (embeddings + chat). I'm not quoting prices — check current OpenAI pricing.
- **Privacy.** These read whatever is in the connected folder. Use a *curated,
  public-safe* folder (see the earlier prep pack) — keep contacts, financials, and
  the MLA database out.
- **Public vs. gated.** This adds the agents to your app; it does not add a login
  gate. If volunteers will access it, put authentication in front (the earlier
  discussion covers why that matters).

---

## The guide figure (convention page)

The convention guide page features a friendly elderly-mentor illustration as an
interactive "guide," plus tappable starter questions, so it opens like a guided
conversation. His face appears on each reply.

- The figure is an **original, generic illustration** (`app/static/img/guide-mentor.svg`)
  — deliberately **not** a photo or likeness of any real person, so the assistant
  never appears to "speak as" a real individual.
- **To use a licensed photo you own instead:** drop an image at
  `app/static/img/convention_guide.jpg` (or `.png` / `.webp`). The page detects it
  and uses it automatically in place of the illustration. Only use an image SPIC
  MACAY actually has the rights to.
- The guide's name label and starter questions live in the agent registry
  (`app/models/knowledge_agent.py`) under `guide_name` and `starter_prompts` — edit
  freely.
