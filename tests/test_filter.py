"""
tests/test_filter.py - filter.py のテスト
"""

import pytest
from filter import filter_clips, score_clip, FilterResult, POLICY_KEYWORDS, VARIETY_KEYWORDS

# サンプルクリップデータ
POLICY_CLIP = {
    "uuid": "policy-uuid-001",
    "title": "チームみらいのAI政策と少子化対策について",
    "transcript_text": "今回の選挙でテクノロジーとAI活用を推進し、少子化対策として子育て支援の税金減税を訴えます。",
}

VARIETY_CLIP = {
    "uuid": "variety-uuid-001",
    "title": "バスの誘導員との心温まるエピソード",
    "transcript_text": "街頭演説で出会ったバスの誘導員から励ましをいただき感謝しています。本当に応援がうれしいです。",
}

NO_KEYWORD_CLIP = {
    "uuid": "no-keyword-uuid-001",
    "title": "特に関係ないクリップ",
    "transcript_text": "これは全く関係のない内容のクリップです。",
}

MIXED_CLIP = {
    "uuid": "mixed-uuid-001",
    "title": "街頭演説でのAI政策説明",
    "transcript_text": "AIを活用して少子化問題を解決するため、子育て支援を強化します。街頭で応援の声をいただき感謝です。",
}


class TestScoreClip:
    def test_policy_keywords_match(self):
        score, matched = score_clip(POLICY_CLIP, POLICY_KEYWORDS)
        assert len(matched) > 0
        assert "AI" in matched or "少子化" in matched or "子育て" in matched

    def test_variety_keywords_match(self):
        score, matched = score_clip(VARIETY_CLIP, VARIETY_KEYWORDS)
        assert len(matched) > 0
        assert "応援" in matched or "感謝" in matched or "街頭" in matched

    def test_no_match_returns_zero_score(self):
        score, matched = score_clip(NO_KEYWORD_CLIP, POLICY_KEYWORDS)
        assert score == 0.0
        assert matched == []

    def test_score_is_float(self):
        score, _ = score_clip(POLICY_CLIP, POLICY_KEYWORDS)
        assert isinstance(score, float)

    def test_score_between_zero_and_one(self):
        score, _ = score_clip(POLICY_CLIP, POLICY_KEYWORDS)
        assert 0.0 <= score <= 1.0


class TestFilterClips:
    def test_policy_mode_filters_policy_clips(self):
        clips = [POLICY_CLIP, VARIETY_CLIP, NO_KEYWORD_CLIP]
        results = filter_clips(clips, mode="policy")
        uuids = [r.uuid for r in results]
        assert "policy-uuid-001" in uuids

    def test_variety_mode_filters_variety_clips(self):
        clips = [POLICY_CLIP, VARIETY_CLIP, NO_KEYWORD_CLIP]
        results = filter_clips(clips, mode="variety")
        uuids = [r.uuid for r in results]
        assert "variety-uuid-001" in uuids

    def test_no_keyword_clip_filtered_out_policy(self):
        clips = [NO_KEYWORD_CLIP]
        results = filter_clips(clips, mode="policy")
        assert len(results) == 0

    def test_no_keyword_clip_filtered_out_variety(self):
        clips = [NO_KEYWORD_CLIP]
        results = filter_clips(clips, mode="variety")
        assert len(results) == 0

    def test_returns_filter_result_objects(self):
        clips = [POLICY_CLIP]
        results = filter_clips(clips, mode="policy")
        assert len(results) > 0
        assert isinstance(results[0], FilterResult)

    def test_result_has_required_fields(self):
        clips = [POLICY_CLIP]
        results = filter_clips(clips, mode="policy")
        assert len(results) > 0
        r = results[0]
        assert r.uuid == "policy-uuid-001"
        assert r.mode == "policy"
        assert r.passed is True
        assert len(r.matched_keywords) > 0

    def test_dry_run_still_returns_results(self):
        clips = [POLICY_CLIP, VARIETY_CLIP]
        results = filter_clips(clips, mode="policy", dry_run=True)
        # dry_runでもフィルタ結果は返す
        assert isinstance(results, list)

    def test_invalid_mode_raises_error(self):
        with pytest.raises(ValueError):
            filter_clips([POLICY_CLIP], mode="invalid_mode")

    def test_empty_clips_returns_empty(self):
        results = filter_clips([], mode="policy")
        assert results == []

    def test_mixed_clip_matches_both_modes(self):
        clips = [MIXED_CLIP]
        policy_results = filter_clips(clips, mode="policy")
        variety_results = filter_clips(clips, mode="variety")
        # 政策系とバラエティ系の両方にマッチ
        assert len(policy_results) > 0
        assert len(variety_results) > 0

    def test_filter_interface_with_threshold(self):
        clips = [POLICY_CLIP, NO_KEYWORD_CLIP]
        # threshold=0.0 (デフォルト): 1件以上マッチ
        results = filter_clips(clips, mode="policy", threshold=0.0)
        assert any(r.uuid == "policy-uuid-001" for r in results)
        assert not any(r.uuid == "no-keyword-uuid-001" for r in results)

    def test_filter_clips_accepts_dict_input(self):
        """dictオブジェクトを受け付ける"""
        clips = [
            {"uuid": "test-1", "title": "AI政策", "transcript_text": "テクノロジーとAIを活用します"},
        ]
        results = filter_clips(clips, mode="policy")
        assert len(results) > 0

    def test_transcript_preview_truncated(self):
        long_clip = {
            "uuid": "long-uuid",
            "title": "AI",
            "transcript_text": "テクノロジー" + "あ" * 200,
        }
        results = filter_clips([long_clip], mode="policy")
        if results:
            assert len(results[0].transcript_preview) <= 100

