#!/usr/bin/env python3
import json
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image

root=Path("recovered/castle-rising-castle")
rep=json.loads((root/"recovery-report.json").read_text(encoding="utf-8"))
text=(root/"index.html").read_text(encoding="utf-8")
assert rep["original_image_positions_identified"]==rep["images_recovered"]+rep["still_missing"]
assert "recovered/castle-rising-castle/" in Path("atoz-part1.html").read_text(encoding="utf-8")
assert "../../atoz-part1.html#c" in text
assert not any(x in text for x in ("â","Ã","�"))
soup=BeautifulSoup(text,"html.parser")
for im in soup.find_all("img",src=True):
    with Image.open(root/im["src"]) as x:
        x.verify()
print(json.dumps({k:v for k,v in rep.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
