"""
tests/test_downloader.py - downloader.py unit tests

Uses unittest.mock to avoid real HTTP/filesystem calls.
One live HTTP test is gated behind MIRAI_LIVE_TEST env var.
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloader import (
    build_download_url,
    init_db,
    upsert_clip,
    mark_downloaded,
    mark_posted,
    is_downloaded,
    is_posted,
    download_clip,
    _safe_filename,
    process_clips_json,
    DEFAULT_DB_PATH,
    DEFAULT_DOWNLOAD_DIR,
)


# ---------------------------------------------------------------------------
# build_download_url
# ---------------------------------------------------------------------------

class TestBuildDownloadUrl:
    def test_contains_file_id(self):
        url = build_download_url("abc123")
        assert "abc123" in url

    def test_uses_drive_usercontent_domain(self):
        url = build_download_url("abc123")
        assert "drive.usercontent.google.com" in url

    def test_has_export_download_param(self):
        url = build_download_url("abc123")
        assert "export=download" in url

    def test_known_file_id(self):
        fid = "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"
        url = build_download_url(fid)
        expected = f"https://drive.usercontent.google.com/download?id={fid}&export=download"
        assert url == expected


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_has_mp4_extension(self):
        assert _safe_filename("test", "abc12345").endswith(".mp4")

    def test_contains_short_file_id(self):
        name = _safe_filename("title", "abc12345xyz")
        assert "abc12345" in name

    def test_removes_forbidden_chars(self):
        name = _safe_filename('test/file:name*?', "abc12345")
        assert "/" not in name
        assert ":" not in name
        assert "*" not in name
        assert "?" not in name

    def test_max_length(self):
        long_title = "a" * 200
        name = _safe_filename(long_title, "abc12345")
        assert len(name) <= 80  # 60 chars + underscore + 8 chars + .mp4


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

class TestDatabase:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self.tmp.name)
        self.conn = init_db(self.db_path)

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_init_creates_clips_table(self):
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='clips'"
        ).fetchall()
        assert len(tables) == 1

    def test_upsert_inserts_new_clip(self):
        upsert_clip(self.conn, "uuid-1", "Title 1", "file-id-1")
        row = self.conn.execute("SELECT * FROM clips WHERE uuid = 'uuid-1'").fetchone()
        assert row is not None
        assert row["title"] == "Title 1"
        assert row["drive_file_id"] == "file-id-1"
        assert row["status"] == "pending"

    def test_upsert_is_idempotent(self):
        upsert_clip(self.conn, "uuid-1", "Title 1", "file-id-1")
        upsert_clip(self.conn, "uuid-1", "Title 1 updated", "file-id-1")
        rows = self.conn.execute("SELECT * FROM clips WHERE uuid = 'uuid-1'").fetchall()
        assert len(rows) == 1
        assert rows[0]["title"] == "Title 1 updated"

    def test_mark_downloaded_updates_status(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        mark_downloaded(self.conn, "uuid-1", "/tmp/test.mp4")
        row = self.conn.execute("SELECT * FROM clips WHERE uuid = 'uuid-1'").fetchone()
        assert row["status"] == "downloaded"
        assert row["local_path"] == "/tmp/test.mp4"
        assert row["downloaded_at"] is not None

    def test_mark_posted_updates_status(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        mark_downloaded(self.conn, "uuid-1", "/tmp/test.mp4")
        mark_posted(self.conn, "uuid-1")
        row = self.conn.execute("SELECT * FROM clips WHERE uuid = 'uuid-1'").fetchone()
        assert row["status"] == "posted"
        assert row["posted_at"] is not None

    def test_is_downloaded_false_for_new_clip(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        assert is_downloaded(self.conn, "uuid-1") is False

    def test_is_downloaded_true_after_mark(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        mark_downloaded(self.conn, "uuid-1", "/tmp/test.mp4")
        assert is_downloaded(self.conn, "uuid-1") is True

    def test_is_downloaded_true_after_posted(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        mark_downloaded(self.conn, "uuid-1", "/tmp/test.mp4")
        mark_posted(self.conn, "uuid-1")
        assert is_downloaded(self.conn, "uuid-1") is True

    def test_is_downloaded_false_for_unknown_uuid(self):
        assert is_downloaded(self.conn, "nonexistent-uuid") is False

    def test_is_posted_false_for_new_clip(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        assert is_posted(self.conn, "uuid-1") is False

    def test_is_posted_true_after_mark(self):
        upsert_clip(self.conn, "uuid-1", "Title", "fid")
        mark_posted(self.conn, "uuid-1")
        assert is_posted(self.conn, "uuid-1") is True

    def test_is_posted_false_for_unknown_uuid(self):
        assert is_posted(self.conn, "nonexistent-uuid") is False


# ---------------------------------------------------------------------------
# download_clip (mocked HTTP)
# ---------------------------------------------------------------------------

class TestDownloadClip:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.dest_dir = Path(self.tmp_dir)

    def _make_session(self, status_code=200, content_type="video/mp4", content=b"fake_video"):
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.headers = {"content-type": content_type}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=[content])
        session.get = MagicMock(return_value=mock_resp)
        session.head = MagicMock(return_value=mock_resp)
        return session

    def test_download_returns_path(self):
        session = self._make_session()
        result = download_clip("test_file_id", dest_dir=self.dest_dir, session=session)
        assert result is not None
        assert result.exists()

    def test_download_file_has_content(self):
        session = self._make_session(content=b"video_data_here")
        result = download_clip("test_file_id", dest_dir=self.dest_dir, session=session)
        assert result is not None
        assert result.read_bytes() == b"video_data_here"

    def test_dry_run_returns_none(self):
        session = self._make_session()
        result = download_clip("test_file_id", dest_dir=self.dest_dir,
                               dry_run=True, session=session)
        assert result is None

    def test_dry_run_does_not_create_file(self):
        session = self._make_session()
        download_clip("test_file_id", dest_dir=self.dest_dir,
                      dry_run=True, session=session)
        files = list(self.dest_dir.glob("*.mp4"))
        assert len(files) == 0

    def test_custom_filename(self):
        session = self._make_session()
        result = download_clip("fid", dest_dir=self.dest_dir,
                               filename="custom.mp4", session=session)
        assert result is not None
        assert result.name == "custom.mp4"

    def test_http_error_returns_none(self):
        import requests
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        session.get = MagicMock(return_value=mock_resp)
        result = download_clip("bad_id", dest_dir=self.dest_dir, session=session)
        assert result is None

    def test_creates_dest_dir_if_missing(self):
        new_dir = self.dest_dir / "subdir" / "nested"
        session = self._make_session()
        result = download_clip("fid", dest_dir=new_dir, session=session)
        assert new_dir.exists()

    def test_default_filename_has_mp4_extension(self):
        session = self._make_session()
        result = download_clip("my_file_id", dest_dir=self.dest_dir, session=session)
        assert result is not None
        assert result.suffix == ".mp4"


# ---------------------------------------------------------------------------
# process_clips_json
# ---------------------------------------------------------------------------

class TestProcessClipsJson:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.dest_dir = Path(self.tmp_dir) / "downloads"
        self.db_path = Path(self.tmp_dir) / "test.db"
        self.clips_json = Path(self.tmp_dir) / "clips.json"

    def _write_clips(self, clips):
        with open(self.clips_json, "w") as f:
            json.dump(clips, f)

    def test_empty_clips_returns_zero_summary(self):
        self._write_clips([])
        summary = process_clips_json(
            self.clips_json, dest_dir=self.dest_dir, db_path=self.db_path, dry_run=True
        )
        assert summary["total"] == 0
        assert summary["downloaded"] == 0

    def test_clips_missing_drive_file_id_are_skipped(self):
        self._write_clips([{"uuid": "u1", "title": "T", "drive_file_id": None}])
        summary = process_clips_json(
            self.clips_json, dest_dir=self.dest_dir, db_path=self.db_path, dry_run=True
        )
        assert summary["skipped"] == 1

    def test_limit_parameter(self):
        clips = [
            {"uuid": f"u{i}", "title": f"T{i}", "drive_file_id": f"fid{i}"}
            for i in range(10)
        ]
        self._write_clips(clips)
        with patch("downloader.download_clip", return_value=None) as mock_dl:
            summary = process_clips_json(
                self.clips_json, dest_dir=self.dest_dir, db_path=self.db_path,
                dry_run=True, limit=3
            )
        assert summary["total"] == 3

    def test_dry_run_does_not_mark_downloaded_in_db(self):
        clips = [{"uuid": "u1", "title": "T", "drive_file_id": "fid1"}]
        self._write_clips(clips)
        with patch("downloader.download_clip", return_value=None):
            process_clips_json(
                self.clips_json, dest_dir=self.dest_dir, db_path=self.db_path, dry_run=True
            )
        conn = init_db(self.db_path)
        row = conn.execute("SELECT status FROM clips WHERE uuid = 'u1'").fetchone()
        conn.close()
        # dry_run: clip is registered but not marked downloaded
        assert row is not None
        assert row["status"] == "pending"

    def test_already_downloaded_clips_are_skipped(self):
        clips = [{"uuid": "u1", "title": "T", "drive_file_id": "fid1"}]
        self._write_clips(clips)
        conn = init_db(self.db_path)
        upsert_clip(conn, "u1", "T", "fid1")
        mark_downloaded(conn, "u1", "/tmp/already.mp4")
        conn.close()

        with patch("downloader.download_clip") as mock_dl:
            summary = process_clips_json(
                self.clips_json, dest_dir=self.dest_dir, db_path=self.db_path,
                dry_run=False, skip_downloaded=True
            )
        mock_dl.assert_not_called()
        assert summary["skipped"] == 1


# ---------------------------------------------------------------------------
# Live HTTP test (gated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("MIRAI_LIVE_TEST"),
    reason="Set MIRAI_LIVE_TEST=1 to run live HTTP tests"
)
class TestLiveDownload:
    """
    Live integration test: verifies the confirmed working Drive file ID.
    Requires internet access. Run with: MIRAI_LIVE_TEST=1 pytest tests/test_downloader.py::TestLiveDownload
    """

    CONFIRMED_FILE_ID = "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"

    def test_live_download_http_200(self):
        import requests
        url = build_download_url(self.CONFIRMED_FILE_ID)
        resp = requests.get(url, stream=True, timeout=30)
        assert resp.status_code == 200

    def test_live_download_content_type_video(self):
        import requests
        url = build_download_url(self.CONFIRMED_FILE_ID)
        resp = requests.get(url, stream=True, timeout=30)
        content_type = resp.headers.get("content-type", "")
        assert "video" in content_type or "octet-stream" in content_type
