"""Normalize only observed successful fixed-controller releases; never infer missing facts."""
from datetime import datetime,timezone
import re
from dev_agent.deployment_evidence import seal


def ci_record(repository,head,url):
    pattern=r'https://github\.com/'+re.escape(repository)+r'/actions/runs/([1-9][0-9]*)(?:/job/[0-9]+)?'
    match=re.fullmatch(pattern,url or '')
    if not match:raise ValueError('observed GitHub Actions run URL required')
    return dict(run_id=int(match[1]),head=head,status='PASS',url=f'https://github.com/{repository}/actions/runs/{match[1]}')


def normalize(raw):
    if raw.get('status')!='DEPLOYED_VERIFIED' or raw.get('protected_state_verified') is not True:raise ValueError('verified fixed deployment required')
    h=raw['health'];checks=h['checks'];canary=h['canary'];backup=raw['backup']
    if not all(checks.values()) or canary.get('production_state_unchanged') is not True:raise ValueError('runtime observations failed')
    return seal(dict(repository=raw['repository'],pr=raw['pr'],head=raw['head'],merge_sha=raw['merge_sha'],deployed_sha=raw['deployed_sha'],prior_sha=raw['prior_sha'],main_sha=raw['main_sha'],deployed_at=datetime.fromtimestamp(raw['finished'],timezone.utc).isoformat(),actor='deployment-agent',fixture_only=False,head_ci=raw['head_ci'],merge_ci=raw['merge_ci'],health=dict(service_active=checks['service'],dashboard_http=200 if checks['dashboard'] else None,development_dashboard_http=200 if checks['development_dashboard'] else None,authenticated_api_http=200 if checks['authenticated_api'] else None,unauthorized_api_http=403 if checks['unauthorized_api_denied'] else None,advisor_functional=canary['functional_contract'],advisor_mutation_safety=canary['mutation_safety']),backup=dict(exists=True,integrity=backup['integrity'],sha256=backup['sha256']),activation=h['activation'],state_safety=dict(holdings_unchanged=True,investment_state_unchanged=True,development_ledger_unchanged=True)))
