"""Auditable local delta/total-variance interpolation; no unsupported extrapolation."""
from __future__ import annotations
import math
from collections import defaultdict
from statistics import median
from datetime import date
from time_utils import now_utc, parse_timestamp, TZ_EASTERN

VERSION='local-total-variance-2'


def valid_points(rows,as_of):
    points=[]
    at=parse_timestamp(as_of)
    for r in rows:
        try:
            bid,ask,iv,delta=map(float,(r['bid'],r['ask'],r['impliedVolatility'],r['delta']))
            stamp=parse_timestamp(r.get('quote_timestamp') or as_of)
            if not all(math.isfinite(x) for x in (bid,ask,iv,delta)) or bid<=0 or ask<bid or not .01<iv<3 or not 0<=delta<=1:continue
            if stamp>at or (at-stamp).total_seconds()>900 or r.get('iv_source','chain')!='chain':continue
            points.append(r)
        except (KeyError,TypeError,ValueError):continue
    groups=defaultdict(list)
    for p in points:groups[p['expiration']].append(p)
    clean=[]
    for group in groups.values():
        center=median(p['impliedVolatility'] for p in group)
        clean.extend(p for p in group if center/2<=p['impliedVolatility']<=center*2)
    return clean


def interpolate_delta(points,delta):
    grouped=defaultdict(list)
    for p in points:grouped[float(p['delta'])].append(float(p['impliedVolatility']))
    values=sorted((x,median(ys)) for x,ys in grouped.items())
    if len(values)<2 or delta<values[0][0] or delta>values[-1][0]:return None
    for x,y in values:
        if abs(delta-x)<1e-12:return y
    for (a,iv_a),(b,iv_b) in zip(values,values[1:]):
        if a<=delta<=b:return iv_a+(iv_b-iv_a)*(delta-a)/(b-a)
    return None


def candidate_metrics(candidate,points,spot,as_of):
    dte=float(candidate['dte']);delta=float(candidate['delta']);iv=float(candidate['impliedVolatility'])
    groups=defaultdict(list)
    for p in points:groups[p['expiration']].append(p)
    references=[]
    for expiration,group in groups.items():
        # Leave this contract out, including duplicate same-snapshot points.
        peers=[p for p in group if not (expiration==candidate['expiration'] and float(p['strike'])==float(candidate['strike']))]
        value=interpolate_delta(peers,delta)
        if value is not None:
            t=float(group[0]['dte'])/365
            references.append(dict(expiration=expiration,dte=group[0]['dte'],iv=value,total_variance=value*value*t,points=[{k:p.get(k) for k in ('expiration','strike','dte','delta','impliedVolatility','bid','ask','quote_timestamp','risk_events')} for p in peers]))
    same=next((r for r in references if r['expiration']==candidate['expiration']),None)
    before=max((r for r in references if r['dte']<dte),key=lambda r:r['dte'],default=None)
    after=min((r for r in references if r['dte']>dte),key=lambda r:r['dte'],default=None)
    expected=None;quality='INSUFFICIENT'
    if before and after:
        weight=(dte-before['dte'])/(after['dte']-before['dte'])
        tv=before['total_variance']+(after['total_variance']-before['total_variance'])*weight
        if tv>=0 and dte>0:expected=math.sqrt(tv/(dte/365));quality='BRACKETED_TOTAL_VARIANCE'
    elif same:expected=same['iv'];quality='SAME_EXPIRY_DELTA_INTERPOLATION'
    usable=any(p is candidate for p in points)
    if not usable:expected=None;quality='CANDIDATE_UNUSABLE'
    residual=iv-expected if expected is not None else None
    events=[e for e in candidate.get('risk_events',[]) if e.get('type')=='earnings']
    event_dates=[]
    for e in events:
        try:event_dates.append(date.fromisoformat(e['date']))
        except (KeyError,ValueError):pass
    variance=raw_variance=premium=contribution=None;event_quality='EVENT_DATE_UNKNOWN' if events and not event_dates else 'INSUFFICIENT'
    event_inputs=None
    if not events:variance=raw_variance=contribution=0.;premium=0.;event_quality='NO_KNOWN_EVENT'
    elif event_dates and usable:
        snapshot_day=parse_timestamp(as_of).astimezone(TZ_EASTERN).date()
        event_dte=(min(event_dates)-snapshot_day).days
        pre=sorted((r for r in references if r['dte']<event_dte),key=lambda r:r['dte'])
        post=min((r for r in references if r['dte']>=event_dte),key=lambda r:r['dte'],default=None)
        # Current expiry is usable evidence for post-event TV even if its own
        # leave-one-out delta support is insufficient for residual estimation.
        if dte>=event_dte and (post is None or dte<post['dte']):
            post=dict(dte=dte,iv=iv,total_variance=iv*iv*dte/365,expiration=candidate['expiration'])
        if pre and post:
            nearest=pre[-1];rate=nearest['total_variance']/(nearest['dte']/365)
            if len(pre)>=2:
                earlier=pre[-2]
                forward=(nearest['total_variance']-earlier['total_variance'])/((nearest['dte']-earlier['dte'])/365)
                rate=max(rate*.5,min(rate*1.5,forward));event_quality='BRACKETED_PRE_EVENT_FORWARD_VARIANCE'
            else:
                rate*=1.5;event_quality='CONSERVATIVE_PRE_EVENT_FORWARD_BOUND'
            baseline=nearest['total_variance']+rate*(post['dte']-nearest['dte'])/365
            raw_variance=post['total_variance']-baseline;variance=max(0.,raw_variance)
            contribution=math.sqrt(variance/(dte/365)) if dte>0 else None
            from covered_call_rec import bs_call_price
            sans_event=math.sqrt(max(.0001,iv*iv-variance/(dte/365)))
            premium=max(0.,bs_call_price(spot,candidate['strike'],dte/365,iv)-bs_call_price(spot,candidate['strike'],dte/365,sans_event))
            event_inputs=dict(event_date=min(event_dates).isoformat(),before=nearest,after=post,
                              non_event_forward_variance_rate=rate,non_event_total_variance_after=baseline)
    return dict(surface_expected_iv=expected,candidate_surface_residual=residual,
        candidate_surface_residual_pct=residual/expected if expected else None,
        surface_interpolation_quality=quality,surface_model_version_v2=VERSION,
        surface_reference_inputs=references,event_variance_estimate_v2=variance,
        event_variance_raw_v2=raw_variance,event_vol_contribution=contribution,
        event_premium_estimate_v2=premium,event_variance_quality=event_quality,event_variance_reference_inputs=event_inputs)


