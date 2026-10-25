"""Bounded immutable Git source for discovery; never a whole-worktree safety view."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType

from .git_exec import output
from .policy import protected_graph,safe_relative

CONTRACT='reviewed-git-source-1'
MAX_FILES=10000
MAX_TREE_BYTES=4000000
MAX_FILE_BYTES=2000000
MAX_SOURCE_BYTES=16000000


@dataclass(frozen=True)
class ReviewedSources:
    head:str
    paths:tuple
    texts:object
    identity:str

    def python(self):return {p:t for p,t in self.texts.items() if p.endswith('.py')}
    def graph(self,root):return protected_graph(root,sources=self.python())
    def configuration(self):return json.loads(self.texts.get('config/development_agent.json','{}'))


def current(root,head):
    if not isinstance(head,str) or not re.fullmatch('[a-f0-9]{40}',head):raise ValueError('exact reviewed discovery head required')
    if output(root,'--no-replace-objects','rev-parse','HEAD').strip()!=head:raise ValueError('reviewed discovery head mismatch')


def reviewed_sources(root,head):
    """Inventory/bytes come from exact regular Git blobs, not working-tree files.

    Dirty tracked bytes are intentionally not substituted here; live observer and
    upgrade reject them separately. This also makes isolated analysis reproducible.
    """
    root=Path(root);current(root,head)
    raw=output(root,'--no-replace-objects','ls-tree','-rz','--full-tree',head,text=False)
    if len(raw)>MAX_TREE_BYTES:raise ValueError('bounded reviewed source tree required')
    rows=[r for r in raw.split(b'\0') if r]
    if len(rows)>MAX_FILES:raise ValueError('bounded reviewed source inventory required')
    names=[];seen=set();texts={};total=0;identities=[]
    for row in rows:
        metadata,name=row.split(b'\t',1);mode,kind,oid=metadata.decode('ascii').split();name=name.decode('utf-8')
        safe_relative(name)
        if any(ord(c)<32 or ord(c)==127 for c in name) or name in seen:raise ValueError('unique canonical reviewed source paths required')
        seen.add(name);names.append(name)
        if kind!='blob' or mode not in {'100644','100755'}:raise ValueError('regular reviewed Git source required')
        if not (name.endswith('.py') or name.startswith('.todos/') and name.endswith('.md') or name=='config/development_agent.json'):continue
        if not re.fullmatch('[a-f0-9]{40}',oid):raise ValueError('exact reviewed blob required')
        size=int(output(root,'--no-replace-objects','cat-file','-s',oid).strip())
        if not 0<=size<=MAX_FILE_BYTES or total+size>MAX_SOURCE_BYTES:raise ValueError('bounded reviewed source bytes required')
        data=output(root,'--no-replace-objects','cat-file','blob',oid,text=False)
        if len(data)!=size or hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data).hexdigest()!=oid:raise ValueError('reviewed blob identity changed')
        total+=size;texts[name]=data.decode('utf-8',errors='replace');identities.append((name,oid))
    current(root,head)
    identity=hashlib.sha256(json.dumps(identities,separators=(',',':')).encode()).hexdigest()
    return ReviewedSources(head,tuple(sorted(names)),MappingProxyType(texts),identity)
