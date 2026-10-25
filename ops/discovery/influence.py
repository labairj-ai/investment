"""Read-only source influence audit. Standalone: system Python -I -S only.

Runtime files are never promoted to source authority. This file imports only the
standard library so it can audit before importing any repository package.
"""
import argparse
import ast
from collections import Counter
import configparser
import hashlib
from importlib.machinery import SOURCE_SUFFIXES,BYTECODE_SUFFIXES,EXTENSION_SUFFIXES
import shlex
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
ENTRY_MODULES=('ops.discovery.upgrade','ops.discovery.observer','dev_agent.cli','scripts.collect_development_signals')
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
    queue=list(ENTRY_MODULES);seen=set();imports=set();dynamic=[];import_names=set()
    while queue:
        module=queue.pop()
        if module in seen or module not in modules:continue
        seen.add(module);name=modules[module]
        tree=ast.parse(sources[name],filename=name)
        package=module if name.endswith('/__init__.py') else module.rpartition('.')[0]
        for node in ast.walk(tree):
            targets=[]
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
                imports.add(target.split('.')[0]);import_names.add(target)
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
                namespaces=sorted(namespaces),dynamic_import_sources=sorted(set(dynamic)),sources=sources,import_names=sorted(import_names))


def code_shape(path):
    name=path.name.lower()
    return (name.endswith(('.py','.pyc','.pyo','.pyw','.pth','.so','.pyd','.dll','.dylib','.sh','.bash','.zsh'))
            or '.so.' in name or name in {'sitecustomize','usercustomize','__init__'})


def import_name(name):
    """Normal source/bytecode/native PathFinder forms, not arbitrary data stems."""
    p=Path(name);suffix=next((s for s in sorted(set(SOURCE_SUFFIXES+BYTECODE_SUFFIXES+EXTENSION_SUFFIXES),key=len,reverse=True) if p.name.endswith(s)),None)
    if suffix is None:return None
    leaf=p.name[:-len(suffix)];parts=[*p.parts[:-1],leaf]
    if leaf=='__init__':parts=parts[:-1]
    if not parts or not all(x.isidentifier() for x in parts):return None
    return '.'.join(parts)


def tracked_discovery_contract(graph):
    helper=graph['sources'].get('dev_agent/reviewed_source.py',b'')
    if b"CONTRACT='reviewed-git-source-1'" not in helper:return False
    for source,function in [('dev_agent/discovery.py','scout'),('dev_agent/scheduler.py','discover_daily')]:
        tree=ast.parse(graph['sources'].get(source,b''))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function]
        if len(functions)!=1 or not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='reviewed_sources' for n in ast.walk(functions[0])):return False
    return True


def execution_references(root,head,tracked):
    """Reviewed unit commands plus read-only installed unit/drop-in references.

    Emit only file names and matched repository paths, never command/env contents.
    """
    units=[];total=0
    for name in tracked:
        if name.endswith('.service'):units.append((name,git(root,'show',head+':'+name).decode('utf-8','replace')))
    for directory in (Path('/etc/systemd/system'),Path('/home/optiplex/.config/systemd/user')):
        if not directory.exists():continue
        count=0
        for path in directory.rglob('*'):
            count+=1
            if count>10000:raise ValueError('bounded unit resolution inventory required')
            if path.is_symlink() or not path.is_file() or not (path.suffix=='.service' or path.suffix=='.conf' and '.service.d' in str(path)):continue
            size=path.stat().st_size;total+=size
            if size>262144 or total>4000000:raise ValueError('bounded unit source required')
            units.append((str(path),path.read_text(errors='replace')))
    refs={};ambiguous=[]
    for label,text in units:
        text=text.replace("%h","/home/optiplex")
        for line in text.splitlines():
            if not re.match(r'^Exec(?:Start|StartPre|StartPost|Stop|StopPost|Reload)=',line):continue
            try:tokens=shlex.split(line.split('=',1)[1])
            except ValueError:ambiguous.append(label);continue
            if any(Path(token).name in {'claude','claude-code','codex'} for token in tokens):ambiguous.append(label+':DEVELOPER_TOOL_EXECUTION')
            if any(Path(token).name in {'sh','bash','zsh'} for token in tokens) and any(t in {'-c','-lc'} for t in tokens):
                if str(root) in line or 'WorkingDirectory='+str(root) in text:ambiguous.append(label+':DYNAMIC_SHELL_EXECUTION')
            python=any(re.fullmatch(r'python(?:3(?:\.\d+)?)?',Path(token).name) for token in tokens)
            if python and '-c' in tokens and (str(root) in line or 'WorkingDirectory='+str(root) in text):ambiguous.append(label+':DYNAMIC_PYTHON_EXECUTION')
            if python and '-m' in tokens:
                i=tokens.index('-m')
                if i+1==len(tokens) or not all(p.isidentifier() for p in tokens[i+1].split('.')):ambiguous.append(label+':DYNAMIC_MODULE_EXECUTION')
                else:
                    module=tokens[i+1].replace('.','/')
                    for rel in (module+'.py',module+'/__init__.py',module+'/__main__.py'):refs.setdefault(rel,[]).append(label)
            for token in tokens:
                token=token.replace('%h','/home/optiplex')
                if token.startswith(str(root)+'/'):rel=token[len(str(root))+1:]
                elif not token.startswith(('/','-')) and '/' in token and not any(c in token for c in ('=','$','%')):rel=token
                elif token.endswith(('.py','.sh','.bak')) and '/' not in token:rel=token
                else:continue
                refs.setdefault(rel,[]).append(label)
    return {k:sorted(set(v)) for k,v in refs.items()},sorted(set(ambiguous))


