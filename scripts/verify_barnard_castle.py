#!/usr/bin/env python3
import json
from pathlib import Path
from PIL import Image
root=Path("recovered/barnard-castle")
rep=json.loads((root/"recovery-report.json").read_text(encoding="utf-8"))
recovered=rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]
assert rep["original_image_positions_identified"]==recovered+rep["still_missing"]
html=(root/"index.html").read_text(encoding="utf-8")
assert "recovered/barnard-castle/" in Path("atoz-part1.html").read_text(encoding="utf-8")
for x in rep["images"]:
    with Image.open(root/x["file"]) as im: im.verify()
    assert x["file"] in html
print(json.dumps(rep,indent=2,ensure_ascii=False))
