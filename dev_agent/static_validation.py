"""Private supervisor client for the separate L0-only static oracle protocol.

A static PASS cannot substitute for mandatory executable validation or technical
certification. Candidate/Builder processes must never inherit this client key.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import stat
import time
from .result_collector import canonical

PROTOCOL='bounded-static-oracle-1'
INVENTORY=['bounded-regular-text','no-active-markup','safe-document-path','utf8-no-control']


def verify(envelope,request,*,key,runtime_identity,validator_source_digest,now=None):
    now=time.time() if now is None else now
    if not isinstance(envelope,dict) or set(envelope)!={'receipt','signature'} or len(key)<32:
        raise ValueError('signed static oracle envelope required')
    receipt=envelope['receipt']
    if not hmac.compare_digest(hmac.new(key,canonical(receipt),hashlib.sha256).hexdigest(),str(envelope['signature'])):
        raise ValueError('static oracle signature mismatch')
    b=receipt.get('binding',{})
    if (receipt.get('protocol')!=PROTOCOL or receipt.get('status')!='PASS'
            or receipt.get('fixture_only') is not False or receipt.get('grants_pytest_authority') is not False
            or type(receipt.get('process_exit')) is not int or receipt['process_exit']!=0
            or receipt.get('timed_out') is not False or receipt.get('containment')!='no-candidate-code-execution'
            or receipt.get('expected')!=INVENTORY
            or receipt.get('results')!=[dict(id=i,status='PASS') for i in INVENTORY]):
        raise ValueError('independently observed complete static PASS required')
    if (any(b.get(k)!=request.get(k) for k in ('repository','base','head'))
            or request.get('protocol')!=PROTOCOL or b.get('oracle_protocol')!=PROTOCOL
            or b.get('command_class')!='L0_STATIC_TEXT' or b.get('runtime_identity')!=runtime_identity
            or b.get('validator_source_digest')!=validator_source_digest):
        raise ValueError('static oracle context/runtime mismatch')
    import re
    for field in ('candidate_source_tree_digest','trusted_test_tree_digest','trusted_inventory_digest'):
        if not re.fullmatch('[a-f0-9]{64}',str(b.get(field,''))):raise ValueError('tree/inventory identity required')
    if b['trusted_inventory_digest']!=hashlib.sha256(canonical(INVENTORY)).hexdigest():
        raise ValueError('trusted static inventory mismatch')
    start=receipt.get('started');end=receipt.get('ended')
    if type(start) not in (int,float) or type(end) not in (int,float) or not 0<=now-end<=60 or not 0<=end-start<=30:
        raise ValueError('fresh bounded static observation required')
    return dict(status='PASS',protocol=PROTOCOL,binding=b,receipt_sha256=hashlib.sha256(canonical(receipt)).hexdigest(),
                grants_pytest_authority=False,grants_activation=False)


def observe(socket_path,key_path,request,*,runtime_identity,validator_source_digest):
    sock,keyfile=Path(socket_path),Path(key_path)
    for path,socket_kind in ((sock,True),(keyfile,False)):
        info=path.lstat()
        if (path.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077
                or (not stat.S_ISSOCK(info.st_mode) if socket_kind else not stat.S_ISREG(info.st_mode))):
            raise ValueError('private supervisor static oracle endpoint/key required')
    key=keyfile.read_bytes();raw=canonical(request)+b'\n'
    if len(raw)>4096:raise ValueError('bounded static request required')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(30);channel.connect(str(sock));channel.sendall(raw);channel.shutdown(socket.SHUT_WR)
        data=bytearray()
        while True:
            part=channel.recv(min(65536,2_000_001-len(data)))
            if not part:break
            data.extend(part)
            if len(data)>2_000_000:raise ValueError('oversized static oracle result')
    from .structured_json import loads
    return verify(loads(data),request,key=key,runtime_identity=runtime_identity,validator_source_digest=validator_source_digest)


def installed(root,base,head):
    """Trusted supervisor adapter; no candidate-configurable endpoint or identity.

    Environment is supplied to the installed supervisor outside candidate source;
    none of these values or the signing key enter Builder/container environments.
    This proves static scope only. All mandatory test/CI gates remain separate.
    """
    from .owner_review import policy
    import re
    source=os.environ.get('DEV_AGENT_STATIC_ORACLE_SOURCE_SHA256','')
    runtime=os.environ.get('DEV_AGENT_STATIC_ORACLE_RUNTIME_IDENTITY','')
    if not re.fullmatch('[a-f0-9]{64}',source) or not re.fullmatch('python@sha256:[a-f0-9]{64}',runtime):
        raise ValueError('installed L0 validator identity unavailable')
    request=dict(protocol=PROTOCOL,repository=policy()['repository'],base=base,head=head)
    return observe(os.environ['DEV_AGENT_STATIC_ORACLE_SOCKET'],os.environ['DEV_AGENT_STATIC_ORACLE_KEY_FILE'],
                   request,runtime_identity=runtime,validator_source_digest=source)
