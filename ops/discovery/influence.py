"""Read-only source influence audit. Standalone: system Python -I -S only.

Runtime files are never promoted to source authority. This file imports only the
standard library so it can audit before importing any repository package.
"""
import argparse
import ast
from collections import Counter
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MAX_PATHS=100000
MAX_LIST_BYTES=24000000
MAX_SOURCE_BYTES=16000000
CACHE_PREFIX='/run/investment-discovery-observer/reviewed-pycache'
MIN_NAMESPACES={'dev_agent','ops','scripts','config','systemd','.github'}
ENTRY_MODULES=('ops.discovery.upgrade','ops.discovery.observer','dev_agent.cli')
ENV={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1',
     'GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_REPLACE_OBJECTS':'1','GIT_ATTR_NOSYSTEM':'1',
     'GIT_TERMINAL_PROMPT':'0','LANG':'C.UTF-8'}


def git(root,*args):
    command=['/usr/bin/git','-C',str(root),'-c','safe.directory='+str(root),
             '-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
             '-c','core.attributesFile=/dev/null','-c','core.alternateRefsCommand=',
             '-c','pack.packObjectsHook=','-c','diff.external=',*args]
    return subprocess.check_output(command,env=ENV,timeout=120)


def paths(raw):
    if len(raw)>MAX_LIST_BYTES:raise ValueError('untracked inventory byte bound exceeded')
    values=[os.fsdecode(v) for v in raw.split(b'\0') if v]
    if len(values)>MAX_PATHS or len(values)!=len(set(values)):raise ValueError('path inventory bound/uniqueness failed')
    for value in values:
        p=Path(value)
        if p.is_absolute() or any(x in {'..','.'} for x in p.parts) or not p.parts or len(value)>4096:raise ValueError('invalid inventory path')
    return values


def git_boundary(root):
    directory=root/'.git';rejected=[]
    if directory.is_symlink() or not directory.is_dir():return ['.git:FIXED_DIRECTORY_REQUIRED']
    for rel in ('config','HEAD','index','objects','refs','packed-refs'):
        p=directory/rel
        if p.is_symlink():rejected.append('.git/'+rel+':SYMLINK')
    if rejected:return rejected
    scanned=0
    for name in ('objects','refs'):
        for child in (directory/name).rglob('*'):
            scanned+=1
            if scanned>250000:return ['.git:METADATA_BOUND_EXCEEDED']
            if child.is_symlink():rejected.append(str(child.relative_to(root))+':SYMLINK')
    if rejected:return sorted(set(rejected))
    config=directory/'config'
    if not config.is_file() or config.stat().st_size>65536:return rejected+['.git/config:INVALID']
    parser=configparser.RawConfigParser(strict=True)
    try:parser.read_string(config.read_text())
    except (ValueError,configparser.Error):return rejected+['.git/config:INVALID']
    core={'repositoryformatversion','filemode','bare','logallrefupdates','ignorecase','precomposeunicode'}
    for section in parser.sections():
        keys=set(parser[section])
        valid=(section=='core' and keys<=core or section=='user' and keys<={'name','email'}
               or re.fullmatch(r'remote "[A-Za-z0-9_.-]+"',section) and keys<={'url','fetch','pushurl'}
               or re.fullmatch(r'branch "[A-Za-z0-9_./-]+"',section) and keys<={'remote','merge'})
        if not valid:rejected.append('.git/config:UNREVIEWED_CONFIG_KEYS')
    for rel in ('info/attributes','info/grafts','objects/info/alternates','objects/info/http-alternates','shallow','commondir','config.worktree'):
        p=directory/rel
        if p.exists() or p.is_symlink():rejected.append('.git/'+rel+':INTERPRETATION_OVERRIDE')
    for rel in ('hooks','refs/replace'):
        p=directory/rel
        if p.is_symlink():rejected.append('.git/'+rel+':SYMLINK');continue
        if p.exists():
            for child in p.rglob('*'):
                if rel=='hooks' and child.name.endswith('.sample') and not child.is_symlink():continue
                if child.is_file() or child.is_symlink():rejected.append(str(child.relative_to(root))+':GIT_BEHAVIOR')
    return sorted(set(rejected))


