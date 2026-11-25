#!/usr/bin/env python3
"""PostToolUse hook on Edit, Write and MultiEdit: flags a new constant that restates mesh structure.

Ixdar has one home for each structural count: the corners of a triangle are
``HalfEdgeMesh.TRIANGLE_CORNERS``, the coordinates of a point are ``PackedPoints.XYZ``, the turns
of a cross field are ``IntegerGridMap.QUARTER_TURNS``, the corners of a quad are
``ExtractedQuadMesh.QUAD_CORNERS``. A survey of the tree on 2026-11-23 found 12 private copies of
TRIANGLE_CORNERS, 11 of COORDINATES_PER_POINT, 9 ``CORNERS = 3``, 5 ``CORNERS_PER_FACE`` and
dozens more spellings (VERTICES_PER_TRIANGLE, TRIANGLE_SIDES, VEC3_SIZE, VECTOR_STRIDE, THREE,
TRIANGLE ...), each added by an agent that did not look for the shared one.

The hook reads only the lines the edit adds (``new_string`` lines absent from ``old_string``; all
of a Write's content), finds ``final int NAME = 2|3|4;`` declarations, static or local, whose
name says what the count is, and reports the constant to use instead. It never blocks the edit:
the report reaches the model as feedback, like the checkstyle hook's. A count with no shared
home yet (two uv or xy components, faces per manifold edge) is reported with the copies that
exist, so the next agent reuses one rather than adding another.
"""

import os
import re
import sys

from hook_common import BLOCK_EXIT_CODE, read_event

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})

DECLARATION = re.compile(r"\bfinal\s+(?:int|long|short|byte)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([234])\s*;")

# Names that are a limit, a tuning value, a component index or another kind of part (colour
# channels, tetrahedra) rather than a structural count.
NOT_A_COUNT = re.compile(
    r"(^|_)(MIN|MINIMUM|MAX|MAXIMUM|DEFAULT|LIMIT|PASSES|ROUNDS|STEPS|DEPTH|INDEX|IDX)(_|$)"
    r"|_[XYZW]$|TETRA|EMISSIVE|COLOU?R|RGB"
)

# The word for a number on its own is never a meaning (THREE_QUARTERS is one, so only bare words).
NUMBER_WORD = re.compile(r"^(TWO|THREE|FOUR)$")

TRIANGLE_PARTS = re.compile(
    r"TRIANG|(^|_)TRI(_|$)|CORNER|VERTICES_PER|VERTS_PER|(^|_)SIDES?(_|$)|PER_FACE|PER_TRIANGLE"
)
COORDINATE_PARTS = re.compile(
    r"COORD|XYZ|POSITION|VEC3|VECTOR|COMPONENT|FLOATS_PER|DOUBLES_PER|(^|_)DIM|DIMENSION|(^|_)AXES(_|$)"
)
PLANE_PARTS = re.compile(r"(^|_)UV(_|$)|(^|_)XY(_|$)|COORD|COMPONENT|(^|_)DIM|DIMENSION|(^|_)AXES(_|$)")
QUAD_PARTS = re.compile(r"QUAD|(^|_)SIDES(_|$)|CORNER")
TURN_PARTS = re.compile(r"QUARTER|ROSY|SYMMETRY|TURNS|ROTATION_COUNT")
EDGE_FACE_PARTS = re.compile(r"(FACES|SLOTS|SHEETS)_PER_EDGE|PER_MANIFOLD_EDGE")

