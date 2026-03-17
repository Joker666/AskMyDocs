from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from pathlib import Path

import httpx


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument(
        "--question",
        help="Optional question to ask after the document finishes ingesting.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-k value to use for the optional query step.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.pdf_path.exists():
        print(f"PDF not found: {args.pdf_path}")
        return 1

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        with args.pdf_path.open("rb") as pdf_file:
            upload = client.post(
                "/documents/upload",
                files={"file": (args.pdf_path.name, pdf_file, "application/pdf")},
            )
        upload.raise_for_status()
        document = upload.json()["document"]
        document_id = document["id"]
        print(json.dumps({"uploaded_document": document}, indent=2))

        ingest = client.post(f"/documents/{document_id}/ingest")
        ingest.raise_for_status()
        print(json.dumps({"ingestion_requested": ingest.json()}, indent=2))

        while True:
            detail = client.get(f"/documents/{document_id}")
            detail.raise_for_status()
            body = detail.json()
            latest = body.get("latest_ingestion")
            print(json.dumps({"document_detail": body}, indent=2))

            if latest and latest["status"] in {"completed", "failed"}:
                break

            time.sleep(args.poll_interval)

        if latest and latest["status"] == "failed":
            print(
                json.dumps(
                    {"ingestion_failed": latest},
                    indent=2,
                )
            )
            return 1

        if args.question:
            query = client.post(
                "/query",
                json={
                    "question": args.question,
                    "document_ids": [document_id],
                    "top_k": args.top_k,
                },
            )
            query.raise_for_status()
            print(json.dumps({"query_response": query.json()}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
