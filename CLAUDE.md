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
# 依存インストール（pyproject.toml + uv.lock が正）
uv sync

# テスト実行
uv run pytest tests/ -v

# 日次収集
python -m src.main
```

`requirements.txt` は過渡期のため当面残す（`pip install` によるローカル互換用）。依存の一次情報は `pyproject.toml` + `uv.lock`。

```bash
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

## 品質ゲートと選定ルール（実装準拠）

### Issue 化直前の actionability ゲート（src/pain_gate.py）

抽出 LLM の skip ルールはリークするため、Issue 化直前（日次 top_n 件のみ）に二段目の専用 LLM 判定を通す。reject 基準は 4 つ: 特定既存アプリの不具合クレーム / 社会問題・政策 / 技術サポート Q&A / プロダクトで解決できない感情・状況（センシティブ領域）。判定失敗時は fail-open（Issue 化を止めない）。pass した Issue には audience ラベル（`👨‍💻dev` / `👤consumer`）が付き、pain-data メタデータにも `audience` が入る。

### 選定（pick_idea.py）のドメイン多様性ルール

`--pick-idea` は技術寄り偏重の抑制をプロンプト指示 + コード後処理の二段で行う:

- 開発者向け候補は最大 1 件（`_enforce_diversity` がコードで強制。LLM が違反したら 2 件目以降を consumer 候補のスコア上位で置換し、置換分の詳細は承認後の Deep Dive で補完）
- audience 判定はラベル優先（`👨‍💻dev` / `👤consumer`）、無ければプロダクト種別ラベル（⌨️CLI・開発ツール / ☁️API・SaaS → developer）でフォールバック
- 直近 pick と同カテゴリの候補はソートで後方に降格（`_demote_same_category`。数値ペナルティ方式ではない）
- ジャッジ LLM の dev ツール過大評価は PICK_PROMPT に自己バイアスとして明示

スコア重み（scoring.py の WEIGHTS が正）: 技術的シンプルさ x2 / スコープ x2 / 差別化 x2 / コミュニティ検証 x2 / ペイン強度 x1 / 収益可能性 x3（最大 60 点）。SCORING_PROMPT にはアンカー例と full-range 指示（3〜4 固着の禁止）を含む。

## 通知 / Issue dedup 方針

`src/notify.py` の `_find_duplicate` は以下の階層で重複検出する:

1. **プロダクトキー dedup**（最優先）: source_url から `appstore:{id}` / `reddit:{sub}` / `togetter:{id}` 等を抽出し、同一プロダクトの open Issue があれば TF-IDF を待たずコメント化
2. **TF-IDF cosine similarity**: 高 0.7 / 低 0.4、グレーゾーンは LLM 判定

Issue 本文には `<!-- product:appstore:1232780281 -->` 形式の隠しメタデータを埋め込み、本文パースなしで高速判定する。既存 Issue は `## ソース` セクションの URL から再抽出するフォールバックで後方互換を維持。

`PAIN_USE_EMBEDDINGS=1` を設定すると、TF-IDF の代わりに `llm_client.embed()`（GitHub Models embeddings API）による cosine similarity 判定に切り替わる（既定 OFF）。閾値は高 0.85 / 低 0.60。embeddings が取得できない場合（`GITHUB_TOKEN` 無し・API 失敗）は自動で TF-IDF にフォールバックする。

通知は個別配信ではなく日次 digest に集約する（severity 降順）。「同一アプリに対する別バグ報告」が大量重複する設計上の盲点への対策。

## モバイル候補の技術スタック既定

`--pick-idea` / `/build` でモバイル対応プロダクトを提案する際は iOS ネイティブ（Swift + SwiftUI）を既定とする。React Native / Expo 等は明確に有利な理由がある場合のみ併記する。

## .gitignore とワークフローの commit 対象を同期する

成果物ディレクトリを `.gitignore` に追加・除外する際は、それを `git add` で明示している全ワークフロー（`collect.yml` 等）の add 対象も同時に揃える。

## LLM 呼び出しの統一（src/llm_client.py）

新規モジュールで LLM を呼ぶ場合は `src/llm_client.py` の `chat()` / `parse_json_response()` / `parse_json_object()` / `embed()` を経由する。モデル名（`openai/gpt-4o-mini`）・base_url（`https://models.github.ai/inference`）・リトライは同モジュールに一元化されている。`openai` SDK や `subprocess`（Claude CLI）を直呼びしてモデル名・base_url をハードコードしない。

