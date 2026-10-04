"""Owner-only durable ledger probe and one fixed synthetic seed/replay."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from notify_bridge import mirror, write_json, discord_gate, audit_delivery
from notify_ledger import GitLedger
spec=importlib.util.spec_from_file_location("smoke",Path(__file__).with_name("slack-smoke.py"))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
TEST="durable-synthetic-20261004-v1"

def main():
    phase=os.environ.get("LEDGER_TEST_PHASE","storage")
    result={"phase":phase,"test_id":TEST,"status":"started"}
    dest=Path(".notification-state/ledger-smoke-result.json")
    write_json(dest,result)
    try:
        if phase not in {"storage","seed","replay","primary-replay"} or os.environ.get("GITHUB_RUN_ATTEMPT")!="1":
            raise RuntimeError("invalid_phase_or_rerun")
        result["identity"]=smoke.identity()
        repo=os.environ.get("GITHUB_REPOSITORY","")
        key=hashlib.sha256((repo+":storage-probe-v1").encode()).hexdigest()
        store=GitLedger(repo,key);prior=store.load()
        if prior and prior.get("status")!="storage_verified":
            raise RuntimeError("unfinished_storage_probe")
        if prior:
            result["storage"]="verified_existing"
        else:
            state={"schema":1,"repo":repo,"key":key,"event":"storage-probe-v1","parts":[],"status":"probe","stage":"reserved"}
            store.save(state);state["status"]="storage_verified";state["stage"]="complete";store.save(state)
            assert store.load()["status"]=="storage_verified"
            result["storage"]="verified_written_and_read"
        write_json(dest,result)
        if phase!="storage":
            assert repo=="kaionn/lazy-product-lab"
            os.environ["NOTIFICATION_MODE"]="slack" if phase=="primary-replay" else "shadow"
            os.environ["NOTIFY_DURABLE_LEDGER"]="true"
            image=Path(".notification-state/durable-test.png");smoke.synthetic_png(image)
            expected="sent" if phase=="seed" else "already_sent"
            report=mirror({"content":f"[SYNTHETIC DURABLE LEDGER TEST {TEST}] Cross-run report and generated image only; no business processing or private data."},"reports",TEST,str(image))
            result["report"]=report;write_json(dest,result)
            if phase=="primary-replay":
                result["report_discord_gate"]=discord_gate(report)
                assert result["report_discord_gate"] is False
            if report["status"]!=expected:raise RuntimeError("report_not_expected")
            alert=mirror({"content":f"[SYNTHETIC DURABLE LEDGER TEST {TEST}] Cross-run alert transport only; not a real failure."},"alerts",TEST)
            result["alert"]=alert;write_json(dest,result)
            if phase=="primary-replay":
                result["alert_discord_gate"]=discord_gate(alert)
                assert result["alert_discord_gate"] is False
                assert audit_delivery()==0
            if alert["status"]!=expected:raise RuntimeError("alert_not_expected")
        result["status"]="verified";write_json(dest,result);print(json.dumps(result));return 0
    except Exception:
        result["status"]="needs_review";write_json(dest,result)
        print(json.dumps(result));return 1

if __name__=="__main__":raise SystemExit(main())
