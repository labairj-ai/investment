"""Deterministic covered-call entry challenger. Economics are dollars PER SHARE.

V2 remains champion. No V3 feature changes live sizing, gates or selection until
an evidence-bound promotion. Model inputs live in immutable decision snapshots.
"""
from __future__ import annotations
import math
from time_utils import today_eastern, now_utc
from statistics import NormalDist
from datetime import date
import numpy as np

VERSION = 'cc-v3.4'
N = NormalDist()


def bounded(x, lo=0., hi=1.):
    return max(lo, min(hi, float(x)))


def drift_model(returns, prior=.08, prior_sd=.15):
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)][-252:]
    n = len(r)
    raw_estimate = float(r.mean() * 252) if n else prior
    estimate = bounded(raw_estimate,-.50,.50)
    annual_vol = max(.20, float(r.std(ddof=1) * math.sqrt(252))) if n > 1 else .40
    sampling_var = annual_vol ** 2 * 252 / max(n, 1)
    weight = prior_sd ** 2 / (prior_sd ** 2 + sampling_var)
    momentum = bounded(float(r[-60:].mean() * 252) if n >= 60 else prior, -.30, .30)
    center = bounded(prior + weight * (estimate - prior) + .05 * (momentum - prior), -.25, .35)
    sd = math.sqrt(1 / (1 / prior_sd ** 2 + 1 / sampling_var))
    return dict(mu_center=center, mu_low=center - 1.645 * sd,
                mu_high=center + 1.645 * sd, mu=center,
                drift_model_version='shrinkage-1', drift_inputs=dict(
                    prior=prior, prior_sd=prior_sd, estimate_252=estimate, raw_estimate_252=raw_estimate,
                    momentum_60=momentum, annual_vol=annual_vol, effective_n=n,
                    sampling_variance=sampling_var, posterior_weight=weight,
                    returns=r.tolist()))


def touch_probability(spot, barrier, years, sigma, mu, q=0.):
    """Continuous GBM upper first passage, including drift and dividends."""
    if barrier <= spot:
        return 1.
    if years <= 0:
        return 0.
    a = math.log(barrier / spot)
    b = mu - q - .5 * sigma ** 2
    if sigma <= 0:
        return float(b * years >= a)
    z = sigma * math.sqrt(years)
    # log-space second term avoids overflow for extreme inputs.
    first = N.cdf((b * years - a) / z)
    x = (-b * years - a) / z
    cdf = N.cdf(x)
    if cdf == 0:
        # stable Gaussian left-tail approximation
        logcdf = -.5 * x * x - math.log(max(1., -x)) - .5 * math.log(2 * math.pi)
    else:
        logcdf = math.log(cdf)
    second = math.exp(min(0., 2 * b * a / sigma ** 2 + logcdf))
    return bounded(first + second)


def path_oracle(spot, strike, premium, days, sigma, mu, q=0., seed=6902, paths=4096):
    """Daily GBM + Brownian bridge strike crossing validation; moving delta barriers.

    Delta thresholds use risk-neutral delta with time remaining; physical paths
    use posterior upper drift. First-touch times are daily-grid estimates.
    """
    rng = np.random.default_rng(seed)
    steps = max(1, int(days))
    dt = days / 365 / steps
    increments = (mu-q-.5*sigma*sigma)*dt + sigma*math.sqrt(dt)*rng.standard_normal((paths, steps))
    logpaths = np.concatenate([np.zeros((paths, 1)), np.cumsum(increments, axis=1)], axis=1)
    prices = spot * np.exp(logpaths)
    hit = prices >= strike
    times = np.argmax(hit, axis=1)
    touched = hit.any(axis=1)
    bridge = touched.copy()
    if sigma > 0:
        a = math.log(strike/spot)
        left, right = logpaths[:, :-1], logpaths[:, 1:]
        probs = np.exp(np.minimum(0, -2*(a-left)*(a-right)/(sigma*sigma*dt)))
        crossing = (left >= a) | (right >= a) | (rng.random(probs.shape) < probs)
        bridge |= crossing.any(axis=1)
    out = dict(mc_strike_touch_prob=float(bridge.mean()),
               expected_days_to_first_touch=float(times[touched].mean()*days/steps) if touched.any() else None,
               path_seed=seed, path_count=paths, path_grid='daily', path_model_version='gbm-bridge-1')
    for level in (.30, .50):
        events = np.zeros(paths, dtype=bool)
        for j in range(steps+1):
            t = (steps-j)*dt
            if t <= 0 or sigma <= 0:
                events |= prices[:, j] >= strike
            else:
                barrier = strike * math.exp(sigma*math.sqrt(t)*N.inv_cdf(level)-(.045-q+.5*sigma*sigma)*t)
                events |= prices[:, j] >= barrier
        out[f'delta{int(level*100)}_touch_prob'] = float(events.mean())
    return out


