"""Render reference pictures of a goal mesh through Ixdar, the way a real reference set looks.

    uv run python render_references.py --checkout IXDAR_CHECKOUT --goal GOAL.obj \
        --out OUT_DIR --manifest MANIFEST.json [--seed N]

Loads the goal in the mesh viewer of IXDAR_CHECKOUT (a checkout or worktree whose ixdar-cli has
`orbit-set --fov --roll`), in clay shading, and takes one screenshot per nominal view (front,
sides, three-quarters, back, top). Each view's azimuth and elevation are jittered by a few degrees,
with a small roll, a field of view anywhere from long lens to wide, the subject filling a random
share of the frame, and the headlight on or off. The pictures are named only by their nominal
view (ref_03_front_right.png); the exact camera of each goes to MANIFEST.json, which belongs with
the goal, out of the sculptor's sight.
"""

import argparse
import json
import math
import random
import subprocess
from pathlib import Path

# Azimuth and elevation in degrees, in the orbit convention multiview uses: the Front cell is
# azimuth 90, the Right cell 0, the Left cell 180.
NOMINAL_VIEWS = [
    ("front", 90.0, 0.0),
    ("front_right", 45.0, 10.0),
    ("front_left", 135.0, 10.0),
    ("right", 0.0, 0.0),
    ("left", 180.0, 0.0),
    ("back", -90.0, 5.0),
    ("top", 90.0, 70.0),
]
ANGLE_JITTER_DEG = 8.0
ROLL_JITTER_DEG = 3.0
FOV_RANGE_DEG = (15.0, 55.0)
FILL_RANGE = (0.55, 0.85)


def ixdar(checkout, *args):
    """Run one ixdar-cli command in the checkout and return its JSON reply, failing loudly."""
    result = subprocess.run(["uv", "run", "ixdar-cli", *args], cwd=checkout, capture_output=True, text=True)
    reply = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
    if result.returncode != 0 or reply.get("ok") is False:
        raise SystemExit(f"ixdar-cli {' '.join(args)} failed: {result.stdout}{result.stderr}")
    return reply


def render(checkout, goal, out_dir, manifest_path, seed):
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    ixdar(
        checkout,
        "run-scene",
        "--scene",
        "mesh-viewer",
        "--property",
        f"ixdar.model={goal}",
        "--keep-alive",
    )
    try:
        framed = ixdar(checkout, "frame")
        center, radius = framed["center"], framed["radius"]
        target = ",".join(f"{c:.6f}" for c in center)
        shots = []
        for index, (name, azimuth, elevation) in enumerate(NOMINAL_VIEWS, start=1):
            az = azimuth + rng.uniform(-ANGLE_JITTER_DEG, ANGLE_JITTER_DEG)
            el = elevation + rng.uniform(-ANGLE_JITTER_DEG, ANGLE_JITTER_DEG)
            roll = rng.uniform(-ROLL_JITTER_DEG, ROLL_JITTER_DEG)
            fov = rng.uniform(*FOV_RANGE_DEG)
            fill = rng.uniform(*FILL_RANGE)
            headlight = rng.random() < 0.5
            distance = radius / (fill * math.tan(math.radians(fov) / 2.0))
            ixdar(checkout, "shading", "clay", *(["--headlight"] if headlight else []))
            ixdar(
                checkout,
                "orbit-set",
                "--azimuth",
                f"{math.radians(az):.6f}",
                "--elevation",
                f"{math.radians(el):.6f}",
                "--distance",
                f"{distance:.6f}",
                "--target",
                target,
                "--fov",
                f"{fov:.4f}",
                "--roll",
                f"{math.radians(roll):.6f}",
            )
            file_name = f"ref_{index:02d}_{name}.png"
            ixdar(checkout, "screenshot", "--out", str(out_dir / file_name))
            shots.append(
                {
                    "file": file_name,
                    "nominal": name,
                    "azimuth_deg": az,
                    "elevation_deg": el,
                    "roll_deg": roll,
                    "fov_deg": fov,
                    "fill": fill,
                    "distance": distance,
                    "headlight": headlight,
                }
            )
    finally:
        ixdar(checkout, "shutdown")
    manifest = {
        "goal": str(goal),
        "seed": seed,
        "center": center,
        "radius": radius,
        "shots": shots,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    render(
        args.checkout,
        args.goal.resolve(),
        args.out.resolve(),
        args.manifest.resolve(),
        args.seed,
    )


main()
