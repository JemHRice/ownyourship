"""Static call-graph extraction (Python only).

Best-effort: callees are resolved by name against project definitions, so it
won't capture dynamic dispatch and may link a few same-named functions. Good
enough for an architecture overview; the edges are real (parsed from the code),
not inferred.
"""
import ast
from pathlib import Path
from typing import List, Set, Tuple

from . import scanner


def _rel(path: Path, project_path: Path) -> str:
    return str(path.relative_to(project_path)).replace("\\", "/")


def _callee_name(func: ast.AST):
    """Name of a call target: foo() -> 'foo', obj.bar()/self.bar() -> 'bar'."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_defs(project_path: Path, config: dict) -> List[Tuple[str, str, ast.AST, bool]]:
    """(qualname, simple_name, node, is_call_source) for every project definition.

    Functions/methods are call sources; classes are indexed (so `Cls()` resolves)
    but don't emit calls themselves — their methods do.
    """
    defs: List[Tuple[str, str, ast.AST, bool]] = []
    for fp in sorted(project_path.rglob("*.py")):
        if not fp.is_file() or scanner.should_exclude(fp, project_path, config):
            continue
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = _rel(fp, project_path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.append((f"{rel}::{node.name}", node.name, node, True))
            elif isinstance(node, ast.ClassDef):
                defs.append((f"{rel}::{node.name}", node.name, node, False))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        defs.append((f"{rel}::{node.name}.{item.name}", item.name, item, True))
    return defs


def extract_call_edges(project_path: Path, config: dict) -> Set[Tuple[str, str]]:
    """Return a set of (caller_qualname, callee_qualname) call edges.

    Qualnames are "relpath::name" for module-level functions/classes and
    "relpath::Class.method" for methods.
    """
    defs = _collect_defs(project_path, config)

    name_index: dict = {}
    for qual, simple, _node, _src in defs:
        name_index.setdefault(simple, set()).add(qual)

    edges: Set[Tuple[str, str]] = set()
    for qual, _simple, node, is_source in defs:
        if not is_source:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                callee = _callee_name(sub.func)
                for target in name_index.get(callee, ()):
                    if target != qual:
                        edges.add((qual, target))
    return edges
