from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload and ingest a sample PDF.")
    parser.add_argument("pdf_path", type=Path, help="Absolute or relative path to a PDF file.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="AskMyDocs API base URL.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds while waiting for ingest completion.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pdf_path.exists():
        raise SystemExit(f"PDF not found: {args.pdf_path}")

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        with args.pdf_path.open("rb") as pdf_file:
            upload = client.post(
                "/documents/upload",
                files={"file": (args.pdf_path.name, pdf_file, "application/pdf")},
            )
        upload.raise_for_status()
        document = upload.json()["document"]
        document_id = document["id"]

        ingest = client.post(f"/documents/{document_id}/ingest")
        ingest.raise_for_status()
        print(f"Ingest requested for document {document_id}: {ingest.json()}")

        while True:
            detail = client.get(f"/documents/{document_id}")
            detail.raise_for_status()
            body = detail.json()
            latest = body.get("latest_ingestion")
            print(body)

            if latest and latest["status"] in {"completed", "failed"}:
                break

            time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
