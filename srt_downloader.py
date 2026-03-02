"""
srt_downloader.py - /clips/{UUID} ページから字幕データを取得しSRT形式で保存

字幕データはページHTML内の __next_f JSON (initialSubtitle.segments) に埋め込まれている。
SRTダウンロードリンクは存在しないためHTMLパースで取得する。
"""

import argparse
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://vstudio.team-mir.ai"
DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_DB_PATH = Path("posted.db")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _seconds_to_srt_time(seconds: float) -> str:
    """秒数をSRT形式のタイムコードに変換 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _segments_to_srt(segments: list) -> str:
    """subtitleセグメントリストをSRTフォーマット文字列に変換"""
    lines = []
    for seg in segments:
        idx = seg["index"] + 1  # SRTは1始まり
        start = _seconds_to_srt_time(seg["startTimeSeconds"])
        end = _seconds_to_srt_time(seg["endTimeSeconds"])
        text = "\n".join(seg["lines"])
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _extract_subtitle_from_html(html: str) -> Optional[dict]:
    """
    HTML内の __next_f スクリプトから initialSubtitle を抽出する

    Next.jsがサーバーサイドレンダリングで埋め込むJSONデータを解析する。
    形式: self.__next_f.push([1,"4:[...{\"initialSubtitle\":{...}}..."])

    HTMLの __next_f.push スクリプト内でJSONが文字列エスケープされているため、
    json.loads で一度アンエスケープしてから処理する。
    """
    for raw_match in re.finditer(
        r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',
        html,
        re.DOTALL,
    ):
        raw = raw_match.group(1)
        if "initialSubtitle" not in raw:
            continue
        # json.loadsでPythonのエスケープ処理と同様にアンエスケープ
        try:
            unescaped = json.loads('"' + raw + '"')
        except json.JSONDecodeError:
            unescaped = raw

        # "initialSubtitle":{...} の開始位置を特定
        m = re.search(r'"initialSubtitle"\s*:\s*(\{[^}]*"segments"\s*:\s*\[)', unescaped)
        if not m:
            continue
        start_idx = m.start(1)
        # ブラケットの対応を数えてJSONオブジェクト全体を取得
        depth = 0
        end_idx = start_idx
        for i, ch in enumerate(unescaped[start_idx:], start_idx):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        try:
            subtitle = json.loads(unescaped[start_idx:end_idx])
            if subtitle.get("segments"):
                return subtitle
        except json.JSONDecodeError:
            continue

    return None


def fetch_subtitle_from_clip_page(uuid: str, session=None) -> Optional[dict]:
    """
    /clips/{UUID} ページを取得して字幕データ(segments)を返す

    Returns:
        dict with keys: segments (list), status (str) or None
    """
    if session is None:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

    url = f"{BASE_URL}/clips/{uuid}"
    logger.info(f"Fetching clip page: {url}")
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    subtitle = _extract_subtitle_from_html(resp.text)
    if subtitle and subtitle.get("segments"):
        logger.info(f"Extracted subtitle: {len(subtitle['segments'])} segments")
        return subtitle

    logger.warning(f"No subtitle found for clip {uuid}")
    return None


def download_srt(
    uuid: str,
    output_dir: str = "downloads",
    dry_run: bool = False,
    overwrite: bool = False,
    session=None,
) -> dict:
    """
    指定のclip UUIDのSRTファイルを取得して保存

    Returns:
        dict: uuid, srt_path, status, segment_count
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    srt_path = output_path / f"{uuid}.srt"
    result = {
        "uuid": uuid,
        "srt_path": str(srt_path),
        "status": "pending",
        "segment_count": 0,
    }

    if dry_run:
        logger.info(f"[DRY-RUN] Would fetch SRT for {uuid}")
        result["status"] = "dry_run"
        return result

    if srt_path.exists() and not overwrite:
        result["status"] = "skipped"
        result["segment_count"] = _count_srt_segments(srt_path)
        logger.info(f"SRT already exists, skipping: {srt_path}")
        return result

    subtitle = fetch_subtitle_from_clip_page(uuid, session)
    if not subtitle:
        result["status"] = "no_subtitle"
        return result

    segments = subtitle.get("segments", [])
    if not segments:
        result["status"] = "empty_subtitle"
        return result

    srt_content = _segments_to_srt(segments)
    srt_path.write_text(srt_content, encoding="utf-8")
    result["status"] = "success"
    result["segment_count"] = len(segments)
    logger.info(f"Saved SRT: {srt_path} ({len(segments)} segments)")
    return result


