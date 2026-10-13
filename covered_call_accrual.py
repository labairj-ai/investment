"""CC Evidence Accrual Health — certification progress, promotion progress, evidence velocity."""
from __future__ import annotations
from collections import Counter
from datetime import timedelta
from time_utils import now_utc,parse_timestamp,TZ_EASTERN


def accrual_health(config,path=None,as_of=None):
    """Return a structured health report with three sections.

    - simulator_certification: usable N, required N, current cert status, exclusion breakdown.
    - promotion_progress: all gate requirements (current vs required), exclusion buckets, economic deltas.
    - evidence_velocity: 7- and 30-day windows for opportunities, pairs, chains; estimated days-to-N.
    """
    from covered_call_ledger import connect,migrate,config_digest
    from covered_call_virtual import metrics as virtual_metrics,SIMULATOR_VERSION,SIMULATOR_CONTRACT_VERSION
    from covered_call_evidence import promotion_report
    from covered_call_validation import certification,run_validation
    db=connect(path);migrate(db)
    as_of=as_of or now_utc()
    gate=config['promotion']
    val_cfg=config['simulator_validation']
    certificate=certification(config,path)

    # ── Simulator certification section ──────────────────────────────────────────
    cert_progress=_cert_progress(db,config,certificate,val_cfg)

    # ── Promotion progress section ────────────────────────────────────────────────
    promo=promotion_report(config,path,as_of=as_of)
    promo_progress=_promo_progress(promo,gate)

    # ── Evidence velocity section ─────────────────────────────────────────────────
    vm=virtual_metrics(db)
    velocity=_velocity(db,config,as_of,vm,promo,gate,certificate)

    db.close()
    return dict(
        as_of=as_of.isoformat(),
        simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        simulator_certification=cert_progress,
        promotion_progress=promo_progress,
        evidence_velocity=velocity,
    )


def _cert_progress(db,config,certificate,val_cfg):
    from covered_call_validation import SIMULATOR_VERSION,SIMULATOR_CONTRACT_VERSION,simulator_contract_hash
    from covered_call_ledger import config_digest
    rows=db.execute('SELECT run_json FROM cc_simulator_validation_runs ORDER BY timestamp DESC').fetchall()
    latest_run=None
    if rows:
        import json
        latest_run=json.loads(rows[0][0])
    required_n=val_cfg.get('minimum_n',20)
    usable_n=latest_run.get('n',0) if latest_run else 0
    return dict(
        certified=certificate is not None,
        certification_id=certificate['id'] if certificate else None,
        simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        simulator_contract_hash=simulator_contract_hash(config),
        usable_n=usable_n,
        required_n=required_n,
        pct_of_required=round(usable_n/required_n*100,1) if required_n else None,
        latest_run_verdict=latest_run.get('verdict') if latest_run else None,
        latest_run_id=latest_run.get('id') if latest_run else None,
        exclusions=latest_run.get('exclusions',{}) if latest_run else {},
        simulator_bias=latest_run.get('simulator_bias') if latest_run else None,
    )


def _promo_progress(promo,gate):
    n=promo['n'];divergent=promo.get('divergent_n',0);days=promo.get('prospective_days',0)
    alpha=promo.get('alpha_improvement')
    mgmt=promo.get('management_cost_delta')
    exec_=promo.get('execution_cost_delta')
    roll=promo.get('roll_rate_delta')
    cal=promo.get('calibration',{})
    preliminary=not promo['eligible']
    def prelim(v):
        return dict(value=v,label='PRELIMINARY — NOT PROMOTION ELIGIBLE') if preliminary and v is not None else dict(value=v)
    return dict(
        eligible=promo['eligible'],
        failures=promo.get('failures',[]),
        n=dict(current=n,required=gate['minimum_n'],pct=round(n/gate['minimum_n']*100,1) if gate['minimum_n'] else None),
        divergent_n=dict(current=divergent,required=gate['minimum_divergent_n'],pct=round(divergent/gate['minimum_divergent_n']*100,1) if gate.get('minimum_divergent_n') else None),
        prospective_days=dict(current=days,required=gate['minimum_days'],pct=round(days/gate['minimum_days']*100,1) if gate['minimum_days'] else None),
        total_opportunities=promo.get('total_opportunities',0),
        excluded_n=promo.get('excluded_n',0),
        exclusions=promo.get('exclusions',{}),
        simulator_certified=promo.get('simulator_certification_id') is not None,
        economics=dict(
            alpha_improvement=prelim(alpha),
            management_cost_delta=prelim(mgmt),
            execution_cost_delta=prelim(exec_),
            roll_rate_delta=prelim(roll),
            calibration=cal,
        ),
    )


