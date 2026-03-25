# CLAUDE.md

## プロジェクト概要

pain-collector: SNS やレビューサイトからペイン（ユーザーの課題・不満）を自動収集し、LLM で構造化・分析して個人開発の MVP 候補を選定するパイプライン。

## 技術スタック

- Python 3.12
- LLM: OpenAI API（`gh models run` 経由）
- テキスト分析: scikit-learn（TF-IDF）、fugashi（日本語形態素解析）
- CI/CD: GitHub Actions（日次・週次・月次の定期実行）
- 通知: LINE Notify
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
