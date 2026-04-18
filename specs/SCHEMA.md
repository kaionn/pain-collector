# Spec Schema v1

pain-collector が生成し、mvp-factory が消費し、mvp-template ベースで実装される Technical Spec の契約フォーマット。

## 設計思想

- 機械可読部（YAML Front Matter）と人間可読部（Markdown body）を分離する
- `mvp-factory` の build.yml は Front Matter を JSON Schema で検証し、欠如時は fail-fast する
- Claude Code（実装側）は Front Matter で構造を把握し、Markdown body で文脈を補完する
- 既存 Spec（schema 不在）は legacy として警告のみで通す（移行猶予）

## ファイル形式

```markdown
---
schema_version: 1
product_name: string                 # MVP リポジトリ名のもとになる識別子（kebab-case）
source_issue: integer                # 紐付く pain-collector Issue 番号
title: string                        # 人間向けタイトル
tech_stack:
  frontend: string                   # 例: "Next.js 14 (App Router)"
  backend: string                    # 例: "Next.js API Routes" / "なし"
  database: string                   # 例: "SQLite" / "Supabase" / "localStorage"
  infrastructure: string             # 例: "Vercel" / "Cloudflare Pages"
data_model:
  - entity: string
    fields: [string, ...]
    relations: [string, ...]         # 任意
api_endpoints:
  - method: GET|POST|PUT|DELETE|PATCH
    path: string                     # 例: "/api/recipes/:id"
    description: string
mvp_scope:                           # 必須機能のリスト（チェックリスト）
  - string
success_metrics:
  - kpi: string
    target: string
deployment_target: vercel|github-pages|cloudflare-pages
---

# Technical Spec: {title}

_Source: Issue #{source_issue}_

## 要件定義

ユーザーストーリー形式で記述する（5-8 件）。

- R1. 「ユーザーとして、〜したい、なぜなら〜だから」
- R2. ...

## 画面一覧

| パス | 画面名 | 主要コンポーネント |
|------|--------|-------------------|
| /    | ホーム  | ...               |

## 補足

実装上の前提・制約・既存サービスとの差別化など、Front Matter では表現しきれない情報を記載する。
```

## 必須フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `schema_version` | integer | 現在は `1` 固定 |
| `product_name` | string (kebab-case) | mvp-factory がリポジトリ名の base に使う |
| `source_issue` | integer | pain-collector の Issue 番号 |
| `title` | string | 人間向けタイトル |
| `tech_stack.frontend` | string | フロントエンド技術 |
| `tech_stack.backend` | string | バックエンド技術（不要なら `"なし"`） |
| `tech_stack.database` | string | DB（不要なら `"なし"`） |
| `tech_stack.infrastructure` | string | インフラ・デプロイ先 |
| `data_model[]` | array | 1 件以上 |
| `api_endpoints[]` | array | 0 件以上（フロントのみアプリは空配列可） |
| `mvp_scope[]` | array | 1 件以上 |
| `success_metrics[]` | array | 1 件以上 |
| `deployment_target` | enum | `vercel` / `github-pages` / `cloudflare-pages` |

## バリデーション

- 機械検証: `specs/schema.json`（JSON Schema draft-07）で Front Matter を検証
- Python: `jsonschema` ライブラリ
- Node.js: `ajv` または `check-jsonschema` CLI
- 検証スクリプト: `scripts/validate_spec.py`

## 既存 Spec の扱い

| パターン | 挙動 |
|---|---|
| Front Matter あり + 検証 OK | 通常処理 |
| Front Matter あり + 検証 NG | mvp-factory 側で fail-fast、`spec-invalid` ラベル付与 |
| Front Matter なし | legacy として警告ログのみ。当面は受理（移行期間） |

## 参考

- 親 Plan Issue: kaionn/pain-collector#128
- 連携先: kaionn/mvp-factory#2, kaionn/mvp-template#1
