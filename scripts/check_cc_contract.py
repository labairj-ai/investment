#!/usr/bin/env python3
"""CI check: verify CC V3 behavioral contract consistency.

Fails with exit code 1 if:
  - engine_hash or simulator_contract_hash changed without a version bump
  - behavioral hash changed without a change manifest in cc_change_manifests/

Run: python3 scripts/check_cc_contract.py [--update-baseline]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-baseline', action='store_true',
                        help='Write current state as new baseline (do this after intentional version bumps)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of human-readable')
    args = parser.parse_args()

    from strategy_config import CC_V3_CONFIG
    from covered_call_change_control import check_contract_consistency, write_baseline, current_contract_state

    if args.update_baseline:
        state = write_baseline(CC_V3_CONFIG)
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print('[CC_CONTRACT] Baseline updated:')
            print(f'  model_version={state["model_version"]}')
            print(f'  simulator_contract_version={state["simulator_contract_version"]}')
            print(f'  engine_hash={state["engine_hash"][:16]}...')
            print(f'  simulator_contract_hash={state["simulator_contract_hash"][:16]}...')
        return 0

    result = check_contract_consistency(CC_V3_CONFIG)

    if args.json:
        safe = dict(result, current={k: v[:16]+'...' if isinstance(v, str) and len(v) > 20 else v
                                      for k, v in result['current'].items()})
        print(json.dumps(safe, indent=2, default=str))
    else:
        status = 'OK' if result['ok'] else 'FAIL'
        print(f'[CC_CONTRACT] {status}')
        if result['baseline'] is None:
            print('  No baseline on file — first deployment. Run with --update-baseline.')
            return 0
        hc = result['hash_changed']
        vb = result['version_bumped']
        print(f'  hash_changed={hc}  version_bumped={vb}  has_manifest={result["has_manifest"]}')
        for finding in result['findings']:
            print(f'  FINDING: {finding}')

    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
