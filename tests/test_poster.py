"""
tests/test_poster.py - poster.py unit tests

dry-run モードで全テストをPASS。実APIコールなし。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from poster import (
    XPoster,
    InstagramPoster,
    post_to_sns,
    build_caption,
    SUPPORTED_PLATFORMS,
)


# ---------------------------------------------------------------------------
# build_caption
# ---------------------------------------------------------------------------

class TestBuildCaption:
    CLIP = {
        "title": "安野たかひろ AI政策について語る",
        "transcript_text": "AIを活用した行政改革で日本を変えていきます。デジタル化により行政コストを削減し、国民の利便性を向上させます。",
        "uuid": "test-uuid-001",
    }

    def test_x_caption_includes_title(self):
        caption = build_caption(self.CLIP, platform="x")
        assert "安野たかひろ" in caption

    def test_x_caption_includes_hashtags(self):
        caption = build_caption(self.CLIP, platform="x")
        assert "#チームみらい" in caption

    def test_x_caption_within_280_chars(self):
        caption = build_caption(self.CLIP, platform="x")
        assert len(caption) <= 280

    def test_ig_caption_includes_title(self):
        caption = build_caption(self.CLIP, platform="instagram")
        assert "安野たかひろ" in caption

    def test_ig_caption_includes_hashtags(self):
        caption = build_caption(self.CLIP, platform="instagram")
        assert "#チームみらい" in caption

    def test_ig_caption_within_2200_chars(self):
        caption = build_caption(self.CLIP, platform="instagram")
        assert len(caption) <= 2200

    def test_ig_caption_includes_transcript(self):
        caption = build_caption(self.CLIP, platform="instagram")
        assert "AI" in caption  # from transcript

    def test_long_title_truncated_x(self):
        long_clip = {**self.CLIP, "title": "a" * 300}
        caption = build_caption(long_clip, platform="x")
        assert len(caption) <= 280

    def test_empty_clip_does_not_raise(self):
        caption = build_caption({}, platform="x")
        assert isinstance(caption, str)

    def test_unknown_platform_returns_title(self):
        caption = build_caption(self.CLIP, platform="unknown")
        assert "安野たかひろ" in caption


# ---------------------------------------------------------------------------
# XPoster - dry_run
# ---------------------------------------------------------------------------

SAMPLE_CLIP = {
    "uuid": "550e8400-e29b-41d4-a716-446655440001",
    "title": "テストクリップ",
    "transcript_text": "これはテストです",
    "local_path": "/tmp/test_video.mp4",
}


class TestXPosterDryRun:
    def test_dry_run_returns_dry_run_status(self):
        poster = XPoster()
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["status"] == "dry_run"

    def test_dry_run_returns_correct_platform(self):
        poster = XPoster()
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["platform"] == "x"

    def test_dry_run_returns_caption(self):
        poster = XPoster()
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["caption"] == "テスト投稿"

    def test_dry_run_returns_video_path(self):
        poster = XPoster()
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["video_path"] == "/tmp/test.mp4"

    def test_dry_run_tweet_id_is_none(self):
        poster = XPoster()
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["tweet_id"] is None

    def test_dry_run_no_api_calls(self):
        poster = XPoster()
        with patch("poster.XPoster._get_client") as mock_client:
            poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
            mock_client.assert_not_called()

    def test_missing_credentials_dry_run_succeeds(self):
        """APIキー未設定でも dry-run は成功する"""
        poster = XPoster(api_key="", api_secret="", access_token="", access_secret="")
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["status"] == "dry_run"


class TestXPosterFailsWithoutCredentials:
    def test_no_credentials_returns_failed(self):
        """APIキー未設定の場合、non-dry-run は failed を返す"""
        poster = XPoster(api_key="", api_secret="", access_token="", access_secret="")
        result = poster.post_video("/tmp/test.mp4", "テスト投稿", dry_run=False)
        assert result["status"] == "failed"
        assert "APIキー" in result.get("error", "")


# ---------------------------------------------------------------------------
# InstagramPoster - dry_run
# ---------------------------------------------------------------------------

class TestInstagramPosterDryRun:
    def test_dry_run_returns_dry_run_status(self):
        poster = InstagramPoster()
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["status"] == "dry_run"

    def test_dry_run_returns_correct_platform(self):
        poster = InstagramPoster()
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["platform"] == "instagram"

    def test_dry_run_returns_caption(self):
        poster = InstagramPoster()
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["caption"] == "テスト投稿"

    def test_dry_run_returns_video_path(self):
        poster = InstagramPoster()
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["video_path"] == "/tmp/test.mp4"

    def test_dry_run_media_id_is_none(self):
        poster = InstagramPoster()
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["media_id"] is None

    def test_missing_credentials_dry_run_succeeds(self):
        poster = InstagramPoster(access_token="", account_id="")
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=True)
        assert result["status"] == "dry_run"


class TestInstagramPosterFailsWithoutCredentials:
    def test_no_credentials_returns_failed(self):
        poster = InstagramPoster(access_token="", account_id="")
        result = poster.post_reel("/tmp/test.mp4", "テスト投稿", dry_run=False)
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# post_to_sns (unified interface)
# ---------------------------------------------------------------------------

class TestPostToSns:
    def test_dry_run_x_only(self):
        result = post_to_sns(SAMPLE_CLIP, ["x"], dry_run=True)
        assert result["results"]["x"]["status"] == "dry_run"

    def test_dry_run_instagram_only(self):
        result = post_to_sns(SAMPLE_CLIP, ["instagram"], dry_run=True)
        assert result["results"]["instagram"]["status"] == "dry_run"

    def test_dry_run_both_platforms(self):
        result = post_to_sns(SAMPLE_CLIP, ["x", "instagram"], dry_run=True)
        assert result["results"]["x"]["status"] == "dry_run"
        assert result["results"]["instagram"]["status"] == "dry_run"

    def test_dry_run_overall_status(self):
        result = post_to_sns(SAMPLE_CLIP, ["x", "instagram"], dry_run=True)
        assert result["overall_status"] == "dry_run"

    def test_clip_id_in_result(self):
        result = post_to_sns(SAMPLE_CLIP, ["x"], dry_run=True)
        assert result["clip_id"] == SAMPLE_CLIP["uuid"]

    def test_unknown_platform_returns_failed_result(self):
        result = post_to_sns(SAMPLE_CLIP, ["unknown_platform"], dry_run=True)
        assert "unknown_platform" in result["results"]
        assert result["results"]["unknown_platform"]["status"] == "failed"

    def test_empty_platforms_list(self):
        result = post_to_sns(SAMPLE_CLIP, [], dry_run=True)
        assert result["results"] == {}

    def test_video_path_override(self):
        result = post_to_sns(SAMPLE_CLIP, ["x"], video_path="/override/path.mp4", dry_run=True)
        assert result["results"]["x"]["video_path"] == "/override/path.mp4"

    def test_dry_run_default_is_true(self):
        """dry_run のデフォルトは True (安全デフォルト)"""
        result = post_to_sns(SAMPLE_CLIP, ["x"])
        assert result["results"]["x"]["status"] == "dry_run"

    def test_clip_without_uuid_uses_id_field(self):
        clip = {**SAMPLE_CLIP, "id": "alt-id"}
        del clip["uuid"]
        result = post_to_sns(clip, ["x"], dry_run=True)
        assert result["clip_id"] == "alt-id"

    def test_custom_posters_used(self):
        """カスタムポスターを注入できる"""
        mock_x = MagicMock()
        mock_x.post_video.return_value = {"status": "dry_run", "platform": "x"}
        mock_ig = MagicMock()
        mock_ig.post_reel.return_value = {"status": "dry_run", "platform": "instagram"}

        result = post_to_sns(
            SAMPLE_CLIP, ["x", "instagram"],
            dry_run=True,
            x_poster=mock_x,
            ig_poster=mock_ig,
        )
        mock_x.post_video.assert_called_once()
        mock_ig.post_reel.assert_called_once()

    def test_non_dry_run_all_failed_returns_failed_overall(self):
        """全プラットフォーム失敗時 overall_status = failed"""
        mock_x = MagicMock()
        mock_x.post_video.return_value = {"status": "failed", "platform": "x"}
        mock_ig = MagicMock()
        mock_ig.post_reel.return_value = {"status": "failed", "platform": "instagram"}

        result = post_to_sns(
            SAMPLE_CLIP, ["x", "instagram"],
            dry_run=False,
            x_poster=mock_x,
            ig_poster=mock_ig,
        )
        assert result["overall_status"] == "failed"

    def test_non_dry_run_all_posted_returns_posted_overall(self):
        """全プラットフォーム成功時 overall_status = posted"""
        mock_x = MagicMock()
        mock_x.post_video.return_value = {"status": "posted", "platform": "x"}
        mock_ig = MagicMock()
        mock_ig.post_reel.return_value = {"status": "posted", "platform": "instagram"}

        result = post_to_sns(
            SAMPLE_CLIP, ["x", "instagram"],
            dry_run=False,
            x_poster=mock_x,
            ig_poster=mock_ig,
        )
        assert result["overall_status"] == "posted"

    def test_non_dry_run_partial_returns_partial_overall(self):
        """一部成功時 overall_status = partial"""
        mock_x = MagicMock()
        mock_x.post_video.return_value = {"status": "posted", "platform": "x"}
        mock_ig = MagicMock()
        mock_ig.post_reel.return_value = {"status": "failed", "platform": "instagram"}

        result = post_to_sns(
            SAMPLE_CLIP, ["x", "instagram"],
            dry_run=False,
            x_poster=mock_x,
            ig_poster=mock_ig,
        )
        assert result["overall_status"] == "partial"
