"""
downloader.py - Google Drive clip downloader

Downloads clips from Google Drive (unauthenticated public file download)
and tracks posted/downloaded state in posted.db (SQLite).

Usage:
    python downloader.py --file-id 1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0 [--dry-run]
    python downloader.py --clips-json clips.json [--dry-run] [--limit 5]
"""

import argparse
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DRIVE_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download"
DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_DB_PATH = Path("posted.db")
CHUNK_SIZE = 8192
REQUEST_TIMEOUT = 60  # seconds


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize SQLite DB and return connection."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            uuid TEXT PRIMARY KEY,
            title TEXT,
            drive_file_id TEXT,
            local_path TEXT,
            downloaded_at TEXT,
            posted_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_clips_drive_file_id ON clips(drive_file_id)
    """)
    conn.commit()
    return conn


def upsert_clip(conn: sqlite3.Connection, uuid: str, title: str,
                drive_file_id: Optional[str]) -> None:
    """Insert or update a clip record (idempotent)."""
    conn.execute("""
        INSERT INTO clips (uuid, title, drive_file_id, status)
        VALUES (?, ?, ?, 'pending')
        ON CONFLICT(uuid) DO UPDATE SET
            title = excluded.title,
            drive_file_id = excluded.drive_file_id
    """, (uuid, title, drive_file_id))
    conn.commit()


def mark_downloaded(conn: sqlite3.Connection, uuid: str, local_path: str) -> None:
    """Mark a clip as downloaded."""
    conn.execute("""
        UPDATE clips SET local_path = ?, downloaded_at = datetime('now'), status = 'downloaded'
        WHERE uuid = ?
    """, (local_path, uuid))
    conn.commit()


def mark_posted(conn: sqlite3.Connection, uuid: str) -> None:
    """Mark a clip as posted."""
    conn.execute("""
        UPDATE clips SET posted_at = datetime('now'), status = 'posted'
        WHERE uuid = ?
    """, (uuid,))
    conn.commit()


def is_downloaded(conn: sqlite3.Connection, uuid: str) -> bool:
    """Check if a clip is already downloaded."""
    row = conn.execute(
        "SELECT status, local_path FROM clips WHERE uuid = ?", (uuid,)
    ).fetchone()
    if row is None:
        return False
    return row["status"] in ("downloaded", "posted") and bool(row["local_path"])


def is_posted(conn: sqlite3.Connection, uuid: str) -> bool:
    """Check if a clip has already been posted."""
    row = conn.execute("SELECT status FROM clips WHERE uuid = ?", (uuid,)).fetchone()
    return row is not None and row["status"] == "posted"


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

def build_download_url(file_id: str) -> str:
    """Build Google Drive usercontent download URL."""
    return DRIVE_DOWNLOAD_URL.format(file_id=file_id)


def _safe_filename(title: str, file_id: str) -> str:
    """Generate a safe filename from title and file_id."""
    safe = re.sub(r'[\\/:*?"<>|]', "_", title)
    safe = safe.strip().replace(" ", "_")[:60]
    short_id = file_id[:8]
    return f"{safe}_{short_id}.mp4"


def download_clip(
    file_id: str,
    dest_dir: Path = DEFAULT_DOWNLOAD_DIR,
    filename: Optional[str] = None,
    dry_run: bool = False,
    session: Optional[requests.Session] = None,
) -> Optional[Path]:
    """
    Download a Google Drive file by file_id.

    Args:
        file_id: Google Drive file ID.
        dest_dir: Directory to save the file.
        filename: Override filename (default: {file_id}.mp4).
        dry_run: If True, only verify the URL is reachable (HEAD request), don't save.
        session: Optional requests.Session (created if not provided).

    Returns:
        Path to downloaded file, or None on failure/dry-run.
    """
    url = build_download_url(file_id)
    filename = filename or f"{file_id}.mp4"
    dest_path = dest_dir / filename

    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    if dry_run:
        logger.info(f"[dry-run] Would download: {url} -> {dest_path}")
        try:
            resp = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            content_type = resp.headers.get("content-type", "")
            logger.info(f"[dry-run] Status: {resp.status_code}, Content-Type: {content_type}")
            return None
        except requests.RequestException as e:
            logger.error(f"[dry-run] Failed to reach {url}: {e}")
            return None

    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Downloading {file_id} -> {dest_path}")
    try:
        resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "video" not in content_type and "octet-stream" not in content_type:
            logger.warning(f"Unexpected content-type: {content_type} for {file_id}")

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)

        logger.info(f"Downloaded: {dest_path} ({dest_path.stat().st_size} bytes)")
        return dest_path

    except requests.RequestException as e:
        logger.error(f"Failed to download {file_id}: {e}")
        if dest_path.exists():
            dest_path.unlink()
        return None


def process_clips_json(
    clips_json: Path,
    dest_dir: Path = DEFAULT_DOWNLOAD_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    dry_run: bool = False,
    limit: Optional[int] = None,
    skip_downloaded: bool = True,
) -> dict:
    """
    Process a clips.json file, registering clips to DB and downloading each.

    Returns summary dict with counts.
    """
    with open(clips_json, encoding="utf-8") as f:
        clips = json.load(f)

    if limit:
        clips = clips[:limit]

    conn = init_db(db_path)
    session = requests.Session()

    summary = {"total": len(clips), "downloaded": 0, "skipped": 0, "failed": 0}

    for clip in clips:
        uuid = clip.get("uuid") or clip.get("id")
        title = clip.get("title", "")
        drive_file_id = clip.get("drive_file_id")

        if not uuid or not drive_file_id:
            logger.warning(f"Skipping clip with missing uuid/file_id: {clip}")
            summary["skipped"] += 1
            continue

        upsert_clip(conn, uuid, title, drive_file_id)

        if skip_downloaded and not dry_run and is_downloaded(conn, uuid):
            logger.info(f"Already downloaded: {uuid}")
            summary["skipped"] += 1
            continue

        filename = _safe_filename(title, drive_file_id)
        path = download_clip(
            file_id=drive_file_id,
            dest_dir=dest_dir,
            filename=filename,
            dry_run=dry_run,
            session=session,
        )

        if dry_run:
            summary["downloaded"] += 1
        elif path:
            mark_downloaded(conn, uuid, str(path))
            summary["downloaded"] += 1
        else:
            summary["failed"] += 1

        time.sleep(0.5)

    conn.close()
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Google Drive clip downloader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file-id", help="Google Drive file ID to download")
    group.add_argument("--clips-json", type=Path, help="clips.json from scraper")

    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                        help="Directory to save downloads")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB path for tracking")
    parser.add_argument("--dry-run", action="store_true",
                        help="Verify URLs only, don't save files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max clips to process (when using --clips-json)")
    parser.add_argument("--filename", default=None,
                        help="Override filename (only with --file-id)")
    args = parser.parse_args()

    if args.file_id:
        path = download_clip(
            file_id=args.file_id,
            dest_dir=args.output_dir,
            filename=args.filename,
            dry_run=args.dry_run,
        )
        if path:
            print(f"Downloaded: {path}")
        elif args.dry_run:
            print("[dry-run] Verification complete")
        else:
            print("Download failed", flush=True)
            raise SystemExit(1)

    else:
        summary = process_clips_json(
            clips_json=args.clips_json,
            dest_dir=args.output_dir,
            db_path=args.db,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
