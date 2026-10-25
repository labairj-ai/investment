"""Discovery consumes exact Git blobs; whole-worktree safety stays conservative."""
import json
import subprocess
from pathlib import Path
import pytest
from dev_agent import discovery,policy,scheduler,reviewed_source as rs
from dev_agent.store import Store
from test_development_agent import repo,commit,proposal


def add(root,name,text):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p


def test_untracked_architecture_source_and_context_cannot_change_scout(repo):
    add(repo,'tracked.py','# FIXME: Validate reviewed metadata before parsing\n')
    add(repo,'.todos/1000-reviewed.md','- **Status:** backlog\n')
    add(repo,'.todos/done/0999-reviewed.md','- **Status:** done\n')
    head=commit(repo);view=rs.reviewed_sources(repo,head);before=discovery.scout(repo,cap=10)
    duplicate='def duplicate():\n'+''.join(f'    a{i} = {i}\n' for i in range(6))
    add(repo,'agents/evil.py','import orchestrator\n'+duplicate)
    add(repo,'orchestrator.py','import agents.evil\n'+duplicate+'# TODO: Untracked architecture must not become authority\n'*8)
    add(repo,'tests/test_untracked.py','import agents.evil\n')
    add(repo,'.todos/9999-untracked.md','- **Status:** in-progress\n')
    add(repo,'.todos/done/9998-untracked.md','- **Status:** done\n')
    after=rs.reviewed_sources(repo,head)
    assert after.identity==view.identity and after.graph(repo)==view.graph(repo)
    assert discovery.scout(repo,cap=10)==before
    assert all('untracked' not in x['path'] for x in before['context']['active_todos'])
    assert before['context']['recent_completed']==['.todos/done/0999-reviewed.md']


def test_committed_source_changes_architecture_and_todo_analysis(repo):
    before=discovery.architecture_signals(repo)
    add(repo,'a.py','import b\n# FIXME: Handle malformed reviewed source explicitly\n')
    add(repo,'b.py','import a\n')
    # Files on disk alone have no production-discovery authority.
    assert discovery.architecture_signals(repo)==before
    head=commit(repo)
    after=discovery.architecture_signals(repo)
    assert any(x['files']==['a.py','b.py'] for x in after)
    assert any(p['source']=='todo' and p['evidence'][0].startswith(head+':a.py:') for p in discovery.scout(repo,cap=10)['proposals'])


def test_duplicate_exception_and_debt_analysis_use_same_blobs(repo):
    text='def duplicate():\n'+''.join(f'    a{i} = {i}\n' for i in range(6))
    add(repo,'one.py',text);add(repo,'two.py',text)
    large='\n'.join('try:\n    pass\nexcept ValueError:\n    pass' for _ in range(11))+'\n'+'# debt\n'*1600
    add(repo,'large.py',large);head=commit(repo)
    before=discovery.architecture_signals(repo)
    assert any(x['files']==['one.py','two.py'] for x in before)
    assert any(x['files']==['large.py'] for x in before)
    add(repo,'one.py','# changed only working tree\n');add(repo,'large.py','')
    assert discovery.architecture_signals(repo)==before
    assert rs.reviewed_sources(repo,head).texts['one.py']==text


def test_scheduler_scores_and_candidate_identity_ignore_untracked_orchestrator(repo,tmp_path,monkeypatch):
    add(repo,'agents/advisor/reviewed.py','import orchestrator\n');head=commit(repo)
    signal=proposal(files=['tests/test_oracle.py'])
    monkeypatch.setattr(scheduler,'trigger',lambda:dict(source='operator',invocation=None))
    def run(name):
        store=Store(tmp_path/name/'development-control.sqlite3');store.migrate()
        result=scheduler.discover_daily(repo,store,cap=1,signals=[signal])
        assert result['status']=='COLLECTED' and result['head']==head
        with store.connect() as db:identities=[r[0] for r in db.execute('SELECT identity FROM dev_candidates ORDER BY identity')]
        scores=[e['payload'] for e in store.events('SCORE')]
        return identities,scores
    before=run('before')
    add(repo,'orchestrator.py','import tests.test_oracle\n')
    add(repo,'tests/untracked.py','import tests.test_oracle\n')
    assert run('after')==before
    assert before[1][0]['risk']['risk']=='L1'
    # Conservative candidate/worktree safety still includes the untracked bridge.
    whole=policy.protected_graph(repo)
    reviewed=rs.reviewed_sources(repo,head).graph(repo)
    assert 'orchestrator.py' in whole and 'orchestrator.py' not in reviewed
    assert policy.classify(['tests/test_oracle.py'],graphs=[whole])['risk']=='L4'
    assert policy.classify(['tests/test_oracle.py'],graphs=[reviewed])['risk']=='L1'


