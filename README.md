# pain-collector

SNS と開発者コミュニティから「日常のペイン（困りごと・不満）」を自動収集し、LLM で構造化して、ビジネスチャンスを発掘するプロジェクト。

## 概要

毎日 Reddit、はてなブックマーク、Zenn から最新の投稿を収集し、AI（GitHub Models / Claude）を使ってペインを自動抽出。市場調査（App Store 検索）と組み合わせ、既存ソリューションの有無や競合状況を分析します。抽出されたペインは GitHub Issues として自動作成され、フィードバックループにより抽出ロジックを継続改善できます。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                  データ収集層                              │
├──────────────┬──────────────────┬──────────────────────────┤
│   Reddit     │  はてなブック    │      Zenn              │
│ (8 subreddits)│   (2 categories)│   (Recent articles)    │
└──────┬───────┴────────┬─────────┴──────────────┬───────────┘
       │                │                        │
       └────────────────┴────────────────────────┘
                        │
                 raw/*.json に保存
                        │
        ┌───────────────▼──────────────────┐
        │     LLM ペイン抽出               │
        │  (GitHub Models / Claude)       │
        └───────────────┬──────────────────┘
                        │
        ┌───────────────▼──────────────────┐
        │  市場調査（App Store API）       │
        │  競合アプリ・市場シグナル       │
        └───────────────┬──────────────────┘
                        │
        ┌───────────────▼──────────────────┐
        │   GitHub Issues 自動作成         │
        │  （ラベル付き、構造化）         │
        └───────────────┬──────────────────┘
                        │
        ┌───────────────▼──────────────────┐
        │  フィードバック収集・分析      │
        │ （Issues のラベル: 👍/👎/💡）   │
        └────────────────────────────────┘

出力:
- daily/YYYY-MM-DD.md → 日次レポート
- weekly/YYYY-Www.md  → 週次トレンド分析
- GitHub Issues      → 個別ペイン（TOP3）
```

## 機能

### 日次実行

毎日 09:00 JST（UTC 0:00）に以下を自動実行:

1. Reddit、はてなブックマーク、Zenn から投稿・エントリを収集
2. LLM でペインを自動抽出（20 件単位でバッチ処理）
3. App Store API で上位 5 件のペインの競合チェック
4. Markdown レポート生成・保存（`daily/YYYY-MM-DD.md`）
5. 深刻度 TOP3 のペインを GitHub Issues として自動作成
6. Git にコミット・プッシュ

### 週次実行

毎週日曜 09:00 JST に過去 7 日分のペインを横断分析:

1. 過去 7 日の抽出済みペインを集約
2. LLM で繰り返し出現するテーマを抽出（トレンド化）
3. 市場機会スコア（出現度 × 深刻度 × 課金可能性）でランキング
4. 週次レポート生成（`weekly/YYYY-Www.md`）
5. Git にコミット・プッシュ

### フィードバック集計

ユーザーが Issues に付けたラベルから抽出精度を分析:

- 👍good   → 良い抽出パターンの カテゴリ集計
- 👎bad    → ノイズ・誤抽出パターンの分析（SYSTEM_PROMPT 改善のヒント）
- 💡interesting → 深掘りが必要なペイン

## セットアップ

### 必要なもの

- Python 3.12+
- GitHub リポジトリ（Issues、Actions の実行権限）
- GitHub Token（GitHub Models API を使う場合）
- インターネット接続

### クイックスタート

1. リポジトリをクローン

```bash
git clone https://github.com/YOUR_USERNAME/pain-collector.git
cd pain-collector
```

2. 依存ライブラリをインストール

```bash
pip install -r requirements.txt
```

3. GitHub リポジトリの Secrets を設定

GitHub の Settings > Secrets and variables > Actions に以下を追加:

- `GITHUB_TOKEN`: GitHub API アクセストークン（デフォルトで利用可能）

GitHub Models を使う場合は、トークンに以下のパーミッションを許可:

- `repo` （Issues 作成）
- `models` （GitHub Models API）

4. 手動実行（テスト）

```bash
# 今日のデータを収集・抽出
python -m src.main

# 過去 7 日分をバックフィル
python -m src.main --backfill 7

# 週次トレンド分析
python -m src.main --weekly

# フィードバック集計
python -m src.main --feedback
```

### GitHub Actions の設定（自動実行）

`.github/workflows/collect.yml` と `weekly.yml` は自動で毎日・毎週実行されます。

手動実行は：

```bash
# GitHub CLI 経由
gh workflow run collect.yml
gh workflow run weekly.yml

# またはブラウザの Actions タブから "Run workflow"
```

## 使用方法

### CLI コマンド

基本的な使用方法:

```bash
# 今日のペインを収集・抽出・保存
python -m src.main

# 過去 N 日分をバックフィル（データ再処理）
python -m src.main --backfill 7

# 週次トレンド分析を実行
python -m src.main --weekly

# フィードバック集計を表示
python -m src.main --feedback
```

### GitHub Issues ラベルシステム

自動作成される Issue には複数のラベルが付きます:

カテゴリ系:
- `子育て・育児`, `食事・料理`, `お金・家計`, `仕事・キャリア`, `人間関係`, `健康・体調`, `住まい・暮らし`, `移動・通勤`, `学習・スキル`, `テクノロジー`, `生き方・価値観`, `趣味・娯楽`

プロダクトタイプ系:
- `📱モバイルアプリ`, `🌐Webサービス`, `🧩ブラウザ拡張`, `⌨️CLI・開発ツール`, `☁️API・SaaS`, `🔧ハードウェア・IoT`

課金意欲:
- `💰high` (数万円/月でも払う)
- `💰medium` (数千円/月でも払う)
- `💰low` (数百円/月なら払う)
- `💰free` (無料でしか使わない)

深刻度（3以上）:
- `🔥severity-3`, `🔥severity-4`, `🔥severity-5`

市場シグナル:
- `🟢whitespace` (競合なし)
- `🟡underserved` (市場あり・満足度低い)

その他:
- `🎯既存なし` (既存ソリューションなし)
- `pain-report` (全ペイン)

ユーザーフィードバック:
- `👍good` (良い抽出、カテゴリ分析に含める)
- `👎bad` (ノイズ、SYSTEM_PROMPT 改善の参考)
- `💡interesting` (深掘りが必要)

### Issue で見つかったペインのアクション

Issue を開いて内容を確認したら、ラベルを付けてフィードバック:

```bash
# 良い抽出だと思ったら
gh issue edit <issue-number> --add-label "👍good"

# ノイズだと思ったら（次回の SYSTEM_PROMPT 改善に活用）
gh issue edit <issue-number> --add-label "👎bad"

# 深掘りしたいペインなら
gh issue edit <issue-number> --add-label "💡interesting"
```

## 出力フォーマット

### 日次レポート（daily/YYYY-MM-DD.md）

```markdown
# Pain Report: 2026-03-15

抽出件数: 26 件

| ジャンル | 件数 |
|---|---|
| 🍽️ 食事・料理 | 3 |
| 💼 仕事・キャリア | 8 |
| ...

## 💼 仕事・キャリア

### リモートワークで集中力が続かない

- 深刻度: ★★★★☆ (4/5)
- 対象ユーザー: フリーランス、在宅勤務者
- 頻度: daily / 課金意欲: medium
- プロダクト: 🌐 Webサービス
- アイデア: デスク環境の集中度を AI で可視化し、集中力低下を事前検出
- 既存ソリューション: Focus@Will, Forest 等の集中支援アプリ
- 市場シグナル: 🟡 市場あり・満足度低い（チャンス）
  - [Focus@Will](https://focusatwill.com) ⭐3.8 (1200件) $10.99/月
  - [Forest](https://forestapp.cc) ⭐4.2 (3100件) $0.99
- ソース: [リモートワークで集中力が... | Reddit](https://reddit.com/r/...)

...
```

### 週次トレンドレポート（weekly/YYYY-Www.md）

```markdown
# Weekly Trend Report: 2026-W11

分析期間: 2026-03-09 〜 2026-03-15
分析対象ペイン数: 182 件
抽出トレンド数: 8 件

| # | テーマ | スコア | 出現数 | 方向 | カテゴリ |
|---|--------|--------|--------|------|----------|
| 1 | AI 誤情報の被害と救済 | 🟩🟩🟩🟩🟩 9/10 | 12 回 | 📈 | テクノロジー |
| 2 | リモートワークの集中力 | 🟩🟩🟩🟩 7/10 | 8 回 | ➡️ | 仕事・キャリア |
| ...

## 1. AI 誤情報の被害と救済 (9/10) 📈

- カテゴリ: テクノロジー
- 出現回数: 12 回 / 方向: rising
- 分析: 生成 AI の事実誤認が社会的問題化。営業被害やプライバシー侵害への対策ニーズが急速に高まっている

代表的なペイン:
- ChatGPT に作られた嘘の経歴が Web に登録される
- 実在しない芸能人の過去が生成 AI で作られている

...
```

### GitHub Issues 本文

自動作成される Issue には以下の情報が含まれます:

- ペイン要約と深刻度
- 対象ユーザー、使用頻度、課金意欲
- アイデア（解決策の提案）
- 既存ソリューション
- App Store での競合アプリ（上位 3 件）
- 市場シグナル（ホワイトスペース/チャンス/競争激化）
- ソース（元の投稿へのリンク）

## プロジェクト構造

```
pain-collector/
├── README.md                          # このファイル
├── requirements.txt                   # Python 依存
├── .github/
│   └── workflows/
│       ├── collect.yml                # 日次実行（毎日 09:00 JST）
│       └── weekly.yml                 # 週次実行（毎週日曜 09:00 JST）
├── src/
│   ├── main.py                        # メインロジック
│   ├── collect_reddit.py              # Reddit 収集（8 subreddits）
│   ├── collect_hatena.py              # はてなブックマーク収集
│   ├── collect_zenn.py                # Zenn 記事収集
│   ├── extract_pains.py               # LLM ペイン抽出（バッチ処理）
│   ├── market_check.py                # App Store 競合チェック
│   ├── notify.py                      # GitHub Issues 自動作成
│   ├── feedback.py                    # フィードバック集計分析
│   └── weekly_trends.py               # 週次トレンド分析
├── daily/                             # 日次レポート（Markdown）
│   ├── 2026-03-08.md
│   ├── 2026-03-09.md
│   └── ...
├── raw/                               # 生データ（JSON）
│   ├── 2026-03-08.json
│   ├── 2026-03-09.json
│   └── ...
└── weekly/                            # 週次トレンドレポート
    ├── 2026-W11.md
    └── ...
```

### ディレクトリの役割

daily/
- マークダウン形式の日次レポート
- ペイン一覧、深刻度、アイデア、市場データを含む

raw/
- 日次に収集した生データ（JSON 形式）
- Reddit、はてなブックマーク、Zenn の投稿をそのまま保存
- 週次分析でも参照される

weekly/
- 過去 7 日分のペインを横断分析したレポート
- テーマ化・ランキング化・トレンド方向を含む

## ペイン抽出のロジック

### 1. データ収集の対象

Reddit:
- r/apps, r/productivity, r/webdev, r/software, r/iphone, r/android, r/LifeProTips, r/mildlyinfuriating
- ペインキーワード（wish, annoying, hate, frustrating, broken 等）でフィルタ

はてなブックマーク:
- カテゴリ: テクノロジー、暮らし
- RSS フィード（ホットエントリ）から最新 60 件

Zenn:
- 最新の記事・スクラップを RSS フィード経由で取得

### 2. ペイン構造化（LLM）

各投稿から以下の情報を自動抽出:

- pain: ペインの要約（1-2 文）
- category: ジャンル 13 種類のいずれか
- product_type: プロダクトタイプ 7 種類のいずれか
- target_user: ペルソナ
- frequency: 使用頻度（daily/weekly/monthly/one-time）
- willingness_to_pay: 課金意欲（free/low/medium/high）
- severity: 深刻度（1-5）
- existing_solutions: 既存解決策
- app_idea: ビジネスアイデア（1 文）
- source_title, source_url: 元の投稿情報

除外ルール（SYSTEM_PROMPT で定義）:
- 宣伝投稿（"I built", "check out my app"）
- 単なるエピソード（ニュース、バズネタ）
- 解決策が自明なもの（「ググればわかる」）
- 抽象的で actionable でない不満

### 3. 市場調査

深刻度 × 課金意欲 でスコア化し、上位 5 件の App Store 検索を実行:

- keyword: app_idea から自動抽出
- entities: software（アプリケーション）
- 返す結果: name, rating, review_count, price, url

市場シグナルの判定:
- whitespace: 競合アプリなし
- emerging: アプリあるが レビュー < 1000 件
- underserved: アプリ平均評価 < 3.5（ニーズはあるが満足度低い）
- competitive: アプリ多数・評価高い

## トラブルシューティング

### GitHub Models API 呼び出しエラー

GitHub Token が設定されていないか、パーミッションが不足している可能性:

```bash
# Token の確認
echo $GITHUB_TOKEN

# または GitHub CLI 経由
gh auth status
```

その場合、自動的に Claude Code CLI にフォールバックします。

### ペイン抽出が 0 件

以下を確認:

1. データ収集は成功しているか（`raw/YYYY-MM-DD.json` が存在）
2. SYSTEM_PROMPT の除外ルールが厳しすぎないか
3. LLM の接続状態

JSON レスポンス解析エラーの場合は、LLM の出力形式が JSON 配列でない可能性:

```python
# extract_pains.py の _parse_json_response を確認
# コードブロック除去・JSON 配列抽出ロジック
```

### GitHub Issues 作成失敗

`gh` コマンド の認証状態を確認:

```bash
gh auth status
gh auth login  # 未認証の場合
```

Issue 本文が長すぎる場合もスキップされます。

## 🎮 Issue コマンド

`pain-report` ラベル付き Issue のコメントから、リポジトリオーナーが直接パイプラインを操作できる。

| コマンド | 動作 |
|---------|------|
| `/pick` | MVP 候補として `picked` に追加し `📌picked` ラベル付与 |
| `/spec` | Issue 本文（または既存 Deep Dive）から技術 Spec を生成。未 pick なら自動 pick |
| `/spec --force` | 既存 Spec を上書き再生成 |
| `/status` | picked / spec / deep_dive の現状と履歴を返答 |
| `/approve` | Spec 生成後、`mvp-factory` で自動実装をトリガー |
| `/reject` | `picked` から削除 |
| `/help` | コマンド一覧を返答 |

実装:
- ワークフロー: `.github/workflows/issue-commands.yml` / `.github/workflows/approve.yml`
- ロジック: `src/issue_commands.py`（共通 GitHub 操作は `src/gh_client.py`）
- 状態管理: `data/pipeline_state.json`（events[] に時系列ログ）

既存 Issue にコマンド一覧を一括投稿するには:

```bash
python scripts/post_help_to_existing_issues.py --dry-run  # 確認
python scripts/post_help_to_existing_issues.py            # 実投稿
```

## 今後の拡張

- LINE / Discord への通知機能
- 複数言語への対応（日本語以外の SNS）
- ペイン検索・フィルタ API
- ダッシュボード Web UI（週次トレンド可視化）
- 複数リポジトリでの集約管理
- フィードバック学習による SYSTEM_PROMPT の自動改善

## ライセンス

MIT License

## 関連リソース

- [GitHub Models | Try AI models free](https://github.com/marketplace/models)
- [Claude Documentation](https://claude.ai/login)
- [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/)
- [Reddit API](https://www.reddit.com/dev/api/)
