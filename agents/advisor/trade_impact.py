"""Pure cash/NAV/share arithmetic using only the captured context."""
from decimal import Decimal
from .contracts import finite


def simulate(request, context):
    errors=[]; result=[]
    nav=context.get('nav'); cash=context.get('cash')
    if not finite(nav) or nav<=0: errors.append('NAV_UNAVAILABLE')
    if request.needs_clarification: errors.extend(request.issues)
    seen=set()
    for leg in (() if request.needs_clarification else request.legs):
        if not finite(leg.quantity) or leg.quantity<0:
            errors.append("INVALID_QUANTITY"); continue
        ticker=leg.ticker
        if ticker in seen: errors.append('DUPLICATE_TICKER:'+ticker); continue
        seen.add(ticker)
        if ticker not in context.get('holdings',{}) and context.get('sources',{}).get('holdings',{}).get('status')!='AVAILABLE':
            errors.append('CURRENT_POSITION_UNAVAILABLE:'+ticker); continue
        holding=context.get('holdings',{}).get(ticker,{})
        shares=holding.get('shares',0)
        price=context.get('prices',{}).get(ticker)
        if not finite(price) or price<=0: errors.append('MISSING_PRICE:'+ticker); continue
        if not finite(shares) or shares<0: errors.append('INVALID_POSITION:'+ticker); continue
        before=Decimal(str(shares)); qty=Decimal(str(leg.quantity)); px=Decimal(str(price))
        if leg.semantics=='TARGET_POSITION':
            delta=qty-before
            if (leg.side=='SELL' and delta>0) or (leg.side=='BUY' and delta<0): errors.append('CONTRADICTORY_TARGET:'+ticker)
        elif leg.semantics=='TRADE_DELTA' and leg.side in {'BUY','SELL'}:
            delta=qty if leg.side=='BUY' else -qty
        else: errors.append('INVALID_LEG:'+ticker); continue
        after=before+delta
        if after<0: errors.append('OVERSELL:'+ticker)
        reserved=sum(float(i.get('quantity') or 0) for i in context.get('open_intents') or [] if i.get('symbol')==ticker and i.get('side')=='SELL')
        calls=sum(int(c['contracts']) for c in context.get('covered_calls') or [] if c['ticker']==ticker)
        if delta<0 and -delta>before-Decimal(str(reserved)): errors.append('COMMITTED_SHARES:'+ticker)
        if delta<0 and after<Decimal(calls*100): errors.append('OPEN_CC_COVERAGE_CONFLICT:'+ticker)
        notional=delta*px
        layer=holding.get('layer_num')
        if layer is None:
            ranked=next((r for r in context.get('candidate_ranks',[]) if r['ticker']==ticker),{})
            layer=ranked.get('layer_rec')
        if layer not in context.get('layer_targets',{}): errors.append('LAYER_UNAVAILABLE:'+ticker)
        result.append(dict(ticker=ticker,side='BUY' if delta>0 else 'SELL' if delta<0 else 'NO_CHANGE',
          reference_price=float(px),delta_shares=float(delta),before_shares=float(before),after_shares=float(after),
          notional=float(abs(notional)),cash_effect=float(-notional),layer=layer,
          position_value_before=float(before*px),position_value_after=float(after*px),
          weight_before=float(before*px)/nav*100 if finite(nav) and nav>0 else None,
          weight_after=float(after*px)/nav*100 if finite(nav) and nav>0 else None,
          cc_contracts_before=int(before//100),cc_contracts_after=max(0,int(after//100)),
          cc_contract_change=max(0,int(after//100))-int(before//100),open_call_contracts=calls))
    result.sort(key=lambda x:x['ticker'])
    buys=sum(Decimal(str(r['notional'])) for r in result if r['side']=='BUY')
    sells=sum(Decimal(str(r['notional'])) for r in result if r['side']=='SELL')
    change=sells-buys
    layer_changes={}
    for row in result:
        if row['layer'] is not None and finite(nav) and nav>0:
            layer_changes[row['layer']]=layer_changes.get(row['layer'],0)-row['cash_effect']/nav*100
    layer_after={str(k):context.get('layer_weights',{}).get(k,0)+layer_changes.get(k,0) for k in set(context.get('layer_weights',{}))|set(layer_changes)}
    return dict(valid=not errors,errors=sorted(set(errors)),legs=result,gross_buys=float(buys),gross_sells=float(sells),
      net_cash_requirement=float(buys-sells),cash_effect=float(change),cash_before=cash,
      cash_after=float(Decimal(str(cash))+change) if finite(cash) else None,
      nav_before=nav,nav_after=nav,layer_weight_change=layer_changes,layer_weights_after=layer_after,
      cash_weight_change=float(change)/nav*100 if finite(nav) and nav>0 else None,
      assumptions=['NAV scope: '+context.get('nav_scope','CAPTURED_FIXTURE_NAV'), 'Reference-price preview only; no fill or executable limit price.',
        'Fees and slippage excluded; modeled stock value change plus cash change equals zero.',
        'Cash sufficiency requires captured account state; unknown cash is not treated as available.'])
