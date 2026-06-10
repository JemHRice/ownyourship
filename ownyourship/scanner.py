import ast
import fnmatch
import re
from pathlib import Path
from typing import Dict, List, Optional


# ── Exclusion logic ──────────────────────────────────────────────────────────

def should_exclude(path: Path, project_path: Path, config: dict) -> bool:
    excluded_dirs = set(config.get("excluded_dirs", []))
    excluded_patterns = config.get("excluded_patterns", [])

    try:
        rel = path.relative_to(project_path)
    except ValueError:
        return True

    for part in rel.parts[:-1]:
        if part in excluded_dirs:
            return True

    filename = path.name
    for pattern in excluded_patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True

    return False


# ── Python AST scanner ───────────────────────────────────────────────────────

def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "..."


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts = []

    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        ann = f": {_unparse(arg.annotation)}" if arg.annotation else ""
        di = i - defaults_offset
        default = f" = {_unparse(args.defaults[di])}" if di >= 0 else ""
        parts.append(f"{arg.arg}{ann}{default}")

    if args.vararg:
        ann = f": {_unparse(args.vararg.annotation)}" if args.vararg.annotation else ""
        parts.append(f"*{args.vararg.arg}{ann}")
    elif args.kwonlyargs:
        parts.append("*")

    kw_defaults = {i: d for i, d in enumerate(args.kw_defaults) if d is not None}
    for i, arg in enumerate(args.kwonlyargs):
        ann = f": {_unparse(arg.annotation)}" if arg.annotation else ""
        default = f" = {_unparse(kw_defaults[i])}" if i in kw_defaults else ""
        parts.append(f"{arg.arg}{ann}{default}")

    if args.kwarg:
        ann = f": {_unparse(args.kwarg.annotation)}" if args.kwarg.annotation else ""
        parts.append(f"**{args.kwarg.arg}{ann}")

    ret = f" -> {_unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)}){ret}"


def _make_func_block(node, rel_path: str, parent_class: Optional[str]) -> Dict:
    return {
        "file_path": rel_path,
        "block_type": "method" if parent_class else "function",
        "block_name": node.name,
        "parent_class": parent_class,
        "signature": _func_signature(node),
        "docstring": ast.get_docstring(node),
        "decorators": [_unparse(d) for d in node.decorator_list],
        "line_start": node.lineno,
        "line_end": node.end_lineno or node.lineno,
    }


def _make_class_block(node, rel_path: str) -> Dict:
    bases = [_unparse(b) for b in node.bases]
    sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    return {
        "file_path": rel_path,
        "block_type": "class",
        "block_name": node.name,
        "parent_class": None,
        "signature": sig,
        "docstring": ast.get_docstring(node),
        "decorators": [_unparse(d) for d in node.decorator_list],
        "line_start": node.lineno,
        "line_end": node.end_lineno or node.lineno,
    }


def _make_const_block(name: str, sig: str, rel_path: str, lineno: int, end_lineno: int) -> Dict:
    return {
        "file_path": rel_path,
        "block_type": "constant",
        "block_name": name,
        "parent_class": None,
        "signature": sig,
        "docstring": None,
        "decorators": [],
        "line_start": lineno,
        "line_end": end_lineno or lineno,
    }


def scan_python_file(file_path: Path, project_path: Path) -> List[Dict]:
    blocks = []
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return blocks

    rel_path = str(file_path.relative_to(project_path)).replace("\\", "/")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            blocks.append(_make_func_block(node, rel_path, None))

        elif isinstance(node, ast.ClassDef):
            blocks.append(_make_class_block(node, rel_path))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    blocks.append(_make_func_block(item, rel_path, node.name))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    val = _unparse(node.value)[:80]
                    blocks.append(_make_const_block(
                        target.id, f"{target.id} = {val}", rel_path,
                        node.lineno, node.end_lineno,
                    ))

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ann = _unparse(node.annotation)
            blocks.append(_make_const_block(
                node.target.id, f"{node.target.id}: {ann}", rel_path,
                node.lineno, node.end_lineno,
            ))

    return blocks


