# CLAUDE.md

## プロジェクト概要

pain-collector: SNS やレビューサイトからペイン（ユーザーの課題・不満）を自動収集し、LLM で構造化・分析して個人開発の MVP 候補を選定するパイプライン。

## 技術スタック

- Python 3.12
- LLM: OpenAI API（`gh models run` 経由）
- テキスト分析: scikit-learn（TF-IDF）、fugashi（日本語形態素解析）
- CI/CD: GitHub Actions（日次・週次・月次の定期実行）
- 通知: Discord（Webhook + Bot API）
- Issue 管理: GitHub Issues（ペイン → スコアリング → 選定 → 承認 → ビルド）

## ディレクトリ構成

```
src/           # コアロジック（収集・抽出・分析・選定）
tests/         # ユニットテスト
raw/           # 収集した生データ（JSON）
daily/         # 日次レポート（Markdown）
weekly/        # 週次トレンドレポート
deep_dive/     # ディープダイブ分析レポート
specs/         # 技術 Spec（Deep Dive から自動生成）
picks/         # MVP 候補選定レポート
data/          # パイプライン状態（pipeline_state.json 等）
.github/workflows/  # CI ワークフロー
```

## コマンド

```bash
# 依存インストール
pip install -r requirements.txt

# テスト実行
python -m pytest tests/ -v

# 日次収集
python -m src.main

# 週次トレンド
python -m src.main --weekly

# MVP 候補選定
python -m src.main --pick-idea
```

## パイプラインの流れ

1. 収集（collect_*.py）: Reddit, はてブ, Zenn, HN, note 等 13 ソースからデータ収集
2. 抽出（extract_pains.py）: LLM でペインを構造化
3. 市場チェック（market_check.py）: App Store で競合調査
4. スコアリング（scoring.py）: GitHub Issue にスコアラベル付与
5. 選定（pick_idea.py）: スコア上位から MVP 候補を選定、pipeline_state.json で状態管理
6. 承認（approve.yml）: Issue に `/approve` コメントで自動ビルドをトリガー

## 開発ルール

- ワークフローの手動実行は `kaionn` アカウントのみ許可（actor ガード）
- `gh models run` を LLM 呼び出しに使用（API キー不要）
- テスト追加時は `tests/` 配下に配置し `pytest` で実行可能にする

## 選定（pick_idea.py）のドメイン多様性ルール

`--pick-idea` の選定基準は技術寄り偏重を抑制するためのハード制約を持つ:

- 開発者向け候補は最大 1 件まで（スコアが高くても 2 件目以降は不採用）
- 一般ユーザー向けを最低 2 件含める
- 直近 pick とカテゴリが連続したら -3 ペナルティ、3 連続目は除外
- ジャッジ（LLM）がエンジニアであることに起因する dev ツール過大評価を自己バイアスとして明示

スコア重み: ペインの強さ x3 / スコープの小ささ x3 / 技術的シンプルさ x2 / 差別化 x2 / 収益可能性 x2（最大 60 点）。

## 通知 / Issue dedup 方針

`src/notify.py` の `_find_duplicate` は以下の階層で重複検出する:

1. **プロダクトキー dedup**（最優先）: source_url から `appstore:{id}` / `reddit:{sub}` / `togetter:{id}` 等を抽出し、同一プロダクトの open Issue があれば TF-IDF を待たずコメント化
2. **TF-IDF cosine similarity**: 高 0.7 / 低 0.4、グレーゾーンは LLM 判定

Issue 本文には `<!-- product:appstore:1232780281 -->` 形式の隠しメタデータを埋め込み、本文パースなしで高速判定する。既存 Issue は `## ソース` セクションの URL から再抽出するフォールバックで後方互換を維持。

通知は個別配信ではなく日次 digest に集約する（severity 降順）。「同一アプリに対する別バグ報告」が大量重複する設計上の盲点への対策。

## モバイル候補の技術スタック既定

`--pick-idea` / `/build` でモバイル対応プロダクトを提案する際は iOS ネイティブ（Swift + SwiftUI）を既定とする。React Native / Expo 等は明確に有利な理由がある場合のみ併記する。

## .gitignore とワークフローの commit 対象を同期する

成果物ディレクトリを `.gitignore` に追加・除外する際は、それを `git add` で明示している全ワークフロー（`collect.yml` 等）の add 対象も同時に揃える。
