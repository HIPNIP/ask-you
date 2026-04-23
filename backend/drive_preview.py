"""
Phase A: Drive Preview.
Lists all Google Docs and Sheets owned by you in your Drive.
No embedding, no database writes — just a preview of what will be ingested.
"""

import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes define what permissions we're requesting.
# drive.readonly = can list and read files, cannot modify or delete.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CREDENTIALS_FILE = "google_drive_credentials.json"
TOKEN_FILE = "token.json"


def get_drive_service():
    """
    Authenticate with Google Drive.
    First run: opens browser for you to authorize.
    Later runs: reuses saved token.
    """
    creds = None

    # Reuse saved token if it exists
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    # If no valid creds, do the OAuth dance
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    return build("drive", "v3", credentials=creds)


def list_my_docs_and_sheets(service):
    """
    List all Google Docs and Sheets owned by 'me' (not shared with me).
    Handles pagination since Drive returns max 1000 per page.
    """
    mime_types = [
        "application/vnd.google-apps.document",    # Google Docs
        "application/vnd.google-apps.spreadsheet", # Google Sheets
    ]
    mime_filter = " or ".join(f"mimeType='{m}'" for m in mime_types)
    query = f"'me' in owners and trashed=false and ({mime_filter})"

    all_files = []
    page_token = None

    while True:
        response = service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            pageToken=page_token,
        ).execute()

        batch = response.get("files", [])
        all_files.extend(batch)
        print(f"  ... fetched {len(all_files)} files so far")

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return all_files


def run_preview(service):
    """List Drive files and save to drive_file_list.json. Called by ingest.py --preview."""
    print("=" * 60)
    print("ASK-YOU — DRIVE PREVIEW")
    print("=" * 60)

    print("\n[1/2] Listing your Docs and Sheets...")
    files = list_my_docs_and_sheets(service)

    docs = [f for f in files if f["mimeType"].endswith("document")]
    sheets = [f for f in files if f["mimeType"].endswith("spreadsheet")]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total files found: {len(files)}")
    print(f"  Google Docs:     {len(docs)}")
    print(f"  Google Sheets:   {len(sheets)}")

    print("\nFirst 10 files (alphabetical):")
    for f in sorted(files, key=lambda x: x["name"])[:10]:
        kind = "DOC" if f["mimeType"].endswith("document") else "SHEET"
        print(f"  [{kind}] {f['name']}")

    import json
    with open("drive_file_list.json", "w") as out:
        json.dump(files, out, indent=2)
    print(f"\nFull list saved to drive_file_list.json ({len(files)} files)")
    print("\nReview the list. If it looks right, run: python ingest.py --source drive")


def main():
    print("\n[1/2] Authenticating with Google Drive...")
    service = get_drive_service()
    print("  ✓ Connected to Drive")
    run_preview(service)


if __name__ == "__main__":
    main()