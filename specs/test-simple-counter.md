# Technical Spec: Simple Counter App

## 出典
- pain-collector Issue: #76
- スコア: S
- 市場シグナル: 🟢 whitespace

## 要件定義
- R1. ユーザーはカウンターを作成できる（名前付き）
- R2. カウンターの値を +1 / -1 できる
- R3. カウンターの一覧を表示できる
- R4. カウンターの値はブラウザの localStorage に保存される

## 技術スタック
- フロントエンド: Next.js 14 (App Router) + Tailwind CSS + shadcn/ui
- バックエンド: なし（クライアントサイドのみ）
- DB: localStorage
- デプロイ: Vercel

## 画面一覧
- / — カウンター一覧 + 新規作成フォーム
- /counter/[id] — 個別カウンター（+1/-1 ボタン）

## MVP スコープ
- [ ] カウンター CRUD（作成・表示・削除）
- [ ] +1 / -1 操作
- [ ] localStorage 永続化
- [ ] レスポンシブ UI（モバイル対応）

## 成功指標
- アプリが Vercel にデプロイ可能な状態になっている
- 全テストが通る