def path_metrics(spot, row, vm, q=0., paths=2048):
    sigma = max(.001, float(row['impliedVolatility']))
    mu = vm['mu_high']
    days = float(row['dte'])
    strike = float(row['strike'])
    premium = float(row['exec_premium'])
    out = path_oracle(spot, strike, premium, days, sigma, mu, q, paths=paths)
    out.update(strike_touch_prob=touch_probability(spot, strike, days/365, sigma, mu, q),
               regret_barrier_touch_prob=touch_probability(spot, strike+premium, days/365, sigma, mu, q),
               management_risk_model_version='first-passage-delta-mc-1')
    # Proxy for management burden, not a prediction that a roll occurred.
    out['management_risk'] = bounded(.5*out['strike_touch_prob']+.5*out['delta30_touch_prob'])
    return out


def eligibility(row, policy, spot, data_mode='live'):
    reasons = []
    if policy.get('strategy') == 'NONE': reasons.append('STRATEGY_NONE')
    checks = [('preferred_dte_min', 'dte', lambda v, p: v < p, 'DTE_BELOW_POLICY'),
              ('preferred_dte_max', 'dte', lambda v, p: v > p, 'DTE_ABOVE_POLICY'),
              ('max_preferred_delta', 'delta', lambda v, p: v > p, 'DELTA_ABOVE_POLICY'),
              ('acceptable_assignment_min_price', 'strike', lambda v, p: v < p, 'ASSIGNMENT_FLOOR')]
    for key, field, cmp, reason in checks:
        if policy.get(key) is not None and cmp(float(row[field]), float(policy[key])):
            reasons.append(reason)
    if float(row['strike']) < spot*(1+float(policy.get('minimum_otm_pct') or 0)):
        reasons.append('OTM_BELOW_POLICY')
    if not row.get('passes_floor', False): reasons.append('PROFIT_FLOOR')
    if row.get('has_avoid', False): reasons.append('EVENT_AVOID')
    if policy.get('avoid_earnings') and any('earning' in str(e).lower() for e in row.get('risk_events', [])):
        reasons.append('EARNINGS_POLICY')
    bid, ask = float(row.get('bid', 0)), float(row.get('ask', 0))
    if data_mode != 'live': reasons.append('NON_LIVE_QUOTE')
    if not all(math.isfinite(x) for x in (bid, ask)) or bid <= 0 or ask < bid:
        reasons.append('INVALID_QUOTE')
    if bid<float(policy.get('minimum_bid',.05)):reasons.append('BID_BELOW_MINIMUM')
    if float(row.get('liquidity_score', 0)) < float(policy.get('minimum_liquidity_score', 20)):
        reasons.append('LIQUIDITY_BELOW_POLICY')
    assignment = policy.get('assignment_policy') or {}
    if assignment.get('allowed') is False: reasons.append('ASSIGNMENT_NOT_ALLOWED')
    if assignment.get('only_if_overweight') and not policy.get('is_overweight', False):
        reasons.append('ASSIGNMENT_REQUIRES_OVERWEIGHT')
    if assignment.get('preserve_high_conviction'):
        if policy.get('conviction') is None or policy.get('thesis_health') is None:
            reasons.append('ASSIGNMENT_THESIS_DATA_MISSING')
        elif float(policy['conviction']) >= float(assignment.get('min_conviction_to_preserve',4)) and float(policy['thesis_health']) >= float(assignment.get('min_thesis_health_for_preservation',80)):
            reasons.append('ASSIGNMENT_PRESERVATION')
    # Any nonfinite economic/risk input fails closed.
    for key in ('dte', 'strike', 'delta', 'exec_premium', 'cc_alpha', 'regret_prob', 'impliedVolatility'):
        try:
            if not math.isfinite(float(row[key])): reasons.append('INVALID_INPUT_'+key.upper())
        except (KeyError, TypeError, ValueError): reasons.append('MISSING_INPUT_'+key.upper())
    return reasons


