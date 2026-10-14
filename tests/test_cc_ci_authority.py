"""0731: CI caller inputs never substitute for authenticated event authority."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from covered_call_change_control import write_baseline
from strategy_config import CC_V3_CONFIG

ROOT=Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('flag',['GITHUB_ACTIONS','CI'])
@pytest.mark.parametrize('case', ['absent','unreadable','malformed','array','unsupported','missing_name',
                                  'missing_sha','zero_sha','short_sha','nonstring_sha','bad_nested'])
@pytest.mark.parametrize('override',['none','prior_ref','prior_file'])
def test_ci_invalid_context_rejects_even_with_caller_authority(tmp_path,flag,case,override):
    env=dict(os.environ,GITHUB_ACTIONS='false',CI='false')
    env[flag]='true'
    env.pop('GITHUB_EVENT_PATH',None)
    env['GITHUB_EVENT_NAME']='push'
    path=tmp_path/'event.json'
    payload={'before':'a'*40}
    if case=='malformed':path.write_text('{')
    elif case=='array':path.write_text('[]')
    elif case=='missing_sha':path.write_text('{}')
    elif case=='zero_sha':path.write_text(json.dumps({'before':'0'*40}))
    elif case=='short_sha':path.write_text(json.dumps({'before':'a'*12}))
    elif case=='nonstring_sha':path.write_text(json.dumps({'before':42}))
    elif case=='bad_nested':
        env['GITHUB_EVENT_NAME']='pull_request';path.write_text(json.dumps({'pull_request':None}))
    elif case!='unreadable':path.write_text(json.dumps(payload))
    if case!='absent':env['GITHUB_EVENT_PATH']=str(path)
    if case=='unsupported':env['GITHUB_EVENT_NAME']='workflow_dispatch'
    if case=='missing_name':env.pop('GITHUB_EVENT_NAME',None)
    command=[sys.executable,str(ROOT/'scripts/check_cc_contract.py'),'--json']
    if override=='prior_ref':command+=['--prior-ref','a'*40]
    if override=='prior_file':
        baseline=tmp_path/'baseline.json';write_baseline(CC_V3_CONFIG,baseline)
        command+=['--trusted-prior-file',str(baseline)]
    result=subprocess.run(command,env=env,capture_output=True,text=True)
    assert result.returncode==1,result.stdout+result.stderr
    data=json.loads(result.stdout)
    assert not data['ok'] and data['findings'][0].startswith('TRUSTED_PRIOR_ERROR:')


@pytest.mark.parametrize('flag',['GITHUB_ACTIONS','CI'])
@pytest.mark.parametrize('event_name',['push','pull_request'])
@pytest.mark.parametrize('override',['prior_ref','prior_file'])
def test_ci_rejects_caller_authority_even_when_equal(tmp_path,flag,event_name,override):
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    event={'before':sha} if event_name=='push' else {'pull_request':{'base':{'sha':sha}}}
    path=tmp_path/'event.json';path.write_text(json.dumps(event))
    env=dict(os.environ,GITHUB_ACTIONS='false',CI='false',GITHUB_EVENT_PATH=str(path),GITHUB_EVENT_NAME=event_name)
    env[flag]='true'
    args=['--prior-ref',sha]
    if override=='prior_file':
        baseline=tmp_path/'baseline.json';write_baseline(CC_V3_CONFIG,baseline)
        args=['--trusted-prior-file',str(baseline)]
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_cc_contract.py'),'--json',*args],env=env,capture_output=True,text=True)
    assert result.returncode==1
    assert 'CI computes authority' in json.loads(result.stdout)['findings'][0]


def test_offline_explicit_prior_file_still_supported(tmp_path):
    baseline=tmp_path/'baseline.json';write_baseline(CC_V3_CONFIG,baseline)
    env=dict(os.environ,GITHUB_ACTIONS='false',CI='false')
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_cc_contract.py'),'--json',
                           '--baseline-file',str(baseline),'--trusted-prior-file',str(baseline)],
                          env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
