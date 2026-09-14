#!/usr/bin/env python3
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image
import json, re

ROOT=Path("recovered/castle-acre")
INDEX=ROOT/"index.html"
REPORT=ROOT/"recovery-report.json"
ATOZ=Path("atoz-part1.html")

assert INDEX.exists(), "index.html missing"
assert REPORT.exists(), "recovery-report.json missing"
assert ATOZ.exists(), "atoz-part1.html missing"

rep=json.loads(REPORT.read_text(encoding="utf-8"))
assert rep["original_image_positions_identified"]==17
assert rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]+rep["still_missing"]==17
assert rep["status"] in ("COMPLETE","PARTIAL")

html=INDEX.read_text(encoding="utf-8")
assert not any(x in html for x in ("Ã","Â","â€","â€™","â€“")), "mojibake remains"
soup=BeautifulSoup(html,"html.parser")
imgs=soup.find_all("img")
assert len(imgs)==rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"], (
    f"displayed image count mismatch: {len(imgs)}"
)
for im in imgs:
    src=im.get("src","")
    assert src and not re.match(r"https?://",src), f"external image reference: {src}"
    p=ROOT/src
    assert p.exists(), f"missing local image: {p}"
    with Image.open(p) as z:
        z.verify()

for x in rep["images"]:
    p=ROOT/x["file"]
    assert p.exists(), f"report image missing: {p}"
    with Image.open(p) as z:
        assert [z.width,z.height]==x["dimensions"], f"dimension mismatch for {p}"
        z.verify()

a=ATOZ.read_text(encoding="utf-8")
assert 'href="recovered/castle-acre/"' in a
assert not re.search(r'href="[^"]*castle_acre\.html"[^>]*>Castle Acre',a,re.I)
print(json.dumps({
    "verified":True,
    "status":rep["status"],
    "positions":rep["original_image_positions_identified"],
    "full_or_near_full":rep["recovered_full_or_near_full"],
    "lower_resolution":rep["recovered_thumbnail_or_lower_resolution"],
    "missing":rep["still_missing"],
    "missing_identities":[x["identity"] for x in rep["missing"]]
},indent=2))