# Abstract path values contain (anchor, exact relative suffix, unresolved).
# No filesystem content or Python source is evaluated by this analysis.
def path_references(root,source_items,cli_modes=()):
    root=str(root);trees={name:ast.parse(raw,filename=name) for name,raw in source_items.items()}
    functions={};globals_by_source={};aliases={}
    def qname(node):
        if isinstance(node,ast.Name):return node.id
        if isinstance(node,ast.Attribute):return qname(node.value)+'.'+node.attr
        return ''
    def path(anchor,rel='',dynamic=False):return ('path',anchor,rel,dynamic)
    def string(value):return ('string',value)
    def bounded(values):
        values=set(values)
        if len(values)>256:raise ValueError('bounded reviewed path alternatives required')
        return frozenset(values)
    def absolute(value):
        if value==root:return path('repo')
        if value.startswith(root+'/'):return path('repo',value[len(root)+1:])
        if value.startswith('/'):return path('external',value)
        return path('repo',value)
    def as_paths(values):return bounded(absolute(v[1]) if v[0]=='string' else ('path',*v[1:]) if v[0]=='taint' else v for v in values if v[0] in {'path','string','taint'})
    def compose(base,suffix,dynamic=False):
        if suffix.startswith('/'):return absolute(suffix)
        rel='/'.join(x for x in (base[2],suffix) if x)
        if any(p in {'.','..'} for p in rel.split('/')):dynamic=True
        return path(base[1],rel,base[3] or dynamic)
    def lookup(source,node):
        name=qname(node);first,*rest=name.split('.')
        target=aliases[source].get(first)
        if target:return '.'.join([target,*rest])
        return source[:-3].replace('/','.')+'.'+name if '.' not in name else name
    for source,tree in trees.items():
        module=source[:-3].replace('/','.')
        package=module.rpartition('.')[0];aliases[source]={}
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                functions.setdefault(module+'.'+node.name,(source,node))
            if isinstance(node,ast.Import):
                for a in node.names:aliases[source][a.asname or a.name]=a.name
            if isinstance(node,ast.ImportFrom):
                parts=package.split('.') if package else []
                base='.'.join(parts[:len(parts)-node.level+1]) if node.level else ''
                prefix='.'.join(filter(None,(base,node.module or '')))
                for a in node.names:aliases[source][a.asname or a.name]='.'.join(filter(None,(prefix,a.name)))
    digest_helpers=set();evidence_helpers=set();denial_helpers=set()
    dangerous={'loads','load','run','Popen','check_output','check_call','import_module','run_path','run_module','exec','eval','__import__','write','write_text','write_bytes','unlink','rename','replace','remove','mkdir','rmdir','system'}
    digest_calls={'sha256','sha512','sha1','hexdigest','digest','read_bytes','read_text','is_file','is_symlink','stat','lstat','exists','ValueError'}
    for key,(source,node) in functions.items():
        calls=[qname(n.func) for n in ast.walk(node) if isinstance(n,ast.Call)]
        leaves={c.rsplit('.',1)[-1] for c in calls}
        returns=[n.value for n in ast.walk(node) if isinstance(n,ast.Return) and n.value is not None]
        constants={n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and type(n.value) is str}
        digest=bool(returns) and all(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'hexdigest','digest'} for n in returns)
        if digest and any(c.startswith('hashlib.') for c in calls) and not leaves&dangerous and leaves<=digest_calls:
            digest_helpers.add(key)
            if leaves&{'read_bytes','read_text'}:evidence_helpers.add(key)
        if digest and 'sqlite3.connect' in calls and any('mode=ro' in c for c in constants) and any('query_only=ON' in c for c in constants) and not leaves&dangerous and 'iterdump' in leaves and leaves<=digest_calls|{'connect','execute','iterdump','as_uri','update','encode'}:
            evidence_helpers.add(key)
        # A denial predicate must return only booleans, use read-only open/close,
        # and must neither read contents nor invoke an execution/config mechanism.
        attrs={n.attr for n in ast.walk(node) if isinstance(n,ast.Attribute)}
        if returns and all(isinstance(n,ast.Constant) and type(n.value) is bool for n in returns) and {'os.open','os.close'}<=set(calls) and 'O_RDONLY' in attrs and not attrs&{'O_WRONLY','O_RDWR','O_CREAT','O_TRUNC'} and not leaves&({'read','read_bytes','read_text'}|dangerous) and set(calls)<={'os.open','os.close'}:
            evidence_helpers.add(key);denial_helpers.add(key)
    unverified_digests=set()
    for key,(_,node) in functions.items():
        returns=[n.value for n in ast.walk(node) if isinstance(n,ast.Return) and n.value is not None]
        if returns and all(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'hexdigest','digest'} for n in returns) and key not in digest_helpers|evidence_helpers:unverified_digests.add(key)
    refs=[];ambiguous=[];summaries={key:set() for key in functions}
    reads={'read_bytes','read_text','read','readlines','read_csv','read_json','read_sql','loadtxt'}
    metadata={'exists','is_file','is_dir','is_symlink','stat','lstat','statvfs','access'}
    execution={'run','Popen','check_output','check_call','execv','execve','execl','run_path','run_module','import_module','SourceFileLoader','ExtensionFileLoader','spec_from_file_location'}
    core={'dev_agent/cli.py','dev_agent/discovery.py','dev_agent/scheduler.py','ops/discovery/observer.py','ops/discovery/upgrade.py'}
    def active(source,node):
        if source=='dev_agent/discovery.py':return node.name in {'git','score','scout','architecture_signals'}
        return True
    def evaluate(node,env):
        if node is None:return frozenset()
        if isinstance(node,ast.Constant) and type(node.value) is str:return frozenset([string(node.value)])
        if isinstance(node,ast.Name):return env.get(node.id,frozenset())
        if isinstance(node,(ast.List,ast.Tuple,ast.Set)):
            return bounded(v for n in node.elts for v in evaluate(n,env))
        if isinstance(node,ast.Attribute):
            name=qname(node)
            if name.endswith('.ROOT'):return frozenset([path('repo')])
            values=evaluate(node.value,env)
            if node.attr=='parent':return bounded(path(v[1],v[2].rsplit('/',1)[0] if '/' in v[2] else '',v[3]) for v in values if v[0]=='path')
            if node.attr=='name':return bounded(string(v[2].rsplit('/',1)[-1]) for v in values if v[0]=='path' and not v[3])
            return frozenset()
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Div,ast.Add)):
            left=evaluate(node.left,env);right=evaluate(node.right,env);out=[]
            sequence=lambda n:isinstance(n,(ast.List,ast.Tuple)) or isinstance(n,ast.Call) and qname(n.func) in {'list','tuple'}
            if isinstance(node.op,ast.Add) and (sequence(node.left) or sequence(node.right)):return bounded(left|right)
            if isinstance(node.op,ast.Add) and all(v[0]=='string' for v in left|right):
                return bounded(string(a[1]+b[1]) for a in left for b in right)
            for base in as_paths(left):
                if not right:out.append(compose(base,'<dynamic>',True))
                for v in right:
                    if v[0]=='string':out.append(base if isinstance(node.op,ast.Add) and v[1].startswith(('?','&')) else compose(base,v[1]))
                    else:out.append(compose(base,'<dynamic>',True))
            return bounded(out)
        if isinstance(node,ast.Subscript):return bounded(v for v in evaluate(node.value,env) if v[0]=='taint')
        if isinstance(node,ast.JoinedStr):return frozenset([path('unknown','',True)])
        if isinstance(node,ast.Call):
            name=qname(node.func);leaf=name.rsplit('.',1)[-1]
            if leaf=='Path':
                if not node.args:return frozenset([path('repo')])
                value=as_paths(evaluate(node.args[0],env)) or frozenset([path('unknown','',True)])
                for arg in node.args[1:]:
                    values=evaluate(arg,env)
                    value=bounded(compose(base,v[1]) if v[0]=='string' else compose(base,'<dynamic>',True) for base in value for v in (values or {('unknown',)}))
                return value
            if leaf in {'str','resolve','absolute','as_uri','as_posix'}:
                return evaluate(node.args[0],env) if node.args else evaluate(node.func.value,env) if isinstance(node.func,ast.Attribute) else frozenset()
            if isinstance(node.func,ast.Attribute) and leaf=='joinpath':
                value=as_paths(evaluate(node.func.value,env))
                for arg in node.args:
                    values=evaluate(arg,env);value=bounded(compose(b,v[1]) if v[0]=='string' else compose(b,'<dynamic>',True) for b in value for v in (values or {('unknown',)}))
                return value
            if isinstance(node.func,ast.Attribute) and leaf in {'with_name','with_suffix'}:
                bases=as_paths(evaluate(node.func.value,env));values=evaluate(node.args[0],env) if node.args else frozenset();out=[]
                for b in bases:
                    for v in values:
                        if v[0]!='string':continue
                        parent=b[2].rsplit('/',1)[0] if '/' in b[2] else ''
                        leafname=v[1] if leaf=='with_name' else b[2].rsplit('/',1)[-1].rsplit('.',1)[0]+v[1]
                        out.append(path(b[1],'/'.join(filter(None,(parent,leafname))),b[3]))
                return bounded(out)
            if leaf in {'tuple','list','set','sorted','iter','enumerate','zip'}:return bounded(v for arg in node.args for v in evaluate(arg,env))
            if isinstance(node.func,ast.Attribute) and leaf in {'read_bytes','read_text','read','readlines'}:
                return bounded(('taint',*v[1:]) for v in as_paths(evaluate(node.func.value,env)))
            if leaf in {name.rsplit('.',1)[-1] for name in evidence_helpers}:
                return bounded(('taint',*v[1:]) for arg in node.args for v in as_paths(evaluate(arg,env)))
            return bounded(v for arg in node.args for v in evaluate(arg,env) if v[0]=='taint')
        return frozenset()
    def bind(target,values,env):
        if isinstance(target,ast.Name):env[target.id]=bounded(env.get(target.id,frozenset())|values)
        elif isinstance(target,(ast.Tuple,ast.List)):
            for child in target.elts:bind(child,values,env)
    for source,tree in trees.items():
        env={'root':frozenset([path('repo')])}
        assigned={t.id for n in tree.body if isinstance(n,(ast.Assign,ast.AnnAssign)) for t in (n.targets if isinstance(n,ast.Assign) else [n.target]) if isinstance(t,ast.Name)}
        if 'ROOT' not in assigned:env['ROOT']=frozenset([path('repo')])
        for _ in range(4):
            for n in tree.body:
                if isinstance(n,(ast.Assign,ast.AnnAssign)):
                    for target in n.targets if isinstance(n,ast.Assign) else [n.target]:bind(target,evaluate(n.value,env),env)
        globals_by_source[source]=env
    def add(values,usage,source,node,operation,key):
        for v in as_paths(values):
            if v[1].startswith('param:'):
                summaries[key].add((v[1][6:],v[2],v[3],usage,operation));continue
            if v[1]=='external':continue
            if v[3]:
                # Git interpretation and exact reviewed manifests are independently
                # verified; dynamic evidence observations do not select source.
                if usage=='SOURCE_OR_EXECUTION_AUTHORITY' and (source in core or key=='<module>') and not v[2].startswith('.git/'):
                    ambiguous.append(dict(source=source,line=node.lineno,operation=operation,prefix=v[2],reason='UNRESOLVED_AUTHORITY_PATH'))
                elif usage=='SOURCE_OR_EXECUTION_AUTHORITY' and v[1]=='unknown' and key in summaries:summaries[key].add((None,v[2],True,usage,operation))
                continue
            if not v[2]:continue
            refs.append(dict(path=v[2],usage=usage,source=source,line=node.lineno,operation=operation,reads_contents=operation not in metadata|{'denied','permission_probe'}))
    modes=set(cli_modes)
    observer_tree=trees.get('ops/discovery/observer.py')
    if observer_tree:
        for function in observer_tree.body:
            if isinstance(function,ast.FunctionDef) and function.name=='scout':
                for call in ast.walk(function):
                    if isinstance(call,ast.Call) and qname(call.func)=='main':
                        if call.args and isinstance(call.args[0],ast.List) and call.args[0].elts and isinstance(call.args[0].elts[0],ast.Constant) and type(call.args[0].elts[0].value) is str:modes.add(call.args[0].elts[0].value)
                        else:ambiguous.append(dict(source='ops/discovery/observer.py',line=call.lineno,operation='main',prefix='',reason='UNRESOLVED_CLI_ENTRY_MODE'))
    def branch_truth(node):
        if not modes or not isinstance(node,ast.Compare) or len(node.ops)!=1 or qname(node.left)!='args.command':return None
        right=node.comparators[0]
        if isinstance(right,ast.Constant) and isinstance(node.ops[0],(ast.Eq,ast.NotEq)):
            results={m==right.value for m in modes}
            if isinstance(node.ops[0],ast.NotEq):results={not v for v in results}
        elif isinstance(right,(ast.Tuple,ast.List,ast.Set)) and isinstance(node.ops[0],(ast.In,ast.NotIn)) and all(isinstance(v,ast.Constant) for v in right.elts):
            results={m in {v.value for v in right.elts} for m in modes}
            if isinstance(node.ops[0],ast.NotIn):results={not v for v in results}
        else:return None
        return next(iter(results)) if len(results)==1 else None
    def walk(node,dispatch=False):
        yield node
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):return
        if dispatch and isinstance(node,ast.If):
            yield from walk(node.test,dispatch)
            truth=branch_truth(node.test)
            for child in ([] if truth is False else node.body)+([] if truth is True else node.orelse):yield from walk(child,dispatch)
            return
        for child in ast.iter_child_nodes(node):yield from walk(child,dispatch)
    def process(source,owner,body,env,key):
        # Bind constant joins and bounded literal loops to a fixed point.
        nodes=[n for statement in body for n in walk(statement,source=='dev_agent/cli.py' and owner is not None and owner.name=='main')]
        for _ in range(6):
            previous=dict(env)
            for n in nodes:
                if isinstance(n,(ast.Assign,ast.AnnAssign)):
                    for target in n.targets if isinstance(n,ast.Assign) else [n.target]:bind(target,evaluate(n.value,env),env)
                if isinstance(n,ast.For):bind(n.target,evaluate(n.iter,env),env)
            if env==previous:break
        parents={child:n for n in nodes for child in ast.iter_child_nodes(n)}
        base_env=env
        for n in nodes:
            if not isinstance(n,ast.Call):continue
            env=base_env;ancestors=[];cursor=n
            while cursor in parents:
                cursor=parents[cursor]
                if isinstance(cursor,(ast.GeneratorExp,ast.ListComp,ast.SetComp,ast.DictComp)):ancestors.append(cursor)
            if ancestors:
                env=dict(base_env)
                def local_bind(target,values):
                    if isinstance(target,ast.Name):env[target.id]=bounded(values)
                    elif isinstance(target,(ast.Tuple,ast.List)):
                        for child in target.elts:local_bind(child,values)
                for scope in reversed(ancestors):
                    for generator in scope.generators:local_bind(generator.target,evaluate(generator.iter,env))
            name=qname(n.func);leaf=name.rsplit('.',1)[-1];qualified=lookup(source,n.func)
            args=n.args
            if qualified in evidence_helpers:
                if args:add(evaluate(args[0],env),'PROTECTED_RUNTIME_EVIDENCE',source,n,'permission_probe' if qualified in denial_helpers else 'readonly_hash',key)
                continue
            if leaf in reads and isinstance(n.func,ast.Attribute):
                parent=parents.get(n);hashed=key not in unverified_digests and (key in evidence_helpers or isinstance(parent,ast.Call) and (lookup(source,parent.func) in digest_helpers or qname(parent.func).startswith('hashlib.')))
                add(evaluate(n.func.value,env),'PROTECTED_RUNTIME_EVIDENCE' if hashed else 'SOURCE_OR_EXECUTION_AUTHORITY',source,n,'readonly_hash' if hashed else leaf,key)
            elif leaf in metadata:
                value=evaluate(n.func.value,env) if isinstance(n.func,ast.Attribute) and not name.startswith('os.') else evaluate(args[0],env) if args else frozenset()
                add(value,'PROTECTED_RUNTIME_EVIDENCE',source,n,leaf,key)
            elif name=='os.open' and args:
                add(evaluate(args[0],env),'PROTECTED_RUNTIME_EVIDENCE' if key in evidence_helpers else 'SOURCE_OR_EXECUTION_AUTHORITY',source,n,'permission_probe' if key in evidence_helpers else 'open_descriptor',key)
            elif leaf=='open' and (args or isinstance(n.func,ast.Attribute)) and not name.startswith(('os.','urllib.')):
                add(evaluate(n.func.value,env) if isinstance(n.func,ast.Attribute) and name not in {'io.open'} else evaluate(args[0],env),'SOURCE_OR_EXECUTION_AUTHORITY',source,n,'open',key)
            elif name=='sqlite3.connect' and args:
                add(evaluate(args[0],env),'PROTECTED_RUNTIME_EVIDENCE' if key in evidence_helpers else 'SOURCE_OR_EXECUTION_AUTHORITY',source,n,'database_hash' if key in evidence_helpers else 'database_input',key)
            elif leaf in execution:
                for arg in args:add(evaluate(arg,env),'SOURCE_OR_EXECUTION_AUTHORITY',source,n,'execution_target',key)
            if qualified in summaries:
                _,callee=functions[qualified];parameters=[a.arg for a in callee.args.args]
                for param,suffix,dynamic,usage,operation in list(summaries[qualified]):
                    if param is None:
                        add(frozenset([path('unknown',suffix,True)]),usage,source,n,operation,key);continue
                    if param not in parameters or parameters.index(param)>=len(args):continue
                    values=as_paths(evaluate(args[parameters.index(param)],env))
                    add(bounded(compose(v,suffix,dynamic) for v in values),usage,source,n,operation,key)
    # Parameters carry effects to exact call-site paths; no parameter name is a
    # filename exception. Unknown rooted authority joins fail closed.
    for _ in range(6):
        before={k:frozenset(v) for k,v in summaries.items()}
        for key,(source,node) in functions.items():
            if source=='ops/discovery/influence.py' or not active(source,node):continue
            env=dict(globals_by_source[source])
            for arg in node.args.args:
                env[arg.arg]=frozenset([path('repo') if arg.arg in {'root','ROOT'} and source in core else path('param:'+arg.arg)])
            process(source,node,node.body,env,key)
        if before=={k:frozenset(v) for k,v in summaries.items()}:break
    else:raise ValueError('reviewed path summary convergence bound exceeded')
    for source,tree in trees.items():
        if source=='ops/discovery/influence.py':continue
        process(source,None,[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))],dict(globals_by_source[source]),'<module>')
    unique={json.dumps(r,sort_keys=True):r for r in refs}
    uncertain={json.dumps(r,sort_keys=True):r for r in ambiguous}
    return dict(references=sorted(unique.values(),key=lambda r:(r['path'],r['source'],r['line'],r['usage'])),
                ambiguous=sorted(uncertain.values(),key=lambda r:(r['source'],r['line'],r['operation'])),
                evidence_helpers=sorted(evidence_helpers),literal_usage='POLICY_LITERAL_ONLY unless an exact path reaches a consuming operation')


