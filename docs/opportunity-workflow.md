# 証拠から小さな試作まで

## 責務と正の情報

| repo | 担当 | 正の情報 |
|---|---|---|
| lazy-product-lab | 自由な発想、過去案の重複回避、仮説の輸出 | ideasの原文と生成時刻。生成文は需要の証拠ではない |
| pain-collector | 収集、証拠付き候補、最大3件のshortlist、build contract、承認・結果の状態 | contracts/opportunity-v1.schema.json とローカル機会record |
| signal-lab | tool/LPの試作、テスト・preview、承認後の配布と計測 | 実験meta、実際のartifact、計測結果 |

新しい大規模orchestratorや有料サービスは導入しない。dotはChatGPT上でshortlistを読んで1件を推薦する人間向け役割であり、呼出可能なdot APIは仮定しない。既存Actionsによる収集・通知は継続するが、新CLIはLLM、ネットワーク、shell check、dispatch、PR、公開、投稿を実行しない。

## 契約 v1

3 repoのschemaコピーは同一。pain-collectorが所有し、変更時は全コピーとfixtureを更新する。未知version/fieldを拒否する。originにrepo・原文locator・URL・観測時刻・hypothesis/painを保存し、evidenceには確認時刻・要約・pain/demand/alternative/distributionを記録する。輸出時刻で古いsourceを新しく見せない。

生成案やLLM採点は需要仮説。30日以内に再確認したpain・代替手段・到達可能な配布先を揃え、直接競合と対象が違うアプリ検索結果を区別する。shortlistは最大3件、対象者+問題の同一文を重複除外し、証拠の種類・鮮度・短い試作時間で決定的に並べる。意味的重複と引用内容の真偽はdot/ユーザーが原文で確認する。自動スコアは売上やバズの予測ではない。

buildは単一core flow、合成demo入力、id付き受入check/期待結果、非対象、最大時間(1〜480分)、最大反復(1〜10)、利用可能toolを明記。toolは実際に動く機能、landing_pageは登録意向の実験。後者の登録を機能利用として扱わない。具体的な配布先・相手・理由、主要event、卒業閾値、最小露出数、観測期間、撤退理由を先に記載する。

## 手動で一周する

1. lazyから候補をstdoutへ輸出する（実行場所lazy-product-lab）:
   `python3 scripts/export_opportunities.py ideas/2026/W40/candidates-3.md > /tmp/candidates.json`
2. painで確認する:
   `python3 -m src.opportunity_pipeline shortlist /tmp/candidates.json`
   dotが原文と代替手段・配布先を調べ1件を推薦。JSONの仮説を狭いcontractへ具体化し、受入checkと新しいevidenceをレビューする。examples/opportunity.jsonは未検証のdraftで承認不可。fixture URLを実需要として流用しない。
3. 個別contractをローカルrecordへ登録:
   `python3 -m src.opportunity_pipeline init /tmp/contract.json --state /tmp/opportunity/state.json`
   digest/revisionを確認し、人間の明示OKの参照をbuild-approval.jsonへ記録する:
   `{"digest":"<contract_digest>","approval_reference":"<ユーザー承認メッセージの参照>"}`
4. 変更は既定dry-run。結果を確認して同じコマンドに`--apply`を付ける:
   `python3 -m src.opportunity_pipeline transition --state /tmp/opportunity/state.json --to approved --event-id build-ok-1 --revision 0 --actor kaionn --data /tmp/build-approval.json`
   `--apply`後、handoffを作る:
   `python3 -m src.opportunity_pipeline handoff --state /tmp/opportunity/state.json --output /tmp/approved-build`
5. signalで輸入を検証:
   `node scripts/check-handoff.mjs /tmp/approved-build/handoff.json`
   ローカルCodexへBUILD.mdとhandoff.jsonを渡す。toolならProbe A、LPならProbe B。別worktree/branchで必要範囲を実装し、building開始をrecordへ記録。新Web実験はdraft、`?demo=1`は合成データ、公開設定・credentials・実ユーザーデータを使わない。
6. 結果JSONにcontract_digest、outcome=passed、全checkのid/passed/artifact、localhost preview URL、elapsed_minutes、iterationsを保存しreview_readyへ。失敗/道具不足/時間超過ならfailedまたはblockedと理由を記録。CLIはcheckを実行せず実測artifactの申告を検査するため、人間/レビューagentがartifactを読む。
7. ユーザーが実物をレビューした後、result JSONのSHA256 digestにrelease承認を記録しrelease_approvedへ。digestは`python3 -c 'import json; from src.opportunity_pipeline import digest; print(digest(json.load(open("/tmp/result.json"))))'`で取得する。commit・push・PR・merge・公開・投稿はそれぞれ明示許可を要する。signalのmain mergeはVercel公開に繋がる既存設定であり、preview承認をmerge許可に拡張しない。
8. 実際の公開URLとartifactをreleasedへ、実際の配布URL/日時・計測日時・observed/unknownとexposures/primary_countをlearningへ記録。unknownはnullで、ゼロにしない。卒業/撤退は露出が十分かつ新しい測定時点が必要。観測期間は最初の配布から、判定は勧告で人間の次の変更承認を置き換えない。

