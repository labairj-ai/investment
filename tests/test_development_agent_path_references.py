"""Exact path/usage analysis never reads the production data being classified."""
from pathlib import Path
import subprocess
import pytest
from ops.discovery import influence as a
from test_development_agent_untracked_influence import repo,add


def model(text,root=Path('/reviewed')):
    return a.path_references(root,{'dev_agent/cli.py':text})


def uses(result,path):return [r for r in result['references'] if r['path']==path]


def test_bare_policy_diagnostic_and_basename_literals_are_not_paths():
    result=model('POLICY=(".env","investment.db")\nmessage="holdings.csv"\nlabel="out/investment.db"\n')
    assert result['references']==[] and result['ambiguous']==[]


def test_full_path_context_is_preserved_for_equal_basenames():
    result=model('from pathlib import Path\nROOT=Path("/reviewed")\na=(ROOT/"out/investment.db").read_bytes()\nb=(Path(root)/"config/policy.json").read_text()\nc=(ROOT/"other/investment.db").read_bytes()\n')
    assert uses(result,'out/investment.db') and uses(result,'other/investment.db')
    assert uses(result,'config/policy.json')
    assert not uses(result,'investment.db')
    assert all(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in result['references'])


def test_aliases_joins_and_open_are_exact_authority_paths():
    result=model('from pathlib import Path\nROOT=Path("/reviewed")\nbase=ROOT/"config"\np=base.joinpath("policy.json")\ntext=p.read_text()\nwith (ROOT/"data/policy.csv").open() as f: content=f.read()\n')
    assert uses(result,'config/policy.json') and uses(result,'data/policy.csv')
    assert not uses(result,'policy.json') and not uses(result,'policy.csv')


HASH='''import hashlib
def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
'''
DBHASH='''import hashlib,sqlite3
def database_hash(path):
    h=hashlib.sha256()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        for line in db.iterdump():h.update(line.encode())
    return h.hexdigest()
'''
DENIED='''import os
def denied(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK);os.close(fd);return False
    except PermissionError:return True
'''


@pytest.mark.parametrize('helper,name',[(HASH,'file_hash'),(DBHASH,'database_hash'),(DENIED,'denied')])
def test_readonly_evidence_helpers_propagate_exact_path(helper,name):
    result=model(helper+'\nvalue='+name+'(Path(root)/"state/evidence.data")\n')
    records=uses(result,'state/evidence.data')
    assert records and all(r['usage']=='PROTECTED_RUNTIME_EVIDENCE' for r in records)
    assert not result['ambiguous']


@pytest.mark.parametrize('suffix',['json','db','csv','env'])
def test_data_extension_does_not_remove_configuration_authority(suffix):
    result=model('from pathlib import Path\nimport json\npolicy=json.loads((Path(root)/"config/policy.'+suffix+'").read_text())\nif policy["execute"]: pass\n')
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(result,'config/policy.'+suffix))


@pytest.mark.parametrize('mechanism',['subprocess.run','runpy.run_path','importlib.util.spec_from_file_location'])
def test_execution_mechanisms_receive_exact_paths(mechanism):
    result=model('from pathlib import Path\n'+mechanism+'(Path(root)/"runtime/data.json")\n')
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(result,'runtime/data.json'))


def test_database_configuration_is_authority_without_hash_contract():
    result=model('import sqlite3\nfrom pathlib import Path\ndb=sqlite3.connect(Path(root)/"policy.db")\nmodule=db.execute("SELECT module FROM config").fetchone()\n')
    assert uses(result,'policy.db')[0]['usage']=='SOURCE_OR_EXECUTION_AUTHORITY'


def test_authority_use_dominates_evidence_of_same_exact_path():
    result=model(HASH+'\na=file_hash(Path(root)/"data.json")\nb=(Path(root)/"data.json").read_text()\n')
    assert {r['usage'] for r in uses(result,'data.json')}=={'SOURCE_OR_EXECUTION_AUTHORITY','PROTECTED_RUNTIME_EVIDENCE'}


def test_hash_helper_name_cannot_hide_side_effect_or_parser():
    result=model('def file_hash(path):\n    value=path.read_text()\n    exec(value)\n    return value\n\nvalue=file_hash(Path(root)/"config.json")\n')
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(result,'config.json'))


