"""Stable configuration identity without trusting transient process bookkeeping."""
import copy
from types import SimpleNamespace
import pytest
from deployment_agent.executor import Executor

UNIT='''# /etc/systemd/system/investment.service
[Service]
User=optiplex
ExecStart=/home/optiplex/investment/venv/bin/python3 serve.py
# /etc/systemd/system/investment.service.d/90-development-agent.conf
EnvironmentFile=/home/optiplex/.local/share/investment-development/service.env
'''
VALUES=dict(FragmentPath='/etc/systemd/system/investment.service',DropInPaths='/etc/systemd/system/investment.service.d/90-development-agent.conf',User='optiplex',Group='optiplex',EnvironmentFiles='/home/optiplex/.local/share/investment-development/service.env (ignore_errors=no)',NeedDaemonReload='no')


def identity(tmp_path,*,values=None,unit=UNIT,after=None,runtime='pid=123 ; start_time=[old] ; status=0/0',reverse=False,corrupt=''):
    values=copy.deepcopy(VALUES if values is None else values);calls=[];count=0
    def invoke(command,**kwargs):
        nonlocal count
        calls.append(command)
        assert command[:3] in (['/bin/systemctl','show','investment.service'],['/bin/systemctl','cat','investment.service'])
        assert kwargs['check'] is True and kwargs['timeout']==15
        if command[1]=='cat':return SimpleNamespace(stdout=unit)
        count+=1;data=values if count==1 or after is None else after
        # Emulate systemd selecting requested properties from a service that has
        # different real execution bookkeeping across reloads/restarts.
        actual=dict(data,ExecStart='{ path=python ; argv[]=python serve.py ; '+runtime+' }')
        requested=command[-1].split('=',1)[1].split(',')
        names=reversed(list(actual)) if reverse else actual
        return SimpleNamespace(stdout='\n'.join(k+'='+actual[k] for k in names if k in requested)+corrupt)
    executor=Executor(tmp_path/'source',tmp_path/'receipts',tmp_path/'development-control.sqlite3',invoke=invoke)
    return executor.config_hash(),calls


def test_daemon_reload_or_restart_keeps_identity_but_retains_configured_execstart(tmp_path):
    before,calls=identity(tmp_path,runtime='pid=1611800 ; start_time=[Sat 2026-10-24 13:50:08 EDT] ; status=0/0')
    reloaded,_=identity(tmp_path,runtime='pid=0 ; start_time=[n/a] ; status=0/0',reverse=True)
    restarted,_=identity(tmp_path,runtime='pid=999999 ; start_time=[new] ; status=1/FAILURE')
    assert before==reloaded==restarted
    assert [c[1] for c in calls]==['show','cat','show']
    assert all('ExecStart' not in c[-1] for c in calls if c[1]=='show')


@pytest.mark.parametrize('field',['FragmentPath','DropInPaths','User','Group','EnvironmentFiles'])
def test_stable_loaded_configuration_changes_still_change_identity(tmp_path,field):
    before,_=identity(tmp_path);changed=dict(VALUES);changed[field]+='-changed'
    after,_=identity(tmp_path,values=changed)
    assert before!=after


@pytest.mark.parametrize('change',['command','argument','dropin','environment'])
def test_full_unit_command_dropin_and_environment_configuration_remains_bound(tmp_path,change):
    changed=UNIT.replace('serve.py','other.py') if change=='command' else UNIT.replace('serve.py','serve.py --unsafe') if change=='argument' else UNIT+'\nReadWritePaths=/unsafe\n' if change=='dropin' else UNIT.replace('service.env','other.env')
    assert identity(tmp_path)[0]!=identity(tmp_path,unit=changed)[0]


@pytest.mark.parametrize('failure',['missing','extra','duplicate','malformed','stale','no_fragment','empty_unit','oversize_unit','race'])
def test_incomplete_stale_or_racing_configuration_never_has_an_identity(tmp_path,failure):
    values=dict(VALUES);kwargs={}
    if failure=='missing':values.pop('User')
    if failure=='extra':kwargs['corrupt']='\nUnexpected=unsafe'
    if failure=='duplicate':kwargs['corrupt']='\nUser=duplicate'
    if failure=='malformed':kwargs['corrupt']='\nnot-a-property'
    if failure=='stale':values['NeedDaemonReload']='yes'
    if failure=='no_fragment':values['FragmentPath']=''
    if failure=='empty_unit':kwargs['unit']=''
    if failure=='oversize_unit':kwargs['unit']='x'*1_000_001
    if failure=='race':kwargs['after']=dict(values,NeedDaemonReload='yes')
    with pytest.raises(ValueError):identity(tmp_path,values=values,**kwargs)
