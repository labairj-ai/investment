"""Evidence-backed context for portfolio news; local caches, never a live macro crawl."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import os
import re
import time
from urllib.parse import urlsplit

from time_utils import today_eastern, parse_timestamp


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def bill_stage(action):
    text = action.lower()
    if re.search(r'became public law|signed by president', text):
        return 'Enacted'
    if 'vetoed' in text:
        return 'Vetoed'
    if 'ordered to be reported' in text or 'reported by' in text:
        return 'Committee reported; not enacted'
    if re.search(r'passed (house|senate)|agreed to in (house|senate)', text):
        return 'Passed one chamber; not enacted'
    if 'calendar' in text:
        return 'On legislative calendar; not enacted'
    if 'referred' in text or 'committee' in text:
        return 'In committee; not enacted'
    return 'Pending; enactment not established'


def load_context(out_dir, tickers, profiles, now=None):
    now = time.time() if now is None else now
    macro = read_json(Path(out_dir)/'macro_cache.json')
    bills_cache = read_json(Path(out_dir)/'bills_cache.json')
    sources, limitations = {}, []
    cache_fresh = 0 <= now-macro.get('_fetched_at', 0) <= 6*3600
    measurements = macro.get('measurements') or {}
    if cache_fresh:
        for key, m in measurements.items():
            if not isinstance(m, dict) or m.get('value') is None or m.get('stale'):
                continue
            series = m.get('series_id', '')
            if m.get('source') != 'FRED' or not series:
                continue
            ref = 'M:'+key
            sources[ref] = {'kind':'macro', 'title':key.replace('_',' '),
                'text': f"{key}: {m['value']} {m.get('units', '')}; observation {m.get('observation_date')}. This is a level, not proof of a new change.",
                'url':'https://fred.stlouisfed.org/series/'+series,
                'as_of':m.get('observation_date'), 'affected_tickers':list(tickers)}
        # Market prices have a cache observation time; never inherit undated RSS headlines.
        for key, symbol, unit in [('yield_10y','%5ETNX','percent'), ('vix','%5EVIX','index'), ('uup_chg','UUP','percent daily change'), ('tlt_chg','TLT','percent daily change')]:
            value = macro.get(key)
            if isinstance(value, (int,float)):
                sources['M:'+key] = {'kind':'macro', 'title':key.replace('_',' '),
                    'text':f'{key}: {value} {unit}. Cached market context; not a legislative fact.',
                    'url':'https://finance.yahoo.com/quote/'+symbol+'/',
                    'as_of':macro.get('date'), 'affected_tickers':list(tickers)}
        stale = [k for k, m in measurements.items() if isinstance(m, dict) and m.get('stale')]
        if stale:
            limitations.append('Stale macro measurements excluded: '+', '.join(stale)+'.')
    else:
        limitations.append('Current macro context unavailable; no live macro assumptions used.')

    # Use the legislative cache's own retrieval time, never the surrounding macro timestamp.
    policy_fresh = 0 <= now-bills_cache.get('_fetched_at', 0) <= 24*3600
    bills = bills_cache.get('bills', []) if policy_fresh else []
    if not policy_fresh:
        limitations.append('Official legislative cache is unavailable or over 24 hours old.')
    candidates = []
    for bill in bills:
        if not isinstance(bill, dict):
            continue
        url = bill.get('url', '')
        if urlsplit(url).hostname not in ('www.congress.gov', 'congress.gov'):
            continue
        if not re.match(r'^(H\.R\.|S\.)\s*\d+', bill.get('bill_id', '')):
            continue  # Committee funding / ceremonial resolutions are not investment policy.
        try:
            age = (today_eastern()-date.fromisoformat(bill.get('action_date',''))).days
        except ValueError:
            continue
        if age < 0 or age > 120:
            continue
        text = bill.get('title','')+' '+bill.get('summary','')
        # Avoid the previous broad-domain mistakes: personal travel is not corporate trade policy.
        if re.search(r'family members|NEXUS application|heritage area|post office|expenses of the committee', text, re.I):
            continue
        domains = set(bill.get('domains') or [])
        if re.search(r'artificial intelligence|\bAI\b', text):
            domains.add('technology')
        primary = domains-{'tax_corporate','tax_capital_gains'} or domains
        matches = []
        for t in tickers:
            p = profiles.get(t) or profiles.get(t.replace('.','-')) or {}
            if p.get('is_fund') and not primary.intersection({'tax_corporate','tax_capital_gains'}):
                continue  # No claimed look-through exposure without constituent evidence.
            if primary.intersection(p.get('domains', [])):
                matches.append(t)
        if not matches:
            continue
        stage = bill_stage(bill.get('latest_action',''))
        record = {'kind':'policy', 'title':bill['bill_id']+' — '+bill['title'],
            'text':f"{bill['bill_id']}: {bill['title']}. Status: {stage}. Last action ({bill['action_date']}): {bill.get('latest_action','')}. " +
                   ('CRS summary: '+bill['summary'][:900] if bill.get('summary') else 'No bill text/CRS summary available: do not invent obligations, financial effects, tax changes or beneficiaries.'),
            'url':url, 'stage':stage, 'as_of':bill['action_date'], 'affected_tickers':matches,
            'domains':sorted(domains), 'detail_available':bool(bill.get('summary'))}
        candidates.append((age, record))
    for i, (_, record) in enumerate(sorted(candidates, key=lambda x:x[0])[:4], 1):
        sources['P'+str(i)] = record
    policy_count = sum(s['kind']=='policy' for s in sources.values())
    return {'sources':sources, 'limitations':limitations, 'policy_count':policy_count,
            'macro_as_of':macro.get('date') if cache_fresh else None,
            'policy_checked_at':bills_cache.get('_fetched_at') if policy_fresh else None}


def hydrate_policy(auxiliary, out_dir, deadline):
    """Fetch missing official summaries concurrently within the caller's deadline.

    Congress list records may omit hasSummary. Never treat absence as proof that
    no summary exists. Cache by official URL and latest action for six hours.
    """
    from agents.news.brief import parallel_until, atomic_json
    from macro_context import _fetch_crs_summary
    key = os.environ.get('CONGRESS_API_KEY', '')
    cache_path = Path(out_dir)/'news_policy_summaries.json'
    cache = read_json(cache_path)
    jobs = []
    for ref, source in auxiliary['sources'].items():
        if source['kind'] != 'policy' or source.get('detail_available'):
            continue
        identity = source['url']+'|'+str(source['as_of'])
        prior = cache.get(identity, {})
        if 0 <= time.time()-prior.get('fetched_at',0) < 6*3600:
            source['summary'] = prior.get('text','')
            continue
        match = re.search(r'/bill/(\d+)(?:st|nd|rd|th)-congress/(house|senate)-bill/(\d+)', source['url'])
        if match and key:
            congress, chamber, number = match.groups()
            jobs.append((ref, (int(congress), 'hr' if chamber=='house' else 's', number, key)))
    results = parallel_until(jobs, _fetch_crs_summary, deadline, workers=4)
    for ref, result in results.items():
        source = auxiliary['sources'][ref]
        source['summary'] = result or ''
        cache[source['url']+'|'+str(source['as_of'])] = {'text':result or '', 'fetched_at':time.time()}
    if results:
        atomic_json(cache_path, cache)
    for source in auxiliary['sources'].values():
        summary = source.pop('summary', '')
        if summary:
            source['text'] = source['text'].split('No bill text/CRS summary available:')[0]+'CRS summary: '+summary
            source['detail_available'] = True
    return auxiliary


def exposure_scores(db_path, tickers):
    """Cached exposure estimates, with contract and age checks; never current-event proof."""
    import sqlite3
    result = {}
    try:
        with sqlite3.connect('file:'+str(db_path)+'?mode=ro', uri=True, timeout=1) as conn:
            rows = conn.execute('SELECT ticker,scores,updated_at FROM holding_macro_scores').fetchall()
        aliases = {t.replace('.', '-'):t for t in tickers}
        for t, raw, updated in rows:
            t = aliases.get(t.replace('.', '-'), t)
            if t not in tickers:
                continue
            obj = json.loads(raw)
            if obj.get('macro_supported') is False or obj.get('evidence_quality') == 'unsupported':
                continue
            if time.time()-parse_timestamp(updated).timestamp() > 7*86400:
                continue
            scores = {}
            for key in ('rate_sensitivity','inflation_hedge','dollar_sensitivity','geopolitical_risk'):
                v = obj.get(key)
                v = v.get('score') if isinstance(v, dict) else v
                if isinstance(v,(int,float)) and 1 <= v <= 10:
                    scores[key] = v
            if scores:
                result[t] = {'scores':scores, 'as_of':updated, 'basis':'exposure estimate, not event confirmation'}
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return result


def source_manifest(selected, auxiliary, article_id):
    sources = dict(auxiliary.get('sources', {}))
    aliases = {}
    for t, articles in selected.items():
        for a in articles:
            aid = article_id(a)
            if aid in aliases:
                sources[aliases[aid]]['affected_tickers'].append(t)
                continue
            key = 'N'+str(len(aliases)+1)
            aliases[aid] = key
            sources[key] = {'kind':'news', 'title':a['title'], 'text':a['model_input_text'],
                'url':a.get('url',''), 'as_of':a.get('pub_date'), 'affected_tickers':[t],
                'article_id':aid}
    return sources


def _validate_analysis(parsed, selected, context, auxiliary, article_id):
    """No portfolio conclusion without supplied source IDs and actual held tickers."""
    rows = parsed.get('brief') if isinstance(parsed,dict) else None
    if not isinstance(rows,list) or len(rows)>6:
        raise ValueError('Portfolio analysis missing or oversized')
    sources = source_manifest(selected, auxiliary, article_id)
    insights = []
    for row in rows:
        event = row.get('event') if isinstance(row,dict) else None
        if isinstance(row,dict):
            row = [row.get(k) for k in ('kind','title','tickers','what_changed','portfolio_impact','watch_or_action','source_ids')]
        if not isinstance(row,list) or len(row)!=7:
            raise ValueError('Invalid portfolio analysis row')
        kind, title, tickers, fact, implication, action, refs = row
        if kind not in ('risk','opportunity','policy'):
            raise ValueError('Invalid portfolio analysis category')
        if not isinstance(tickers,list) or not tickers or not all(isinstance(t,str) and t in context for t in tickers):
            raise ValueError('Analysis references unheld ticker')
        if not isinstance(refs,list) or not refs or not all(isinstance(r,str) and r in sources for r in refs):
            raise ValueError('Analysis contains unknown evidence')
        if not all(isinstance(v,str) and v.strip() and len(v)<=1400 for v in (title,fact,implication,action)):
            raise ValueError('Incomplete portfolio implication or action')
        cited = [sources[r] for r in refs]
        eligible = {t for s in cited for t in s['affected_tickers']}
        if not set(tickers).issubset(eligible):
            raise ValueError('Portfolio conclusion exceeds evidenced exposure')
        if re.search(r'\b(?:validates|confirms|proves)\b.{0,65}\bthesis\b', implication, re.I):
            raise ValueError('Unsupported thesis confirmation')
        policy = [s for s in cited if s['kind']=='policy']
        if kind == 'policy' and re.search(r'no direct (?:business|portfolio) (?:link|connection)|does not qualify|omitted from', title+' '+implication+' '+action, re.I):
            raise ValueError('Policy conclusion has no direct portfolio connection')
        if kind == 'policy' and not policy:
            raise ValueError('Policy analysis requires an official record')
        def numbers(text):
            return {float(n.replace(',','')) for n in re.findall(r'(?<![\w])\d[\d,]*(?:\.\d+)?', text)}
        source_text = ' '.join(s['title']+' '+s['text'] for s in cited)
        if not numbers(fact).issubset(numbers(source_text)):
            raise ValueError('Unsupported number in portfolio fact')
        thesis_text = json.dumps({t:{k:context[t].get(k) for k in ('thesis','review_trigger')} for t in tickers})
        if not numbers(implication+' '+action).issubset(numbers(source_text+' '+thesis_text)):
            raise ValueError('Unsupported number in portfolio implication or action')
        if policy and not any(s.get('stage')=='Enacted' for s in policy):
            if re.search(r'has been enacted|is now law|signed into law|became law', fact, re.I):
                raise ValueError('Pending legislation misrepresented as law')
        # Headline/action-only legislative evidence belongs on the watch list,
        # never in confirmed risk/opportunity claims or tax savings estimates.
        if policy and not any(s.get('detail_available') for s in policy):
            kind = 'policy'
        exposure = None
        if all(context[t].get('weight_pct') is not None for t in set(tickers)):
            exposure = round(sum(context[t]['weight_pct'] for t in set(tickers)),2)
        insights.append({'kind':kind,'title':title,'tickers':list(dict.fromkeys(tickers)),
            'what_changed':fact,'portfolio_impact':implication,'watch_or_action':action,
            'source_ids':refs,'exposure_pct':exposure,'event':event,
            'evidence_level':'Policy watch — provisions unverified' if policy and not any(s.get('detail_available') for s in policy) else 'Reported facts · impact is analysis'})
    return {'insights':insights,'sources':sources, 'context_status':auxiliary,
            'context_hash':hashlib.sha256(json.dumps([context,auxiliary],sort_keys=True).encode()).hexdigest()}


def validate_analysis(parsed, selected, context, auxiliary, article_id):
    """Keep independently grounded conclusions; never publish rejected claims.

    If every proposed conclusion fails, retain the prior good briefing. A single
    invalid card must not discard the rest of a useful, validated portfolio brief.
    """
    rows = parsed.get('brief') if isinstance(parsed,dict) else None
    if not isinstance(rows,list) or len(rows)>6 or not rows:
        return _validate_analysis(parsed,selected,context,auxiliary,article_id)
    accepted, rejected, result = [], [], None
    for row in rows:
        try:
            result = _validate_analysis({'brief':[row]},selected,context,auxiliary,article_id)
            accepted.extend(result['insights'])
        except ValueError as exc:
            rejected.append(str(exc))
    if not accepted:
        raise ValueError('; '.join(dict.fromkeys(rejected)))
    result['insights'] = accepted
    result['validation'] = {'accepted':len(accepted),'withheld':len(rejected),'reasons':rejected}
    if rejected:
        result['context_status'] = dict(auxiliary, limitations=list(auxiliary.get('limitations',[]))+[
            f'{len(rejected)} proposed conclusion(s) withheld because the supplied evidence did not support them.'])
    return result
