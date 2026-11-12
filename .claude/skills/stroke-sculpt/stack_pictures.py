"""Join pictures for the orchestrator's report: top to bottom at one width (the reference strip
above a round's multiview), or with --across left to right at one height (the seven reference
pictures into one strip).
usage: stack_pictures.py <out.png> <picture.png>... [--across] [--size 2000]"""

import sys

from PIL import Image

arguments = sys.argv[1:]
across = "--across" in arguments
if across:
    arguments.remove("--across")
size = 300 if across else 2000
if "--size" in arguments:
    at = arguments.index("--size")
    size = int(arguments[at + 1])
    del arguments[at:at + 2]
out, pictures = arguments[0], [Image.open(path).convert("RGB") for path in arguments[1:]]
if across:
    pictures = [picture.resize((picture.width * size // picture.height, size)) for picture in pictures]
    sheet = Image.new("RGB", (sum(picture.width for picture in pictures), size), "white")
else:
    pictures = [picture.resize((size, picture.height * size // picture.width)) for picture in pictures]
    sheet = Image.new("RGB", (size, sum(picture.height for picture in pictures)), "white")
offset = 0
for picture in pictures:
    sheet.paste(picture, (offset, 0) if across else (0, offset))
    offset += picture.width if across else picture.height
sheet.save(out)
