"""
Drive Ingestion.
Reads drive_file_list.json (produced by --preview), downloads each doc's
content, chunks it, embeds each chunk, and inserts into Supabase.

Resumable: skips files already logged in ingest_progress.json.

Run standalone:  python drive_ingest.py
Via unified CLI: python ingest.py --source drive
"""

import os
import io
import json
import pickle
import time
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
from supabase import create_client

# ─── Config ────────────────────────────────────────────────────────────
load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CREDENTIALS_FILE = "google_drive_credentials.json"
TOKEN_FILE = "token.json"
FILE_LIST = "drive_file_list.json"
PROGRESS_FILE = "ingest_progress.json"

CHUNK_SIZE = 1000       # characters per chunk
CHUNK_OVERLAP = 200     # characters of overlap between chunks
MIN_CHUNK_SIZE = 100    # skip chunks smaller than this (empty-ish)


# ─── Drive service ─────────────────────────────────────────────────────
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)


def download_doc_as_text(service, file_id):
    """Export a Google Doc as plain text."""
    request = service.files().export_media(fileId=file_id, mimeType="text/plain")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8", errors="ignore")


def download_sheet_as_text(service, file_id):
    """Export a Google Sheet as CSV."""
    request = service.files().export_media(fileId=file_id, mimeType="text/csv")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8", errors="ignore")


# ─── Chunking ──────────────────────────────────────────────────────────
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if len(chunk) >= MIN_CHUNK_SIZE:
            chunks.append(chunk)
        start += size - overlap
    return chunks


# ─── Embedding ─────────────────────────────────────────────────────────
def embed_batch(client, texts):
    """Embed a list of strings in one API call. Returns list of vectors."""
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=texts,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return [e.values for e in result.embeddings]


# ─── Progress tracking ─────────────────────────────────────────────────
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed_file_ids": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ─── Core ingestion ────────────────────────────────────────────────────
def run_drive_ingest(drive, genai_client, supabase):
    """Run Drive ingestion using pre-initialized clients. Called by ingest.py."""
    print("=" * 60)
    print("ASK-YOU — DRIVE INGESTION")
    print("=" * 60)

    if not os.path.exists(FILE_LIST):
        print(f"\nERROR: {FILE_LIST} not found.")
        print("Run `python ingest.py --preview` first to generate the file list.")
        return

    with open(FILE_LIST) as f:
        all_files = json.load(f)
    print(f"\nTotal files to process: {len(all_files)}")

    progress = load_progress()
    done_ids = set(progress["completed_file_ids"])
    remaining = [f for f in all_files if f["id"] not in done_ids]
    print(f"Already completed: {len(done_ids)}")
    print(f"Remaining: {len(remaining)}")

    if not remaining:
        print("\nNothing to do — all files already ingested.")
        return

    total_chunks_inserted = 0
    failed_files = []
    start_time = time.time()

    for i, file in enumerate(remaining, 1):
        file_id = file["id"]
        file_name = file["name"]
        mime = file["mimeType"]
        is_doc = mime.endswith("document")

        print(f"\n[{i}/{len(remaining)}] {file_name}")

        try:
            if is_doc:
                text = download_doc_as_text(drive, file_id)
            else:
                text = download_sheet_as_text(drive, file_id)

            chunks = chunk_text(text)
            if not chunks:
                print("  (skipped — empty or too short)")
                progress["completed_file_ids"].append(file_id)
                save_progress(progress)
                continue

            print(f"  {len(chunks)} chunks, {len(text)} chars total")

            BATCH = 100
            all_vectors = []
            for b in range(0, len(chunks), BATCH):
                batch = chunks[b:b + BATCH]
                vectors = embed_batch(genai_client, batch)
                all_vectors.extend(vectors)

            rows = [
                {
                    "content": chunk,
                    "embedding": vec,
                    "source_doc": file_name,
                    "chunk_index": idx,
                }
                for idx, (chunk, vec) in enumerate(zip(chunks, all_vectors))
            ]
            supabase.table("knowledge").insert(rows).execute()
            total_chunks_inserted += len(rows)
            print(f"  ✓ Inserted {len(rows)} chunks")

            progress["completed_file_ids"].append(file_id)
            save_progress(progress)

        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed_files.append({"id": file_id, "name": file_name, "error": str(e)})

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"Files processed:   {len(remaining) - len(failed_files)} / {len(remaining)}")
    print(f"Chunks inserted:   {total_chunks_inserted}")
    print(f"Failed files:      {len(failed_files)}")
    print(f"Elapsed time:      {elapsed/60:.1f} minutes")

    if failed_files:
        with open("ingest_failures.json", "w") as f:
            json.dump(failed_files, f, indent=2)
        print("\nFailed files logged to ingest_failures.json")
        print("You can re-run the script to retry them.")


# ─── Standalone entry point ────────────────────────────────────────────
def main():
    print("\nInitializing Drive, Vertex AI, Supabase...")
    drive = get_drive_service()
    genai_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print("  ✓ All clients ready")
    run_drive_ingest(drive, genai_client, supabase)


if __name__ == "__main__":
    main()
