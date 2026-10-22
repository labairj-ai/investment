"""Operator-only image build; the agent runtime has no image provisioning authority."""
import argparse
import re
import subprocess
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--tag',required=True)
a=p.parse_args()
if not re.fullmatch(r'(docker.io/library/)?python:[A-Za-z0-9_.-]+@sha256:[a-f0-9]{64}',a.base):
    raise SystemExit('reviewed immutable Python base digest required')
if not re.fullmatch(r'ghcr.io/labairj-ai/investment-validator:[A-Za-z0-9_.-]+',a.tag):
    raise SystemExit('approved validator registry required')
subprocess.run(['docker','build','--build-arg','APPROVED_BASE_IMAGE='+a.base,'-t',a.tag,str(Path(__file__).resolve().parent)],check=True)
print('Review the built image and publish it out-of-band; configure only its registry digest for validation.')
