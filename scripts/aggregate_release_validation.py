"""Independent repository CI diagnostics, never an agent technical certificate.

Trusted candidate admission continues to require the isolated development-agent
validator. A green repository workflow alone cannot authorize model execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

GATES=('todo_consistency','agent_contract','development_governance','focused_agent_tests','full_suite','release_baseline','cc_contract','summary_integrity')


def inventory(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8_000_000:raise ValueError('regular bounded JUnit required')
    cases=list(ET.parse(path).getroot().iter('testcase'))
    ids=[c.get('classname','')+'::'+c.get('name','') for c in cases]
    if not cases or len(ids)!=len(set(ids)):raise ValueError('nonempty unique test inventory required')
    failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    skipped=sum(c.find('skipped') is not None for c in cases)
    return dict(total=len(cases),passed=len(cases)-failed-skipped,failed=failed,skipped=skipped,sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def integrity(summary):
    rows=summary.get('gates',[])
    return (len(rows)==len(GATES) and [r.get('name') for r in rows]==list(GATES)
            and all(r.get('status')=='PASS' and r.get('exit_code')==0 for r in rows)
            and summary.get('source_unchanged') is True and summary.get('head')==summary.get('expected_head')
            and summary.get('pytest',{}).get('total',0)>0 and summary['pytest'].get('failed')==0)


def cc_command(py,prior):
    # In CI only the checker may derive authority from the GitHub event.
    # A local caller may provide an explicit reviewed prior reference.
    command=[py,'scripts/check_cc_contract.py']
    if os.environ.get('GITHUB_ACTIONS')!='true' and os.environ.get('CI')!='true':
        command+=['--prior-ref',prior]
    return command


def run(root,out,expected_head,prior,*,invoke=subprocess.run):
    root=Path(root).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    py=sys.executable; junit=out/'test-results.xml';junit.unlink(missing_ok=True)
    commands=[('todo_consistency',[py,'scripts/check_todo_status.py']),('agent_contract',[py,'scripts/check_agent_contract.py']),('development_governance',[py,'scripts/check_development_agent.py']),('focused_agent_tests',[py,'-m','pytest',*[str(p.relative_to(root)) for p in sorted(set((root/'tests').glob('test_development_agent*.py')) | {root/'tests'/n for n in ('test_continuous_improvement.py','test_deployment_agent.py','test_owner_gateway.py','test_live_operational_acceptance.py') if (root/'tests'/n).is_file()})],'-q','--tb=short']),('full_suite',[py,'-m','pytest','tests/','-v','--tb=short','--junitxml='+str(junit)]),('release_baseline',[py,'scripts/check_release_baseline.py',str(junit)]),('cc_contract',cc_command(py,prior))]
    clean_before=subprocess.run(['git','-C',str(root),'diff','--quiet','HEAD','--'],capture_output=True).returncode==0
    result=dict(version='repository-validation-1',head=head,expected_head=expected_head,authority='repository-ci-diagnostics-only',trusted_agent_certification=False,gates=[],pytest={},created=time.time())
    for name,command in commands:
        row=dict(name=name,command=command,status='FAIL',exit_code=None)
        if name=='release_baseline' and not junit.is_file():row.update(status='NOT_RUN',reason='full-suite JUnit missing')
        else:
            try:
                with (out/(name+'.log')).open('w') as log:
                    process=invoke(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=2400,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
                row.update(status='PASS' if process.returncode==0 else 'FAIL',exit_code=process.returncode)
                if name=='full_suite':
                    result['pytest']=inventory(junit)
                    if result['pytest']['failed']:row['status']='FAIL'
            except (OSError,ValueError,subprocess.TimeoutExpired,ET.ParseError) as error:row.update(status='FAIL',reason=type(error).__name__)
        result['gates'].append(row)
        (out/'validation-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    result['source_unchanged']=clean_before and subprocess.run(['git','-C',str(root),'diff','--quiet','HEAD','--'],capture_output=True).returncode==0 and subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==head
    result['gates'].append(dict(name='summary_integrity',status='PASS',exit_code=0))
    if not integrity(result):result['gates'][-1].update(status='FAIL',exit_code=1,reason='incomplete, failed or SHA-mismatched mandatory evidence')
    result['status']='PASS' if integrity(result) else 'FAIL'
    (out/'validation-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Exact-head repository validation',f"SHA: `{head}`",f"Result: **{result['status']}**",'','| Gate | Status | Reason |','|---|---|---|']
    lines += [f"| {r['name']} | {r['status']} | {r.get('reason','')} |" for r in result['gates']]
    lines += ['', 'Pytest: '+json.dumps(result['pytest']), '', 'Repository CI is not a technical certificate or approval.']
    (out/'validation-summary.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--out',type=Path,required=True);p.add_argument('--head',required=True);p.add_argument('--prior',required=True);a=p.parse_args()
    result=run(a.root,a.out,a.head,a.prior);print(json.dumps(dict(status=result['status'],head=result['head'],gates=result['gates']),indent=2));raise SystemExit(0 if result['status']=='PASS' else 1)
