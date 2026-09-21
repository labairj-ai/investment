"""Shared user-facing terminology; no investment/scoring dependencies."""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HEADER_HELP = {
 'ticker': 'Stock or fund trading symbol identifying the holding in this row.',
 'symbol': 'Trading symbol for the position, order or execution.',
 'structuralhealth': 'Macro Health from 0–100. Higher means lower structural exposure: rate, dollar and geopolitical risk scores are reversed; inflation benefit is retained. This is not a return forecast.',
 'health0100': 'Macro Health from 0–100. Higher means lower structural exposure. All four dimension scores are required; missing inputs display a dash. This is not a predicted return or experiment eligibility badge.',
 'raterisk': 'Rate sensitivity, 1–10: higher means more potential harm from a +50 basis-point rise in the 10-year yield. Exposure estimate, not a probability.',
 'inflationbenefit': 'Inflation hedge, 1–10: higher means more potential benefit or resilience under sustained inflation above 3%. This is the benefit dimension, so its color direction differs from the risk dimensions.',
 'dollarrisk': 'Dollar sensitivity, 1–10: higher means more potential harm from a strengthening US dollar.',
 'georisk': 'Geopolitical risk, 1–10: higher means greater company exposure to trade, tariffs or sanctions-related disruption.',
 'rateinteraction': 'Experimental interaction between structural rate sensitivity and current signed rate stress. Positive indicates adverse pressure; negative indicates favorable pressure. Research context only.',
 'dollarinteraction': 'Experimental interaction between dollar sensitivity and current signed dollar stress. Positive indicates adverse pressure; negative indicates favorable pressure. Research context only.',
 'inflationhedge': 'Company inflation resilience or benefit; higher is more favorable. In the interaction view this is structural context, not a predicted return.',
 'scorerange': 'Bucket of the original score or component score. Outcomes within the bucket are summarized to assess calibration; the bucket is not a probability forecast.',
 'n': 'Number of evaluable observations included in this table row. A larger count alone is not proof of predictive value, and rows from the same decision date may be correlated.',
 'meanreturn': 'Average forward ticker return among evaluable episodes in this score bucket, over the table’s selected outcome horizon.',
 'meanspy': 'Average SPY benchmark return over the same episode horizons used for the ticker returns.',
 'meanalpha': 'Average forward ticker return minus the matching SPY return. Positive means outperformance of SPY, not necessarily a positive absolute return.',
 'mean90dalpha': 'Average SPY-relative forward return for this component-score bucket at the report’s 90-day target. Check the horizon version: 63 trading sessions and legacy calendar horizons are not interchangeable.',
 'convictionstars': 'LLM conviction rating recorded when the candidate was selected. It is a judgment category, not a calibrated success probability.',
 'nselected': 'Number of selected episodes with usable outcomes in this conviction category.',
 'hitratealpha0': 'Share of evaluable selected episodes whose forward return exceeded SPY over the same horizon.',
 'rule': 'Risk rule that prevented the proposed trade or recommendation from proceeding.',
 'blocked': 'Number of risk-rejected intents represented by this rule’s labeled counterfactual outcomes.',
 'lossesavoided': 'Count of blocked outcomes with negative decision-relative alpha (or ticker alpha for legacy rows). This can mean SPY underperformance rather than an absolute loss; it is not realized savings.',
 'alphamissed': 'Count of blocked outcomes with positive decision-relative alpha (or ticker alpha for legacy rows). This is a count, not a dollar amount or an instruction to weaken the rule.',
 'meanblockedalpha': 'Average forward SPY-relative return of labeled risk-blocked candidates; these are hypothetical outcomes rather than actual fills.',
 'exploratorydimension': 'Macro dimension or dimension combination tested on the original frozen candidate evidence. Exploratory diagnostics do not replace the preregistered primary experiment.',
 'alpha': 'Macro-selected minus control-selected SPY-relative outcome. Positive favors the macro selection. Percent displays represent percentage-point differences between returns.',
 'mae': 'Maximum adverse excursion: the worst price movement below the entry reference during the outcome horizon. More negative means a deeper adverse move; a dash means unavailable.',
 'mfe': 'Maximum favorable excursion: the best price movement above the entry reference during the outcome horizon. It is an intrahorizon diagnostic, not the final realized return.',
 'deltaalpha': 'Macro-arm minus control-arm SPY-relative outcome on evaluable divergent cohorts. Positive favors the macro arm; shown as a percentage-point difference.',
 'deltamae': 'Macro-arm maximum adverse excursion minus control-arm maximum adverse excursion. With negative adverse returns, a positive difference means a shallower drawdown during the horizon.',
 'nfills': 'Number of fills with usable labeled outcomes included for this comparison arm. It is not the number of independent decision dates.',
 'alphamean': 'Mean forward SPY-relative alpha for the comparison arm, based only on usable labeled outcomes.',
 'hitrate': 'Fraction of evaluable outcomes with positive SPY-relative alpha for this arm.',
 'decisionret': 'Mean outcome return after accounting for the decision direction, as defined by the comparison report. Distinct from the underlying stock’s raw return.',
 'implshortfall': 'Average implementation shortfall: fill price relative to the recorded arrival-price reference, signed so positive means adverse execution. Newer records use the decision quote; legacy records may use the limit-price proxy. Displayed as a percent.',
 'shares': 'Number of shares held in this execution account, not the household’s total holdings.',
 'avgcost': 'Average acquisition cost per share recorded for this account position.',
 'value': 'Position value reported by this execution account. Account valuation can use different price sources from the portfolio or learning virtual books.',
 'date': 'Recorded date/time for the intent or fill. This is an event timestamp, not an outcome maturity date.',
 'order': 'Proposed order action and quantity for the trade intent. An intent is not evidence that an order was submitted or filled.',
 'status': 'Current intent lifecycle status, such as awaiting review, blocked, submitted or completed. Read the row’s risk result before interpreting it as executed.',
 'risk': 'Result of the deterministic pre-trade risk checks. A passing check permits the next workflow step; it does not guarantee a fill or a profitable trade.',
 'side': 'Execution direction, such as buy or sell.',
 'execution': 'Recorded executed quantity and fill price. Distinct from the proposed order and decision-time quote.',
 'rec': 'Recommendation identifier linking the execution to its originating recommendation.',
 'timeutc': 'Start time of this runner cycle, displayed in Coordinated Universal Time (UTC).',
 'state': 'Runner cycle state. Completion describes the cycle’s workflow, not whether every possible investment opportunity was traded.',
 'duration': 'Elapsed runner-cycle execution time. A long duration can indicate waiting for data or external services.',
 'intents': 'Trade intents processed or reported during this runner cycle; proposals are distinct from orders and fills.',
 'orders': 'Orders reported by this runner cycle; an order is distinct from a completed execution.',
 'fills': 'Fill count reported by this runner cycle. Partial fills may be separate execution records.',
 'apierrs': 'External API errors recorded during this runner cycle; inspect the run record for details.',
 'arm': 'Comparison arm: the existing champion/control or the challenger. A learned challenger is separate from the stage-zero macro experiment.',
}


