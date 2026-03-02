"""
tests/test_scraper.py - scraper.py のテスト
"""

import json
import pytest
import requests

from scraper import (
    extract_drive_file_id,
    parse_duration,
    parse_clips_from_html,
    scrape_page,
    DRIVE_USERCONTENT_DL,
)


# ===== ユニットテスト =====

def test_extract_drive_file_id_standard():
    url = "https://drive.google.com/file/d/18z__BBptnKfF62ncKmpCftUzaG81nOJ8/view?usp=drivesdk"
    assert extract_drive_file_id(url) == "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"


def test_extract_drive_file_id_none():
    assert extract_drive_file_id(None) is None
    assert extract_drive_file_id("https://example.com") is None


def test_parse_duration_mm_ss():
    assert parse_duration("1:23") == 83.0
    assert parse_duration("0:04") == 4.0
    assert parse_duration("4:07") == 247.0


def test_parse_duration_invalid():
    assert parse_duration("") is None
    assert parse_duration(None) is None
    assert parse_duration("abc") is None


def test_download_url_format():
    file_id = "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"
    expected = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    result = DRIVE_USERCONTENT_DL.format(file_id=file_id)
    assert result == expected


# ===== HTMLパーステスト =====

SAMPLE_HTML = """
<html><body>
<div class="border rounded-lg p-4 space-y-3 hover:bg-muted/50">
  <div class="flex items-start justify-between gap-3">
    <a class="text-sm font-semibold hover:underline" href="/clips/8ba8cd03-bca6-438f-a7f6-67445b0b806e">
      街頭演説で出会ったバス誘導員からの励ましの言葉
    </a>
    <div>
      <a href="https://drive.google.com/file/d/1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0/view?usp=drivesdk"
         target="_blank" rel="noopener noreferrer"
         class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-white bg-black rounded">
        DL
      </a>
    </div>
  </div>
  <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
    <span class="inline-flex items-center gap-1">
      <a class="underline hover:text-foreground" href="/videos/6b18bb52">テスト動画タイトル.mp4</a>
    </span>
    <span class="inline-flex items-center gap-1 font-semibold text-foreground">
      <svg></svg>1:26
    </span>
    <span>2026/02/07 23:19</span>
  </div>
  <p class="text-xs text-muted-foreground leading-relaxed line-clamp-2">
    <svg></svg>これはテストのtranscriptです。
  </p>
</div>
</body></html>
"""

def test_parse_clips_from_html_basic():
    clips = parse_clips_from_html(SAMPLE_HTML)
    assert len(clips) == 1
    clip = clips[0]
    assert clip.uuid == "8ba8cd03-bca6-438f-a7f6-67445b0b806e"
    assert clip.drive_file_id == "1VEyqtWH14gE6xjmsDDv8-qXbtBPWQtM0"
    assert "バス誘導員" in clip.title
    assert clip.duration_sec == 86.0
    assert "transcript" in clip.transcript_text


def test_parse_clips_drive_url_present():
    clips = parse_clips_from_html(SAMPLE_HTML)
    assert clips[0].download_url is not None
    assert "drive.usercontent.google.com" in clips[0].download_url
    assert clips[0].drive_file_id in clips[0].download_url


def test_parse_clips_empty_html():
    clips = parse_clips_from_html("<html><body></body></html>")
    assert clips == []


# ===== 結合テスト（実際のHTTP）=====

@pytest.mark.integration
def test_scrape_page_live():
    """実際のサイトから1ページ取得するテスト"""
    clips, total_pages = scrape_page(1)
    assert len(clips) > 0, "クリップが取得できなかった"
    assert total_pages >= 1

    # スキーマ検証
    for clip in clips:
        assert clip.uuid, f"UUID空: {clip}"
        assert clip.title, f"タイトル空: {clip}"
        # Drive URLが存在する場合はfile_idも必要
        if clip.drive_url:
            assert clip.drive_file_id, f"drive_file_idがない: {clip}"
            assert clip.download_url, f"download_urlがない: {clip}"

    print(f"\n取得クリップ数: {len(clips)}, 総ページ数: {total_pages}")
    print(f"サンプル: {clips[0].title} / {clips[0].drive_file_id}")

