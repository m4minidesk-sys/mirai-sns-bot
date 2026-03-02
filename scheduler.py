"""
scheduler.py - 投稿スケジューラ

1日N本ペースで posted.db 未投稿クリップを選択し、
SNS に順次投稿する。

優先度: 政策系 > バラエティ系 > その他

Usage:
    python scheduler.py [--dry-run] [--daily-limit 3] [--platforms x instagram]
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from downloader import init_db, is_downloaded, mark_posted
from filter import score_clip, POLICY_KEYWORDS, VARIETY_KEYWORDS
from poster import post_to_sns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DAILY_LIMIT = 3
DEFAULT_DB_PATH = Path("posted.db")
DEFAULT_PLATFORMS = ["x", "instagram"]

PRIORITY_POLICY = 10
PRIORITY_VARIETY = 5
PRIORITY_OTHER = 1


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def get_todays_post_count(conn: sqlite3.Connection) -> int:
    """今日すでに投稿した件数を返す（JST基準）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) FROM clips WHERE status = 'posted' AND posted_at LIKE ?",
        (f"{today}%",),
    ).fetchone()
    return row[0] if row else 0


def get_downloadable_candidates(conn: sqlite3.Connection) -> list[dict]:
    """
    ダウンロード済みかつ未投稿のクリップを取得する。
    """
    rows = conn.execute("""
        SELECT uuid, title, local_path, drive_file_id
        FROM clips
        WHERE status = 'downloaded' AND local_path IS NOT NULL
        ORDER BY downloaded_at ASC
    """).fetchall()
    return [dict(row) for row in rows]


def prioritize_candidates(candidates: list[dict]) -> list[dict]:
    """
    クリップに優先度スコアを付けてソートする。
    政策系 > バラエティ系 > その他

    Returns:
        優先度降順にソートされたリスト（各要素に _priority フィールド追加）
    """
    scored = []
    for clip in candidates:
        policy_score, _ = score_clip(clip, POLICY_KEYWORDS)
        variety_score, _ = score_clip(clip, VARIETY_KEYWORDS)

        if policy_score > 0:
            priority = PRIORITY_POLICY + policy_score
        elif variety_score > 0:
            priority = PRIORITY_VARIETY + variety_score
        else:
            priority = PRIORITY_OTHER

        scored.append({**clip, "_priority": priority})

    scored.sort(key=lambda x: x["_priority"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Scheduler core
# ---------------------------------------------------------------------------

def run_schedule(
    db_path: Path = DEFAULT_DB_PATH,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
    platforms: Optional[list] = None,
    dry_run: bool = True,
    clips_override: Optional[list] = None,
) -> dict:
    """
    スケジューラのメイン処理。

    Args:
        db_path: SQLite DB パス。
        daily_limit: 1日の最大投稿数。
        platforms: 投稿先プラットフォーム（例: ["x", "instagram"]）。
        dry_run: True のとき実際の投稿は行わない。
        clips_override: テスト用クリップリスト（DB をバイパス）。

    Returns:
        {
            "posted": int,
            "skipped": int,
            "failed": int,
            "daily_limit": int,
            "dry_run": bool,
            "results": list[dict]
        }
    """
    if platforms is None:
        platforms = DEFAULT_PLATFORMS

    summary = {
        "posted": 0,
        "skipped": 0,
        "failed": 0,
        "daily_limit": daily_limit,
        "dry_run": dry_run,
        "results": [],
    }

    conn = init_db(db_path)

    # 今日の投稿済み件数確認
    todays_count = get_todays_post_count(conn)
    remaining = daily_limit - todays_count

    logger.info(
        f"今日の投稿状況: {todays_count}/{daily_limit} 件済み, 残り {remaining} 件"
    )

    if remaining <= 0:
        logger.info("本日の投稿上限に達しています。スキップします。")
        summary["skipped"] = 0
        conn.close()
        return summary

    # 候補取得
    if clips_override is not None:
        candidates = clips_override
    else:
        candidates = get_downloadable_candidates(conn)

    if not candidates:
        logger.info("投稿可能なクリップがありません。")
        conn.close()
        return summary

    # 優先度ソート
    prioritized = prioritize_candidates(candidates)

    try:
        for clip in prioritized[:remaining]:
            clip_id = clip.get("uuid") or clip.get("id") or ""
            title = clip.get("title", "")
            video_path = clip.get("local_path", "")

            logger.info(
                f"処理中: {clip_id} [{clip.get('_priority', 0)}] {title[:40]}"
            )

            # 投稿実行
            result = post_to_sns(
                clip=clip,
                platforms=platforms,
                video_path=video_path,
                dry_run=dry_run,
            )

            # DB 更新: 投稿成功時のみコミット（トランザクション整合性）
            status = result.get("overall_status", "failed")
            if not dry_run and status in ("posted", "partial"):
                try:
                    mark_posted(conn, clip_id)
                    summary["posted"] += 1
                    logger.info(f"DB更新完了: {clip_id} -> posted")
                except Exception as db_err:
                    logger.error(f"DB更新失敗: {clip_id}: {db_err}")
                    summary["failed"] += 1
            elif dry_run:
                summary["posted"] += 1  # dry-run は全件カウント
            else:
                summary["failed"] += 1

            summary["results"].append({
                "clip_id": clip_id,
                "title": title,
                "priority": clip.get("_priority", 0),
                "post_result": result,
            })
    finally:
        conn.close()

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SNS投稿スケジューラ")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="実際の投稿を行わない（デフォルト: True）")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="実際に投稿する（APIキー必須）")
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT,
                        help=f"1日の最大投稿数（デフォルト: {DEFAULT_DAILY_LIMIT}）")
    parser.add_argument("--platforms", nargs="+", default=DEFAULT_PLATFORMS,
                        choices=["x", "instagram"],
                        help="投稿先プラットフォーム")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB パス")
    args = parser.parse_args()

    summary = run_schedule(
        db_path=args.db,
        daily_limit=args.daily_limit,
        platforms=args.platforms,
        dry_run=args.dry_run,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    logger.info(
        f"完了: 投稿={summary['posted']}, スキップ={summary['skipped']}, "
        f"失敗={summary['failed']}"
    )


if __name__ == "__main__":
    main()