def reviewed_graph(root,head,tracked):
    # Read Git blobs, never import or execute candidate/source modules.
    modules={}
    sources={};total=0
    for name in tracked:
        if not name.endswith('.py'):continue
        raw=git(root,'show',head+':'+name);total+=len(raw)
        if total>MAX_SOURCE_BYTES:raise ValueError('reviewed Python source bound exceeded')
        module=name[:-3].replace('/','.')
        if module.endswith('.__init__'):module=module[:-9]
        modules[module]=name;sources[name]=raw
    queue=list(ENTRY_MODULES);seen=set();imports=set();dynamic=[];root_configs=set()
    while queue:
        module=queue.pop()
        if module in seen or module not in modules:continue
        seen.add(module);name=modules[module]
        tree=ast.parse(sources[name],filename=name)
        package=module if name.endswith('/__init__.py') else module.rpartition('.')[0]
        for node in ast.walk(tree):
            targets=[]
            if isinstance(node,ast.Constant) and type(node.value) is str and '/' not in node.value and node.value.endswith(('.json','.toml','.ini','.yaml','.yml')):root_configs.add(node.value)
            if isinstance(node,ast.Import):targets=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                parts=package.split('.') if package else []
                base='.'.join(parts[:len(parts)-node.level+1]) if node.level else ''
                prefix='.'.join(filter(None,(base,node.module or '')))
                targets=[prefix,*[prefix+'.'+a.name for a in node.names]]
            elif isinstance(node,ast.Call):
                f=node.func
                if isinstance(f,ast.Name) and f.id in {'__import__','eval','exec'}:dynamic.append(name)
                if isinstance(f,ast.Attribute) and f.attr in {'import_module','run_module','run_path','SourceFileLoader','ExtensionFileLoader','spec_from_file_location'}:dynamic.append(name)
            for target in targets:
                if not target:continue
                imports.add(target.split('.')[0])
                if target in modules:queue.append(target)
                # Package __init__ modules execute before children.
                for i in range(1,len(target.split('.'))):
                    ancestor='.'.join(target.split('.')[:i])
                    if ancestor in modules:queue.append(ancestor)
    # Trusted package/source directories are protected even for namespace packages.
    namespaces=set(MIN_NAMESPACES)
    for name in tracked:
        if '/' in name and name.endswith(('.py','.sh','.service','.timer')):namespaces.add(name.split('/')[0])
    return dict(modules=sorted(seen),import_roots=sorted(imports|set(sys.stdlib_module_names)),
                namespaces=sorted(namespaces),dynamic_import_sources=sorted(set(dynamic)),root_configuration_names=sorted(root_configs),sources=sources)


def code_shape(path):
    name=path.name.lower()
    return (name.endswith(('.py','.pyc','.pyo','.pyw','.pth','.so','.pyd','.dll','.dylib','.sh','.bash','.zsh'))
            or '.so.' in name or name in {'sitecustomize','usercustomize','__init__'})


