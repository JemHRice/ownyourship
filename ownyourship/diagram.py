"""Assemble the architecture-diagram payload.

Components are files; each holds its functions/methods/classes. Edges are the
call graph: function-to-function plus an aggregated component-to-component view
(intra-file calls are dropped from the component view as internal detail).
"""
from pathlib import Path
from typing import Dict

from . import callgraph, scanner


def _qualname(block: Dict) -> str:
    name = block["block_name"]
    if block.get("parent_class"):
        name = f"{block['parent_class']}.{name}"
    return f"{block['file_path']}::{name}"


def build_diagram(project_path: Path, config: dict) -> Dict:
    blocks = scanner.get_meaningful_blocks(scanner.scan_project(project_path, config))
    edges = callgraph.extract_call_edges(project_path, config)

    components: Dict[str, Dict] = {}
    for b in blocks:
        comp = components.setdefault(
            b["file_path"],
            {"id": b["file_path"], "name": Path(b["file_path"]).name, "functions": []},
        )
        comp["functions"].append({
            "id": _qualname(b),
            "name": b["block_name"],
            "type": b["block_type"],
            "parent_class": b.get("parent_class"),
        })

    function_edges = [{"source": s, "target": t} for s, t in sorted(edges)]

    comp_counts: Dict[tuple, int] = {}
    for s, t in edges:
        sf, tf = s.split("::", 1)[0], t.split("::", 1)[0]
        if sf != tf:
            comp_counts[(sf, tf)] = comp_counts.get((sf, tf), 0) + 1
    component_edges = [
        {"source": sf, "target": tf, "count": c}
        for (sf, tf), c in sorted(comp_counts.items())
    ]

    return {
        "components": sorted(components.values(), key=lambda c: c["id"]),
        "function_edges": function_edges,
        "component_edges": component_edges,
    }
