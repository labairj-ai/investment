#!/usr/bin/env python3
"""Installed-role permission audit; never restarts services or changes ACLs."""
import json
import sys
sys.path.insert(0,'/opt/investment-deployment-controller')
from deployment_agent.__main__ import configuration
from deployment_agent.installation import preflight

if __name__=='__main__':
    try:result=preflight(configuration())
    except Exception as error:result=dict(status='NOT READY',reason='deployment installation preflight is unavailable',diagnostic=type(error).__name__)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='READY' else 1)
