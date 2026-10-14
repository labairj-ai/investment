"""Exercise the tracker chart callbacks with signed income and hidden series."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_signed_stacks_labels_tooltips_and_responsive_layout():
    if not shutil.which('node'):
        pytest.skip('node is required for dashboard JavaScript execution')
    source = (ROOT / 'generate_dashboard.py').read_text()
    start = source.index('      const monthData = {{}};', source.index('function renderCCPositions'))
    end = source.index('    }})();', start)
    js = source[start:end].replace('{{', '{').replace('}}', '}')
    harness = r'''
const assert = require('assert');
const otherClosed = [{closed_date:'2026-10-12',net_premium:-497}];
const expiredPos = [{expiry:'2026-10-09',net_premium:27}];
const open = [{opened_date:'2026-10-12',premium_per_contract:10,contracts:1}];
const window = {};
const document = {getElementById: () => ({})};
let spec;
const Chart = function(element, options) {spec=options;};
'''
    checks = r'''
assert.deepStrictEqual(spec.data.labels, ["Oct '26"]);
assert.deepStrictEqual(spec.data.datasets.map(d=>d.data[0]), [27,-497,1000]);
assert.strictEqual(spec.options.maintainAspectRatio,false);
assert.strictEqual(spec.options.scales.y.beginAtZero,true);
const calls = [];
const chart = {data:spec.data, isDatasetVisible:i=>i!==hidden,
  scales:{x:{getPixelForValue:i=>42},y:{getPixelForValue:v=>200-v/10}},
  ctx:{save(){},restore(){},fillText(text,x,y){calls.push({text,x,y,baseline:this.textBaseline});}}};
let hidden = -1;
spec.plugins[0].afterDatasetsDraw(chart);
assert.deepStrictEqual(calls.map(c=>c.text), ['Net $530']);
assert.strictEqual(calls[0].y, 200-1027/10-4);
assert.strictEqual(calls[0].baseline,'bottom');
calls.length=0; hidden=2;
spec.plugins[0].afterDatasetsDraw(chart);
assert.deepStrictEqual(calls.map(c=>c.text), ['Net -$470']);
calls.length=0;
chart.data.datasets[0].data[0]=0;
chart.data.datasets[2].data[0]=0;
spec.plugins[0].afterDatasetsDraw(chart);
assert.deepStrictEqual(calls.map(c=>c.text), ['Net -$497']);
assert.strictEqual(calls[0].y, 200+497/10+4);
assert.strictEqual(calls[0].baseline,'top');
calls.length=0;
chart.data.datasets[0].data[0]=497;
spec.plugins[0].afterDatasetsDraw(chart);
assert.deepStrictEqual(calls.map(c=>c.text), ['Net $0']);
const cb=spec.options.plugins.tooltip.callbacks;
assert.strictEqual(cb.label({parsed:{y:-497},dataset:{label:'Closed / Assigned'}}), ' Closed / Assigned: -$497.00');
assert.strictEqual(cb.footer([{parsed:{y:27}},{parsed:{y:-497}},{parsed:{y:1000}}]), ' Net total: +$530.00');
assert.strictEqual(cb.footer([{parsed:{y:-497}}]), ' Net total: -$497.00');
'''
    result = subprocess.run(['node', '-e', harness+js+checks], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'position:relative;height:240px' in source