def render_glossary():
    legacy = (ROOT/'static/glossary_legacy.html').read_text()
    sections = json.loads((ROOT/'static/glossary_terms.json').read_text())
    parts = ['<div class="gloss-intro">Definitions for the portfolio, Macro Risk, Learning Lab, Agent Engine, and covered-call tools. Score meanings depend on the page; missing data is not zero. Hover, focus, or tap a dotted column header for a quick explanation.</div>',
             '<label class="gloss-search-label">Find a term <input type="search" class="gloss-search" placeholder="Try alpha, coverage, intent, or delta" aria-label="Search glossary"></label>',
             '<p class="gloss-search-status" role="status" aria-live="polite"></p>']
    for section in sections:
        parts.append('<section class="gloss-section"><h2 class="gloss-h2">'+escape(section['section'])+'</h2>')
        for term in section['terms']:
            parts.append('<div class="gloss-term"><div class="gloss-term-name">'+escape(term['term'])+'</div><div class="gloss-term-body">'+escape(term['definition'])+'</div></div>')
        parts.append('</section>')
    parts.append(legacy)
    return ''.join(parts)


def help_assets():
    # Static reviewed text only. Escaping '<' keeps JSON safe inside a script tag.
    data=json.dumps(HEADER_HELP,ensure_ascii=False).replace('<','\\u003c')
    return '<style>'+(ROOT/'static/site_help.css').read_text()+'</style><script>window.SITE_COLUMN_HELP='+data+';</script><script>'+(ROOT/'static/site_help.js').read_text()+'</script>'


def glossary_page():
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Investment Dashboard — Glossary</title></head><body class="standalone-glossary"><header><h1>Glossary</h1><a href="/">← Back to Dashboard</a></header><main class="gloss-container">'+render_glossary()+'</main>'+help_assets()+'</body></html>'