def evidence_sandbox(root,service,observer_unit):
    def properties(raw):
        values={}
        for line in raw.decode('utf-8','replace').splitlines():
            if '=' in line and not line.startswith('#'):
                k,v=line.split('=',1);values.setdefault(k,[]).append(v.replace('%h','/home/optiplex'))
        return values
    values=properties(service);obs=properties(observer_unit);root=str(root)
    safe=(values.get('ProtectSystem')==['strict'] and values.get('ProtectHome')==['read-only']
          and values.get('NoNewPrivileges') in (['true'],['yes'])
          and not any(p.lstrip('-+').startswith(root) for v in values.get('ReadWritePaths',[]) for p in v.split()))
    def denied(config):return sorted({p.lstrip('-') for value in config.get('InaccessiblePaths',[]) for p in value.split()})
    return dict(repo_read_only=safe,scout_denied=denied(values),observer_denied=denied(obs))


def evidence_proof(root,name,uses,sandbox):
    full=str(root/name)
    under=lambda p:full==p or full.startswith(p+'/')
    source=any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses)
    denial=any(r['operation'] in {'denied','permission_probe'} for r in uses)
    content=any(r['reads_contents'] for r in uses)
    scout_denied=any(under(p) for p in sandbox['scout_denied'])
    observer_denied=any(under(p) for p in sandbox['observer_denied'])
    allowed=not source and sandbox['repo_read_only'] and (not denial or scout_denied) and not (content and observer_denied)
    return dict(verified=allowed,read_only_evidence=not source,scout_not_writable=sandbox['repo_read_only'],
                scout_denied=scout_denied,denial_probe_only=denial and not content,
                observer_denied=observer_denied,contents_observed=content)

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
    reachable_roots={m.split('.')[0] for m in graph['modules']}|set(MIN_NAMESPACES)
    authority=tracked_discovery_contract(graph)
    unit_refs,ambiguous_units=execution_references(root,head,tracked)
    cli_modes=set()
    for unit_name in tracked:
        if unit_name.endswith('.service'):
            unit_source=git(root,'show',head+':'+unit_name).decode('utf-8','replace')
            cli_modes.update(re.findall(r'-m\s+dev_agent\.cli\s+([a-z-]+)',unit_source))
    # Only discovery's reviewed fixed modes enter this recovery analysis; an
    # installed supervised loop is separately forbidden by activation boundaries.
    cli_modes&={'scout','scheduler-status'}
    reference_model=path_references(root,{name:graph['sources'][name] for name in graph['sources'] if name[:-3].replace('/','.').removesuffix('.__init__') in graph['modules']},cli_modes=cli_modes)
    reference_map={}
    for item in reference_model['references']:reference_map.setdefault(item['path'],[]).append(item)
    sandbox=evidence_sandbox(root,git(root,'show',head+':systemd/development-scout.service') if 'systemd/development-scout.service' in tracked else b'',
        git(root,'show',head+':ops/discovery/investment-discovery-observer.service') if 'ops/discovery/investment-discovery-observer.service' in tracked else b'')
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
    venv_interpreters={r+'/bin/'+p for r in runtime_roots if (root/r/'pyvenv.cfg').is_file() for p in ('python','python3','python3.12')}
    cache_roots=set()
    for child in root.iterdir():
        marker=child/'CACHEDIR.TAG'
        if child.is_dir() and not child.is_symlink() and child.name not in roots|imports and not any(n.startswith(child.name+'/') for n in tracked) and marker.is_file() and not marker.is_symlink() and marker.stat().st_size<4096:
            if b'Signature: 8a477f597d28d172789f06886806bc55' in marker.read_bytes():cache_roots.add(child.name)
    allowed=Counter();rejected=Counter();details=[];dispositions=[]
    for name in sorted(entries):
        p=root/name;parts=Path(name).parts;reason=None;category=None
        module=import_name(name);native=any(p.name.endswith(s) for s in EXTENSION_SUFFIXES) or p.suffix in {'.so','.pyd','.dll','.dylib'}
        uses=reference_map.get(name,[])
        reference=any(r['usage']=='SOURCE_OR_EXECUTION_AUTHORITY' for r in uses)
        evidence=bool(uses) and not reference
        proof=evidence_proof(root,name,uses,sandbox) if evidence else None
        executed=bool(unit_refs.get(name))
        reachable=bool(module and (module.split('.')[0] in imports or module.split('.')[0] in reachable_roots))
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
        if not reason and executed and name not in venv_interpreters:reason='SYSTEMD_EXECUTION'
        elif not reason and reference:reason='REVIEWED_SOURCE_REFERENCE'
        elif not reason and evidence and not proof['verified']:reason='PROTECTED_EVIDENCE_SANDBOX_UNPROVEN'
        elif not reason and cache:category='non_authoritative_cache'
        elif not reason and parts[0] in runtime_roots and len(parts)==2 and p.name.startswith('__init__.'):reason='RUNTIME_PACKAGE_INJECTION'
        elif not reason and parts[0] in runtime_roots:category='non_authoritative_runtime'
        elif not reason and parts[0] in cache_roots and (code_shape(p) or info and info.st_mode&0o111):reason='TOOL_CACHE_EXECUTABLE'
        elif not reason and parts[0] in cache_roots:category='non_authoritative_tool_cache'
        elif not reason and (p.name in {'.gitattributes','.gitmodules','.gitconfig','.envrc','sitecustomize.py','usercustomize.py','pyproject.toml','setup.cfg','setup.py'} or p.suffix in {'.pth','.service','.timer','.socket'} or '.service.d' in name or '.timer.d' in name):reason='EXECUTION_CONFIGURATION'
        elif not reason and executed and name not in venv_interpreters:reason='SYSTEMD_EXECUTION'
        elif not reason and reference:reason='REVIEWED_SOURCE_REFERENCE'
        elif not reason and module and p.name.startswith('__init__.'):reason='PACKAGE_INITIALIZER'
        elif not reason and native:reason='NATIVE_CODE_REVIEW_REQUIRED'
        elif not reason and reachable:reason='IMPORT_SHADOW'
        elif not reason and evidence and not proof['verified']:reason='PROTECTED_EVIDENCE_SANDBOX_UNPROVEN'
        elif not reason and evidence:category='protected_runtime_evidence'
        elif not reason and parts[0] in {'config','systemd','.github'}:reason='REVIEWED_CONFIGURATION_NAMESPACE'
        elif not reason and parts[0]=='.claude':
            if name=='.claude/settings.local.json' and info and stat.S_ISREG(info.st_mode) and not info.st_mode&0o111:
                category='non_authoritative_developer_tool_config'
            else:reason='UNCLASSIFIED_DEVELOPER_TOOL_PATH'
        elif not reason and module and parts[0] in reachable_roots:reason='TRUSTED_NAMESPACE_EXTENSION'
        elif not reason and not module and parts[0] in reachable_roots and (code_shape(p) or info and info.st_mode&0o111) and p.suffix not in {'.bak','.before','.patch'}:reason='TRUSTED_EXECUTION_NAMESPACE'
        elif not reason and p.suffix in {'.bak','.before','.patch'}:category='non_authoritative_backup'
        elif not reason and code_shape(p):
            if authority and p.suffix in {'.py','.pyw','.pyc'}:category='non_authoritative_legacy_source'
            else:reason='UNREVIEWED_EXECUTABLE_NAMESPACE'
        elif not reason and info and info.st_mode&0o111:reason='UNREVIEWED_EXECUTABLE_NAMESPACE'
        elif not reason and len(parts)>1:
            if parts[0] in roots and p.suffix in {'.json','.csv','.txt','.md'} and authority:category='non_authoritative_package_data'
            else:reason='UNCLASSIFIED_NAMESPACE'
        elif not reason and p.suffix in {'.md','.html','.log','.txt'}:category='non_authoritative_root_document'
        elif not reason and (p.suffix in {'.json','.db','.sqlite3','.csv','.numbers'} or p.name in {'.env','.DS_Store'}):category='non_authoritative_root_data'
        elif not reason:reason='UNCLASSIFIED_ROOT_CONFIGURATION'
        if category not in {'non_authoritative_cache','non_authoritative_runtime','non_authoritative_tool_cache'}:
            dispositions.append(dict(path=name,classification=reason or category,python_importable=module is not None,
                import_name=module,reachable_import=reachable,reviewed_unit_execution=unit_refs.get(name,[]),
                reviewed_source_reference=reference,exact_path_references=uses,evidence_proof=proof,live_discovery_reads_untracked_source=not authority,
                git_interpretation=reason in {'GIT_INFLUENCE','EXECUTION_CONFIGURATION'} and p.name.startswith('.git'),
                python_startup_or_import=bool(reachable or native or p.suffix=='.pth' or p.name in {'sitecustomize.py','usercustomize.py'} or module and p.name.startswith('__init__.'))))
        if reason:
            rejected[reason]+=1;details.append(dict(path=name,reason=reason))
        else:allowed[category]+=1
    if reference_model['ambiguous']:
        rejected['AMBIGUOUS_REVIEWED_PATH']+=len(reference_model['ambiguous'])
        details.extend(dict(path=r['prefix'],reason='AMBIGUOUS_REVIEWED_PATH',source=r['source'],line=r['line']) for r in reference_model['ambiguous'])
    if ambiguous_units:
        rejected['AMBIGUOUS_UNIT_EXECUTION']+=len(ambiguous_units)
        details.extend(dict(path=x,reason='AMBIGUOUS_UNIT_EXECUTION') for x in ambiguous_units)
    if graph['dynamic_import_sources']:
        for name in graph['dynamic_import_sources']:details.append(dict(path=name,reason='DYNAMIC_IMPORT_REVIEW_REQUIRED'))
        rejected['DYNAMIC_IMPORT_REVIEW_REQUIRED']+=len(graph['dynamic_import_sources'])
    result.update(untracked_source_influence='FAIL' if rejected else 'PASS',scanned=len(entries),visible_untracked=len(visible),
                  allowed_categories=dict(sorted(allowed.items())),rejected_categories=dict(sorted(rejected.items())),
                  rejected_paths=details,trusted_namespaces=sorted(roots),trusted_module_count=len(graph['modules']),
                  trusted_modules=graph['modules'],runtime_roots=sorted(runtime_roots),cache_roots=sorted(cache_roots),
                  reviewed_module_graph_sha256=hashlib.sha256(json.dumps([(m,hashlib.sha256(graph['sources'].get(m.replace('.','/')+'.py',graph['sources'].get(m.replace('.','/')+'/__init__.py',b''))).hexdigest()) for m in graph['modules']]).encode()).hexdigest(),
                  discovery_source_authority='reviewed-git-source-1' if authority else 'UNPROVEN',
                  path_dispositions=dispositions,reviewed_path_references=reference_model,sandbox_evidence=sandbox,git_boundary='PASS',unit_execution_coverage='reviewed Git and installed system/user service/drop-in commands')
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
