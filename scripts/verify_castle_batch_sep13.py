#!/usr/bin/env python3
import json
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image

p=Path("page-audit/castle-image-audit-batch-2026-09-13.json")
data=json.loads(p.read_text(encoding="utf-8"))
assert len(data["pages"])==14
bad=[]
for row in data["pages"]:
    if row["status"]!="built":
        bad.append((row["name"],row["status"]))
        continue
    root=Path("recovered")/row["slug"]
    rep=json.loads((root/"recovery-report.json").read_text(encoding="utf-8"))
    recovered=rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]
    assert rep["original_image_positions_identified"]==recovered+rep["still_missing"],row["name"]
    html=(root/"index.html").read_text(encoding="utf-8")
    assert not any(x in html for x in ("â","Ã","�")),row["name"]
    soup=BeautifulSoup(html,"html.parser")
    imgs=[x["src"] for x in soup.find_all("img",src=True)]
    assert len(imgs)==recovered,(row["name"],len(imgs),recovered)
    for rel in imgs:
        with Image.open(root/rel) as im:
            im.verify()
assert not bad,bad
allidx="".join(Path(f"atoz-part{i}.html").read_text(encoding="utf-8") for i in range(1,6))
for row in data["pages"]:
    assert f'recovered/{row["slug"]}/' in allidx,row["name"]
print(json.dumps(data,indent=2,ensure_ascii=False))