def surface_v2(rows,spot,as_of=None):
    as_of=as_of or now_utc().isoformat()
    points=valid_points(rows,as_of)
    return [candidate_metrics(r,points,spot,as_of) for r in rows]


def duration_adjust(rows,config):
    cfg=config['duration_utility']
    strength=float(cfg['flexibility_lambda']);availability=float(cfg['second_cycle_availability']);retention=float(cfg['second_cycle_alpha_retention'])
    if not all(0<=v<=1 for v in (strength,availability,retention)):raise ValueError('duration assumptions must be bounded')
    for row in rows:
        shorter=[r for r in rows if not r.get('v3_rejection_reasons') and r['dte']<=row['dte']/2 and r.get('adjusted_cc_alpha') is not None and r['adjusted_cc_alpha']>0]
        peer=max(shorter,key=lambda r:r['adjusted_cc_alpha']/r['dte'],default=None)
        benchmark=peer['adjusted_cc_alpha']*(1+availability*retention) if peer else None
        alpha=row.get('adjusted_cc_alpha')
        cost=max(0.,benchmark-alpha)*strength if benchmark is not None and alpha is not None else 0. if alpha is not None else None
        adjusted=alpha-cost if alpha is not None else None
        row.update(sequential_short_cycle_benchmark=benchmark,flexibility_cost=cost,
            benchmark_candidate_reference=dict(strike=peer['strike'],expiration=peer['expiration'],dte=peer['dte'],adjusted_cc_alpha=peer['adjusted_cc_alpha']) if peer else None,
            benchmark_available=peer is not None,second_cycle_availability=availability,second_cycle_alpha_retention=retention,
            flexibility_lambda=strength,duration_utility_version=cfg['version'],
            duration_adjusted_alpha=adjusted,duration_adjusted_utility_margin=adjusted-row['utility_hurdle'] if adjusted is not None else None,
            sequential_benchmark_assumptions='Observed first-cycle net alpha plus discounted availability and alpha retention; no repeated current IV')
    return rows