def _velocity(db,config,as_of,vm,promo,gate,certificate):
    from covered_call_ledger import config_digest
    from covered_call_virtual import SIMULATOR_CONTRACT_VERSION
    import json
    windows={'7d':7,'30d':30}
    cutoffs={k:as_of-timedelta(days=v) for k,v in windows.items()}

    # New forward opportunities per window (prospective, current config)
    current_hash=config_digest(config)
    decisions=db.execute('SELECT id,timestamp,config_hash,prospective FROM cc_decisions ORDER BY timestamp').fetchall()
    opps={k:0 for k in windows}
    for d in decisions:
        if not d['prospective'] or d['config_hash']!=current_hash:continue
        ts=parse_timestamp(d['timestamp'])
        for k,cut in cutoffs.items():
            if ts>=cut:opps[k]+=1

    # New completed paired outcomes per window (using exclusion_details timestamps)
    pair_completed={k:0 for k in windows}
    for eid in (promo.get('cohort_ids') or []):
        row=db.execute('SELECT timestamp FROM cc_decisions WHERE id=?',(eid,)).fetchone()
        if not row:continue
        ts=parse_timestamp(row[0])
        for k,cut in cutoffs.items():
            if ts>=cut:pair_completed[k]+=1

    # Divergent pairs per window
    divergent_completed={k:0 for k in windows}
    details=promo.get('exclusion_details') or []
    all_pairs=db.execute('SELECT id,timestamp,divergence FROM cc_decisions WHERE prospective=1 AND config_hash=?',(current_hash,)).fetchall()
    cohort_set=set(promo.get('cohort_ids') or [])
    for d in all_pairs:
        if d['id'] not in cohort_set:continue
        if d['divergence'] in ('SAME_NO_CALL','SAME_CONTRACT',None,''):continue
        ts=parse_timestamp(d['timestamp'])
        for k,cut in cutoffs.items():
            if ts>=cut:divergent_completed[k]+=1

    # Virtual chains per window
    chains=vm.get('chains',[])
    opened={k:0 for k in windows};completed={k:0 for k in windows};censored={k:0 for k in windows}
    for c in chains:
        row=db.execute('SELECT created_at FROM cc_virtual_chains WHERE id=?',(c['chain_id'],)).fetchone()
        if not row:continue
        ts=parse_timestamp(row[0])
        for k,cut in cutoffs.items():
            if ts>=cut:
                opened[k]+=1
                st=c['state']['status']
                if st not in ('OPEN','AWAIT_ASSIGNMENT'):completed[k]+=1
                if st=='VERSION_CENSORED':censored[k]+=1

    # Estimated days to minimum N (promotion)
    min_n=gate['minimum_n'];current_n=promo['n']
    remaining=max(0,min_n-current_n)
    rate_30=pair_completed['30d']/30 if pair_completed['30d'] else 0
    same_contract=not any(c.get('simulator_contract_version','')!=SIMULATOR_CONTRACT_VERSION for c in chains if c['state']['status'] in ('OPEN','AWAIT_ASSIGNMENT'))
    est_days_to_n=None
    if rate_30>0 and remaining>0 and same_contract and certificate is not None:
        est_days_to_n=round(remaining/rate_30,0)

    return dict(
        new_opportunities=opps,
        new_completed_pairs=pair_completed,
        new_divergent_pairs=divergent_completed,
        chains_opened=opened,
        chains_completed=completed,
        chains_version_censored=censored,
        estimated_days_to_minimum_n=est_days_to_n,
        estimated_days_to_n_note='DIAGNOSTIC_ONLY — must not influence scoring or promotion' if est_days_to_n is not None else None,
        velocity_basis='TRAILING_30D_PAIRS_PER_DAY',
        velocity_rate_30d=round(rate_30,4),
    )