def surface(rows, spot, hv, now=None):
    """Local interpolation only within observed delta support; no extrapolation."""
    now = now or today_eastern().isoformat()
    valid = []
    for r in rows:
        bid, ask, iv = (float(r.get(k, 0) or 0) for k in ('bid', 'ask', 'impliedVolatility'))
        timestamp = r.get('quote_timestamp')
        stale = bool(timestamp and str(timestamp)[:10] < str(now)[:10])
        if bid > 0 and ask >= bid and .01 < iv < 3 and not stale and r.get('iv_source', 'chain') == 'chain':
            valid.append(r)
    slices = {}
    usable_points = []
    for exp in sorted({r['expiration'] for r in valid}):
        group = [r for r in valid if r['expiration'] == exp]
        # Robustly reject isolated IV outliers against this expiry's median.
        med = float(np.median([r['impliedVolatility'] for r in group]))
        group = [r for r in group if med/2 <= r['impliedVolatility'] <= med*2]
        usable_points.extend(group)
        ordered = sorted(group, key=lambda r: r['delta'])
        xs = [r['delta'] for r in ordered]; ys = [r['impliedVolatility'] for r in ordered]
        def at(delta):
            return float(np.interp(delta, xs, ys)) if len(xs) >= 3 and xs[0] <= delta <= xs[-1] else None
        slices[exp] = dict(dte=group[0]['dte'] if group else None, atm_iv=at(.5), iv20=at(.2), iv25=at(.25), iv30=at(.3), points=len(group),
                           has_event=any(any(e.get('type')=='earnings' for e in r.get('risk_events',[])) for r in group))
    out = []
    for r in rows:
        sl = slices.get(r['expiration'], {})
        peer = sl.get('iv25')
        others = [s['iv25'] for exp, s in slices.items() if exp != r['expiration'] and s.get('iv25') is not None and abs((s.get('dte') or 0)-r['dte']) <= 35]
        event = bool(r.get('risk_events'))
        iv = float(r['impliedVolatility'])
        usable = any(r is x for x in usable_points)
        baseline=[s for s in slices.values() if not s.get('has_event') and s.get('atm_iv') is not None and s.get('dte') is not None and s['dte']<r['dte']]
        pre_event=max(baseline,key=lambda s:s['dte'],default=None)
        event_variance=None; event_premium=None
        if sl.get('has_event') and sl.get('atm_iv') is not None and pre_event and usable:
            event_variance=max(0.,(sl['atm_iv']**2-pre_event['atm_iv']**2)*r['dte']/365)
            from covered_call_rec import bs_call_price
            sans_event=math.sqrt(max(.0001,iv**2-event_variance/(r['dte']/365)))
            event_premium=max(0.,bs_call_price(spot,r['strike'],r['dte']/365,iv)-bs_call_price(spot,r['strike'],r['dte']/365,sans_event))
        out.append(dict(atm_iv_surface=sl.get('atm_iv'), iv20_surface=sl.get('iv20'), iv25_surface=peer, iv30_surface=sl.get('iv30'),
                        vrp_estimate=iv-hv if usable else None,
                        term_richness=peer-float(np.median(others)) if peer is not None and others and usable else None,
                        skew_richness=iv-sl['atm_iv'] if sl.get('atm_iv') is not None and usable else None,
                        event_premium=event_premium, event_variance_estimate=event_variance,
                        event_variance_state='LOCAL_PRE_EVENT_BASELINE_ESTIMATE' if event_variance is not None else 'UNMEASURED_EVENT' if event else 'NO_KNOWN_EVENT',
                        comparable_delta_iv_percentile=None, surface_quality='LOCAL' if peer is not None and usable else 'INSUFFICIENT',
                        surface_point_usable=usable, vol_surface_model_version='local-delta-1', surface_snapshot=slices))
    return out


