"""Read-only disposition scenarios using canonical IRS calendar semantics."""
from datetime import date
from decimal import Decimal
from tax_utils import is_long_term
from .contracts import finite


def plan_disposition(lots, quantity, price, as_of, *, strategy='FIFO', rates=None, broker_capability='UNKNOWN'):
    if not finite(quantity) or quantity<=0 or not finite(price) or price<=0:
        return {'valid':False,'errors':['INVALID_DISPOSITION'],'selected':[],'unsatisfied_quantity':quantity}
    day=date.fromisoformat(as_of)
    available=[]
    errors=[]
    for lot in lots or []:
        try:
            purchased=date.fromisoformat(lot['purchase_date'])
            if purchased>day or not finite(lot['shares']) or lot['shares']<0 or not finite(lot['cost_per_share']) or lot['cost_per_share']<0:
                raise ValueError('invalid lot')
            available.append(dict(lot,long_term=is_long_term(purchased,day)))
        except (ValueError,KeyError,TypeError): errors.append('INVALID_LOT')
    if strategy=='FIFO': key=lambda l:(l['purchase_date'],l['id'])
    elif strategy=='LONG_TERM_FIRST': key=lambda l:(not l['long_term'],l['purchase_date'],l['id'])
    elif strategy=='MINIMUM_REALIZED_GAIN': key=lambda l:(price-l['cost_per_share'],l['purchase_date'],l['id'])
    else: return {'valid':False,'errors':['UNKNOWN_LOT_STRATEGY'],'selected':[]}
    remaining=Decimal(str(quantity)); selected=[]; st=Decimal(0); lt=Decimal(0)
    for lot in sorted(available,key=key):
        qty=min(remaining,Decimal(str(lot['shares'])))
        if qty<=0: continue
        gain=qty*(Decimal(str(price))-Decimal(str(lot['cost_per_share'])))
        if lot['long_term']: lt+=gain
        else: st+=gain
        selected.append(dict(lot_id=lot['id'],quantity=float(qty),term='LT' if lot['long_term'] else 'ST',gain_loss=float(gain)))
        remaining-=qty
        if remaining<=0: break
    if remaining: errors.append('INSUFFICIENT_LOTS')
    result=dict(valid=not errors,strategy=strategy,selected=selected,st_gain_loss=float(st),lt_gain_loss=float(lt),
      gross_gain_loss=float(st+lt),unsatisfied_quantity=float(remaining),errors=errors,
      broker_lot_selection_capability=broker_capability,broker_will_honor=False)
    if rates is not None:
        if set(rates)!={'st','lt'} or any(not finite(v) or not 0<=v<=1 for v in rates.values()):
            result.update(valid=False,errors=errors+['INVALID_EXPLICIT_TAX_RATE_POLICY'])
        else:
            result['estimated_federal_tax_drag']=float(st*Decimal(str(rates['st']))+lt*Decimal(str(rates['lt'])))
            result['tax_assumptions']='Explicit federal rates only; excludes state/local, NIIT and loss-deduction limitations.'
    return result


def analyze(impact,context):
    output={}
    for leg in impact['legs']:
        if leg['side']=='SELL':
            lots=[l for l in context.get('lots') or [] if l['ticker']==leg['ticker']]
            output[leg['ticker']]={s:plan_disposition(lots,-leg['delta_shares'],leg['reference_price'],context['as_of'],strategy=s)
                                  for s in ('FIFO','LONG_TERM_FIRST','MINIMUM_REALIZED_GAIN')}
    return output
