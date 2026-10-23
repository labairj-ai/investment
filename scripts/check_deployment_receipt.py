"""Validate immutable sanitized deployment evidence, not deployment authority."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.deployment_evidence import load


def check(path):
    path=Path(path);envelope=load(path)
    sidecar=path.with_suffix(path.suffix+'.sha256')
    expected=hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n'
    if sidecar.is_symlink() or not sidecar.is_file() or sidecar.read_text()!=expected:raise ValueError('deployment evidence file digest mismatch or missing')
    return dict(status='PASS',schema=envelope['schema'],sha256=envelope['sha256'],deployed_sha=envelope['receipt']['deployed_sha'],authority='NONE')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('path',type=Path);a=p.parse_args()
    try:result=check(a.path)
    except (OSError,ValueError,KeyError,TypeError) as e:print(json.dumps(dict(status='FAIL',reason=str(e))));raise SystemExit(1)
    print(json.dumps(result))