def audit(root,head,*,tracked=None,untracked=None):
    root=Path(root)
    if not re.fullmatch('[a-f0-9]{40}',str(head)) or root.is_symlink() or root.resolve(strict=True)!=root:raise ValueError('exact reviewed head and nonsymlinked absolute checkout required')
    result=dict(untracked_source_influence='FAIL',scanned=0,visible_untracked=0,
                allowed_categories={},rejected_categories={},rejected_paths=[],
                entry_modules=list(ENTRY_MODULES),isolation_required='system Python -I -S; protected cache prefix before repository imports')
    bad=git_boundary(root)
    if bad:
        result['rejected_paths']=bad;result['rejected_categories']={'git_influence':len(bad)};return result
    result.update(source_graph_head=head,checkout_head=git(root,'rev-parse','HEAD').decode().strip(),
                  tracked_source_clean=not git(root,'status','--porcelain','--untracked-files=no').strip())
    tracked=set(paths(git(root,'ls-tree','-rz','--name-only',head))) if tracked is None else set(tracked)
    entries=paths(git(root,'ls-files','--others','-z')) if untracked is None else list(untracked)
    visible=paths(git(root,'ls-files','--others','--exclude-standard','-z')) if untracked is None else entries
    if len(entries)>MAX_PATHS:raise ValueError('untracked inventory count exceeded')
    graph=reviewed_graph(root,head,tracked)
    roots=set(graph['namespaces']);imports=set(graph['import_roots'])
    trusted={root/name for name in tracked}
    trusted.update({Path('/opt/investment-discovery-observer/observer.py'),Path('/etc/investment-discovery-observer'),
                    Path('/etc/systemd/system/investment-discovery-observer.service'),
                    Path('/home/optiplex/.config/systemd/user/development-scout.service'),
                    Path('/home/optiplex/.config/systemd/user/development-scout.timer')})
    # Actual reviewed source identifies out as state, not an import root. Venv
    # roots are discovered from pyvenv.cfg layout, not trusted for dependencies.
    observer=graph['sources'].get('ops/discovery/observer.py',b'')
    runtime_roots={'out'} if b"ROOT/'out/investment.db'" in observer and b"ROOT/'out/buffett.db'" in observer else set()
    for child in root.iterdir():
        cfg=child/'pyvenv.cfg'
        if child.is_dir() and not child.is_symlink() and cfg.is_file() and not cfg.is_symlink() and not any(n==child.name or n.startswith(child.name+'/') for n in tracked):runtime_roots.add(child.name)
    cache_roots=set()
    for child in root.iterdir():
        marker=child/'CACHEDIR.TAG'
        if child.is_dir() and not child.is_symlink() and child.name not in roots|imports and not any(n.startswith(child.name+'/') for n in tracked) and marker.is_file() and not marker.is_symlink() and marker.stat().st_size<4096:
            if b'Signature: 8a477f597d28d172789f06886806bc55' in marker.read_bytes():cache_roots.add(child.name)
    allowed=Counter();rejected=Counter();details=[]
    for name in sorted(entries):
        p=root/name;parts=Path(name).parts;reason=None;category=None
        if name in tracked:reason='TRACKED_COLLISION'
        if parts[0]=='.git':reason='GIT_INFLUENCE'
        for parent in p.parents:
            if parent==root:break
            if parent.is_symlink() or not parent.is_dir():reason='TRUSTED_PARENT_RESOLUTION';break
        try:info=p.lstat()
        except OSError:reason='UNREADABLE_PATH';info=None
        if info and stat.S_ISLNK(info.st_mode):
            try:target=p.resolve(strict=False)
            except (OSError,RuntimeError):target=None
            if target is None or any(target==t or target in t.parents or t in target.parents for t in trusted):reason='SYMLINK_TRUSTED_COLLISION'
            elif parts[0] not in runtime_roots:reason='SYMLINK_OUTSIDE_RUNTIME'
        # Isolated launch never reads checkout __pycache__; legacy sourceless
        # .pyc outside __pycache__ remains executable source and is rejected.
        cache='__pycache__' in parts and p.suffix=='.pyc'
        if not reason and cache:category='non_authoritative_cache'
        elif not reason and parts[0] in runtime_roots and len(parts)==2 and p.name.startswith('__init__.'):reason='RUNTIME_PACKAGE_INJECTION'
        elif not reason and parts[0] in runtime_roots:category='non_authoritative_runtime'
        elif not reason and parts[0] in cache_roots and (code_shape(p) or info and info.st_mode&0o111):reason='TOOL_CACHE_EXECUTABLE'
        elif not reason and parts[0] in cache_roots:category='non_authoritative_tool_cache'
        elif not reason and parts[0] in roots:reason='TRUSTED_NAMESPACE_EXTENSION'
        elif not reason and (p.name in {'.gitattributes','.gitmodules','.gitconfig','.envrc','sitecustomize.py','usercustomize.py','pyproject.toml','setup.cfg','setup.py'} or p.suffix in {'.pth','.service','.timer','.socket'} or '.service.d' in name or '.timer.d' in name):reason='EXECUTION_CONFIGURATION'
        elif not reason and (code_shape(p) or info and info.st_mode&0o111):reason='UNREVIEWED_EXECUTABLE_NAMESPACE'
        elif not reason and len(parts)>1:reason='UNCLASSIFIED_NAMESPACE'
        elif not reason and (p.stem in imports or p.name in imports):reason='IMPORT_SHADOW'
        elif not reason and p.name in graph['root_configuration_names']:reason='REVIEWED_CONFIGURATION_INFLUENCE'
        elif not reason and (p.name.endswith(('.bak','.before','.patch'))):category='non_authoritative_root_backup'
        elif not reason and p.suffix in {'.md','.html','.log','.txt'}:category='non_authoritative_root_document'
        elif not reason and (p.suffix in {'.json','.db','.sqlite3','.csv','.numbers'} or p.name in {'.env','.DS_Store'}):category='non_authoritative_root_data'
        elif not reason:reason='UNCLASSIFIED_ROOT_CONFIGURATION'
        if reason:
            rejected[reason]+=1;details.append(dict(path=name,reason=reason))
        else:allowed[category]+=1
    if graph['dynamic_import_sources']:
        for name in graph['dynamic_import_sources']:details.append(dict(path=name,reason='DYNAMIC_IMPORT_REVIEW_REQUIRED'))
        rejected['DYNAMIC_IMPORT_REVIEW_REQUIRED']+=len(graph['dynamic_import_sources'])
    result.update(untracked_source_influence='FAIL' if rejected else 'PASS',scanned=len(entries),visible_untracked=len(visible),
                  allowed_categories=dict(sorted(allowed.items())),rejected_categories=dict(sorted(rejected.items())),
                  rejected_paths=details,trusted_namespaces=sorted(roots),trusted_module_count=len(graph['modules']),
                  trusted_modules=graph['modules'],runtime_roots=sorted(runtime_roots),cache_roots=sorted(cache_roots),root_configuration_names=graph['root_configuration_names'],
                  reviewed_module_graph_sha256=hashlib.sha256(json.dumps(graph['modules']).encode()).hexdigest())
    return result