def regime_model(closes, policy):
    c = np.asarray(closes, dtype=float)
    c = c[np.isfinite(c) & (c > 0)]
    def momentum(n): return float(c[-1]/c[-n-1]-1) if len(c) > n else None
    m20, m60, m120 = (momentum(n) for n in (20,60,120))
    persistence = float(np.mean(np.diff(c[-61:]) > 0)) if len(c) > 20 else None
    distance = float(c[-1]/max(c[-252:])-1) if len(c) else None
    breakout = bool(len(c)>20 and c[-1]>max(c[-21:-1]))
    state = 'NEUTRAL'
    if m60 is not None and m120 is not None:
        if m60>.12 and m120>.18 and m20 is not None and m20>0 and persistence>.55: state='STRONG_UPTREND'
        elif m60>.04 and m120>0: state='UPTREND'
        elif m60<-.05 and m120<0: state='DOWNTREND'
    return dict(regime_state=state, regime_model_version='bounded-trend-1', regime_inputs=dict(
        momentum20=m20,momentum60=m60,momentum120=m120,distance_52w_high=distance,
        trend_persistence=persistence,breakout=breakout,conviction=policy.get('conviction'),
        thesis_health=policy.get('thesis_health'), concentration=policy.get('portfolio_weight'),
        catalyst=policy.get('catalyst'), assignment_target=policy.get('acceptable_assignment_min_price')))


