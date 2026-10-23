"""Conservative whole-diff classification, protected dependency reachability."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import ast
import io
import fnmatch
import re
import subprocess
import tarfile
from html.parser import HTMLParser
from html import unescape
from urllib.parse import unquote
from pathlib import Path, PurePosixPath

VERSION = "risk-surface-2"
TEST_RUNNER_FILES = {'conftest.py','pytest.ini','.pytest.ini','pytest.toml','.pytest.toml',
                     'pyproject.toml','setup.cfg','tox.ini','sitecustomize.py','usercustomize.py'}
FINANCIAL = ("portfolio*", "covered_call*", "tax*", "thesis*", "agents/advisor/*", "agents/learning/*", "agents/*agent.py", "agents/critic*", "strategy*", "macro*", "financials*", "config/*")
EXECUTION = ("config/development_agent.json","owner_gateway/*","deployment_agent/*","trade_engine/*", "agent_db.py", "schema.sql", "serve.py", "dev_agent/*", "scripts/dev_agent*", "systemd/*", "ops/*")
GOVERNANCE = ("owner_gateway/*","deployment_agent/*","AGENTS.md", "docs/development-agent.md", ".github/*", "scripts/check_*", "config/*", "cc_change_manifests/*")
FORBIDDEN = (".env*", "*/.env*", "*credential*", "*token.json", "*.db", "*.sqlite*", "holdings.csv", "*/holdings.csv", "covered_calls.csv", "out/*", "*/out/*", "venv/*", ".git/*", "*/.git/*")
PRINCIPLES = {
    "P1": "Single source of truth; never mutate authoritative investment state.",
    "P2": "Deterministic financial arithmetic and explicit unavailable states.",
    "P3": "Immutable SHA-bound evidence; missing evidence is not PASS.",
    "P4": "Minimal duplication and bounded model authority.",
    "P5": "Mobile usability and explicit human review for protected behavior.",
    "P6": "Fail closed; never relax gates, tests or this contract to obtain PASS.",
}


def test_runner_surface(path, text=''):
    """Runner and plugin declarations cannot be approved as ordinary L1 tests."""
    return (Path(path).name in TEST_RUNNER_FILES or
            (path.endswith(('.py','.toml','.cfg','.ini')) and bool(re.search(r'pytest_plugins|pytest\.hookimpl|def\s+pytest_|pytest11', text))))


class PassiveContent(HTMLParser):
    SAFE = set('html head body title meta main section article div span p a h1 h2 h3 h4 h5 h6 ul ol li dl dt dd strong em b i small br hr pre code blockquote table thead tbody tr th td caption svg g path rect circle ellipse line polyline polygon text tspan defs desc'.split())
    ATTRIBUTES=set('id class role title lang dir style charset name content tabindex colspan rowspan scope headers href xlink:href xmlns xmlns:xlink viewbox preserveaspectratio d fill stroke stroke-width width height x y cx cy r rx ry x1 y1 x2 y2 points transform font-family font-size text-anchor'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.SAFE: self.active = True
        for key, value in attrs:
            raw_value=value or ''
            if key not in self.ATTRIBUTES and not key.startswith('aria-'):self.active=True
            value = unescape(unquote(value or '')).lower()
            compact = re.sub(r'\s|[\x00-\x1f]', '', value)
            if (key.startswith('on') or key in {'src', 'srcset', 'action', 'formaction', 'srcdoc', 'http-equiv', 'background', 'lowsrc', 'dynsrc', 'poster', 'ping', 'manifest', 'codebase', 'archive'} or
                'javascript:' in compact or 'vbscript:' in compact or 'data:' in compact or
                '\\' in value or re.search(r'url\s*\(|@import|expression\s*\(|\bimport\s*\(', value) or
                (key=='charset' and value not in {'utf-8','utf8'}) or
                (key in {'href', 'xlink:href'} and not raw_value.lstrip().startswith('#'))):
                self.active = True

    handle_startendtag = handle_starttag

    def unknown_decl(self, data): self.active = True
    def handle_comment(self, data): self.active = True
    def handle_decl(self, data):
        if data.strip().lower()!='doctype html':self.active=True


def passive_content(text):
    if not text or re.search(r'<\?|<!\[|<!ENTITY', text, re.I): return False
    parser = PassiveContent()
    try:
        parser.feed(text); parser.close()
    except Exception:
        return False
    return not parser.active


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def safe_relative(path):
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\\" in path or str(p) != path:
        raise ValueError("non-canonical relative path")
    return p


def protected_graph(root, sources=None):
    """Resolve imports for *all* Python files, including formerly deleted helpers.

    Call on the base and candidate trees; union results so deleting/renaming a
    protected import cannot remove its risk classification.
    """
    root = Path(root)
    graph = {}
    if sources is None:
        sources = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if any(part.startswith(".") or part in {"venv", "__pycache__", "out"} for part in rel.parts) or path.is_symlink(): continue
            sources[rel.as_posix()] = path.read_text(errors="replace")
    for rel, text in sorted(sources.items()):
        path = root / rel
        try:
            tree = ast.parse(text)
        except (SyntaxError, UnicodeError):
            graph[rel] = {"<unresolved>"}
            continue
        edges = set()
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = ".".join(path.relative_to(root).parts[:-node.level]) if node.level else ""
                base = ".".join(filter(None, (prefix, node.module or "")))
                names = [base] + [".".join(filter(None, (base, n.name))) for n in node.names]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}:
                edges.add("<unresolved>")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"import_module", "load_module", "run_module", "run_path"}:
                edges.add("<unresolved>")
            for name in names:
                for candidate in (name.replace(".", "/") + ".py", name.replace(".", "/") + "/__init__.py"):
                    if candidate in sources:
                        edges.add(candidate)
        graph[rel] = edges
    return graph


def whole_diff(root, base):
    if not re.fullmatch(r"[a-f0-9]{40}", base): raise ValueError("full base SHA required")
    git_run(root, "merge-base", "--is-ancestor", base, "HEAD")
    paths = git_output(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", base).split("\0")
    archive = git_output(root, "archive", base, text=False)
    sources = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for entry in stream:
            if entry.isfile() and entry.name.endswith(".py") and entry.size <= 2_000_000:
                sources[entry.name] = stream.extractfile(entry).read().decode(errors="replace")
    diff = git_output(root, "diff", "--no-ext-diff", "--no-textconv", base)
    content = {}
    for path in filter(None, paths):
        if path.endswith(('.html', '.svg')):
            if (Path(root)/path).is_symlink():continue
            try: old = git_output(root, 'show', base+':'+path)
            except subprocess.CalledProcessError: old = ''
            new = (Path(root)/path).read_text() if (Path(root)/path).is_file() else ''
            content[path] = (old, new)
    return classify([p for p in paths if p], graphs=[protected_graph(root, sources), protected_graph(root)], diff=diff, content=content)


def classify(paths, *, graphs=(), declared=0, model=0, manifest=None, diff="", content=None):
    if content is not None and (not isinstance(content,dict) or any(not isinstance(pair,(tuple,list)) or len(pair)!=2 or not all(isinstance(text,str) for text in pair) for pair in content.values())):
        raise ValueError('unproven whole-content representation; human review required')
    paths = sorted(set(paths))
    floor = max(int(declared), int(model))
    if not 0 <= floor <= 5:
        raise ValueError("invalid risk")
    reasons = []
    protected = {}
    for graph in graphs:
        for source in graph:
            level = 5 if matches(source, EXECUTION) else 4 if matches(source, FINANCIAL) else 0
            if not level:
                continue
            todo = [source]; seen = set()
            while todo:
                node = todo.pop()
                if node in seen:
                    continue
                seen.add(node)
                protected[node] = max(protected.get(node, 0), level)
                todo.extend(graph.get(node, ()))
    for path in paths:
        safe_relative(path)
        if matches(path, EXECUTION): level, reason = 5, "execution/account/governance tooling"
        elif matches(path, FINANCIAL): level, reason = 4, "financial surface"
        elif matches(path, GOVERNANCE): level, reason = 5, "safety contract"
        elif path in protected: level, reason = protected[path], "protected import reachability"
        elif test_runner_surface(path, '\n'.join((content or {}).get(path, ())) or diff): level, reason = 3, "protected test runner or plugin configuration"
        elif path.endswith(('.js', '.mjs', '.cjs', '.ts')): level, reason = 3, "human-started browser/application execution"
        elif path.startswith("static/") and path.endswith('.css'):
            text='\n'.join((content or {}).get(path, ())) or diff
            active=bool(re.search(r'url\s*\(|@import|expression\s*\(|\\',text,re.I))
            level,reason=(3,'active CSS resource behavior') if active else (2,'presentation')
        elif path.endswith(('.html', '.svg')):
            versions = (content or {}).get(path)
            passive = versions is not None and all(passive_content(t) for t in versions if t)
            level, reason = (2, "inspected passive presentation") if passive else (3, "active or unproven HTML/SVG content")
        elif path.startswith(("docs/", ".todos/")) or path == "README.md": level, reason = 0, "documentation"
        elif path.startswith("tests/"): level, reason = 1, "tests"
        elif path.startswith("scripts/"): level, reason = 3, "application tooling"
        else: level, reason = 5, "unknown surface; human review required"
        reasons.append(dict(path=path, level=f"L{level}", reason=reason))
        floor = max(floor, level)
    if manifest:
        floor = max(floor, int(manifest.get("minimum_risk", 5)))
    if "<unresolved>" in protected and any(p.endswith(".py") and not p.startswith("tests/") for p in paths):
        floor = 5
        reasons.append(dict(path="<dependencies>", level="L5", reason="unresolved dynamic protected dependency"))
    if re.search(r"(?i)(broker|execute_order|risk_limit|promotion_threshold|sqlite3|subprocess|importlib|__import__|\bexec\(|\beval\()", diff):
        floor = 5
        reasons.append(dict(path="<diff>", level="L5", reason="mutation/dynamic-execution semantic marker"))
    gates = ["focused_tests", "full_suite", "release_baseline", "cc_contract", "agent_contract", "independent_review", "fresh_sha_evidence", "human_merge"]
    if floor >= 3: gates += ["human_scope_approval", "observation_window"]
    if floor >= 4: gates += ["financial_human_review", "domain_canaries"]
    return dict(version=VERSION, risk=f"L{floor}", reasons=reasons, gates=gates, auto_merge=False)


def engineering_checks(changes):
    """changes maps path -> (base text, head text); independent of model review."""
    findings = []
    for path, (old, new) in sorted(changes.items()):
        if matches(path, FORBIDDEN) or matches(path, GOVERNANCE):
            findings.append(dict(id="protected:" + path, severity="HIGH", file=path, principle="P6", evidence="protected file requires human review"))
        if path.startswith("tests/"):
            before = len(re.findall(r"\bassert\b|pytest\.raises|def test_", old))
            after = len(re.findall(r"\bassert\b|pytest\.raises|def test_", new))
            if after < before or new.count("pytest.mark.skip") > old.count("pytest.mark.skip") or new.count("xfail") > old.count("xfail"):
                findings.append(dict(id="test-integrity:" + path, severity="HIGH", file=path, principle="P6", evidence="test assertions removed or skip/xfail added"))
            elif old and old != new:
                try:
                    old_defs = {n.name:ast.dump(n) for n in ast.walk(ast.parse(old)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test_")}
                    new_defs = {n.name:ast.dump(n) for n in ast.walk(ast.parse(new)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test_")}
                    if any(new_defs.get(k) != v for k,v in old_defs.items()):
                        findings.append(dict(id="test-semantics:" + path, severity="HIGH", file=path, principle="P6", evidence="existing test semantics changed; independent human review required"))
                except SyntaxError:
                    findings.append(dict(id="test-syntax:" + path, severity="HIGH", file=path, principle="P6", evidence="invalid test syntax"))
        if len(new.encode()) > 200_000:
            findings.append(dict(id="scope:" + path, severity="HIGH", file=path, principle="P4", evidence="oversized source change"))
    return findings


def human_override(classification, requested, actor, rationale):
    """Human prioritization overrides cannot lower deterministic safety floors."""
    if not re.fullmatch(r"L[0-5]", requested) or not actor or not rationale.strip():
        raise ValueError("recorded human rationale required")
    floor = int(classification["risk"][1:])
    if int(requested[1:]) < floor: raise ValueError("mandatory risk floor cannot be lowered")
    raised = classify([], declared=int(requested[1:]))
    return dict(classification, risk=requested, gates=raised["gates"], override=dict(actor=actor, rationale=rationale, prior=classification["risk"]))
