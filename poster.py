"""
poster.py - SNS投稿モジュール (X / Instagram)

dry-run=True のとき、実際の投稿は行わずログ出力のみ。
APIキーが未設定の場合も dry-run で正常動作する。

Usage:
    from poster import XPoster, InstagramPoster, post_to_sns
    result = post_to_sns(clip, ["x", "instagram"], dry_run=True)
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caption builder
# ---------------------------------------------------------------------------

MAX_X_CAPTION_LEN = 250  # X: 280 chars, reserve buffer for hashtags
MAX_IG_CAPTION_LEN = 2200  # Instagram Reels caption limit

HASHTAGS = "#チームみらい #安野たかひろ #政治"


def build_caption(clip: dict, platform: str = "x") -> str:
    """
    Build SNS caption from clip dict.

    clip keys used: title, transcript_text, video_title
    """
    title = clip.get("title", "")
    transcript = clip.get("transcript_text", "")

    if platform == "x":
        # X: title + hashtags (≤280 chars)
        base = f"{title}\n\n{HASHTAGS}"
        if len(base) > 280:
            base = title[:MAX_X_CAPTION_LEN] + f"\n\n{HASHTAGS}"
        return base

    elif platform == "instagram":
        # Instagram: title + transcript excerpt + hashtags
        excerpt = transcript[:300] if transcript else ""
        if excerpt and len(excerpt) == 300:
            excerpt += "…"
        parts = [title]
        if excerpt:
            parts.append(excerpt)
        parts.append(HASHTAGS)
        caption = "\n\n".join(parts)
        if len(caption) > MAX_IG_CAPTION_LEN:
            caption = caption[:MAX_IG_CAPTION_LEN]
        return caption

    return title


# ---------------------------------------------------------------------------
# X (Twitter) Poster
# ---------------------------------------------------------------------------

class XPoster:
    """
    X (Twitter) 投稿クライアント。

    Tweepy v4 を使用。APIキーは環境変数から取得。
    dry_run=True の場合、実際の投稿は行わない。

    環境変数:
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("X_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("X_API_SECRET", "")
        self.access_token = access_token or os.environ.get("X_ACCESS_TOKEN", "")
        self.access_secret = access_secret or os.environ.get("X_ACCESS_SECRET", "")
        self._client = None

    def _get_client(self):
        """Tweepy Client を遅延初期化 (dry-run 時は呼ばれない)"""
        if self._client is not None:
            return self._client
        try:
            import tweepy  # noqa: PLC0415
        except ImportError as e:
            raise ImportError("tweepy が未インストールです: pip install tweepy") from e

        self._client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
        )
        return self._client

    def post_video(
        self,
        video_path: str,
        caption: str,
        dry_run: bool = False,
    ) -> dict:
        """
        動画ファイルを X に投稿する。

        Args:
            video_path: 動画ファイルのパス。
            caption: 投稿テキスト (≤280文字)。
            dry_run: True のとき投稿しない（ログのみ）。

        Returns:
            {"status": "dry_run" | "posted" | "failed",
             "platform": "x",
             "caption": caption,
             "video_path": video_path,
             "tweet_id": str | None}
        """
        result = {
            "status": "dry_run",
            "platform": "x",
            "caption": caption,
            "video_path": str(video_path),
            "tweet_id": None,
        }

        if dry_run:
            logger.info(
                f"[dry-run][X] Would post video: {video_path}\n"
                f"  Caption ({len(caption)} chars): {caption[:80]}..."
            )
            return result

        # Validate credentials (空白のみも未設定とみなす)
        if not _validate_credentials(
            self.api_key, self.api_secret, self.access_token, self.access_secret,
            label="X"
        ):
            result["status"] = "failed"
            result["error"] = "APIキーが未設定"
            return result

        try:
            import tweepy  # noqa: PLC0415
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_secret)
            api_v1 = tweepy.API(auth)

            # Upload video via v1.1 (chunked upload)
            media = api_v1.media_upload(
                filename=str(video_path),
                media_category="tweet_video",
                chunked=True,
            )

            # Post tweet with media via v2
            client = self._get_client()
            response = client.create_tweet(
                text=caption,
                media_ids=[str(media.media_id)],
            )

            tweet_id = response.data.get("id") if response.data else None
            result["status"] = "posted"
            result["tweet_id"] = tweet_id
            logger.info(f"[X] Posted tweet_id={tweet_id}")

        except Exception as e:
            logger.error(f"[X] Post failed: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        return result


# ---------------------------------------------------------------------------
# Instagram Poster
# ---------------------------------------------------------------------------

class InstagramPoster:
    """
    Instagram Reels 投稿クライアント。

    Meta Graph API を使用。
    dry_run=True の場合、実際の投稿は行わない。

    環境変数:
        INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        self.access_token = access_token or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        self.account_id = account_id or os.environ.get("INSTAGRAM_ACCOUNT_ID", "")

    def post_reel(
        self,
        video_path: str,
        caption: str,
        dry_run: bool = False,
    ) -> dict:
        """
        動画を Instagram Reels として投稿する。

        Meta Graph API フロー:
        1. /media エンドポイントでコンテナ作成 (VIDEO_URL が必要)
        2. /media_publish でパブリッシュ

        Note: Instagram Graph API は公開 URL からの動画アップロードのみ対応。
              ローカルファイルを直接アップロードする場合は別途ホスティングが必要。

        Args:
            video_path: 動画ファイルのパス（または公開URL）。
            caption: 投稿テキスト。
            dry_run: True のとき投稿しない（ログのみ）。

        Returns:
            {"status": "dry_run" | "posted" | "failed",
             "platform": "instagram",
             "caption": caption,
             "video_path": video_path,
             "media_id": str | None}
        """
        result = {
            "status": "dry_run",
            "platform": "instagram",
            "caption": caption,
            "video_path": str(video_path),
            "media_id": None,
        }

        if dry_run:
            logger.info(
                f"[dry-run][Instagram] Would post reel: {video_path}\n"
                f"  Caption ({len(caption)} chars): {caption[:80]}..."
            )
            return result

        # Validate credentials (空白のみも未設定とみなす)
        if not _validate_credentials(self.access_token, self.account_id, label="Instagram"):
            result["status"] = "failed"
            result["error"] = "APIキーが未設定"
            return result

        try:
            import requests  # noqa: PLC0415

            video_url = str(video_path)

            # Step 1: Create media container
            container_url = f"{self.GRAPH_API_BASE}/{self.account_id}/media"
            container_resp = requests.post(
                container_url,
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            container_resp.raise_for_status()
            container_data = container_resp.json()
            container_id = container_data.get("id")

            if not container_id:
                result["status"] = "failed"
                result["error"] = f"Container creation failed: {container_data}"
                return result

            # Step 2: Publish
            publish_url = f"{self.GRAPH_API_BASE}/{self.account_id}/media_publish"
            publish_resp = requests.post(
                publish_url,
                data={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            publish_resp.raise_for_status()
            publish_data = publish_resp.json()

            media_id = publish_data.get("id")
            result["status"] = "posted"
            result["media_id"] = media_id
            logger.info(f"[Instagram] Posted media_id={media_id}")

        except Exception as e:
            logger.error(f"[Instagram] Post failed: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        return result


# ---------------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------------

SUPPORTED_PLATFORMS = {"x", "instagram"}


def post_to_sns(
    clip: dict,
    platforms: list,
    video_path: Optional[str] = None,
    dry_run: bool = True,
    x_poster: Optional[XPoster] = None,
    ig_poster: Optional[InstagramPoster] = None,
) -> dict:
    """
    クリップを指定プラットフォームに投稿する統合インターフェース。

    Args:
        clip: clip dict (title, transcript_text, uuid, drive_file_id 等)
        platforms: 投稿先プラットフォームのリスト ["x", "instagram"]
        video_path: 動画ファイルパス（省略時は clip["local_path"] を使用）
        dry_run: True のとき実際の投稿は行わない (デフォルト True)
        x_poster: XPoster インスタンス（省略時は新規作成）
        ig_poster: InstagramPoster インスタンス（省略時は新規作成）

    Returns:
        {
            "clip_id": str,
            "results": {
                "x": {...} | None,
                "instagram": {...} | None,
            },
            "overall_status": "dry_run" | "posted" | "partial" | "failed"
        }
    """
    clip_id = clip.get("uuid") or clip.get("id") or ""
    path = video_path or clip.get("local_path") or ""

    response = {
        "clip_id": clip_id,
        "results": {},
        "overall_status": "dry_run" if dry_run else "pending",
    }

    unknown = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if unknown:
        logger.warning(f"Unknown platforms: {unknown}")

    _x_poster = x_poster or XPoster()
    _ig_poster = ig_poster or InstagramPoster()

    for platform in platforms:
        platform = platform.lower()

        if platform == "x":
            caption = build_caption(clip, platform="x")
            result = _x_poster.post_video(str(path), caption, dry_run=dry_run)
            response["results"]["x"] = result

        elif platform == "instagram":
            caption = build_caption(clip, platform="instagram")
            result = _ig_poster.post_reel(str(path), caption, dry_run=dry_run)
            response["results"]["instagram"] = result

        else:
            response["results"][platform] = {
                "status": "failed",
                "error": f"Unsupported platform: {platform}",
            }

    # Compute overall_status
    if not dry_run:
        statuses = [r.get("status") for r in response["results"].values()]
        if all(s == "posted" for s in statuses):
            response["overall_status"] = "posted"
        elif all(s == "failed" for s in statuses):
            response["overall_status"] = "failed"
        elif any(s == "posted" for s in statuses):
            response["overall_status"] = "partial"
        else:
            response["overall_status"] = "failed"

    return response


# ---------------------------------------------------------------------------
# Credential validation helper
# ---------------------------------------------------------------------------

def _validate_credentials(*creds: str, label: str = "API") -> bool:
    """
    認証情報が全て設定済みかチェックする。
    空文字列・空白のみの文字列は未設定とみなす。

    Args:
        *creds: 検証する認証情報文字列。
        label: ログ出力用のラベル。

    Returns:
        全て設定済みなら True、未設定項目があれば False。
    """
    missing_count = sum(1 for c in creds if not c or not c.strip())
    if missing_count > 0:
        logger.error(
            f"[{label}] {missing_count}/{len(creds)} 個の認証情報が未設定です。"
            f" 環境変数を確認してください。"
        )
        return False
    return True
