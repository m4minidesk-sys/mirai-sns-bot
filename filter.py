"""
filter.py - クリップのキーワードフィルタリング

transcript_text と title を対象にスコアリングし、
政策系 / バラエティ系 に分類する。
"""

import argparse
import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 政策系キーワード
POLICY_KEYWORDS = [
    "テクノロジー", "AI", "人工知能", "デジタル", "DX",
    "子育て", "育児", "保育", "教育", "学校", "奨学金",
    "医療", "病院", "健康", "介護", "福祉",
    "政治資金", "政治", "選挙", "国会", "政策",
    "経済", "GDP", "物価", "インフレ", "景気", "財政", "予算",
    "エネルギー", "原発", "再生可能", "電力", "脱炭素",
    "安全保障", "防衛", "外交", "国防",
    "少子化", "人口減少", "出生率",
    "税金", "減税", "増税", "社会保険料",
    "規制緩和", "行政改革", "官僚",
    "憲法", "法律", "司法",
    "環境", "気候変動", "SDGs",
    "格差", "貧困", "最低賃金",
]

# バラエティ・人間的エピソード系キーワード（感動・ユ���モア系）
VARIETY_KEYWORDS = [
    "エピソード", "話", "感動", "笑い", "面白",
    "子ども", "こども", "家族", "友達",
    "日常", "生活", "趣味", "音楽", "スポーツ",
    "思い出", "過去", "学生", "青春",
    "ありがとう", "感謝", "応援", "励まし",
    "心温まる", "うれしい", "楽しい",
    "街頭", "演説", "聴衆", "握手",
]


@dataclass
class FilterResult:
    uuid: str
    title: str
    mode: str
    score: float
    matched_keywords: list = field(default_factory=list)
    passed: bool = False
    transcript_preview: str = ""


def score_clip(clip: dict, keywords: list) -> tuple:
    """
    クリップに対してキーワードスコアリングを実行

    Returns:
        (score: float, matched: list[str])
    """
    text = (clip.get("title") or "") + " " + (clip.get("transcript_text") or "")
    matched = []
    for kw in keywords:
        if kw in text:
            matched.append(kw)
    score = len(matched) / max(len(keywords), 1)
    return score, matched


def filter_clips(
    clips: list,
    mode: str = "policy",
    threshold: float = 0.0,
    dry_run: bool = False,
) -> list:
    """
    クリップリストをフィルタリングして条件に合うものを返す

    Args:
        clips: Clip dataclassのlist or dict list
        mode: "policy" | "variety"
        threshold: スコアの閾値（0.0 = 1件以上のキーワードマッチ）
        dry_run: Trueの場合、結果を返すが実際の処理はしない

    Returns:
        FilterResult のリスト（passed=Trueのみ）
    """
    if mode == "policy":
        keywords = POLICY_KEYWORDS
    elif mode == "variety":
        keywords = VARIETY_KEYWORDS
    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'policy' or 'variety'")

    results = []
    passed_count = 0

    for clip in clips:
        # dataclass or dict 両対応
        if hasattr(clip, "__dict__"):
            clip_dict = vars(clip)
        elif hasattr(clip, "_asdict"):
            clip_dict = clip._asdict()
        else:
            clip_dict = clip

        uuid = clip_dict.get("uuid", "")
        title = clip_dict.get("title", "")
        transcript = clip_dict.get("transcript_text", "")

        score, matched = score_clip(clip_dict, keywords)

        # threshold=0.0 の場合は1件以上マッチで通過
        passed = (len(matched) > 0) if threshold == 0.0 else (score >= threshold)

        result = FilterResult(
            uuid=uuid,
            title=title,
            mode=mode,
            score=score,
            matched_keywords=matched,
            passed=passed,
            transcript_preview=transcript[:100] if transcript else "",
        )
        results.append(result)
        if passed:
            passed_count += 1

    if dry_run:
        logger.info(f"[DRY-RUN] mode={mode}, {passed_count}/{len(clips)} clips would pass")
    else:
        logger.info(f"Filter: mode={mode}, {passed_count}/{len(clips)} clips passed")

    return [r for r in results if r.passed]


def main():
    parser = argparse.ArgumentParser(description="クリップキーワードフィルタ")
    parser.add_argument("--clips-json", default="clips.json", help="スクレイプ済みclips.json")
    parser.add_argument("--mode", choices=["policy", "variety", "all"], default="policy",
                        help="フィルタモード")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="スコア閾値（0.0=1件以上マッチ）")
    parser.add_argument("--dry-run", action="store_true", help="結果表示のみ")
    parser.add_argument("--output", "-o", help="結果出力JSONファイル")
    args = parser.parse_args()

    with open(args.clips_json, encoding="utf-8") as f:
        clips = json.load(f)

    logger.info(f"Loaded {len(clips)} clips from {args.clips_json}")

    if args.mode == "all":
        modes = ["policy", "variety"]
    else:
        modes = [args.mode]

    all_results = []
    for mode in modes:
        results = filter_clips(clips, mode=mode, threshold=args.threshold, dry_run=args.dry_run)
        all_results.extend(results)
        logger.info(f"mode={mode}: {len(results)} passed")

    output = [asdict(r) for r in all_results]

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info(f"Results saved to {args.output}")

    print(json.dumps(output[:5], ensure_ascii=False, indent=2))
    print(f"\nTotal passed: {len(output)}")


if __name__ == "__main__":
    main()
