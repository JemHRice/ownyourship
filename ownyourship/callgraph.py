"""Static call-graph extraction (Python only).

Best-effort: callees are resolved by name against project definitions, so it
won't capture dynamic dispatch and may link a few same-named functions. Good
enough for an architecture overview; the edges are real (parsed from the code),
not inferred.
"""
from pathlib import Path
from typing import Dict, Set, Tuple

# Stub — implemented in the green commit.


def extract_call_edges(project_path: Path, config: dict) -> Set[Tuple[str, str]]:
    """Return a set of (caller_qualname, callee_qualname) call edges.

    Qualnames are "relpath::name" for module-level functions/classes and
    "relpath::Class.method" for methods.
    """
    return set()