def _count_srt_segments(srt_path: Path) -> int:
    """SRTファイルのセグメント数をカウント"""
    try:
        text = srt_path.read_text(encoding="utf-8")
        return len(re.findall(r"^\d+$", text, re.MULTILINE))
    except Exception:
        return 0


def update_db_srt_path(uuid: str, srt_path: str, db_path: Path = DEFAULT_DB_PATH):
    """posted.dbのclipsテーブルにsrt_pathを更新"""
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        # srt_pathカラムがなければ追加
        try:
            conn.execute("ALTER TABLE clips ADD COLUMN srt_path TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # カラムが既に存在する場合
        conn.execute(
            "UPDATE clips SET srt_path = ? WHERE uuid = ?",
            (srt_path, uuid),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"DB update failed for {uuid}: {e}")


def batch_download_srt(
    clips_json: str,
    output_dir: str = "downloads",
    dry_run: bool = False,
    overwrite: bool = False,
    delay: float = 0.5,
    db_path: Path = DEFAULT_DB_PATH,
) -> list:
    """clips.json から全クリップのSRTをバッチダウンロード"""
    with open(clips_json, encoding="utf-8") as f:
        clips = json.load(f)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    results = []
    for i, clip in enumerate(clips):
        uuid = clip.get("uuid")
        if not uuid:
            continue
        result = download_srt(
            uuid=uuid,
            output_dir=output_dir,
            dry_run=dry_run,
            overwrite=overwrite,
            session=session,
        )
        results.append(result)
        if result["status"] == "success":
            update_db_srt_path(uuid, result["srt_path"], db_path)
        if i < len(clips) - 1:
            time.sleep(delay)

    success = sum(1 for r in results if r["status"] == "success")
    skip = sum(1 for r in results if r["status"] == "skipped")
    fail = sum(1 for r in results if r["status"] not in ("success", "skipped", "dry_run"))
    logger.info(f"SRT batch done: {success} success / {skip} skip / {fail} fail / {len(results)} total")
    return results


def main():
    parser = argparse.ArgumentParser(description="クリップSRT字幕ダウンローダー")
    parser.add_argument("--uuid", help="クリップUUID（単体DL）")
    parser.add_argument("--clips-json", help="clips.json（バッチDL）")
    parser.add_argument("--output-dir", "-o", default="downloads", help="保存ディレクトリ")
    parser.add_argument("--dry-run", action="store_true", help="実際にはDLしない")
    parser.add_argument("--overwrite", action="store_true", help="既存SRTを上書き")
    parser.add_argument("--delay", type=float, default=0.5, help="バッチ時のページ間待機秒数")
    args = parser.parse_args()

    if args.uuid:
        result = download_srt(
            uuid=args.uuid,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.clips_json:
        results = batch_download_srt(
            clips_json=args.clips_json,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            delay=args.delay,
        )
        print(json.dumps(results[:5], ensure_ascii=False, indent=2))
    else:
        # デフォルト: テスト用UUID
        test_uuid = "f6e453a5-5ef6-44ca-b8da-b33677ec9a16"
        logger.info(f"No args, using test UUID: {test_uuid}")
        result = download_srt(
            uuid=test_uuid,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            overwrite=True,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