def overwrite(shares, policy, regime, config):
    maximum = max(0, int(shares//100))
    strategy = policy.get('strategy', 'INCOME')
    cap = bounded(policy.get('max_overwrite_fraction', config['max_overwrite_fraction'].get(strategy, 0)))
    if config.get('regime_enabled') and regime['regime_state'] == 'STRONG_UPTREND': cap=min(cap,.5)
    if float(policy.get('conviction') or 0) >= 4: cap=min(cap,.5)
    contracts = int(maximum*cap)
    # Fractions rounded down to covered round lots; a 50% cap on 300 shares => 1 call.
    return dict(eligible_contracts_max=maximum,recommended_contracts=contracts,
                overwrite_fraction=contracts*100/shares if shares>0 else 0.,
                overwrite_policy_version='policy-fractions-1', overwrite_cap=cap)


def execution(row, fills=(), config=None):
    cfg = config or {}
    bid, ask = float(row['bid']),float(row['ask'])
    width = ask-bid
    if bid<=0 or width<0 or not math.isfinite(width):
        return dict(execution_available=False, execution_model_version='shrinkage-fill-1')
    mid=(bid+ask)/2
    bucket = 'tight' if width/max(mid,.01)<=.10 else 'wide'
    real = [f for f in fills if f.get('bucket')==bucket and f.get('actual') and f.get('fill_fraction') is not None]
    n=len(real); prior=float(cfg.get('fill_prior', .15)); min_n=int(cfg.get('fill_min_n',30))
    fraction=prior
    if n>=min_n:
        strength=float(cfg.get('fill_prior_strength',50))
        fraction=bounded((sum(bounded(f['fill_fraction']) for f in real)+strength*prior)/(n+strength),0,.5)
    fee=float(cfg.get('fee_per_contract',.65))/100
    slippage=width*(.5-fraction)
    return dict(execution_available=True, expected_fill=bid+fraction*width,
        expected_entry_slippage=slippage, expected_exit_slippage=width*.5,
        expected_roll_slippage=slippage+width*.5+2*fee,
        expected_execution_cost=slippage+fee, execution_fee_per_share=fee,
        execution_bucket=bucket, execution_bucket_n=n, expected_fill_fraction=fraction,
        execution_model_version='shrinkage-fill-1', spread_dollars=width,
        spread_percentage=width/max(mid,.01))


def tax_metrics(ticker, row, contracts, policy):
    from covered_call_rec import _lot_tax_friction
    shares=contracts*100
    detail=_lot_tax_friction(ticker,float(row['strike']),shares,date.fromisoformat(row['expiration'])) if shares else None
    available=bool(detail and detail.available)
    schedule=detail.lot_schedule if available else []
    cost=sum(float(l['friction_contribution']) for l in schedule)
    # Warning only: qualification needs more facts than this quote snapshot.
    return dict(tax_data_available=available, assignment_lot_schedule=schedule,
        shares_potentially_delivered=shares, projected_assignment_gain=sum(
            float(l['allocated_shares'])*(float(row['strike'])-float(l['cost_per_share'])) for l in schedule) if available else None,
        expected_tax_cost=cost/max(1,shares)*float(row['itm_prob_real_conservative']) if available else None,
        tax_rule_warning='QCC_REVIEW_REQUIRED' if int(row['dte'])<30 else 'QCC_UNASSESSED',
        qualified_covered_call_state='UNASSESSED',
        ex_dividend_early_assignment_risk='REVIEW_EVENT' if any('dividend' in str(e).lower() for e in row.get('risk_events', [])) else 'NO_KNOWN_EVENT',
        assignment_floor_compatible=policy.get('acceptable_assignment_min_price') is None or row['strike']>=policy['acceptable_assignment_min_price'],
        thesis_assignment_acceptable=(policy.get('assignment_policy') or {}).get('allowed',True),
        tax_model_version='fifo-entry-1', tax_assumptions='FIFO, expiry disposal, ST-LT differential; no QCC tax conclusion',
        tax_unavailable_reason=None if available else (detail.reason if detail else 'zero overwrite'))


def utility(row, spot, config):
    # Start at mid then subtract modeled slippage once. Management is intervention
    # labor + two-leg execution friction, never mark-to-market call loss (already
    # represented by expected upside surrendered).
    premium=(float(row['bid'])+float(row['ask']))/2
    upside=float(row['upside_lost_conservative'])
    management=float(row['management_risk'])*(float(config['management_cost_per_contract'])/100+float(row.get('expected_roll_slippage',0)))
    execution_cost=row.get('expected_execution_cost')
    tax=row.get('expected_tax_cost')
    complete=all(x is not None and math.isfinite(float(x)) for x in (execution_cost,tax))
    alpha=premium-upside-management-execution_cost-tax if complete else None
    days=max(1,int(row['dte']))
    hurdle=spot*float(config['utility_hurdle_annual_pct'])*days/365
    if config.get('regime_enabled') and row.get('regime_state')=='STRONG_UPTREND': hurdle*=1.5
    return dict(expected_premium=premium,expected_upside_surrendered=upside,
        expected_management_cost=management,expected_execution_cost=execution_cost,expected_tax_cost=tax,
        adjusted_cc_alpha=alpha, adjusted_cc_alpha_pct=alpha/spot if alpha is not None else None,
        adjusted_cc_alpha_per_day=alpha/days if alpha is not None else None,
        premium_per_day=premium/days,cc_alpha_per_day=float(row['cc_alpha'])/days,
        theta_efficiency=-float(row.get('theta') or 0)/max(premium,.01),
        management_risk_per_day=float(row['management_risk'])/days,
        utility_hurdle=hurdle,utility_margin=alpha-hurdle if alpha is not None else None,
        utility_inputs_complete=complete,utility_units='USD_PER_SHARE',utility_model_version='absolute-utility-1')


def divergence(champion, challenger):
    ca,cb=champion.get('action','NO_CALL'),challenger.get('action','NO_CALL')
    if ca==cb=='NO_CALL': return 'SAME_NO_CALL'
    if ca=='SELL_CC' and cb=='NO_CALL': return 'CHAMPION_CALL_CHALLENGER_NO_CALL'
    if ca=='NO_CALL' and cb=='SELL_CC': return 'CHALLENGER_CALL_CHAMPION_NO_CALL'
    dimensions=[k for k in ('strike','expiration','contracts') if champion.get(k)!=challenger.get(k)]
    if len(dimensions)>1: return 'MULTI_DIMENSION_DIVERGENCE'
    if not dimensions: return 'SAME_CONTRACT'
    return {'strike':'DIFFERENT_STRIKE','expiration':'DIFFERENT_EXPIRY','contracts':'DIFFERENT_COVERAGE'}[dimensions[0]]


def prepare(ticker, result, policy, shares, config, fills=(), history=()):
    """Prepare every considered alternative before truncation, retaining rejections."""
    from covered_call_rec import itm_prob_real,regret_prob,expected_upside_lost
    rows=result.get('all_calls',result['recs']).to_dict('records')
    spot=float(result['current_price']); vm=result['vol_model']
    if 'mu_center' not in vm: vm={**vm,**drift_model([])}
    regime=result.get('regime') or regime_model([],policy)
    coverage=overwrite(shares,policy,regime,config)
    peer_rows=result.get('surface_points', [])
    surfaces=surface(rows+peer_rows,spot,vm['hv_forecast'],result.get('snapshot_timestamp'))[:len(rows)]
    from covered_call_surface import surface_v2, duration_adjust
    surfaces_v2=surface_v2(rows+peer_rows,spot,result.get('snapshot_timestamp'))[:len(rows)]
    for row,sf,sf2 in zip(rows,surfaces,surfaces_v2):
        row.update(sf2)
        row.update(sf);row.update(regime);row.update(coverage);row.update(vm)
        row['spot']=spot; row['origin_holding_shares']=float(shares); row['policy_snapshot']=policy;row['data_mode']=result.get('data_mode')
        row['quote_timestamp']=row.get('quote_timestamp') or result.get('snapshot_timestamp')
        row['otm_pct']=row['strike']/spot-1
        # Comparable-delta/DTE percentiles require independent historical sessions.
        peer_history={}
        for old in history:
            if abs(float(old.get('delta',0))-row['delta'])<=.05 and abs(float(old.get('dte',0))-row['dte'])<=14 and old.get('surface_point_usable') and old.get('quote_timestamp','')<row['quote_timestamp']:
                peer_history.setdefault(old['quote_timestamp'][:10],[]).append(float(old['impliedVolatility']))
        historical=[float(np.median(points)) for points in peer_history.values()]
        row['comparable_delta_iv_history_n']=len(historical)
        row['comparable_delta_iv_percentile']=sum(iv<=row['impliedVolatility'] for iv in historical)/len(historical) if len(historical)>=30 else None
        row['rejection_reasons']=eligibility(row,policy,spot,result.get('data_mode','live'))
        row['eligible']=not row['rejection_reasons']
        for label,mu in (('base',vm['mu_center']),('conservative',vm['mu_high'])):
            args=(spot,row['strike'],row['dte']/365,row['impliedVolatility'],mu,result.get('dividend_yield',0))
            row['itm_prob_real_'+label]=itm_prob_real(*args)
            row['regret_prob_'+label]=regret_prob(spot,row['strike'],row['exec_premium'],*args[2:])
            lost=expected_upside_lost(*args)
            row['upside_lost_'+label]=lost;row['cc_alpha_'+label]=row['exec_premium']-lost
        row.update(path_metrics(spot,row,vm,result.get('dividend_yield',0),paths=int(config.get('path_count',2048))))
        row.update(execution(row,fills,config));row.update(tax_metrics(ticker,row,coverage['recommended_contracts'],policy))
        row.update(utility(row,spot,config))
        row['v3_rejection_reasons']=list(row['rejection_reasons'])
        if config.get('regime_enabled') and regime['regime_state']=='STRONG_UPTREND':
            if row['delta'] > min(.20,float(policy.get('max_preferred_delta') or .30)):
                row['v3_rejection_reasons'].append('REGIME_DELTA_CAP')
            if row['otm_pct'] < min(.15,float(policy.get('minimum_otm_pct') or 0)+.02):
                row['v3_rejection_reasons'].append('REGIME_OTM_FLOOR')
        if not row['utility_inputs_complete']:row['v3_rejection_reasons'].append('MISSING_UTILITY_INPUTS')
        if coverage['recommended_contracts']==0:row['v3_rejection_reasons'].append('ZERO_POLICY_COVERAGE')
        if row['regret_prob_conservative']>config['max_regret_probability']:row['v3_rejection_reasons'].append('CONSERVATIVE_REGRET_LIMIT')
        if row['surface_quality']=='INSUFFICIENT':row['v3_rejection_reasons'].append('INSUFFICIENT_SURFACE')
        if row['surface_interpolation_quality'] in ('INSUFFICIENT','CANDIDATE_UNUSABLE'):row['v3_rejection_reasons'].append('INSUFFICIENT_SURFACE_V2')
    duration_adjust(rows,config)
    v2=sorted([r for r in rows if r['eligible']],key=lambda r:(-float(r.get('opp_score',r['score'])),r['expiration'],r['strike']))
    v3=sorted([r for r in rows if not r['v3_rejection_reasons'] and r['duration_adjusted_utility_margin'] is not None],key=lambda r:(-r['duration_adjusted_utility_margin']/r['dte'],r['expiration'],r['strike']))
    for rank,r in enumerate(v2,1):r['v2_rank']=rank
    for rank,r in enumerate(v3,1):r['v3_rank']=rank
    best=v3[0] if v3 and v3[0]['duration_adjusted_utility_margin']>0 else None
    challenger=dict(action='SELL_CC',strike=best['strike'],expiration=best['expiration'],contracts=best['recommended_contracts'],overwrite_fraction=best['overwrite_fraction']) if best else dict(action='NO_CALL',contracts=0,overwrite_fraction=0)
    for raw in result.get('raw_rejected_quotes',[]):
        reasons=['OUTSIDE_SCOREABLE_ENTRY_UNIVERSE']
        bid,ask=float(raw['bid']),float(raw['ask'])
        if not math.isfinite(bid) or not math.isfinite(ask) or bid<=0 or ask<bid:reasons.append('INVALID_QUOTE')
        if bid<float(policy.get('minimum_bid',.05)):reasons.append('BID_BELOW_MINIMUM')
        if raw['strike']<=spot:reasons.append('NOT_OTM')
        if raw['strike']>spot*1.5:reasons.append('STRIKE_OUTSIDE_ENTRY_RANGE')
        rows.append(dict(raw,spot=spot,eligible=False,rejection_reasons=reasons,
            v3_rejection_reasons=reasons,policy_snapshot=policy,data_mode=result.get('data_mode'),
            raw_quote_only=True,feature_availability='RAW_QUOTE_UNSCOREABLE',model_version=VERSION))
    return rows,challenger
