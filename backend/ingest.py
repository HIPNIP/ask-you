"""
Ask-You — Unified ingestion CLI.

Orchestrates Drive preview, Drive ingestion, and local file ingestion
through a single interface.

Usage:
    python ingest.py --preview
        List all Drive Docs/Sheets and save to drive_file_list.json.
        Run this before --source drive.

    python ingest.py --source drive
        Ingest files listed in drive_file_list.json into Supabase.

    python ingest.py --source local --path ~/path/to/folder
        Ingest .docx and .xlsx files from a local folder.

    python ingest.py --source all --path ~/path/to/folder
        Run both Drive and local ingestion.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from supabase import create_client

import drive_ingest
import drive_preview
import local_ingest

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")


def main():
    parser = argparse.ArgumentParser(
        description="Ask-You ingestion tool — embed your writing into Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preview",
        action="store_true",
        help="List Drive files without ingesting (saves drive_file_list.json)",
    )
    mode.add_argument(
        "--source",
        choices=["drive", "local", "all"],
        help="Ingestion source",
    )
    parser.add_argument(
        "--path",
        type=str,
        help="Local folder path (required when --source is 'local' or 'all')",
    )

    args = parser.parse_args()

    if args.source in ("local", "all") and not args.path:
        parser.error("--path is required when --source is 'local' or 'all'")

    # Preview mode: no embedding clients needed
    if args.preview:
        print("\nAuthenticating with Google Drive...")
        service = drive_preview.get_drive_service()
        print("  ✓ Connected\n")
        drive_preview.run_preview(service)
        return

    # All ingestion modes need these clients
    missing = [k for k, v in {
        "GCP_PROJECT_ID": GCP_PROJECT_ID,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    }.items() if not v]
    if missing:
        sys.exit(f"ERROR: Missing required .env values: {', '.join(missing)}")

    print("\nInitializing Vertex AI and Supabase...")
    genai_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print("  ✓ Ready\n")

    if args.source in ("drive", "all"):
        drive_service = drive_ingest.get_drive_service()
        drive_ingest.run_drive_ingest(drive_service, genai_client, supabase)

    if args.source in ("local", "all"):
        source_folder = Path(args.path).expanduser().resolve()
        local_ingest.run_local_ingest(genai_client, supabase, source_folder)


if __name__ == "__main__":
    main()
