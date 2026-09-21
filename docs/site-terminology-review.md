# Site terminology review — September 21, 2026

Reviewed the dashboard navigation and labels across portfolio holdings, covered
calls, dividends/lots, screener, decisions, Macro Risk, Learning Lab, Agent Engine,
and the glossary against their current renderers and calculation/report sources.

Changes made:

- Added explicit header explanations throughout Macro Risk, Learning Lab and
  Agent Engine, including tables inserted asynchronously. Dotted headers support
  hover, keyboard focus and tap; a viewport-positioned tooltip avoids clipping in
  horizontally scrolling tables. Escape or tapping outside dismisses it.
- Unified the dashboard glossary tab and `/glossary` into one rendered source.
  Preserved the fuller existing options/portfolio definitions and removed stale
  NEW badges. Added macro exposure, provenance, coverage, experimental design,
  outcome, execution and watchdog terminology: 105 terms in total, searchable by
  term, abbreviation or definition.
- Clarified that higher macro Health means lower exposure, while higher Rate,
  Dollar and Geo scores indicate higher sensitivity. Inflation is the benefit
  dimension. Health is not an eligibility badge or return forecast.
- Distinguished labeled episode counts from independent cohorts/decision dates,
  ordinary SPY-relative alpha from macro selection delta, percentage points from
  percent, learned-model 90% ranking intervals from macro 95% clustered intervals,
  and legacy calendar targets from 5/21/63-session prospective horizons.
- Corrected the per-trade comparison display: zero labeled fills no longer falls
  back to the total fill count. No outcome calculations or production rules changed.
- Explained that risk-audit “Losses Avoided” and “Alpha Missed” are counts using
  decision-relative alpha when available, not realized dollar savings. Explained
  the historical arrival-price proxy used for implementation shortfall.
- Clarified that exploratory attribution’s display threshold does not establish
  predictive value; removed the command-line implementation instruction from the
  no-data user message.

Validation: all 65 current header instances in the three target areas received
reviewed definitions in DOM checks. Focus, hover, Escape, outside tap and dynamic
insertion passed. Glossary filtering, no-results feedback and reset passed for
105 entries. JavaScript and Python syntax checks passed; the full Python suite
passed (1,376 passed, 16 skipped). Native browser visual inspection remains
unavailable while the existing macOS computer-use permissions are pending; the
review uses source, rendered HTML/API and DOM behavior checks.

Content is maintained in `site_help.py`, `static/glossary_terms.json` and
`static/glossary_legacy.html`; shared behavior/styles are in `static/site_help.js`
and `static/site_help.css`. Changes are presentation-only and preserve the
accepted scorer, experiment protocol, epoch and production macro influence.