def isolated():
    return (sys.flags.isolated==1 and sys.flags.no_site==1 and sys.pycache_prefix==CACHE_PREFIX
            and sys.dont_write_bytecode and Path(sys.executable).resolve()==Path('/usr/bin/python3').resolve())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--head',required=True)
    parser.add_argument('--upgrade',action='store_true');parser.add_argument('--expected-old-head');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.apply and not args.upgrade:parser.error('--apply requires --upgrade')
    if sys.flags.isolated!=1 or sys.flags.no_site!=1:raise SystemExit('system Python -I -S required')
    sys.pycache_prefix=CACHE_PREFIX;sys.dont_write_bytecode=True
    result=audit(args.root,args.head)
    if not args.upgrade or result['untracked_source_influence']!='PASS':
        print(json.dumps(result,indent=2));raise SystemExit(0 if result['untracked_source_influence']=='PASS' else 1)
    if not args.expected_old_head:parser.error('--expected-old-head required for upgrade')
    if not isolated():raise SystemExit('fixed isolated system Python required for upgrade')
    parent=Path(CACHE_PREFIX).parent
    for path in [parent,*parent.parents]:
        info=path.lstat()
        if path.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise SystemExit('protected cache ancestry required')
    prefix=Path(CACHE_PREFIX)
    if prefix.exists() and (prefix.is_symlink() or prefix.stat().st_uid!=0 or prefix.stat().st_mode&0o022):raise SystemExit('protected cache prefix required')
    # No repository package is imported until the standalone audit passes.
    sys.path.insert(0,str(args.root))
    from ops.discovery.upgrade import upgrade
    outcome=upgrade(args.root,args.head,args.expected_old_head,apply=args.apply)
    print(json.dumps(outcome,indent=2))
    raise SystemExit(1 if 'NOT_READY' in outcome['status'] else 0)


if __name__=='__main__':main()
