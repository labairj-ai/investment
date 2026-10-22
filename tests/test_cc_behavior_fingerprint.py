"""0730: independent named mutation, completeness and release-boundary evidence."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import covered_call_fingerprint as fp
import covered_call_change_control as cc
from strategy_config import CC_V3_CONFIG
from test_cc_adversarial_release import _make_manifest

EXPECTED = json.loads(Path(__file__).with_name('fixtures').joinpath('cc_behavior_inventory_v1.json').read_text())


class MutatedSource(fp.SourceCatalog):
    def __init__(self, target=None, constant=False):
        super().__init__()
        self.target=target
        self.constant=constant

    def node(self, identifier):
        node=super().node(identifier)
        if identifier==self.target and not self.constant:
            node=deepcopy(node)
            marker=ast.parse('raise RuntimeError("controlled behavior mutation")').body[0]
            node.body.insert(0,marker)
        return node

    def value(self, identifier):
        value=super().value(identifier)
        return mutate(value) if identifier==self.target and self.constant else value


def mutate(value):
    if type(value) is bool:return not value
    if isinstance(value,(float,int)):return value+0.125
    if isinstance(value,str):return value+'-mutation'
    if isinstance(value,dict):return dict(value, controlled_mutation=True)
    if isinstance(value,(list,tuple)):return [*value,'controlled-mutation']
    if value is None:return 'controlled-mutation'
    raise AssertionError('unhandled test fixture constant type')


@pytest.mark.parametrize('side,name', [(side,name) for side in ('model','simulator')
                                       for name in EXPECTED[side]['functions']+EXPECTED[side]['types']])
def test_every_named_function_and_type_contributes_and_restores(side,name):
    generate=getattr(fp,side+'_fingerprint')
    source=MutatedSource()
    before=generate(CC_V3_CONFIG,source)
    source.target=name
    assert generate(CC_V3_CONFIG,source)!=before,name
    source.target=None
    assert generate(CC_V3_CONFIG,source)==before,name


@pytest.mark.parametrize('side,name', [(side,name) for side in ('model','simulator') for name in EXPECTED[side]['constants']])
def test_every_named_constant_contributes_and_restores(side,name):
    generate=getattr(fp,side+'_fingerprint')
    source=MutatedSource(constant=True)
    before=generate(CC_V3_CONFIG,source)
    source.target=name
    assert generate(CC_V3_CONFIG,source)!=before,name
    source.target=None
    assert generate(CC_V3_CONFIG,source)==before,name


@pytest.mark.parametrize('side,key', [(side,key) for side in ('model','simulator') for key in EXPECTED[side]['config_keys']])
def test_every_config_key_contributes(side,key):
    generate=getattr(fp,side+'_fingerprint')
    changed=deepcopy(CC_V3_CONFIG)
    path=key.split('.');parent=changed
    for part in path[:-1]:parent=parent[part]
    parent[path[-1]]=mutate(parent[path[-1]])
    assert generate(changed)!=generate(CC_V3_CONFIG),key
    assert generate(CC_V3_CONFIG)==generate(deepcopy(CC_V3_CONFIG))


def test_independent_inventory_and_all_guarded_functions_classified():
    actual=fp.inventory()
    for side in ('model','simulator'):
        assert actual[side]==EXPECTED[side]
    assert fp.classification_findings()==[]


def test_removed_required_registry_function_fails_completeness():
    removed=tuple(name for name in fp.MODEL_BEHAVIOR_FUNCTIONS if name!='covered_call_v3.utility')
    assert 'UNCLASSIFIED_FUNCTION: covered_call_v3.utility' in fp.classification_findings(model=removed)
    assert set(removed)!=set(EXPECTED['model']['functions'])


def test_unclassified_addition_requires_deliberate_classification(monkeypatch):
    source=fp.SourceCatalog()
    original=source.tree
    def tree(module):
        result=original(module)
        if module=='covered_call_v3':
            result=deepcopy(result)
            result.body += ast.parse('def new_helper(): return 1').body
        return result
    monkeypatch.setattr(source,'tree',tree)
    assert 'UNCLASSIFIED_FUNCTION: covered_call_v3.new_helper' in fp.classification_findings(source)
    exclusions=dict(fp.NONBEHAVIORAL_FUNCTIONS, **{'covered_call_v3.new_helper':'Explicit fixture rendering helper.'})
    assert fp.classification_findings(source,exclusions=exclusions)==[]
    assert fp.model_fingerprint(CC_V3_CONFIG,source)==fp.model_fingerprint(CC_V3_CONFIG)


@pytest.mark.parametrize('names', [('covered_call_v3.utility','covered_call_v3.utility'), ('missing',), ('covered_call_v3.not_present',), ('',)])
def test_invalid_missing_duplicate_canonical_components_reject(names):
    with pytest.raises(ValueError):
        fp.fingerprint_payload(CC_V3_CONFIG,names,(),(),())


def test_registry_order_is_canonical_and_repeated_generation_deterministic():
    for side in ('model','simulator'):
        functions=getattr(fp,side.upper()+'_BEHAVIOR_FUNCTIONS')
        constants=getattr(fp,side.upper()+'_BEHAVIOR_CONSTANTS')
        types=getattr(fp,side.upper()+'_BEHAVIOR_TYPES')
        keys=getattr(fp,side.upper()+'_CONFIG_KEYS')
        original=fp.fingerprint_payload(CC_V3_CONFIG,functions,constants,types,keys)
        reversed_payload=fp.fingerprint_payload(CC_V3_CONFIG,functions[::-1],constants[::-1],types[::-1],keys[::-1])
        assert fp.stable_digest(original)==fp.stable_digest(reversed_payload)
        assert fp.stable_digest(original)==getattr(fp,side+'_fingerprint')(CC_V3_CONFIG)
        assert '/Users/' not in json.dumps(original)
        assert '0x7f' not in json.dumps(original)


def test_runtime_monkeypatch_objects_do_not_enter_source_hash(monkeypatch):
    import covered_call_v3
    before=fp.model_fingerprint(CC_V3_CONFIG)
    monkeypatch.setattr(covered_call_v3,'utility',lambda *args: object())
    monkeypatch.setattr(covered_call_v3,'N',object())
    assert fp.model_fingerprint(CC_V3_CONFIG)==before


def test_nonbehavioral_source_comments_docs_and_files_stay_stable(tmp_path,monkeypatch):
    source=fp.SourceCatalog()
    original=source.text
    def changed(relative):
        text=original(relative)
        if relative=='covered_call_v3.py':
            return '# different comment\n'+text.replace('Daily GBM + Brownian bridge','Documentation-only revised GBM + Brownian bridge')
        if relative=='covered_call_rec.py':
            tree=deepcopy(ast.parse(text))
            for node in tree.body:
                if isinstance(node,ast.FunctionDef) and node.name=='print_report':
                    node.body=ast.parse('print("new dashboard/report formatting")').body
            return ast.unparse(tree)
        return text
    monkeypatch.setattr(source,'text',changed)
    for side in ('model','simulator'):
        generate=getattr(fp,side+'_fingerprint')
        assert generate(CC_V3_CONFIG,source)==generate(CC_V3_CONFIG)
    for name in ('README.md','dashboard.py','.todos/done/0730.md'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Nonbehavioral edit')
    # Standalone artifact names never appear in the named source inventory.
    assert all(name.split('.')[0] not in ('README','dashboard') for side in ('model','simulator') for name in EXPECTED[side]['functions'])


def test_irrelevant_config_and_flat_wrapped_equivalence():
    for side in ('model','simulator'):
        generate=getattr(fp,side+'_fingerprint')
        assert generate(dict(CC_V3_CONFIG,dashboard_copy='new',config_version='display-only'))==generate(CC_V3_CONFIG)
        assert generate({'cc_v3':CC_V3_CONFIG})==generate(CC_V3_CONFIG)
    with pytest.raises(ValueError,match='mixed'):
        fp.simulator_fingerprint(dict(CC_V3_CONFIG,cc_v3={'fill_prior':99}))


@pytest.mark.parametrize('target,versions', [
    ('covered_call_v3.utility',{'model_version':'cc-v3.4'}),
    ('covered_call_virtual.advance',{'simulator_contract_version':'simulator-contract-3'}),
    ('covered_call_v3.execution',{'model_version':'cc-v3.4','simulator_contract_version':'simulator-contract-3'}),
])
def test_real_fingerprint_mutations_require_exact_component_release(tmp_path,monkeypatch,target,versions):
    prior=cc.current_contract_state(CC_V3_CONFIG)
    source=MutatedSource(target)
    proposed=dict(prior,engine_hash=fp.model_fingerprint(CC_V3_CONFIG,source),
                  simulator_contract_hash=fp.simulator_fingerprint(CC_V3_CONFIG,source))
    pf=tmp_path/'prior.json';bf=tmp_path/'candidate.json';md=tmp_path/'manifests';md.mkdir()
    pf.write_text(json.dumps(dict(prior,schema_version=cc.BASELINE_SCHEMA_VERSION)))
    monkeypatch.setattr(cc,'current_contract_state',lambda cfg:proposed)
    def check():
        bf.write_text(json.dumps(dict(proposed,schema_version=cc.BASELINE_SCHEMA_VERSION)))
        return cc.check_contract_consistency(CC_V3_CONFIG,_baseline_file=bf,trusted_prior_file=pf,_manifests_dir=md)
    assert not check()['ok']  # matching candidate cannot erase source drift
    proposed.update(versions)
    assert not check()['ok']  # correct versions alone cannot authorize
    _make_manifest(md,prior,proposed)
    assert check()['ok'],check()['findings']
    if len(versions)>1:
        proposed['model_version']=prior['model_version']
        assert not check()['ok']


def test_definition_implementation_mutation_is_release_visible():
    source=MutatedSource('covered_call_fingerprint.canonical_node')
    assert fp.model_fingerprint(CC_V3_CONFIG,source)!=fp.model_fingerprint(CC_V3_CONFIG)
    assert fp.simulator_fingerprint(CC_V3_CONFIG,source)!=fp.simulator_fingerprint(CC_V3_CONFIG)


@pytest.fixture
def definition_transition(tmp_path,monkeypatch):
    root=fp.ROOT
    repo=tmp_path/'repo';repo.mkdir()
    modules={name.rsplit('.',1)[0] for side in ('model','simulator')
             for key in ('functions','types','constants') for name in EXPECTED[side][key]}
    modules.add('strategy_config')
    for relative in [*(module.replace('.','/')+'.py' for module in modules),'config/strategy.json']:
        target=repo/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/relative,target)
    virtual=repo/'covered_call_virtual.py'
    tree=ast.parse(virtual.read_text())
    legacy=ast.parse(Path(__file__).with_name('fixtures').joinpath('cc_fingerprint_legacy_virtual.py').read_text())
    replacements={n.name:n for n in legacy.body if isinstance(n,ast.FunctionDef)}
    tree.body=[replacements.get(n.name,n) if isinstance(n,ast.FunctionDef) else n for n in tree.body]
    if not any(isinstance(n,ast.Import) and any(a.name=='inspect' for a in n.names) for n in tree.body):
        tree.body.insert(1,ast.Import(names=[ast.alias(name='inspect',asname=None)]))
    virtual.write_text(ast.unparse(tree))
    old=fp.legacy_contract_state(fp.SourceCatalog(repo),CC_V3_CONFIG)
    (repo/'.cc_contract_baseline.json').write_text(json.dumps(dict(old,schema_version=cc.LEGACY_BASELINE_SCHEMA_VERSION)))
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=repo,text=True,stderr=subprocess.DEVNULL).strip()
    git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.com')
    git('add','.');git('commit','-m','legacy source authority');prior_sha=git('rev-parse','HEAD')
    prior=cc.baseline_at_ref(prior_sha,repo)
    for module in modules|{'covered_call_fingerprint'}:
        relative=module.replace('.','/')+'.py'
        (repo/relative).parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/relative,repo/relative)
    md=repo/'cc_change_manifests';md.mkdir()
    current=dict(cc.current_contract_state(CC_V3_CONFIG))
    monkeypatch.setattr(cc,'current_contract_state',lambda cfg:current)
    def check():
        provider=fp.SourceCatalog(repo)
        current.update(engine_hash=fp.model_fingerprint(CC_V3_CONFIG,provider),
                       simulator_contract_hash=fp.simulator_fingerprint(CC_V3_CONFIG,provider))
        (repo/'.cc_contract_baseline.json').write_text(json.dumps(dict(current,schema_version=cc.BASELINE_SCHEMA_VERSION)))
        _make_manifest(md,prior,current,category='EVIDENCE_INFRASTRUCTURE')
        path=md/'test-manifest.md'
        path.write_text(path.read_text().replace('manifest_id:', 'fingerprint_migration: legacy-to-named-v1\nmanifest_id:',1))
        return cc.check_contract_consistency(CC_V3_CONFIG,_baseline_file=repo/'.cc_contract_baseline.json',
                                             prior_ref=prior_sha,repo=repo,_manifests_dir=md)
    return repo,current,prior,prior_sha,check


def test_source_proven_definition_migration_keeps_runtime_versions(definition_transition):
    repo,current,prior,sha,check=definition_transition
    result=check()
    assert result['ok'],result['findings']
    assert result['fingerprint_definition_migration']
    assert not result['version_bumped']
    assert all(prior[k]==current[k] for k in cc.VERSION_PATTERNS)


def test_definition_migration_cannot_hide_actual_behavior_edit(definition_transition):
    repo,current,prior,sha,check=definition_transition
    path=repo/'covered_call_v3.py';tree=ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name=='utility':
            node.body.insert(0,ast.parse('raise RuntimeError("behavior change")').body[0])
    path.write_text(ast.unparse(tree))
    result=check()  # exact rewritten candidate AND exact rewritten migration manifest
    assert not result['ok']
    assert not result['fingerprint_definition_migration']
    assert any('UNAUTHORIZED_FINGERPRINT_DEFINITION_CHANGE' in f for f in result['findings'])


def test_definition_migration_cannot_authorize_runtime_version_change(definition_transition):
    repo,current,prior,sha,check=definition_transition
    current['model_version']='cc-v3.4'
    assert not check()['fingerprint_definition_migration']
    assert not check()['ok']


def test_definition_migration_requires_trusted_git_source(definition_transition):
    repo,current,prior,sha,check=definition_transition
    assert check()['ok']
    prior_file=repo/'prior.json';prior_file.write_text(json.dumps(prior))
    result=cc.check_contract_consistency(CC_V3_CONFIG,_baseline_file=repo/'.cc_contract_baseline.json',
                                       trusted_prior_file=prior_file,_manifests_dir=repo/'cc_change_manifests')
    assert not result['ok']
    assert any('immutable prior Git source' in f for f in result['findings'])


def test_cli_inventory_reports_all_canonical_component_names():
    import os,sys
    result=subprocess.run([sys.executable,str(fp.ROOT/'scripts/check_cc_contract.py'),
                           '--fingerprint-inventory','--json'],cwd=fp.ROOT,
                          env=dict(os.environ,GITHUB_ACTIONS='false',CI='false'),
                          capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(result.stdout)['fingerprint_inventory']
    assert data['model']==EXPECTED['model']
    assert data['simulator']==EXPECTED['simulator']


@pytest.mark.parametrize('statement', ['utility = lambda *args: 999', 'utility.__defaults__ = (999,)', 'globals()["utility"] = lambda *args: 999', 'if True:\n    utility = lambda *args: 999'])
def test_module_initialization_cannot_hide_function_replacement(monkeypatch,statement):
    source=fp.SourceCatalog();original=source.tree
    def tree(module):
        parsed=original(module)
        if module=='covered_call_v3':
            parsed=deepcopy(parsed);parsed.body+=ast.parse(statement).body
        return parsed
    monkeypatch.setattr(source,'tree',tree)
    with pytest.raises(ValueError,match='REBOUND_BEHAVIOR_COMPONENT|UNCLASSIFIED_INITIALIZER'):
        fp.model_fingerprint(CC_V3_CONFIG,source)


def test_constant_source_loader_changes_are_visible(monkeypatch):
    source=fp.SourceCatalog();original=source.tree
    def tree(module):
        parsed=original(module)
        if module=='strategy_config':
            parsed=deepcopy(parsed)
            for item in parsed.body:
                if isinstance(item,ast.Assign) and any(isinstance(n,ast.Name) and n.id=='_cfg' for n in item.targets):
                    item.value=ast.parse('dict(controlled_loader_change=True)',mode='eval').body
        return parsed
    monkeypatch.setattr(source,'tree',tree)
    # Constant value resolver is static; source provenance still closes loader drift.
    assert fp.model_fingerprint(CC_V3_CONFIG,source)!=fp.model_fingerprint(CC_V3_CONFIG)
    assert fp.simulator_fingerprint(CC_V3_CONFIG,source)!=fp.simulator_fingerprint(CC_V3_CONFIG)
