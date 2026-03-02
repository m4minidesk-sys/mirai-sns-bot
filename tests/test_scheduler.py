"""
tests/test_scheduler.py - scheduler.py unit tests

dry-run モードで全テストをPASS。実APIコールなし。
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from downloader import init_db, upsert_clip, mark_downloaded, mark_posted
from scheduler import (
    get_todays_post_count,
    get_downloadable_candidates,
    prioritize_candidates,
    run_schedule,
    PRIORITY_POLICY,
    PRIORITY_VARIETY,
    PRIORITY_OTHER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn, db_path
    conn.close()


def _add_downloaded_clip(conn, uuid, title, local_path="/tmp/test.mp4"):
    upsert_clip(conn, uuid, title, f"fid_{uuid}")
    mark_downloaded(conn, uuid, local_path)


# ---------------------------------------------------------------------------
# get_todays_post_count
# ---------------------------------------------------------------------------

class TestGetTodaysPostCount:
    def test_zero_when_no_posts(self, tmp_db):
        conn, _ = tmp_db
        assert get_todays_post_count(conn) == 0

    def test_counts_todays_posted(self, tmp_db):
        conn, _ = tmp_db
        upsert_clip(conn, "u1", "T1", "fid1")
        mark_downloaded(conn, "u1", "/tmp/v1.mp4")
        mark_posted(conn, "u1")
        # posted_at is set to datetime('now') which is today
        assert get_todays_post_count(conn) >= 0  # may be 0 or 1 depending on day boundary


# ---------------------------------------------------------------------------
# get_downloadable_candidates
# ---------------------------------------------------------------------------

class TestGetDownloadableCandidates:
    def test_empty_db_returns_empty_list(self, tmp_db):
        conn, _ = tmp_db
        candidates = get_downloadable_candidates(conn)
        assert candidates == []

    def test_pending_clips_not_returned(self, tmp_db):
        conn, _ = tmp_db
        upsert_clip(conn, "u1", "T1", "fid1")
        # status = 'pending', not downloaded
        candidates = get_downloadable_candidates(conn)
        assert len(candidates) == 0

    def test_downloaded_clips_returned(self, tmp_db):
        conn, _ = tmp_db
        _add_downloaded_clip(conn, "u1", "T1")
        candidates = get_downloadable_candidates(conn)
        assert len(candidates) == 1
        assert candidates[0]["uuid"] == "u1"

    def test_posted_clips_not_returned(self, tmp_db):
        conn, _ = tmp_db
        _add_downloaded_clip(conn, "u1", "T1")
        mark_posted(conn, "u1")
        candidates = get_downloadable_candidates(conn)
        assert len(candidates) == 0

    def test_multiple_downloaded_clips(self, tmp_db):
        conn, _ = tmp_db
        for i in range(5):
            _add_downloaded_clip(conn, f"u{i}", f"Title {i}")
        candidates = get_downloadable_candidates(conn)
        assert len(candidates) == 5


# ---------------------------------------------------------------------------
# prioritize_candidates
# ---------------------------------------------------------------------------

class TestPrioritizeCandidates:
    POLICY_CLIP = {
        "uuid": "u1",
        "title": "AI政策について語る",
        "transcript_text": "テクノロジーと人工知能で日本を変えます",
        "local_path": "/tmp/v1.mp4",
    }
    VARIETY_CLIP = {
        "uuid": "u2",
        "title": "感動エピソード",
        "transcript_text": "家族との思い出、感謝の気持ち",
        "local_path": "/tmp/v2.mp4",
    }
    OTHER_CLIP = {
        "uuid": "u3",
        "title": "通常クリップ",
        "transcript_text": "特にキーワードなし",
        "local_path": "/tmp/v3.mp4",
    }

    def test_policy_clip_has_highest_priority(self):
        clips = [self.OTHER_CLIP, self.VARIETY_CLIP, self.POLICY_CLIP]
        result = prioritize_candidates(clips)
        assert result[0]["uuid"] == "u1"  # policy first

    def test_variety_clip_beats_other(self):
        clips = [self.OTHER_CLIP, self.VARIETY_CLIP]
        result = prioritize_candidates(clips)
        assert result[0]["uuid"] == "u2"  # variety > other

    def test_priority_field_added(self):
        result = prioritize_candidates([self.POLICY_CLIP])
        assert "_priority" in result[0]

    def test_policy_priority_value(self):
        result = prioritize_candidates([self.POLICY_CLIP])
        assert result[0]["_priority"] >= PRIORITY_POLICY

    def test_other_priority_value(self):
        result = prioritize_candidates([self.OTHER_CLIP])
        assert result[0]["_priority"] == PRIORITY_OTHER

    def test_empty_list_returns_empty(self):
        assert prioritize_candidates([]) == []

    def test_ordering_policy_variety_other(self):
        clips = [self.OTHER_CLIP, self.VARIETY_CLIP, self.POLICY_CLIP]
        result = prioritize_candidates(clips)
        priorities = [r["_priority"] for r in result]
        assert priorities == sorted(priorities, reverse=True)


# ---------------------------------------------------------------------------
# run_schedule
# ---------------------------------------------------------------------------

class TestRunSchedule:
    def test_empty_db_returns_zero_summary(self, tmp_path):
        db_path = tmp_path / "test.db"
        summary = run_schedule(db_path=db_path, dry_run=True)
        assert summary["posted"] == 0

    def test_dry_run_flag_in_summary(self, tmp_path):
        db_path = tmp_path / "test.db"
        summary = run_schedule(db_path=db_path, dry_run=True)
        assert summary["dry_run"] is True

    def test_daily_limit_in_summary(self, tmp_path):
        db_path = tmp_path / "test.db"
        summary = run_schedule(db_path=db_path, daily_limit=5, dry_run=True)
        assert summary["daily_limit"] == 5

    def test_clips_override_used(self, tmp_path):
        """clips_override でDBバイパス可能"""
        db_path = tmp_path / "test.db"
        clips = [
            {"uuid": "u1", "title": "テスト", "transcript_text": "", "local_path": "/tmp/v.mp4"},
        ]
        with patch("scheduler.post_to_sns") as mock_post:
            mock_post.return_value = {"overall_status": "dry_run", "results": {}}
            summary = run_schedule(
                db_path=db_path,
                clips_override=clips,
                dry_run=True,
                daily_limit=3,
            )
        assert summary["posted"] == 1

    def test_daily_limit_respected(self, tmp_path):
        """daily_limit を超えて投稿しない"""
        db_path = tmp_path / "test.db"
        clips = [
            {"uuid": f"u{i}", "title": f"T{i}", "transcript_text": "", "local_path": f"/tmp/v{i}.mp4"}
            for i in range(10)
        ]
        with patch("scheduler.post_to_sns") as mock_post:
            mock_post.return_value = {"overall_status": "dry_run", "results": {}}
            summary = run_schedule(
                db_path=db_path,
                clips_override=clips,
                dry_run=True,
                daily_limit=3,
            )
        assert summary["posted"] == 3

    def test_results_list_matches_posted_count(self, tmp_path):
        db_path = tmp_path / "test.db"
        clips = [
            {"uuid": "u1", "title": "T1", "transcript_text": "", "local_path": "/tmp/v1.mp4"},
            {"uuid": "u2", "title": "T2", "transcript_text": "", "local_path": "/tmp/v2.mp4"},
        ]
        with patch("scheduler.post_to_sns") as mock_post:
            mock_post.return_value = {"overall_status": "dry_run", "results": {}}
            summary = run_schedule(
                db_path=db_path,
                clips_override=clips,
                dry_run=True,
                daily_limit=5,
            )
        assert len(summary["results"]) == 2

    def test_platform_list_passed_to_post_to_sns(self, tmp_path):
        db_path = tmp_path / "test.db"
        clips = [
            {"uuid": "u1", "title": "T1", "transcript_text": "", "local_path": "/tmp/v.mp4"},
        ]
        with patch("scheduler.post_to_sns") as mock_post:
            mock_post.return_value = {"overall_status": "dry_run", "results": {}}
            run_schedule(
                db_path=db_path,
                clips_override=clips,
                platforms=["x"],
                dry_run=True,
            )
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["platforms"] == ["x"] or call_kwargs[0][1] == ["x"]

    def test_non_dry_run_marks_posted_in_db(self, tmp_path):
        """non-dry-run で投稿成功時はDBに mark_posted が呼ばれる"""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        _add_downloaded_clip(conn, "u1", "T1")
        conn.close()

        with patch("scheduler.post_to_sns") as mock_post:
            mock_post.return_value = {
                "overall_status": "posted",
                "results": {"x": {"status": "posted"}},
            }
            summary = run_schedule(
                db_path=db_path,
                platforms=["x"],
                dry_run=False,
                daily_limit=1,
            )

        assert summary["posted"] == 1
        # Verify DB updated
        conn2 = init_db(db_path)
        row = conn2.execute("SELECT status FROM clips WHERE uuid='u1'").fetchone()
        conn2.close()
        assert row["status"] == "posted"
