"""
tests/test_downloader.py - downloader.py のテスト
"""

import os
import json
import pytest
import tempfile
from pathlib import Path

from downloader import (
    build_download_url,
    download_video,
    _extract_confirm_token,
)

TEST_FILE_ID = "18z__BBptnKfF62ncKmpCftUzaG81nOJ8"  # AYA確認済みパブリックID


# ===== ユニットテスト =====

def test_build_download_url():
    url = build_download_url(TEST_FILE_ID)
    assert url == f"https://drive.usercontent.google.com/download?id={TEST_FILE_ID}&export=download"


def test_extract_confirm_token_standard():
    html = '<input name="confirm" value="abc123XYZ">'
    assert _extract_confirm_token(html) == "abc123XYZ"


def test_extract_confirm_token_query():
    html = 'href="?confirm=t_XY-z123&id=foo"'
    assert _extract_confirm_token(html) == "t_XY-z123"


def test_extract_confirm_token_none():
    assert _extract_confirm_token("<html></html>") is None


def test_download_dry_run():
    """dry_run=Trueでは実際にDLしない"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = download_video(
            file_id=TEST_FILE_ID,
            output_dir=tmpdir,
            dry_run=True,
        )
    assert result["status"] == "dry_run"
    assert result["file_id"] == TEST_FILE_ID


def test_download_skip_existing():
    """既存ファイルがあればスキップ"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 空ファイルを事前作成
        dummy = Path(tmpdir) / f"{TEST_FILE_ID}.mp4"
        dummy.write_bytes(b"dummy")

        result = download_video(
            file_id=TEST_FILE_ID,
            output_dir=tmpdir,
            overwrite=False,
        )
    assert result["status"] == "skipped"


# ===== 結合テスト（実際のDL）=====

@pytest.mark.integration
def test_download_real_video():
    """実際にGoogle DriveからMP4をDL (AYA確認済みパブリックID)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = download_video(
            file_id=TEST_FILE_ID,
            output_dir=tmpdir,
            overwrite=True,
        )

    print(f"\nDL結果: {json.dumps(result, ensure_ascii=False, indent=2)}")

    assert result["status"] == "success", f"DL失敗: {result['status']}"
    assert result["size_bytes"] > 0, "ファイルサイズが0"
    assert "video" in (result["content_type"] or ""), f"Content-Type不正: {result['content_type']}"


@pytest.mark.integration
def test_download_http_200():
    """DL URLがHTTP 200を返すことを確認"""
    import requests
    url = build_download_url(TEST_FILE_ID)
    resp = requests.head(url, timeout=15, allow_redirects=True)
    assert resp.status_code == 200, f"HTTP {resp.status_code}"
    print(f"\nHTTP Status: {resp.status_code}, Content-Type: {resp.headers.get('Content-Type')}")

