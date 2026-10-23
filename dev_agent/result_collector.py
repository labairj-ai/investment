"""Host-only final receipt writer. Candidate output is never PASS authority.

An isolated oracle adapter must attest observed outcomes independently of the
candidate interpreter. Its key/configuration stay outside all candidate mounts.
Without that adapter, pytest results are diagnostic and certification is UNAVAILABLE.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def normalize(raw,expected,*,returncode,timed_out=False):
    if timed_out or returncode!=0:return dict(status='FAIL',reason='candidate process failed, crashed or timed out')
    if not isinstance(raw,bytes) or len(raw)>2_000_000:return dict(status='FAIL',reason='bounded raw result required')
    try:
        import xml.etree.ElementTree as E
        root=E.fromstring(raw)
        if root.tag not in {'testsuite','testsuites'}:raise ValueError()
        rows=list(root.iter('testcase'));ids=sorted(r.get('classname','')+'::'+r.get('name','') for r in rows)
        if not expected or ids!=sorted(expected) or len(set(ids))!=len(ids):raise ValueError()
        if any(r.find('failure') is not None or r.find('error') is not None for r in rows):return dict(status='FAIL',reason='observed regression failure')
        # This deliberately does not infer independent PASS from candidate XML.
        return dict(status='UNAVAILABLE',reason='independent isolated oracle attestation required',diagnostic_inventory=ids,raw_sha256=hashlib.sha256(raw).hexdigest())
    except (ValueError,TypeError,E.ParseError):return dict(status='FAIL',reason='invalid, truncated or mismatched raw inventory')


def verify(attestation,binding,expected,*,key,process_exit):
    if not isinstance(key,bytes) or len(key)<32 or process_exit!=0:raise ValueError('independent oracle authority unavailable')
    if not isinstance(attestation,dict) or set(attestation)!={'receipt','signature'}:raise ValueError('signed oracle receipt required')
    receipt=attestation['receipt']
    if not isinstance(receipt,dict) or receipt.get('protocol')!='isolated-oracle-1' or receipt.get('isolation')!='separate-process-no-candidate-imports':raise ValueError('independent oracle isolation required')
    if not hmac.compare_digest(hmac.new(key,canonical(receipt),hashlib.sha256).hexdigest(),str(attestation['signature'])):raise ValueError('oracle signature mismatch')
    if receipt.get('binding')!=binding or receipt.get('expected')!=sorted(expected) or receipt.get('results')!=[{ 'id':i,'status':'PASS'} for i in sorted(expected)]:raise ValueError('oracle identity, binding or outcome mismatch')
    if not re.fullmatch(r'.+@sha256:[a-f0-9]{64}',binding.get('image','')):raise ValueError('digest-pinned image required')
    return dict(status='PASS',protocol='isolated-oracle-1',receipt_sha256=hashlib.sha256(canonical(receipt)).hexdigest(),binding=binding)


def write_final(directory,name,receipt):
    if not re.fullmatch(r'[a-z0-9_-]+',name):raise ValueError('receipt name')
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('symlink collector directory')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode)&0o077:raise ValueError('private host-only collector directory required')
    path=directory/(name+'.json')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(canonical(receipt)+b'\n');f.flush();os.fsync(f.fileno())
    return path


class OracleClient:
    """Operator-provisioned local oracle RPC; no candidate code or credentials sent."""
    def __init__(self,socket_path,key_path):
        self.socket_path=Path(socket_path);self.key_path=Path(key_path)
        for path,kind in [(self.socket_path,'socket'),(self.key_path,'key')]:
            info=path.lstat()
            if path.is_symlink() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('private operator oracle boundary required')
            if kind=='socket' and not stat.S_ISSOCK(info.st_mode) or kind=='key' and not stat.S_ISREG(info.st_mode):raise ValueError('oracle endpoint/key type')
        self.key=self.key_path.read_bytes()
        if len(self.key)<32:raise ValueError('oracle key too short')

    def observe(self,binding,expected,process_exit):
        import socket
        request=canonical(dict(protocol='isolated-oracle-1',binding=binding,expected=sorted(expected)))+b'\n'
        if len(request)>2_000_000:raise ValueError('oracle request inventory too large')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
            channel.settimeout(30);channel.connect(str(self.socket_path));channel.sendall(request);channel.shutdown(socket.SHUT_WR)
            data=bytearray()
            while True:
                part=channel.recv(min(65536,2_000_001-len(data)))
                if not part:break
                data.extend(part)
                if len(data)>2_000_000:raise ValueError('oracle response too large')
        attestation=json.loads(data)
        result=verify(attestation,binding,expected,key=self.key,process_exit=process_exit)
        evidence=self.socket_path.parent/'oracle-receipts'
        try:path=write_final(evidence,result['receipt_sha256'],attestation)
        except FileExistsError:
            path=evidence/(result['receipt_sha256']+'.json')
            if path.is_symlink() or path.read_bytes()!=canonical(attestation)+b'\n':raise ValueError('immutable oracle evidence conflict')
        return dict(result,receipt_path=str(path))
