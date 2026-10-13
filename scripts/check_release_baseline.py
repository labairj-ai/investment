"""Exact JUnit failure inventory gate; new/changed/expired failures always fail."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


def normalize(text):
    text=re.sub(r'0x[0-9a-fA-F]+','<ADDRESS>',text)
    text=re.sub(r'/[^\s\'\"]*(?:pytest-[0-9]+|pytest-of-[^/]+)[^\s\'\"]*','<TEST_TMP>',text)
    return '\n'.join(line.rstrip() for line in text.replace('\r\n','\n').strip().splitlines())


def signature(failure):
    # The full assertion/error message is stable across pytest traceback layouts.
    # Full normalized tracebacks are also archived, but don't gate path/UUID logs.
    return normalize(failure.get('message') or (failure.text or ''))


def read_failures(xml_path):
    result={}
    for case in ET.parse(xml_path).getroot().iter('testcase'):
        failure=case.find('failure')
        if failure is None:failure=case.find('error')
        if failure is None:continue
        classname=case.get('classname','');parts=classname.split('.')
        index=next((i for i,p in enumerate(parts) if p.startswith('test_')),None)
        if index is None:raise ValueError('unrecognized JUnit classname '+classname)
        module='/'.join(parts[:index+1]);classes='::'.join(parts[index+1:])
        node=module+'.py::'+(classes+'::' if classes else '')+case.get('name','')
        if node in result:raise ValueError('duplicate result node ID '+node)
        result[node]=dict(signature=signature(failure),full_failure=normalize(failure.text or ''))
    return result


def load_inventory(path):
    data=json.loads(Path(path).read_text());seen=set()
    for item in data['failures']:
        for key in ('node_id','signature','baseline_commit','subsystem','owner','reason','remediation_link','review_date','expected_resolution'):
            if not item.get(key):raise ValueError('missing baseline inventory '+key)
        if item['node_id'] in seen:raise ValueError('duplicate baseline test ID')
        if 'covered_call' in item['node_id'] or '/test_cc_' in item['node_id']:raise ValueError('covered-call-specific waivers are prohibited')
        seen.add(item['node_id'])
    return data


def compare(current,inventory,as_of=None):
    as_of=as_of or date.today()
    known=[];new=[];changed=[];expired=[];resolved=[]
    approved={f['node_id']:f for f in inventory['failures'] if f.get('status','active')!='resolved'}
    for node,observed in current.items():
        item=approved.get(node)
        if item is None:new.append(node)
        elif not item.get('permitted_in_release') or date.fromisoformat(item['review_date'])<as_of:expired.append(node)
        elif observed['signature']!=item['signature']:changed.append(dict(node_id=node,expected=item['signature'],observed=observed['signature']))
        else:known.append(node)
    for node,item in approved.items():
        if node not in current:resolved.append(node)
    return dict(passed=not (new or changed or expired or resolved),known_debt=known,new_failures=new,
                changed_failures=changed,expired_waivers=expired,resolved_stale_inventory=resolved,
                resolution_policy='resolved failures require inventory cleanup before release')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('junit_xml');parser.add_argument('--inventory',default=str(Path(__file__).resolve().parent.parent/'config/release_baseline_failures.json'))
    args=parser.parse_args()
    report=compare(read_failures(args.junit_xml),load_inventory(args.inventory))
    print(json.dumps(report,indent=2));sys.exit(0 if report['passed'] else 1)
