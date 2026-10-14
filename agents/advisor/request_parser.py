"""Extraction only: no trade math, writes, risk or actionability fields."""
from __future__ import annotations
import re
from dataclasses import asdict
from portfolio_positions import _normalize
from .contracts import AdvisorDecisionRequest, AdvisorTradeLegRequest, finite

TICKER=r'([A-Z][A-Z0-9./-]{0,12})'
QTY=r'(\d+(?:\.\d+)?)'


def _leg(text):
    text=text.strip().rstrip('.!?')
    m=re.fullmatch(r'(?:get|bring|take)\s+'+TICKER+r'\s+(?:up\s+)?to\s+'+QTY+r'(?:\s+shares)?',text,re.I)
    if m: return AdvisorTradeLegRequest(_normalize(m[1]),'TARGET_POSITION',float(m[2]))
    m=re.fullmatch(r'(buy|add|sell|trim)\s+'+QTY+r'\s+(?:shares\s+(?:of\s+)?)?'+TICKER,text,re.I)
    if m: return AdvisorTradeLegRequest(_normalize(m[3]),'TRADE_DELTA',float(m[2]),'BUY' if m[1].lower() in {'buy','add'} else 'SELL')
    m=re.fullmatch(r'(?:sell|exit)\s+(?:all\s+)?'+TICKER+r'(?:\s+shares)?',text,re.I)
    if m: return AdvisorTradeLegRequest(_normalize(m[1]),'TARGET_POSITION',0,'SELL')
    return None


def _validate(raw,intent,legs,context,model=None,constraints=()):
    issues=[]
    if intent not in {'TARGET_POSITION','TRADE_DELTA','REALLOCATE','RESEARCH'}: issues.append('INVALID_INTENT')
    known=set(context.get('holdings',{}))|{_normalize(c['ticker']) for c in context.get('candidates') or []}
    for leg in legs:
        if leg.ticker not in known: issues.append('UNKNOWN_TICKER:'+leg.ticker)
        if leg.semantics not in {'TARGET_POSITION','TRADE_DELTA'}: issues.append('INVALID_QUANTITY_SEMANTICS')
        if not finite(leg.quantity) or leg.quantity<0 or (leg.semantics=='TRADE_DELTA' and leg.quantity==0): issues.append('INVALID_QUANTITY')
        if leg.side not in {'BUY','SELL','TARGET'} or (leg.semantics=='TRADE_DELTA' and leg.side=='TARGET'): issues.append('CONTRADICTORY_SIDE')
    if len({l.ticker for l in legs})!=len(legs): issues.append('DUPLICATE_TICKER')
    if not legs and intent!='RESEARCH': issues.append('QUANTITY_SEMANTICS_UNRESOLVED')
    return AdvisorDecisionRequest(raw,intent,tuple(legs),tuple(constraints),model=model,
                                  needs_clarification=bool(issues),issues=tuple(issues))


def parse_request(raw, context, *, extractor=None, use_llm=True):
    if not isinstance(raw,str) or not raw.strip() or len(raw)>8000:
        return AdvisorDecisionRequest(str(raw)[:8000],'RESEARCH',needs_clarification=True,issues=('INVALID_REQUEST',))
    raw=raw.strip()
    parts=re.split(r'\s+and\s+(?:use\s+(?:it|the proceeds|proceeds)\s+to\s+)?',raw,flags=re.I)
    legs=[_leg(part) for part in parts]
    if all(legs):
        if len(legs)>1 and re.search(r'\band\s+use\s+',raw,re.I):
            if legs[0].side!='SELL':
                return AdvisorDecisionRequest(raw,'REALLOCATE',needs_clarification=True,issues=('FUNDING_SEMANTICS_UNRESOLVED',))
            legs=[legs[0]]+[AdvisorTradeLegRequest(l.ticker,l.semantics,l.quantity,l.side,legs[0].ticker) for l in legs[1:]]
        return _validate(raw,'REALLOCATE' if len(legs)>1 else legs[0].semantics,legs,context)
    missing_quantity = re.fullmatch(r'(?:buy|add)\s+'+TICKER,raw,re.I) or re.fullmatch(TICKER+r'\s+(?:buy|add)',raw,re.I)
    if missing_quantity:
        return AdvisorDecisionRequest(raw,'TRADE_DELTA',needs_clarification=True,
                                      issues=('QUANTITY_REQUIRED:'+_normalize(missing_quantity[1]),))
    if not use_llm:
        return AdvisorDecisionRequest(raw,'RESEARCH',needs_clarification=True,issues=('QUANTITY_SEMANTICS_UNRESOLVED',))
    import ollama_client
    model=ollama_client.DEFAULT_MODEL
    extract=extractor or ollama_client.generate_structured
    try:
        data=extract(prompt='Extract ONLY the user request. Do not calculate quantities, prices, risk or approval. '
          'intent is TARGET_POSITION, TRADE_DELTA, REALLOCATE or RESEARCH. Each leg contains a source_text '
          'copied verbatim from the request, e.g. "get IGV to 100 shares" or "buy 17 IGV". '
          'Use needs_clarification=true if the request cannot be represented without guessing.\nUSER TEXT:\n'+raw,
          schema={'intent':'','legs':[],'needs_clarification':False},model=model,temperature=0,num_predict=800,retries=1)
        if set(data)-{'intent','legs','needs_clarification'} or type(data.get('needs_clarification')) is not bool:
            raise ValueError('INVALID_EXTRACTION_FIELDS')
        if data['needs_clarification']: raise ValueError('QUANTITY_SEMANTICS_UNRESOLVED')
        parsed=[]
        for item in data['legs']:
            if set(item)!={'source_text'} or not isinstance(item['source_text'],str) or item['source_text'] not in raw:
                raise ValueError('UNSUPPORTED_EXTRACTION')
            leg=_leg(item['source_text'])
            if leg is None: raise ValueError('QUANTITY_SEMANTICS_UNRESOLVED')
            parsed.append(leg)
        intent=data['intent']
        if parsed and intent!=('REALLOCATE' if len(parsed)>1 else parsed[0].semantics): raise ValueError('INTENT_MISMATCH')
        return _validate(raw,intent,parsed,context,model)
    except Exception:
        return AdvisorDecisionRequest(raw,'RESEARCH',model=model,needs_clarification=True,issues=('EXTRACTION_UNAVAILABLE_OR_AMBIGUOUS',))
