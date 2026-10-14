#!/usr/bin/env python3
"""CI check: verify CC V3 behavioral contract consistency.

Fails with exit code 1 if:
  - .cc_contract_baseline.json is absent (fail closed)
  - .cc_contract_baseline.json is malformed or unknown schema
  - engine_hash or simulator_contract_hash changed without a version bump
  - behavioral hash changed without a change manifest in cc_change_manifests/

Run: python3 scripts/check_cc_contract.py [--update-baseline]

Local bootstrap (one-time, never in CI):
  python3 scripts/check_cc_contract.py --update-baseline
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _in_ci():
    return os.environ.get('GITHUB_ACTIONS') == 'true' or os.environ.get('CI') == 'true'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-baseline', action='store_true',
                        help='Write current state as new baseline (local use only — never in CI)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of human-readable')
    parser.add_argument('--baseline-file', default=None,
                        help='Override baseline file path (for testing only)')
    parser.add_argument('--manifests-dir', default=None,
                        help='Override manifests directory path (for testing only)')
    parser.add_argument('--prior-ref', help='Exact trusted prior Git commit SHA')
    parser.add_argument('--trusted-prior-file', help='Explicit prior baseline for offline validation')
    parser.add_argument('--fingerprint-inventory', action='store_true', help='List canonical protected component names')
    args = parser.parse_args()

    if args.update_baseline:
        if _in_ci():
            print('[CC_CONTRACT] ERROR: --update-baseline must not be invoked in CI.',
                  file=sys.stderr)
            print('Baseline updates require a local intentional commit.', file=sys.stderr)
            return 1
        from strategy_config import CC_V3_CONFIG
        from covered_call_change_control import write_baseline
        state = write_baseline(CC_V3_CONFIG, path=args.baseline_file)
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print('[CC_CONTRACT] Baseline updated:')
            print(f'  schema_version={state["schema_version"]}')
            print(f'  model_version={state["model_version"]}')
            print(f'  simulator_contract_version={state["simulator_contract_version"]}')
            print(f'  engine_hash={state["engine_hash"][:16]}...')
            print(f'  simulator_contract_hash={state["simulator_contract_hash"][:16]}...')
        return 0

    expected = None
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    if _in_ci():
        try:
            if not event_path:
                raise ValueError('CI event authority required: missing GITHUB_EVENT_PATH')
            if args.trusted_prior_file or args.prior_ref:
                raise ValueError('CI computes authority; caller prior-ref/prior-file inputs are prohibited')
            event = json.loads(Path(event_path).read_text())
            if not isinstance(event, dict):
                raise ValueError('event payload must be a JSON object')
            if os.environ.get('GITHUB_EVENT_NAME') == 'pull_request':
                expected = event['pull_request']['base']['sha']
            elif os.environ.get('GITHUB_EVENT_NAME') == 'push':
                expected = event['before']
            else:
                raise ValueError('unsupported CI event')
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{40}', expected) or expected == '0' * 40:
                raise ValueError('no trusted prior; initialize baseline locally before enabling CI')
            args.prior_ref = expected
        except (KeyError, TypeError, ValueError, OSError) as exc:
            print(json.dumps(dict(ok=False, findings=[f'TRUSTED_PRIOR_ERROR: {exc}'])))
            return 1

    from strategy_config import CC_V3_CONFIG
    from covered_call_change_control import check_contract_consistency

    from pathlib import Path as _Path
    result = check_contract_consistency(CC_V3_CONFIG,
        _baseline_file=args.baseline_file,
        trusted_prior_file=args.trusted_prior_file, prior_ref=args.prior_ref,
        expected_prior_ref=expected,
        _manifests_dir=_Path(args.manifests_dir) if args.manifests_dir else None)

    if args.fingerprint_inventory:
        from covered_call_fingerprint import inventory
        result['fingerprint_inventory'] = inventory()

    if args.json:
        safe = dict(result, current={k: v[:16]+'...' if isinstance(v, str) and len(v) > 20 else v
                                      for k, v in result['current'].items()})
        print(json.dumps(safe, indent=2, default=str))
    else:
        status = 'OK' if result['ok'] else 'FAIL'
        print(f'[CC_CONTRACT] {status}')
        print(f'  trusted_prior_ref={result.get("trusted_prior_ref")}')
        print(f'  fingerprint_version={result["current"].get("fingerprint_version", "unavailable")}  definition_migration={result.get("fingerprint_definition_migration", False)}')
        for side in ('baseline', 'current'):
            state = result.get(side) or {}
            print(f'  {side}: engine={str(state.get("engine_hash", ""))[:16]} simulator={str(state.get("simulator_contract_hash", ""))[:16]}')
        if result.get('baseline_missing'):
            print('  Required baseline is missing — restore reviewed prior history; repository bootstrap is local only')
        elif result.get('baseline_malformed'):
            print('  Baseline is malformed — restore the reviewed trusted state; regeneration cannot authorize a transition')
        else:
            hc = result['hash_changed']
            vb = result['version_bumped']
            hm = result['has_manifest']
            print(f'  hash_changed={hc}  version_bumped={vb}  has_manifest={hm}')
            am = result.get('applicable_manifest')
            if am:
                print(f'  applicable_manifest={am.get("manifest_id")}  path={am["path"].name}')
        if args.fingerprint_inventory:
            print(json.dumps(result['fingerprint_inventory'], indent=2))
        for finding in result['findings']:
            print(f'  FINDING: {finding}')

    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