def test_dynamic_rooted_configuration_path_fails_closed():
    result=model('from pathlib import Path\nimport os\np=Path(root)/os.environ["POLICY_FILE"]\nvalue=p.read_text()\n')
    assert result['ambiguous'] and result['ambiguous'][0]['reason']=='UNRESOLVED_AUTHORITY_PATH'


def test_unknown_path_constructor_fails_closed():
    result=model('from pathlib import Path\nimport os\nvalue=Path(os.environ["POLICY_FILE"]).read_text()\n')
    assert result['ambiguous']


SCOUT='''[Service]
ProtectSystem=strict
ProtectHome=read-only
NoNewPrivileges=true
ReadWritePaths=/home/optiplex/.local/share/investment-development
'''


def commit_reader(root,text,scout=SCOUT):
    (root/'dev_agent/cli.py').write_text(text)
    (root/'systemd/development-scout.service').write_text(scout)
    subprocess.run(['git','-C',str(root),'add','--','dev_agent/cli.py','systemd/development-scout.service'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','reviewed path consumer'],check=True)
    return subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()


def test_protected_evidence_requires_sandbox_proof(repo):
    root,_=repo;head=commit_reader(root,HASH+'\nvalue=file_hash(Path(root)/"state.csv")\n')
    add(root,'state.csv')
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='PASS'
    assert result['allowed_categories']=={'protected_runtime_evidence':1}
    record=result['path_dispositions'][0]
    assert record['evidence_proof']['scout_not_writable']
    assert record['exact_path_references'][0]['path']=='state.csv'


def test_denial_probe_requires_reviewed_inaccessible_path(repo):
    root,_=repo
    source=DENIED+'\nvalue=denied(Path(root)/"private.data")\n'
    head=commit_reader(root,source);add(root,'private.data')
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'
    # This is a synthetic source change proving a generic policy rule, not an
    # exception derived from production audit output.
    head=commit_reader(root,source,SCOUT+'InaccessiblePaths=-'+str(root/'private.data')+'\n')
    assert a.audit(root,head)['allowed_categories']=={'protected_runtime_evidence':1}


def test_hash_plus_configuration_read_still_fails(repo):
    root,_=repo;head=commit_reader(root,HASH+'\na=file_hash(Path(root)/"state.json")\nb=(Path(root)/"state.json").read_text()\n')
    add(root,'state.json')
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='FAIL'
    assert any(r['path']=='state.json' and r['reason']=='REVIEWED_SOURCE_REFERENCE' for r in result['rejected_paths'])


def test_evidence_hash_cannot_select_an_execution_target():
    result=model(HASH+'\nimport subprocess\ncommand=file_hash(Path(root)/"state.csv")\nsubprocess.run([command])\n')
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(result,'state.csv'))


def test_evidence_hash_cannot_select_configuration_path():
    result=model(HASH+'\nconfiguration=Path(file_hash(Path(root)/"selector.db")).read_text()\n')
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(result,'selector.db'))


def test_fixed_cli_mode_does_not_analyze_unrelated_interactive_authority():
    source='''from pathlib import Path
import os
def main(args):
    if args.command=='scout':
        return 0
    elif args.command=='interactive-owner':
        return Path(os.environ['PRIVATE_KEY']).read_bytes()
'''
    observer="def scout():\n    return main(['scout','--root',str(ROOT)])\n"
    result=a.path_references(Path('/reviewed'),{'dev_agent/cli.py':source,'ops/discovery/observer.py':observer})
    assert result['ambiguous']==[]
    # Without a reviewed fixed entry mode, the authority remains unresolved.
    assert a.path_references(Path('/reviewed'),{'dev_agent/cli.py':source})['ambiguous']


def test_helper_names_do_not_grant_a_readonly_or_denial_privilege():
    dangerous=HASH.replace('file_hash','denied')+'\nvalue=denied(Path(root)/"data.bin")\n'
    result=model(dangerous)
    assert uses(result,'data.bin')[0]['reads_contents'] is True
    assert uses(result,'data.bin')[0]['operation']!='denied'
    harmless=DENIED.replace('denied','permission_check')+'\nvalue=permission_check(Path(root)/"data.bin")\n'
    result=model(harmless)
    assert uses(result,'data.bin')[0]['operation']=='permission_probe'
    assert uses(result,'data.bin')[0]['reads_contents'] is False


def test_hashing_cannot_hide_writes_or_unknown_side_effects():
    source=HASH.replace('return hashlib','path.write_text("changed")\n    return hashlib')+'\nvalue=file_hash(Path(root)/"data.csv")\n'
    assert any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses(model(source),'data.csv'))