例外: 呼び出しごとに可変のタイムアウトを CLI 引数で公開しているモジュール（`generate_product_name.py` 等）や、「例外を投げず None を返す」契約をテストが検証しているモジュールは、トランスポート統合はせず定数（`llm_client.DEFAULT_MODEL` / `GITHUB_MODELS_BASE_URL`）の共有のみに留める。`chat()` はタイムアウト引数を持たず例外を投げる契約のため。

## コレクタの追加方法（collector registry）

新しいコレクタを追加する際は `src/collector_registry.py` の `@register_collector(key, display_name, supports_backfill=...)` デコレータで登録する。`main.py` に手動の並行リスト（collectors / raw_keys）を書き足さない（registry 撤廃済み）。出力 post は `validate_post()` を通す。テスト `test_collector_registry.py` の「登録済みキー集合が期待値と一致する」検証があるため、追加時は期待集合も更新する。

## コレクタのテスト方針（tests/collectors/）

各コレクタは最低 2 テスト（happy path + エラー時空リスト）を `tests/collectors/` に置く。モック方式はソースの取得手段で決める:

- HTTP JSON/HTML API（reddit, hn, appstore 等）: `responses` で HTTP レスポンスをモック
- RSS 系（hatena, zenn, note, producthunt）: `responses` は効かない（`feedparser.parse` が内部で `urllib` を使い requests をフックしないため）。`feedparser.parse` 自体をモックし、モック内で本物の `feedparser.parse(FIXTURE_XML)` に生の RSS 文字列を渡す。**必ず `real_parse = feedparser.parse` で元関数を先に退避してから使う**（lambda 内で `feedparser.parse` を参照するとパッチ後の自分自身を指して無限再帰する）
- google_play_scraper: batchexecute プロトコルのため HTTP モック不可。`reviews` 関数自体をモックする

リトライ系コレクタは実待機を避けるため `time.sleep` を monkeypatch する。

## ワークフローのコードは src/ モジュールに置く

`.github/workflows/*.yml` に `python3 - <<'PY'` の heredoc や `python3 -c` を埋めない（テスト不能・レビュー困難）。ロジックは `src/` の CLI サブコマンド（`state_sync.py` / `workflow_alerts.py` / `approve_checks.py` 等）に置き、`uv run python -m src.xxx` で呼ぶ。単純な JSON 抽出は `jq` で済ませる。`grep -rnE "python3? +(- <<|-c )" .github/workflows/` がヒット 0 件であることを維持する（`python -c` の 3 なし表記も対象。weekly.yml のインライン `python -c` が YAML folding の先頭空白で IndentationError になり 17 週サイレント失敗した実績あり）。

注: `issue-commands.yml` には未撤廃のインライン bash（SHA 取得 + PUT）が残存。将来統一するなら `state_sync.py` へ寄せる。

## ワークフローの PAT_TOKEN 運用

- **main へ push する全ワークフロー（collect / weekly / monthly / learn）は `actions/checkout` に `token: ${{ secrets.PAT_TOKEN }}` を渡す。** 既定の `GITHUB_TOKEN` では Branch Protection に拒否され `GH006: Protected branch update failed` で失敗する。新規ワークフローを追加する際も必ず揃える
- `PAT_TOKEN` は fine-grained PAT（対象: 本リポジトリ、権限: Contents Read/Write + Issues Read/Write）で **約 90 日で失効し、失効するとパイプライン全体が停止する**。ローテート手順:
  1. https://github.com/settings/personal-access-tokens/new で再発行
  2. `gh secret set PAT_TOKEN --repo kaionn/pain-collector`（トークンをチャットに貼らず手元実行）
  3. `gh workflow run collect.yml` で疎通確認（checkout 通過 + commit/push 成功まで見る）
- 失効の事前警告は `monitor.yml` の「Check PAT expiry」ステップ（`src/pat_expiry_check.py`）が担う。残り 7 日以内から毎朝 JST 6 時台に Discord へ警告、失効済み（401）なら即アラート。疎通確認: `gh workflow run monitor.yml -f force_pat_check=true -f dry_run=true`
- **monitor.yml は PAT 非依存で動く設計を維持する**（PAT が失効しても監視自体が生き残るための前提。監視ステップに PAT 必須の処理を足さない）

## Discord 通知の構成

- 通知は 2 系統: 日次 digest・Issue 通知・パイプラインアラートは `DISCORD_WEBHOOK_URL`（宛先チャンネルは Webhook URL 自体に埋め込み）、週次 MVP 選定（承認ボタン付き）は `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID`
- メンション先の Discord ユーザー ID は `src/discord_notify.py` にハードコードされている。通知が届いているのに気づけない場合はここを疑う
