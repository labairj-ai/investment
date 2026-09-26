"""Exercise the generated news renderer with untrusted model/source text."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node unavailable')
def test_portfolio_renderer_groups_evidence_and_escapes_untrusted_content():
    template = (Path(__file__).resolve().parents[1]/'generate_dashboard.py').read_text()
    script = template[template.index('  function _newsEscape('):template.index('  function _renderBrief(')]
    script = script.replace('{{','{').replace('}}','}')
    analysis = {'insights':[{'kind':'risk','title':'<img src=x onerror=alert(1)>',
        'tickers':['AAA','BBB'],'exposure_pct':19,'what_changed':'Reported fact',
        'portfolio_impact':'Funding costs could pressure cash generation.',
        'watch_or_action':'Review debt maturity schedule.', 'source_ids':['bad','good'],
        'evidence_level':'Reported facts · impact is analysis'}],
        'sources':{'bad':{'title':'Unsafe link','url':'javascript:alert(1)'},
                   'good':{'title':'Official source','url':'https://example.com/?a=1&b=2'}},
        'context_status':{'policy_count':0,'limitations':['Stale observations excluded.']}}
    script += '\nconst h=_renderPortfolioAnalysis('+json.dumps(analysis)+');\n'+'''
const assert=require('node:assert/strict');
for (const text of ['Risks','Opportunities','Legislative & policy watch','19.0% of portfolio',
                    'AAA, BBB','Funding costs','Review debt maturity','Stale observations excluded.']) assert.ok(h.includes(text),text);
assert.ok(h.includes('&lt;img'));
assert.ok(!h.includes('<img'));
assert.ok(!h.includes('javascript:'));
assert.ok(h.includes('href="https://example.com/?a=1&amp;b=2"'));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