def test_working_tree_policy_and_todo_symlink_cannot_replace_reviewed_context(repo,tmp_path):
    add(repo,'.todos/1000-reviewed.md','- **Status:** backlog\n');head=commit(repo)
    before=discovery.scout(repo)
    outside=tmp_path/'outside.md';outside.write_text('- **Status:** in-progress\nUNREVIEWED\n')
    p=repo/'.todos/1000-reviewed.md';p.unlink();p.symlink_to(outside)
    cfg=json.loads((repo/'config/development_agent.json').read_text());cfg['architecture_exclusions']={'bad':{}}
    (repo/'config/development_agent.json').write_text(json.dumps(cfg))
    assert discovery.scout(repo)==before
    assert rs.reviewed_sources(repo,head).configuration().get('architecture_exclusions',{})=={}


@pytest.mark.parametrize('head',['HEAD','a'*39,'A'*40,'0'*40])
def test_head_must_be_exact_current_reviewed_commit(repo,head):
    with pytest.raises(ValueError):rs.reviewed_sources(repo,head)


def test_reviewed_inventory_bounds(repo,monkeypatch):
    head=discovery.git(repo,'rev-parse','HEAD')
    for name,value in [('MAX_FILES',1),('MAX_TREE_BYTES',10),('MAX_FILE_BYTES',1),('MAX_SOURCE_BYTES',1)]:
        with monkeypatch.context() as m:
            m.setattr(rs,name,value)
            with pytest.raises(ValueError,match='bounded'):rs.reviewed_sources(repo,head)


def test_duplicate_and_noncanonical_git_paths_rejected(repo,monkeypatch):
    head=discovery.git(repo,'rev-parse','HEAD');real=rs.output
    tree=real(repo,'--no-replace-objects','ls-tree','-rz','--full-tree',head,text=False)
    row=tree.split(b'\0')[0]
    monkeypatch.setattr(rs,'output',lambda root,*a,**k:row+b'\0'+row+b'\0' if 'ls-tree' in a else real(root,*a,**k))
    with pytest.raises(ValueError,match='unique'):rs.reviewed_sources(repo,head)
    monkeypatch.setattr(rs,'output',real)
    add(repo,'bad\\name.py','pass\n');head=commit(repo)
    with pytest.raises(ValueError,match='canonical'):rs.reviewed_sources(repo,head)


def test_tracked_symlink_rejected_without_reading_target(repo,tmp_path):
    outside=tmp_path/'outside.py';outside.write_text('raise RuntimeError("must not execute")\n')
    (repo/'link.py').symlink_to(outside);head=commit(repo)
    with pytest.raises(ValueError,match='regular reviewed'):rs.reviewed_sources(repo,head)


def test_git_replace_cannot_substitute_reviewed_bytes(repo):
    add(repo,'tracked.py','# FIXME: Preserve the reviewed source identity\n');old=commit(repo)
    expected=rs.reviewed_sources(repo,old).texts['tracked.py']
    add(repo,'tracked.py','# unreviewed replacement\n');other=commit(repo)
    subprocess.run(['git','-C',str(repo),'update-ref','HEAD',old],check=True)
    subprocess.run(['git','-C',str(repo),'replace',old,other],check=True)
    assert rs.reviewed_sources(repo,old).texts['tracked.py']==expected


def test_dirty_source_stays_out_of_analysis_but_observer_rejects_it(repo,monkeypatch):
    import hashlib
    from ops.discovery import observer
    p=add(repo,'reviewed.py','pass\n');head=commit(repo)
    expected=hashlib.sha256(p.read_bytes()).hexdigest()
    add(repo,'reviewed.py','# dirty working-tree metadata\n')
    assert rs.reviewed_sources(repo,head).texts['reviewed.py']=='pass\n'
    monkeypatch.setattr(observer,'ROOT',repo)
    with pytest.raises(ValueError,match='reviewed discovery source changed'):
        observer.snapshot(dict(files={'reviewed.py':expected},head=head))
