"""Human identity from the authenticated host/application boundary, never model JSON."""
from __future__ import annotations

import os
import pwd
import sys
import time
import uuid

_PROOF=object()


class HumanIdentity:
    def __init__(self, actor, source, proof=None):
        if proof is not _PROOF or not actor: raise ValueError('authenticated identity required')
        self.actor,self.source=actor,source

    def audit(self):
        return dict(actor=self.actor, authentication_source=self.source, authenticated_at=time.time(), nonce=str(uuid.uuid4()))


def cli_identity():
    if not sys.stdin.isatty(): raise ValueError('explicit interactive human CLI invocation required')
    return HumanIdentity(pwd.getpwuid(os.getuid()).pw_name,'os-interactive-cli',_PROOF)


def dashboard_identity():
    # Called only after server-side token and same-origin checks; no payload actor.
    return HumanIdentity('dashboard-operator','authenticated-dashboard',_PROOF)
