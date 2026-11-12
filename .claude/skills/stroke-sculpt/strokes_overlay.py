"""Overlay every stroke of a synced one-pass stroke SVG on a multiview capture taken through the
SVG's own camera, one colour per <g id> group: a translucent band about as wide as the stroke's
data-radius, a solid centre line (faint where the span is hidden from that cell), fills tinted.
The background is the final sculpt captured through the SVG's camera: `ixdar-cli model --path
<sculpt>.dsl`, then `ixdar-cli multiview --camera <strokes.svg> --shading clay --out <background.png>`.
usage: strokes_overlay.py <background.png> <strokes.svg> <out.png>"""

import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

COLOURS = [(230, 25, 75), (60, 180, 75), (255, 200, 25), (0, 130, 200), (245, 130, 48),
           (145, 30, 180), (70, 240, 240), (240, 50, 230), (128, 128, 0), (0, 128, 128)]
background = Image.open(sys.argv[1]).convert("RGBA")
text = re.sub(r"<!--.*?-->", "", Path(sys.argv[2]).read_text(), flags=re.S)
scale = background.width / float(re.search(r'width="(\d+)"', text).group(1))
cell = float(re.search(r'data-cell-height="(\d+)"', text).group(1))
distance = float(re.search(r'data-distance="([\d.]+)"', text).group(1))
fov = float(re.search(r'data-fov="([\d.]+)"', text).group(1))
pixels_per_unit = cell / (2 * distance * math.tan(math.radians(fov) / 2)) * scale
layer = Image.new("RGBA", background.size)
draw = ImageDraw.Draw(layer)
legend = []
for index, group in enumerate(re.finditer(r'<g id="([^"]+)"(.*?)</g>', text, re.S)):
    colour = COLOURS[index % len(COLOURS)]
    legend.append((group.group(1), colour))
    for shape in re.finditer(r"<(polyline|polygon)\b([^>]*)/?>", group.group(2)):
        attributes = shape.group(2)
        points = [tuple(float(v) * scale for v in p.split(","))
                  for p in re.search(r'points="([^"]+)"', attributes).group(1).split()]
        radius = re.search(r'data-radius="([\d.]+)"', attributes)
        band = max(2, int(2 * float(radius.group(1)) * pixels_per_unit)) if radius else 4
        hidden = "data-hidden" in attributes
        tint, line = (40, 25, 110) if hidden else (90, 70, 255), None
        if shape.group(1) == "polygon" and len(points) > 2:
            draw.polygon(points, fill=colour + (tint[0],))
            draw.line(points + [points[0]], fill=colour + (tint[2],), width=2)
        elif len(points) > 1:
            draw.line(points, fill=colour + (tint[1],), width=band, joint="curve")
            draw.line(points, fill=colour + (tint[2],), width=2)
canvas = Image.alpha_composite(background, layer)
key = ImageDraw.Draw(canvas)
for row, (name, colour) in enumerate(legend):
    key.rectangle([20, 20 + row * 34, 46, 46 + row * 34], fill=colour + (255,))
    key.text((56, 24 + row * 34), name, fill=(0, 0, 0, 255), font_size=26)
canvas.convert("RGB").resize((canvas.width // 2, canvas.height // 2)).save(sys.argv[3])
