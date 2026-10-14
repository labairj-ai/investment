"""Behavioral checks for the presentation-only CC monthly income view."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dashboard_cc_income import income_assets

ROOT = Path(__file__).resolve().parents[1]
JS = re.search(r'<script>(.*?)</script>', income_assets(), re.S).group(1)


def run_js(checks):
    if not shutil.which('node'):
        pytest.skip('node is required for dashboard JavaScript execution')
    setup = r'''
const assert = require('assert');
const now = new Date('2026-10-14T01:00:00Z');
const positions = [
 {status:'expired',expiry:'2026-10-09',net_premium:27},
 {status:'closed',closed_date:'2026-10-12',expiry:'2026-11-06',net_premium:-497},
 {status:'open',opened_date:'2026-10-12',premium_per_contract:10,contracts:1,pnl_total:42},
 {status:'open',opened_date:'2026-09-12',premium_per_contract:2,contracts:1,pnl_total:null},
 {status:'closed',closed_date:'2026-08-02',net_premium:150},
 {status:'expired',expiry:'2026-01-01',net_premium:2000,notes:'pre-system income entry'}
];
'''
    result = subprocess.run(['node', '-'], input=JS+setup+checks, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_realized_excludes_open_premium_and_historical_placeholder():
    run_js(r'''
const d=ccIncomeData(positions,now);
assert.strictEqual(d.months['2026-10'].realized,-470);
assert.strictEqual(d.months['2026-10'].openPremium,1000);
assert.strictEqual(d.openPremium,1200);
assert.strictEqual(d.openPnl,42);
assert.strictEqual(d.marked,1);
assert.strictEqual(d.openCount,2);
assert.strictEqual(d.ytd,1680);
assert.strictEqual(d.historicalYtd,2000);
assert.strictEqual(d.months['2026-01'],undefined);
const html=renderCCIncome(positions,now);
assert(html.includes('Includes $2,000.00 historical income'));
assert(html.includes('Marks available for 1 of 2 open positions'));
assert(html.includes('not realized profit'));
''')


def test_one_signed_realized_value_per_month_and_signed_bar():
    run_js(r'''
const html=renderCCIncome(positions,now);
const rows=html.match(/<tbody>(.*?)<\/tbody>/s)[1].match(/<tr\b.*?<\/tr>/gs);
assert.strictEqual(rows.length,6);
assert(rows[0].includes('Oct 2026'));
assert(rows[0].includes('Month to date'));
assert.strictEqual((rows[0].match(/−\$470\.00/g)||[]).length,1);
assert(rows[0].includes('cc-income-bar-negative'));
assert(rows[0].includes('$1,000.00'));
assert(!rows[0].includes('$530.00'));
assert(rows[1].includes('Sep 2026'));
assert(rows[1].includes('$0.00'));
assert(rows[1].includes('$200.00'));
assert(!rows[1].includes('cc-income-bar-positive'));
assert(rows[2].includes('cc-income-bar-positive'));
assert(!html.includes('<canvas'));
assert(!html.includes('tooltip'));
''')


def test_ranges_fill_calendar_gaps_and_cross_years():
    run_js(r'''
const d=ccIncomeData(positions,now);
assert.deepStrictEqual(ccIncomeMonths(d,'6'),['2026-10','2026-09','2026-08','2026-07','2026-06','2026-05']);
assert.strictEqual(ccIncomeMonths(d,'12').length,12);
assert.strictEqual(ccIncomeMonths(d,'12')[11],'2025-11');
assert.deepStrictEqual(ccIncomeMonths(d,'all'),['2026-10','2026-09','2026-08']);
assert.deepStrictEqual(ccIncomeMonths(ccIncomeData([],now),'all'),['2026-10']);
// At UTC month rollover the financial reporting month is still Eastern time.
assert.strictEqual(ccIncomeCurrentMonth(new Date('2027-01-01T02:00:00Z')),'2026-12');
assert.deepStrictEqual(ccIncomeMonths(ccIncomeData([],new Date('2027-01-15T12:00:00Z')),'6'),['2027-01','2026-12','2026-11','2026-10','2026-09','2026-08']);
''')


def test_invalid_dates_unavailable_marks_and_empty_states():
    run_js(r'''
assert.strictEqual(ccIncomeMonth('2026-02-30'),null);
assert.strictEqual(ccIncomeMonth('2026-13-01'),null);
assert.strictEqual(ccIncomeMonth('<img onerror=alert(1)>'),null);
assert.strictEqual(ccIncomeMonth('2024-02-29'),'2024-02');
const bad=[{status:'closed',closed_date:'bad',expiry:'2026-10-16',net_premium:12},
 {status:'closed',closed_date:'bad',expiry:'bad',net_premium:25},
 {status:'open',opened_date:'bad',premium_per_contract:1,contracts:1},
 {status:'closed',closed_date:'2026-10-10',net_premium:null}];
const d=ccIncomeData(bad,now);
assert.strictEqual(d.months['2026-10'].realized,12);
assert.strictEqual(d.skippedDates,2);
assert.strictEqual(d.missingAmounts,1);
const html=renderCCIncome(bad,now);
assert(html.includes('Current option marks unavailable'));
assert(html.includes('totals are partial'));
assert(!html.includes('NaN'));
assert(renderCCIncome([],now).includes('No realized income recorded'));
assert.strictEqual(ccIncomeMoney(-0.001),'$0.00');
''')


def test_range_controls_are_keyboard_accessible_and_persist_on_refresh():
    run_js(r'''
let _allCCPositions=positions;
let focused=false;
const overview={innerHTML:''};
const document={getElementById:id=>id==='cc-income-overview'?overview:{focus:()=>{focused=true;}}};
setCCIncomeRange('12');
assert(focused);
assert.strictEqual((overview.innerHTML.match(/<th scope="row"/g)||[]).length,12);
assert(overview.innerHTML.includes('id="cc-income-range-12" aria-pressed="true"'));
assert(renderCCIncome(positions,now).includes('id="cc-income-range-12" aria-pressed="true"'));
setCCIncomeRange('all');
assert.strictEqual(_ccIncomeRange,'all');
setCCIncomeRange('invalid');
assert.strictEqual(_ccIncomeRange,'all');
assert(overview.innerHTML.includes('role="group" aria-label="Income history range"'));
assert(overview.innerHTML.includes('scope="col"'));
''')


def test_dashboard_integration_and_mobile_numeric_layout():
    source=(ROOT/'generate_dashboard.py').read_text()
    assert '{income_assets()}' in source
    assert 'renderCCIncome(positions)' in source
    assert '_ccIncomeChart' not in source
    assert 'cc-income-chart' not in source
    assets=income_assets()
    assert '@media (max-width: 560px)' in assets
    assert '.cc-income-months .cc-income-trend { display: none; }' in assets
    assert 'grid-template-columns: repeat(2,minmax(0,1fr))' in assets
    assert ':focus-visible' in assets
