"""An open page must recover after quote refresh without reload or mutations."""
import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'static/portfolio_valuation.js').read_text()


def node(body):
    prelude='''
const assert = require('node:assert/strict');
const nodes = {'kpi-net-value':{},'kpi-gross-value':{},'kpi-net-status':{}};
global.document={getElementById:id=>nodes[id]};
const now=Date.parse('2026-11-05T16:10:00Z');
const report={complete:true,net_value:9100,gross_stock_value:10000,open_count:1,priced_count:1,
 session:'2026-11-05',observations:['2026-11-05T16:05:00Z'],issues:[],valid_until:'2026-11-05T16:35:00Z'};
const data={totalValue:null,valuation:{complete:false,net_value:null}};
'''
    result=subprocess.run(['node','-e',JS+prelude+'\n'+body],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_fresh_data_restores_expired_headline_and_shared_goal_value_without_reload():
    node('''
assert(applyPortfolioValuation(data,report,now));
assert.equal(data.totalValue,9100);
assert.equal(data.grossStockValue,10000);
assert.equal(nodes['kpi-net-value'].textContent,'$9,100.00');
assert(nodes['kpi-net-status'].textContent.includes('1/1 open calls priced'));
assert(expirePortfolioValuation(data,Date.parse('2026-11-05T16:36:00Z')));
assert.equal(data.totalValue,null);
const next={...report,complete:true,net_value:9000,valid_until:'2026-11-05T17:00:00Z'};
assert(applyPortfolioValuation(data,next,Date.parse('2026-11-05T16:36:00Z')));
assert.equal(data.totalValue,9000);
assert.equal(nodes['kpi-net-value'].textContent,'$9,000.00');
''')


def test_an_expired_server_snapshot_cannot_restore_a_stale_value():
    node('''
assert(applyPortfolioValuation(data,report,Date.parse('2026-11-05T16:36:00Z')));
assert.equal(data.totalValue,null);
assert.equal(nodes['kpi-net-value'].textContent,'Unavailable');
''')


@pytest.mark.parametrize('bad',[
    'null','{...report,net_value:null}','{...report,open_count:2}',
    '{...report,observations:"bad"}','{...report,valid_until:null}',
    '{...report,priced_count:-1}',
])
def test_malformed_snapshots_do_not_partially_mutate_the_page(bad):
    node(f"assert.equal(applyPortfolioValuation(data,{bad},now),false); assert.equal(data.totalValue,null);")


def test_poll_uses_read_only_snapshot_and_a_failed_fetch_keeps_existing_state():
    node('''
Date.now=()=>now;
let calls=0;
global.fetch=async(url,options)=>{
 assert.equal(url,'/api/portfolio-valuation');assert.equal(options.cache,'no-store');
 assert.equal(options.method,undefined);calls++;
 return {ok:true,json:async()=>({ok:true,valuation:report})};
};
(async()=>{
 assert(await pullPortfolioValuation(data));assert.equal(data.totalValue,9100);assert.equal(calls,1);
 global.fetch=async()=>{throw Error('offline');};
 assert.equal(await pullPortfolioValuation(data),false);assert.equal(data.totalValue,9100);
 assert(expirePortfolioValuation(data,Date.parse('2026-11-05T16:36:00Z')));
 assert.equal(data.totalValue,null);
})().catch(error=>{console.error(error);process.exit(1);});
''')


def test_main_publishes_complete_atomic_snapshot_and_html_only_in_fixture(tmp_path,monkeypatch):
    import generate_dashboard as dashboard
    report=dict(complete=True,net_value=9100.,gross_stock_value=10000.)
    monkeypatch.setattr(dashboard,'OUT_PATH',tmp_path/'dashboard.html')
    monkeypatch.setattr(dashboard,'load_data',lambda:([],[],[]))
    monkeypatch.setattr(dashboard,'build_dashboard',lambda *a,**kw:('<html>fixture</html>',report))
    dashboard.main()
    assert (tmp_path/'dashboard.html').read_text()=='<html>fixture</html>'
    assert json.loads((tmp_path/'portfolio-valuation.json').read_text())==report
    assert set(p.name for p in tmp_path.iterdir())=={'dashboard.html','portfolio-valuation.json'}


def test_failed_atomic_replacement_preserves_previous_snapshot(tmp_path,monkeypatch):
    import generate_dashboard as dashboard
    path=tmp_path/'snapshot.json';path.write_text('original')
    def fail(*a):raise OSError('fixture replace failure')
    monkeypatch.setattr(dashboard.os,'replace',fail)
    with pytest.raises(OSError):dashboard._atomic_dashboard_write(path,'new')
    assert path.read_text()=='original'
    assert list(tmp_path.iterdir())==[path]


def test_snapshot_route_only_reads_the_fixed_generated_artifact(tmp_path):
    # Execute only the relevant branch from do_GET, with a fixture response object.
    tree=ast.parse((ROOT/'serve.py').read_text())
    target=None
    for item in ast.walk(tree):
        if isinstance(item,ast.If) and isinstance(item.test,ast.Compare):
            if any(isinstance(v,ast.Constant) and v.value=='/api/portfolio-valuation' for v in item.test.comparators):
                target=item;break
    assert target is not None
    node_ast=ast.Module(body=target.body,type_ignores=[]);ast.fix_missing_locations(node_ast)
    output=[]
    handler=SimpleNamespace(_json=lambda v:output.append(v),_json_error=lambda *v:output.append(v))
    scope=dict(PROJECT_DIR=tmp_path,json=json,self=handler)
    exec(compile(node_ast,'fixture-route','exec'),scope)
    assert output==[(503,'Valuation snapshot unavailable')]
    (tmp_path/'out').mkdir();(tmp_path/'out'/'portfolio-valuation.json').write_text('{"complete":false,"net_value":null}')
    output.clear();exec(compile(node_ast,'fixture-route','exec'),scope)
    assert output==[dict(ok=True,valuation=dict(complete=False,net_value=None))]
