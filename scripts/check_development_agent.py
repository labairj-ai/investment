"""Read-only static governance checks; no claim of operational certification."""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dev_agent.discovery import task_index
from dev_agent.policy import PRINCIPLES
from dev_agent.store import digest


def check(root=ROOT):
    root = Path(root); findings=[]
    if digest(PRINCIPLES) != "3f9a811cd9238ba1c1bf1e0ab801f1d710a0f2f4f03d93dc893cc6f41e537636": findings.append("reviewed principle contract changed")
    config = json.loads((root/"config/development_agent.json").read_text())
    if config["auto_merge"] or not config["required_human_merge"]: findings.append("human merge boundary weakened")
    if config["minimum_supervised_successes"] < 3 or config["minimum_observation_days"] < 7: findings.append("certification minima weakened")
    if config.get('autonomous_max_risk','L2')!='L2': findings.append('autonomous risk ceiling changed')
    if not 0<=config.get('daily_implementation_cap',1)<=3: findings.append('daily implementation cap out of bounds')
    if config.get('technical_certificate_max_age_hours',24)>24 or config.get('github_evidence_max_age_seconds',300)>300 or config.get('snapshot_max_age_hours',24)>24: findings.append('evidence freshness policy weakened')
    if config.get('governance_model')!='solo-owner-1': findings.append('solo-owner authority model missing')
    from scripts.check_agent_contract import validate_contract
    try:findings.extend(validate_contract((root/'AGENTS.md').read_text()))
    except OSError:findings.append('repository governance contract unavailable')
    for name in ('autonomous_implementation','supervised_loop_enabled','supervised_publish_pr'):
        if type(config.get(name,False)) is not bool:findings.append('non-boolean runtime policy: '+name)
    if config.get('autonomy_stage','SHADOW') not in {'SHADOW','BUILD_ONLY','PR'}:findings.append('invalid autonomy promotion stage')
    document=(root/"docs/development-agent.md").read_text()
    for key,text in PRINCIPLES.items():
        if f"{key}: {text}" not in document: findings.append("principle missing: "+key)
    for path in (root/"dev_agent").glob("*.py"):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            imports=[]
            if isinstance(node,ast.Import):imports=[a.name for a in node.names]
            if isinstance(node,ast.ImportFrom):imports=[node.module or ""]
            if any(name.split(".")[0] in {"agent_db","trade_engine","portfolio_ai","covered_call_rec","deployment_agent","owner_gateway"} for name in imports):
                findings.append("investment runtime import: "+path.name)
    try:task_index(root)
    except ValueError as error:findings.append(str(error))
    return dict(status="PASS" if not findings else "FAIL",findings=findings,operational_certification="NOT_EVALUATED")


if __name__=="__main__":
    result=check();print(json.dumps(result));raise SystemExit(result["status"]!="PASS")
