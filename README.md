# mirai-sns-bot

チームみらい切り抜き動画 → SNS自動投稿パイプライン

## 概要
`vstudio.team-mir.ai` から切り抜きクリップを自動収集し、X/Instagram に自動投稿するボット。

## アーキテクチャ
```
vstudio.team-mir.ai/clips
  └─→ クリップ一覧スクレイプ
       └─→ Google Drive 直接DL（認証不要）
            └─→ 政策系フィルタリング
                 └─→ X投稿 / Instagram投稿
```

## セットアップ
TBD
