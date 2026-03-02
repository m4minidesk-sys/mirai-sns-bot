"""
tests/test_scraper.py - scraper.py unit tests
"""

import json
import re
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import (
    extract_drive_file_id,
    parse_clips_from_html,
    parse_duration,
    Clip,
)


# ---------------------------------------------------------------------------
# extract_drive_file_id
# ---------------------------------------------------------------------------

class TestExtractDriveFileId:
    def test_standard_drive_url(self):
        url = "https://drive.google.com/file/d/1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0/view?usp=drivesdk"
        assert extract_drive_file_id(url) == "1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0"

    def test_confirmed_working_file_id(self):
        url = "https://drive.google.com/file/d/18z__BBptnKfF62ncKmpCftUzaG81nOJ8/view"
        assert extract_drive_file_id(url) == "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"

    def test_empty_url_returns_none(self):
        assert extract_drive_file_id("") is None

    def test_none_url_returns_none(self):
        assert extract_drive_file_id(None) is None

    def test_non_drive_url_returns_none(self):
        assert extract_drive_file_id("https://example.com/file") is None

    def test_file_id_with_underscores(self):
        url = "https://drive.google.com/file/d/abc_123-XYZ/view"
        assert extract_drive_file_id(url) == "abc_123-XYZ"


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------

class TestParseDuration:
    def test_mm_ss(self):
        assert parse_duration("1:23") == pytest.approx(83.0)

    def test_zero_mm_ss(self):
        assert parse_duration("0:04") == pytest.approx(4.0)

    def test_hh_mm_ss(self):
        assert parse_duration("1:02:03") == pytest.approx(3723.0)

    def test_empty_string_returns_none(self):
        assert parse_duration("") is None

    def test_none_returns_none(self):
        assert parse_duration(None) is None

    def test_invalid_returns_none(self):
        assert parse_duration("invalid") is None

    def test_whitespace_stripped(self):
        assert parse_duration("  2:30  ") == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# parse_clips_from_html - structure tests using synthetic HTML
# ---------------------------------------------------------------------------

SAMPLE_CARD_HTML = """
<html><body>
<div class="border rounded-lg p-4 space-y-3">
  <a href="/clips/550e8400-e29b-41d4-a716-446655440000" class="text-sm font-semibold">
    テストクリップタイトル
  </a>
  <a href="https://drive.google.com/file/d/1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0/view?usp=drivesdk">
    Download
  </a>
  <a href="/videos/v123" class="underline hover:text-foreground">
    元動画タイトル
  </a>
  <span class="font-semibold text-foreground">1:23</span>
  <p class="text-xs text-muted-foreground leading-relaxed">
    これはトランスクリプトのサンプルです
  </p>
</div>
</body></html>
"""


class TestParseClipsFromHtml:
    def test_parses_one_clip(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert len(clips) == 1

    def test_clip_has_uuid(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].uuid == "550e8400-e29b-41d4-a716-446655440000"

    def test_clip_has_title(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].title == "テストクリップタイトル"

    def test_clip_has_drive_file_id(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].drive_file_id == "1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0"

    def test_clip_has_download_url(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].download_url is not None
        assert "1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0" in clips[0].download_url

    def test_clip_has_duration(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].duration_sec == pytest.approx(83.0)

    def test_clip_has_transcript(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert "トランスクリプト" in clips[0].transcript_text

    def test_clip_has_video_title(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert clips[0].video_title == "元動画タイトル"

    def test_clip_has_clip_url(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert "/clips/550e8400" in clips[0].clip_url

    def test_empty_html_returns_empty_list(self):
        clips = parse_clips_from_html("<html><body></body></html>")
        assert clips == []

    def test_multiple_clips(self):
        html = SAMPLE_CARD_HTML + """
<html><body>
<div class="border rounded-lg p-4 space-y-3">
  <a href="/clips/aaaabbbb-0000-1111-2222-333344445555" class="text-sm font-semibold">
    別のクリップ
  </a>
  <a href="https://drive.google.com/file/d/18z__BBptnKfF62ncKmpCftUzaG81nOJ8/view">
    Download
  </a>
</div>
</body></html>
"""
        clips = parse_clips_from_html(html)
        assert len(clips) == 2

    def test_returns_clip_dataclass(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        assert isinstance(clips[0], Clip)

    def test_clip_schema_has_required_fields(self):
        clips = parse_clips_from_html(SAMPLE_CARD_HTML)
        clip = clips[0]
        # All required fields must be present
        assert hasattr(clip, "uuid")
        assert hasattr(clip, "drive_file_id")
        assert hasattr(clip, "title")
        assert hasattr(clip, "transcript_text")
        assert hasattr(clip, "duration_sec")
        assert hasattr(clip, "video_title")
        assert hasattr(clip, "clip_url")
        assert hasattr(clip, "drive_url")
        assert hasattr(clip, "download_url")
