# Ask-You

A personal AI trained on your own writing — not a generic assistant, but a searchable version of how you actually think.

![Demo](docs/demo.gif)

## What it is

Most AI tools answer questions from a general knowledge base. Ask-You answers from *yours*. You ingest your own Google Docs, Sheets, and local files into a vector database. When you ask a question, the system retrieves the most relevant excerpts from your writing and uses them as grounding context for a Gemini response — so the answer sounds like you, not like ChatGPT.

The pipeline is: **ingest → embed → retrieve → generate**. Your documents are chunked into overlapping segments, embedded via Google's `gemini-embedding-001` model, and stored in Supabase with pgvector. At query time, your question is embedded the same way, the closest chunks are retrieved by cosine similarity, and Gemini 2.5 Pro generates a response in your voice, grounded in those excerpts.

Two response modes let you choose how explicit the AI is about its reasoning: **Clean mode** responds naturally in first person, the way you'd actually talk. **Dev mode** labels each claim as `[GROUNDED]`, `[INFERRED]`, or `[EXTRAPOLATED]` and cites source documents — useful when you're debugging retrieval quality or auditing the AI's confidence.

There's also an **ego slider** (0.0 to 1.0) that modulates how the AI presents your voice — from genuinely self-doubting at 0, to baseline at 0.5, to emperor-level certainty at 1.0. It's useful for exploring how you think about yourself across different emotional registers, and sometimes for getting unstuck when you need a push.

## Screenshots

![Interface](docs/screenshot.png)

## Prerequisites

- **Mac** (Linux should work; Windows untested)
- **Google Cloud account** with billing enabled — free tier is sufficient for personal use
- **Supabase account** — free tier works
- **Homebrew** — [brew.sh](https://brew.sh)
- **Python 3.12** — the setup script installs this via Homebrew
- **Google Cloud SDK** (`gcloud`) — [install guide](https://cloud.google.com/sdk/docs/install)

## Quick Start

### 1. Clone and run setup

```bash
git clone https://github.com/HIPNIP/ask-you.git
cd ask-you
./scripts/setup.sh
```

The setup script will:
- Install Python 3.12 if missing
- Create a virtual environment and install all dependencies
- Prompt you for your GCP project ID, Supabase URL, and Supabase service key
- Authenticate with Google Cloud

### 2. Set up Google Cloud

Enable the Vertex AI API in your GCP project:

```bash
gcloud services enable aiplatform.googleapis.com --project YOUR_PROJECT_ID
```

Make sure your project has billing enabled — Vertex AI won't work otherwise. Gemini embedding and generation costs are very low for personal use (typically under $1/month).

### 3. Run the SQL migration in Supabase

Open your Supabase project → **SQL Editor** and run `docs/migration.sql`.

- **New users**: run Section 1 only — creates the `knowledge` table and `match_knowledge` function
- **Migrating from ask-isaac**: run Section 2 only — renames existing tables/functions in-place

**The server will not work until you run this.**

### 4. Ingest your writing

```bash
cd backend
source ../venv/bin/activate

# Preview what's in your Drive (no ingestion yet)
python ingest.py --preview

# Ingest from Google Drive
python ingest.py --source drive

# Ingest from a local folder (.docx and .xlsx files)
python ingest.py --source local --path ~/path/to/your/files

# Both at once
python ingest.py --source all --path ~/path/to/your/files
```

Ingestion is resumable — if it stops partway through, re-run the same command and it will skip already-completed files.

For Google Drive ingestion, you need a `google_drive_credentials.json` OAuth credential file in the `backend/` directory. Create one in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) under your project — type: Desktop app, API: Google Drive.

### 5. Start the server

```bash
cd backend && source ../venv/bin/activate && uvicorn server:app --reload --port 8000
```

Then open `frontend/ask-you.html` in your browser.

## Configuration

All configuration lives in `.env` at the project root:

| Variable | Description |
|---|---|
| `YOUR_NAME` | Your name — used in system prompts and the UI |
| `GCP_PROJECT_ID` | Your Google Cloud project ID |
| `GCP_LOCATION` | Vertex AI region (default: `us-central1`) |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (not the anon key) |
| `CUSTOM_SYSTEM_PROMPT` | Optional: completely override both system prompts |

## How it works

```
Your question
    │
    ▼
Query rewriting (if follow-up)
    │
    ▼
Embed question → vector
    │
    ▼
Supabase: cosine similarity search → top N chunks
    │
    ▼
Build prompt: system + retrieved context + question
    │
    ▼
Gemini 2.5 Pro → streaming response
    │
    ▼
Sources panel + token stream → browser
```

Conversation memory is held in-process (last 6 turns). Follow-up questions are automatically rewritten into standalone queries before retrieval, so "why?" after a complex answer still retrieves the right context.

## Project structure

```
ask-you/
├── backend/
│   ├── server.py          # FastAPI server, RAG logic, streaming
│   ├── ingest.py          # Unified ingestion CLI
│   ├── drive_ingest.py    # Google Drive ingestion
│   ├── local_ingest.py    # Local file ingestion (.docx, .xlsx)
│   └── drive_preview.py   # Drive file listing (run before ingesting)
├── frontend/
│   └── ask-you.html       # Single-file UI (NERV-inspired)
├── scripts/
│   └── setup.sh           # One-command setup
├── docs/
│   └── migration.sql      # Supabase schema
├── .env.example           # Template for required environment variables
└── requirements.txt
```

## License

MIT — see [LICENSE](LICENSE).