# ── Generic regex scanner ────────────────────────────────────────────────────

_JS_PATTERNS = [
    (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", "function"),
    (r"(?:export\s+)?class\s+(\w+)", "class"),
    (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", "function"),
    (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function", "function"),
]

_GO_PATTERNS = [
    (r"func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", "function"),
    (r"type\s+(\w+)\s+struct", "class"),
    (r"type\s+(\w+)\s+interface", "class"),
]

_RUST_PATTERNS = [
    (r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", "function"),
    (r"(?:pub\s+)?struct\s+(\w+)", "class"),
    (r"(?:pub\s+)?enum\s+(\w+)", "class"),
    (r"(?:pub\s+)?trait\s+(\w+)", "class"),
]

_JAVA_PATTERNS = [
    (r"(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(", "function"),
    (r"(?:public|private|protected|\s)*\s*class\s+(\w+)", "class"),
    (r"(?:public|private|protected|\s)*\s*interface\s+(\w+)", "class"),
]

_EXT_PATTERNS = {
    ".js": _JS_PATTERNS, ".ts": _JS_PATTERNS,
    ".jsx": _JS_PATTERNS, ".tsx": _JS_PATTERNS,
    ".go": _GO_PATTERNS,
    ".rs": _RUST_PATTERNS,
    ".java": _JAVA_PATTERNS, ".kt": _JAVA_PATTERNS,
}


def _block_end_line(source: str, match_start: int) -> Optional[int]:
    """Line number of the brace that closes the block opened at match_start.

    Naive brace counting — strings and comments aren't lexed, so a stray
    brace inside one can skew the range. Good enough for snippet display.
    Returns None for body-less declarations (e.g. `struct Foo(i32);`,
    `func Bar(x int)` in an interface).
    """
    head = source[match_start : match_start + 500]
    brace = head.find("{")
    semi = head.find(";")
    if brace == -1 or (0 <= semi < brace):
        return None
    depth = 0
    for i in range(match_start + brace, len(source)):
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[:i].count("\n") + 1
    return None


def scan_generic_file(file_path: Path, project_path: Path) -> List[Dict]:
    ext = file_path.suffix.lower()
    patterns = _EXT_PATTERNS.get(ext)
    if not patterns:
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    rel_path = str(file_path.relative_to(project_path)).replace("\\", "/")
    blocks = []
    seen = set()

    for pattern, block_type in patterns:
        for match in re.finditer(pattern, source, re.MULTILINE):
            name = match.group(1)
            key = (name, block_type)
            if key in seen:
                continue
            seen.add(key)
            line_num = source[: match.start()].count("\n") + 1
            blocks.append({
                "file_path": rel_path,
                "block_type": block_type,
                "block_name": name,
                "parent_class": None,
                "signature": match.group(0)[:120].strip(),
                "docstring": None,
                "decorators": [],
                "line_start": line_num,
                "line_end": _block_end_line(source, match.start()) or line_num,
            })

    return blocks


# ── Project scanner ──────────────────────────────────────────────────────────

def scan_project(project_path: Path, config: dict) -> List[Dict]:
    included = set(config.get("included_extensions", [".py"]))
    all_blocks: List[Dict] = []

    for file_path in sorted(project_path.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in included:
            continue
        if should_exclude(file_path, project_path, config):
            continue

        if file_path.suffix.lower() == ".py":
            blocks = scan_python_file(file_path, project_path)
        else:
            blocks = scan_generic_file(file_path, project_path)

        all_blocks.extend(blocks)

    return all_blocks


def get_meaningful_blocks(blocks: List[Dict]) -> List[Dict]:
    """Blocks that count toward the 95% coverage metric."""
    return [b for b in blocks if b["block_type"] in {"function", "method", "class"}]