## 有限状態と再開

shortlisted → approved → building → review_ready → release_approved → released → learning → graduated/killed。
各非終端状態からblocked/failed/cancelledへ停止可能。blockedからshortlistedへ戻すと承認とresultを破棄し再承認。failed/cancelled/graduated/killedは終端。訂正や別仮説は新idのrecordで履歴を残す。contract変更は既存recordを上書きせず新recordとしてレビューする。

各transitionはexpected revision・event id・actor・dataを持つ。同一eventの同一内容は再生しても増えず、異なる内容の同じevent idと古いrevisionは拒否。ローカルfile lock＋atomic replaceで同時writerを直列化する。承認はcontract/result digestに結び付く改変検知で、CLI利用者の本人認証ではない。ローカルファイルを書ける者は承認記録も書けるため、trusted operatorが人間の許可を確認して使う。build開始時のdeadlineを超えてreview_readyへ進めないが、CLIは外部Codexプロセスを強制停止しない。実行者が上限で止め、必要ならblockedを記録する。

## 既存データと互換経路

raw/daily/weekly/picks/specs、既存pipeline_state、実験と通知設定を保全する。新recordはまず/tmp等のローカル作業領域で管理し、CIのmain stateと二重writerにしない。古い候補レポートは履歴として変更しない。/pick・/spec・/status・/rejectは互換、/approveは廃止、/probeは従来の外部LLMによるLP生成経路で新contractとは別。新導線はこれを呼ばず、旧経路の実行許可が必要。mvp-factory・mvp-template・subscription-guardは2026-10-04に既にarchive確認済み、再稼働しない。

旧building/probingは24h超過をstalled候補にするが成否を推定しない。元run/PRを読み、24h以内に確認したsnapshotを作る:
`[{"issue_number":223,"checked_at":"<ISO日時>","evidence_url":"https://github.com/kaionn/signal-lab/pull/1","outcome":"closed_unmerged"}]`
`python3 -m src.opportunity_pipeline reconcile-legacy --state data/pipeline_state.json --snapshots /tmp/snapshots.json`
これはstdoutへmigration案を出すだけ。failed→failed、closed_unmerged→cancelled、merged→probe-ready（公開成功ではない）。実remoteへの適用は別承認とfresh snapshotが必要。monitorのremote同期はfetch時content+SHAを一緒に取得しbase sidecarを保持、pushはそのSHAだけ使用。競合は停止して再fetch・再検出し、push成功後だけ通知する。取得失敗を空stateに置き換えない。

## 計測・停止と運用の完了条件

signalの週次判定はtool_useとsignupを型別に分離。未集客、計測欠落、露出不足はWATCH理由として明示し、KILLしない。既存metaのminimum_exposuresは20を既定に後方互換。閾値は試行開始前の仮説で、バズを保証しない。再訪は直近7日で2日以上の活動があったdistinct_idを集計し、同一sessionの2イベントをリテンション証拠とみなさない。匿名idの端末差・cookie削除の限界は残る。卒業は次のbuildを検討するIssueで、自動本実装ではない。

各試行の完了は「選択→contract承認→動くdemo/テスト証拠→ユーザーレビュー」までをまず1件通すこと。公開の次は配布から観測期間を決め、計測未接続なら設定の別許可と確認、露出不足なら配布改善か実験停止を人間が決める。無期限WATCHを成功と報告しない。

## 参考にした一次資料（2026-10-04確認）

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): 小さな明示workflow、観測結果、停止条件から始める。
- [OpenAI: Safety in building agents](https://developers.openai.com/api/docs/guides/agent-builder-safety): structured outputs、untrusted input分離、承認と評価。特定builderを導入する根拠にはしない。
- [Temporal: Activity definition](https://docs.temporal.io/activity-definition): 再実行可能性/冪等性の設計を参考にするがTemporalは導入しない。
- [GitHub: Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency): 同時実行制御だけではstateのCASを代替しない。
- [GitHub: GITHUB_TOKEN](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token): 必要最小限の権限とrepo設定を分けて扱う。