def test_evidence_sandbox_denies_credential_content_reads_generically():
    sandbox=dict(repo_read_only=True,scout_denied=['/reviewed/private'],observer_denied=['/reviewed/private'])
    uses_=[dict(usage='PROTECTED_RUNTIME_EVIDENCE',operation='file_hash',reads_contents=True)]
    assert not a.evidence_proof(Path('/reviewed'),'private/secret.dat',uses_,sandbox)['verified']
    uses_=[dict(usage='PROTECTED_RUNTIME_EVIDENCE',operation='denied',reads_contents=False)]
    assert a.evidence_proof(Path('/reviewed'),'private/secret.dat',uses_,sandbox)['verified']


def test_unknown_recovery_cli_mode_cannot_hide_behind_other_fixed_unit_mode():
    source={'dev_agent/cli.py':'def main(args): pass\n','ops/discovery/observer.py':'def scout(argv):\n    return main(argv)\n'}
    result=a.path_references(Path('/reviewed'),source,cli_modes={'scheduler-status'})
    assert result['ambiguous'][0]['reason']=='UNRESOLVED_CLI_ENTRY_MODE'


def test_unbounded_recursive_path_summary_fails_closed():
    source='def recursive(path):\n    value=path.read_text()\n    recursive(path/"child")\n'
    with pytest.raises(ValueError,match='convergence bound'):model(source)


def test_unresolved_library_configuration_effect_reaches_recovery_caller():
    sources={'dev_agent/cli.py':'from library import configuration\nvalue=configuration()\n',
             'library.py':'from pathlib import Path\nimport os\ndef configuration():\n    return Path(os.environ["CONFIG"]).read_text()\n'}
    result=a.path_references(Path('/reviewed'),sources)
    assert result['ambiguous']


def test_rooted_library_parameter_retains_dynamic_authority_at_callsite():
    sources={'dev_agent/cli.py':'from library import configuration\nimport os\nvalue=configuration(root,os.environ["CONFIG"])\n',
             'library.py':'from pathlib import Path\ndef configuration(root,name):\n    return (Path(root)/name).read_text()\n'}
    assert a.path_references(Path('/reviewed'),sources)['ambiguous']


@pytest.mark.parametrize('suffix',['json','db','csv','env'])
def test_runtime_location_cannot_override_authority_usage(repo,suffix):
    root,_=repo
    name='out/discovery.'+suffix
    head=commit_reader(root,'from pathlib import Path\nconfiguration=(Path(root)/"'+name+'").read_text()\n')
    add(root,name)
    result=a.audit(root,head)
    assert {'path':name,'reason':'REVIEWED_SOURCE_REFERENCE'} in result['rejected_paths']


def test_command_sequence_concatenation_is_not_a_filesystem_join():
    source='''import subprocess
def output(root,*args):
    prefix=['/usr/bin/git','-C',str(root)]
    return subprocess.run(prefix+list(args))
value=output(root,'ls-tree','HEAD')
'''
    assert model(source)['ambiguous']==[]


def test_dynamic_filesystem_join_remains_ambiguous():
    source='''from pathlib import Path
import os
value=(Path(root)/('config/'+os.environ['POLICY'])).read_text()
'''
    assert model(source)['ambiguous']


def test_runtime_location_does_not_bypass_evidence_sandbox_requirements(repo):
    root,_=repo
    head=commit_reader(root,HASH+'\nvalue=file_hash(Path(root)/"out/state.csv")\n',scout='[Service]\n')
    add(root,'out/state.csv')
    assert {'path':'out/state.csv','reason':'PROTECTED_EVIDENCE_SANDBOX_UNPROVEN'} in a.audit(root,head)['rejected_paths']


def test_comprehension_scopes_cannot_mix_evidence_and_configuration_paths():
    result=model(HASH+'\nROOT=Path("/reviewed")\na=[file_hash(p) for p in [ROOT/"state.csv"]]\nb=[p.read_text() for p in [ROOT/"policy.json"]]\n')
    assert {r['usage'] for r in uses(result,'state.csv')}=={'PROTECTED_RUNTIME_EVIDENCE'}
    assert {r['usage'] for r in uses(result,'policy.json')}=={'SOURCE_OR_EXECUTION_AUTHORITY'}
