"""Assemble the architecture-diagram payload.

Components are files; each holds its functions/methods/classes. Edges are the
call graph: function-to-function plus an aggregated component-to-component view
(intra-file calls are dropped from the component view as internal detail).
"""
from pathlib import Path
from typing import Dict

# Stub — implemented in the green commit.


def build_diagram(project_path: Path, config: dict) -> Dict:
    return {"components": [], "function_edges": [], "component_edges": []}
