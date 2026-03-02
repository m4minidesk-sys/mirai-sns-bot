"""
scraper.py - vstudio.team-mir.ai/clips スクレイパー
/clips ページから全クリップ情報を取得してJSONで出力する
"""

import json
import re
import sys
import argparse
import time
import logging
from dataclasses import dataclass, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://vstudio.team-mir.ai"
CLIPS_URL = f"{BASE_URL}/clips"
DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_USERCONTENT_DL = "https://drive.usercontent.google.com/download?id={file_id}&export=download"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass
class Clip:
    uuid: str
    drive_file_id: Optional[str]
    title: str
    transcript_text: str
    duration_sec: Optional[float]
    video_title: Optional[str]
    clip_url: str
    drive_url: Optional[str]
    download_url: Optional[str]


def extract_drive_file_id(url: str) -> Optional[str]:
    """Google Drive URLからfile IDを抽出"""
    if not url:
        return None
    m = DRIVE_FILE_RE.search(url)
    return m.group(1) if m else None


def parse_duration(text: str) -> Optional[float]:
    """'1:23' 形式 or '0:04' 形式を秒数に変換"""
    if not text:
        return None
    text = text.strip()
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    return None


def parse_clips_from_html(html: str) -> list:
    """HTMLからクリップ一覧をパース"""
    soup = BeautifulSoup(html, "html.parser")
    clips = []

    # 各クリップカード: .border.rounded-lg.p-4 が各クリップ
    cards = soup.select("div.border.rounded-lg.p-4.space-y-3")
    logger.info(f"Found {len(cards)} clip cards")

    for card in cards:
        # タイトル & UUID
        title_a = card.select_one("a.text-sm.font-semibold")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        clip_href = title_a.get("href", "")
        # /clips/{UUID}
        uuid_match = re.search(r"/clips/([a-f0-9-]+)", clip_href)
        uuid = uuid_match.group(1) if uuid_match else ""

        # Drive URL (DLボタン)
        dl_a = card.select_one("a[href*='drive.google.com/file/d/']")
        drive_url = dl_a.get("href", "") if dl_a else None
        drive_file_id = extract_drive_file_id(drive_url) if drive_url else None
        download_url = DRIVE_USERCONTENT_DL.format(file_id=drive_file_id) if drive_file_id else None

        # 動画タイトル
        video_a = card.select_one("a.underline.hover\\:text-foreground")
        video_title = video_a.get_text(strip=True) if video_a else None

        # 再生時間 (font-semibold text-foreground span)
        duration_span = card.select_one("span.font-semibold.text-foreground")
        duration_text = ""
        if duration_span:
            for svg in duration_span.find_all("svg"):
                svg.decompose()
            duration_text = duration_span.get_text(strip=True)
        duration_sec = parse_duration(duration_text)

        # transcript (最後のp要素)
        transcript_p = card.select_one("p.text-xs.text-muted-foreground.leading-relaxed")
        transcript_text = ""
        if transcript_p:
            for svg in transcript_p.find_all("svg"):
                svg.decompose()
            transcript_text = transcript_p.get_text(strip=True)

        clips.append(Clip(
            uuid=uuid,
            drive_file_id=drive_file_id,
            title=title,
            transcript_text=transcript_text,
            duration_sec=duration_sec,
            video_title=video_title,
            clip_url=f"{BASE_URL}{clip_href}",
            drive_url=drive_url,
            download_url=download_url,
        ))

    return clips


def scrape_page(page: int = 1, session=None):
    """
    指定ページのクリップを取得
    Returns: (clips, total_pages)
    """
    if session is None:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

    params = {"page": page}
    logger.info(f"Fetching page {page}: {CLIPS_URL}")
    resp = session.get(CLIPS_URL, params=params, timeout=30)
    resp.raise_for_status()

    # total_pages をHTMLから抽出
    soup = BeautifulSoup(resp.text, "html.parser")
    total_pages = 1
    page_span = soup.find(string=re.compile(r"\d+\s*/\s*\d+"))
    if page_span:
        m = re.search(r"(\d+)\s*/\s*(\d+)", page_span)
        if m:
            total_pages = int(m.group(2))

    clips = parse_clips_from_html(resp.text)
    return clips, total_pages


def scrape_all(max_pages=None, dry_run=False, delay=1.0):
    """
    全ページをスクレイプ
    dry_run=True: 1ページのみ取得
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    all_clips = []
    clips, total_pages = scrape_page(1, session)
    all_clips.extend(clips)
    logger.info(f"Page 1/{total_pages}: {len(clips)} clips")

    if dry_run:
        logger.info("[DRY-RUN] Stopping after page 1")
        return all_clips

    if max_pages:
        total_pages = min(total_pages, max_pages)

    for page in range(2, total_pages + 1):
        time.sleep(delay)
        clips, _ = scrape_page(page, session)
        all_clips.extend(clips)
        logger.info(f"Page {page}/{total_pages}: {len(clips)} clips (total: {len(all_clips)})")

    return all_clips


def main():
    parser = argparse.ArgumentParser(description="vstudio.team-mir.ai/clips スクレイパー")
    parser.add_argument("--output", "-o", default="clips.json", help="出力JSONファイル名")
    parser.add_argument("--max-pages", type=int, default=None, help="取得最大ページ数")
    parser.add_argument("--dry-run", action="store_true", help="1ページのみ取得（テスト用）")
    parser.add_argument("--delay", type=float, default=1.0, help="ページ間の待機秒数")
    args = parser.parse_args()

    clips = scrape_all(
        max_pages=args.max_pages,
        dry_run=args.dry_run,
        delay=args.delay,
    )

    result = [asdict(c) for c in clips]
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(clips)} clips to {args.output}")
    print(json.dumps(result[:3], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
