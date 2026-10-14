# 日次収集レポートの保存

main 以外の ref で手動起動した場合は backup upload 後に保存を拒否し、branch のコード変更が main へ混入することを防ぐ。

`collect.yml` は収集成功後、変更された直下の `daily/*.md` と `deep_dive/*.md` の regular file だけを `RUNNER_TEMP` にコピーし、保存操作より先に `collected-reports-<run_id>-<run_attempt>` artifact を upload する。保持期間は 7 日。変更なしなら artifact は作らず成功する。削除、隠しファイル、入れ子のファイルは生成レポートの対象外で、シンボリックリンクは拒否する。

artifact は本リポジトリに公開する予定の Markdown のみを含む。公開リポジトリの既存 Actions artifact の閲覧権限を用い、新しい共有先・権限は追加しない。raw、logs、data、env、.git、通知状態、ローカル manifest は含めない。通知 receipts/outbox の既存 artifact 設定は変更しない。

backup と checkout が同じ内容であることを確認して report-only commit を作る。push は最大 3 回、各 Git 操作は 60 秒で停止する。main が進んだ場合だけ fetch（浅い checkout では unshallow）して生成 commit を rebase し、force push はしない。レポート衝突は rebase を abort して終了コード 1 で停止する。認証・通信障害、無関係の tracked/staged 差分も安全に失敗する。通常成功と変更なしは終了コード 0。収集や通知は再実行しない。

最終 push 失敗時は、7 日以内に当該 run の artifact を download し、Markdown を最新 main と比較して別 branch/PR で復旧する。report conflict は手動レビューして解消する。artifact の upload 自体が失敗すると persistence を開始しない。runner の停止や収集失敗など、backup upload 前の障害はこの変更の保護対象外。

2026-10-11 の過去の失われたレポートはこの変更で復元されない。元の正確な Markdown が保存されていない限り、同一レポートの復元を主張できない。
