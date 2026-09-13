#!/usr/bin/env python3
import json
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image

root=Path("recovered/castle-rising-castle")
rep=json.loads((root/"recovery-report.json").read_text(encoding="utf-8"))
text=(root/"index.html").read_text(encoding="utf-8")
recovered=rep.get("images_recovered")
if recovered is None:
    recovered=rep.get("recovered_full_or_near_full",0)+rep.get("recovered_thumbnail_or_lower_resolution",0)
assert rep["original_image_positions_identified"]==recovered+rep["still_missing"]
assert "recovered/castle-rising-castle/" in Path("atoz-part1.html").read_text(encoding="utf-8")
assert "../../atoz-part1.html#c" in text
assert not any(x in text for x in ("â","Ã","�"))
soup=BeautifulSoup(text,"html.parser")
seen=[]
for im in soup.find_all("img",src=True):
    p=root/im["src"]
    with Image.open(p) as x:
        x.verify()
    seen.append(im["src"])
assert len(seen)==recovered, (len(seen),recovered)
print(json.dumps({k:v for k,v in rep.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
