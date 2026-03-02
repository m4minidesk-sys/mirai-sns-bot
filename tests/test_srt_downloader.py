"""
tests/test_srt_downloader.py - srt_downloader.py のテスト
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from srt_downloader import (
    _seconds_to_srt_time,
    _segments_to_srt,
    _extract_subtitle_from_html,
    _count_srt_segments,
    download_srt,
    update_db_srt_path,
)

TEST_UUID = "f6e453a5-5ef6-44ca-b8da-b33677ec9a16"

# サンプルセグメント（実際のデータ構造）
SAMPLE_SEGMENTS = [
    {"index": 0, "lines": ["その時に朝霞で"], "startTimeSeconds": 0.0, "endTimeSeconds": 1.372},
    {"index": 1, "lines": ["私は該当避難をしていました", "その日は残念ながら"], "startTimeSeconds": 1.372, "endTimeSeconds": 5.754},
    {"index": 2, "lines": ["誰も聞いてはくれなかった"], "startTimeSeconds": 5.754, "endTimeSeconds": 8.2},
]

SAMPLE_HTML_WITH_SUBTITLE = """
<html><body>
<script>self.__next_f.push([1,"4:[\\"$\\",\\"$Lc\\",null,{\\"clip\\":{\\"id\\":\\"test-uuid\\"},\\"initialSubtitle\\":{\\"id\\":\\"sub-id\\",\\"clipId\\":\\"test-uuid\\",\\"segments\\":[{\\"index\\":0,\\"lines\\":[\\"テスト字幕\\"],\\"startTimeSeconds\\":0,\\"endTimeSeconds\\":1.5},{\\"index\\":1,\\"lines\\":[\\"2行目字幕\\"],\\"startTimeSeconds\\":1.5,\\"endTimeSeconds\\":3.0}],\\"status\\":\\"confirmed\\"}}]"])</script>
</body></html>
"""

SAMPLE_HTML_NO_SUBTITLE = """
<html><body>
<script>self.__next_f.push([1,"4:[\\"$\\",\\"$Lc\\",null,{\\"clip\\":{\\"id\\":\\"test-uuid\\"}}]"])</script>
</body></html>
"""


class TestSecondsToSrtTime:
    def test_zero_seconds(self):
        assert _seconds_to_srt_time(0) == "00:00:00,000"

    def test_milliseconds(self):
        assert _seconds_to_srt_time(1.372) == "00:00:01,372"

    def test_minutes(self):
        assert _seconds_to_srt_time(81.24) == "00:01:21,240"

    def test_hours(self):
        assert _seconds_to_srt_time(3661.5) == "01:01:01,500"

    def test_only_seconds(self):
        assert _seconds_to_srt_time(30.0) == "00:00:30,000"

    def test_rounding(self):
        result = _seconds_to_srt_time(1.9999)
        assert "00:00:01" in result


class TestSegmentsToSrt:
    def test_basic_format(self):
        srt = _segments_to_srt(SAMPLE_SEGMENTS)
        assert "1\n" in srt
        assert "00:00:00,000 --> 00:00:01,372" in srt
        assert "その時に朝霞で" in srt

    def test_multiline_segment(self):
        srt = _segments_to_srt(SAMPLE_SEGMENTS)
        assert "私は該当避難をしていました" in srt
        assert "その日は残念ながら" in srt

    def test_sequential_numbering(self):
        srt = _segments_to_srt(SAMPLE_SEGMENTS)
        lines = srt.split("\n")
        assert lines[0] == "1"

    def test_empty_segments(self):
        srt = _segments_to_srt([])
        assert srt == ""

    def test_three_segments(self):
        srt = _segments_to_srt(SAMPLE_SEGMENTS)
        # 3つのセグメントが含まれること
        assert "誰も聞いてはくれなかった" in srt


class TestExtractSubtitleFromHtml:
    def test_extracts_segments(self):
        result = _extract_subtitle_from_html(SAMPLE_HTML_WITH_SUBTITLE)
        assert result is not None
        assert "segments" in result
        assert len(result["segments"]) == 2

    def test_segment_content(self):
        result = _extract_subtitle_from_html(SAMPLE_HTML_WITH_SUBTITLE)
        assert result["segments"][0]["lines"][0] == "テスト字幕"

    def test_no_subtitle_returns_none(self):
        result = _extract_subtitle_from_html(SAMPLE_HTML_NO_SUBTITLE)
        assert result is None

    def test_empty_html_returns_none(self):
        result = _extract_subtitle_from_html("<html></html>")
        assert result is None


class TestCountSrtSegments:
    def test_count_three_segments(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nテスト\n\n2\n00:00:01,000 --> 00:00:02,000\nテスト2\n\n3\n00:00:02,000 --> 00:00:03,000\nテスト3\n")
            fname = f.name
        try:
            assert _count_srt_segments(Path(fname)) == 3
        finally:
            os.unlink(fname)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            fname = f.name
        try:
            assert _count_srt_segments(Path(fname)) == 0
        finally:
            os.unlink(fname)


class TestDownloadSrtUnit:
    def test_dry_run_returns_dry_run_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_srt(TEST_UUID, output_dir=tmpdir, dry_run=True)
        assert result["status"] == "dry_run"
        assert result["uuid"] == TEST_UUID

    def test_skip_existing_srt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 事前にSRTファイルを作成
            srt_path = Path(tmpdir) / f"{TEST_UUID}.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nテスト\n", encoding="utf-8")
            result = download_srt(TEST_UUID, output_dir=tmpdir, overwrite=False)
        assert result["status"] == "skipped"

    def test_result_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_srt(TEST_UUID, output_dir=tmpdir, dry_run=True)
        assert "uuid" in result
        assert "srt_path" in result
        assert "status" in result
        assert "segment_count" in result


class TestUpdateDbSrtPath:
    def test_no_db_does_not_crash(self):
        # DBファイルが存在しない場合はスルー
        update_db_srt_path("test-uuid", "/tmp/test.srt", Path("/tmp/nonexistent.db"))

    def test_updates_existing_db(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "posted.db"
            # テーブルを作成
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE clips (
                    uuid TEXT PRIMARY KEY,
                    title TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("INSERT INTO clips (uuid, title) VALUES (?, ?)", ("test-uuid", "テスト"))
            conn.commit()
            conn.close()
            # srt_path更新
            update_db_srt_path("test-uuid", "/tmp/test.srt", db_path)
            # 確認
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT srt_path FROM clips WHERE uuid = ?", ("test-uuid",)).fetchone()
            conn.close()
            assert row[0] == "/tmp/test.srt"


# ===== 結合テスト（実際のHTTP）=====

@pytest.mark.integration
def test_download_srt_real():
    """実際のサイトからSRTをDLするテスト"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = download_srt(TEST_UUID, output_dir=tmpdir, overwrite=True)

    print(f"\nSRT DL結果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    assert result["status"] == "success", f"SRT DL失敗: {result['status']}"
    assert result["segment_count"] > 0
    # SRTファイルの中身確認
    srt_content = Path(result["srt_path"]).read_text(encoding="utf-8") if Path(result["srt_path"]).exists() else ""
    # tmpdir内のファイルはwithブロック外で消えるのでここではpathを確認のみ
    assert result["srt_path"].endswith(".srt")

