"""Human identity from the authenticated host/application boundary, never model JSON."""
from __future__ import annotations

import os
import pwd
import sys
import time
import uuid
import ipaddress
import re

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


def dashboard_identity(handler):
    """Serve strips spoofed identity headers. Only its loopback-only backend is trusted.

    A public/wildcard listener, missing operator allowlist, tagged node, direct
    network request or shared token alone cannot create attributable decisions.
    """
    if os.environ.get('DEV_AGENT_IDENTITY_SOURCE') != 'tailscale-serve':
        raise ValueError('unique authenticated operator identity unavailable')
    try:
        peer = ipaddress.ip_address(handler.client_address[0])
        listener = ipaddress.ip_address(handler.server.server_address[0])
    except (AttributeError, ValueError, IndexError):
        raise ValueError('trusted proxy boundary unavailable') from None
    if not peer.is_loopback or not listener.is_loopback:
        raise ValueError('identity headers require a loopback-only proxy backend')
    values = handler.headers.get_all('Tailscale-User-Login', [])
    if len(values) != 1 or not re.fullmatch(r'[A-Za-z0-9_.+@-]{1,200}', values[0]):
        raise ValueError('unique human identity unavailable')
    operators = {v.strip() for v in os.environ.get('DEV_AGENT_OPERATORS', '').split(',') if v.strip()}
    if values[0] not in operators: raise ValueError('operator not authorized')
    return HumanIdentity(values[0], 'tailscale-serve-loopback', _PROOF)