# (value, name pattern, meaning, the shared constant or None, existing copies to reuse)
FAMILIES = (
    (
        3,
        TRIANGLE_PARTS,
        "the corners of a triangle",
        "whole-triangle operations so the count never appears: TriangleGeometry (corner angles, "
        "cross products, areas) and MeshTopology (facePoints, faceArea, faceVertexAt, oneRings), "
        "both in ixdar.geometry.mesh.data.representation; only where a bare count is unavoidable, "
        "HalfEdgeMesh.TRIANGLE_CORNERS",
        "",
    ),
    (
        3,
        COORDINATE_PARTS,
        "the coordinates of a 3-D point",
        "PackedPoints (ixdar.geometry.mesh.data.representation) and read and write whole points as "
        "Vector3f (get, set, gather, ringMean, centroid) instead of striding a float[] by hand; "
        "only where a bare stride is unavoidable, PackedPoints.XYZ",
        "",
    ),
    (
        4,
        TURN_PARTS,
        "the quarter turns of a cross field",
        "IntegerGridMap.QUARTER_TURNS (ixdar.geometry.mesh.quadlayout.gridmap)",
        "",
    ),
    (
        4,
        QUAD_PARTS,
        "the corners or sides of a quad",
        "ExtractedQuadMesh.QUAD_CORNERS (ixdar.geometry.mesh.quadlayout.extraction)",
        "",
    ),
    (
        2,
        EDGE_FACE_PARTS,
        "the faces on a manifold edge",
        None,
        "MeshRepair.SLOTS_PER_EDGE",
    ),
    (
        2,
        PLANE_PARTS,
        "the two components of a uv or xy coordinate",
        None,
        "CurveGeometry.XY, GltfMeshParser.UV_COMPONENTS, MeshExport.UV_COMPONENTS, "
        "IntegerGridMap.GRID_COORDINATES, GlobalGridMap.GRID_COORDINATES",
    ),
)

# The shared declarations themselves, by file name and constant name.
CANONICAL = frozenset(
    {
        ("HalfEdgeMesh.java", "TRIANGLE_CORNERS"),
        ("PackedPoints.java", "XYZ"),
        ("IntegerGridMap.java", "QUARTER_TURNS"),
        ("ExtractedQuadMesh.java", "QUAD_CORNERS"),
        ("MeshRepair.java", "SLOTS_PER_EDGE"),
    }
)


def added_text(tool, tool_input):
    """The lines this edit adds, as one string."""
    if tool == "Write":
        return str(tool_input.get("content") or "")
    pairs = []
    if tool == "MultiEdit":
        for edit in tool_input.get("edits") or []:
            pairs.append((str(edit.get("old_string") or ""), str(edit.get("new_string") or "")))
    else:
        pairs.append((str(tool_input.get("old_string") or ""), str(tool_input.get("new_string") or "")))
    added = []
    for old, new in pairs:
        before = set(line.strip() for line in old.splitlines())
        added.extend(line for line in new.splitlines() if line.strip() not in before)
    return "\n".join(added)


def finding(name, value):
    """The report for one declaration, or None when it is not a structural count."""
    upper = name.upper()
    if NUMBER_WORD.search(upper):
        return (
            f"'{name} = {value}' names the number, not what it counts; use the shared constant for that count"
        )
    if NOT_A_COUNT.search(upper):
        return None
    for family_value, pattern, meaning, shared, copies in FAMILIES:
        if value != family_value or not pattern.search(upper):
            continue
        if shared:
            return f"'{name} = {value}' restates {meaning}; use {shared}"
        return (
            f"'{name} = {value}' restates {meaning}, which has no shared constant yet; reuse one of "
            f"{copies} instead of adding another copy"
        )
    return None


def line_of(path, declaration):
    """The 1-based line of a declaration in the edited file, or 0 when it cannot be found."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if declaration in line:
                    return number
    except OSError:
        pass
    return 0


def reports(path, text):
    """Every structural-constant report for the added text of one file."""
    base = os.path.basename(path)
    found = []
    for match in DECLARATION.finditer(text):
        name, value = match.group(1), int(match.group(2))
        if (base, name) in CANONICAL:
            continue
        message = finding(name, value)
        if message:
            line = line_of(path, match.group(0))
            where = f"{base}:{line}" if line else base
            found.append(f"{where}: {message}. [StructuralConstant]")
    return found


def main():
    event = read_event()
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path")
    if tool not in EDIT_TOOLS or not isinstance(path, str) or not path.endswith(".java"):
        sys.exit(0)
    found = reports(path, added_text(tool, tool_input))
    if found:
        sys.stderr.write("\n".join(found) + "\n")
        sys.exit(BLOCK_EXIT_CODE)
    sys.exit(0)


if __name__ == "__main__":
    main()
