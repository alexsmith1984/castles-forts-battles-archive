#!/usr/bin/env python3
import json,re
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from PIL import Image

PAGES=[
 ("Bolingbroke Castle","bolingbroke-castle","http://www.castlesfortsbattles.co.uk/midlands/bolingbroke_castle.html"),
 ("Conisbrough Castle","conisbrough-castle","https://www.castlesfortsbattles.co.uk/yorkshire/conisbrough_castle.html"),
 ("Pembroke Castle","pembroke-castle","http://www.castlesfortsbattles.co.uk/south_west_wales/pembroke_castle.html"),
 ("Kenilworth Castle","kenilworth-castle","http://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html"),
 ("Goodrich Castle","goodrich-castle","http://www.castlesfortsbattles.co.uk/midlands/goodrich_castle.html"),
 ("Fotheringhay Castle","fotheringhay-castle","http://www.castlesfortsbattles.co.uk/midlands/fotheringhay_castle.html"),
 ("Framlingham Castle","framlingham-castle","http://www.castlesfortsbattles.co.uk/east/framlingham_castle.html"),
 ("Pevensey Castle","pevensey-castle","http://www.castlesfortsbattles.co.uk/south_east/pevensey_castle.html"),
 ("Pickering Castle","pickering-castle","http://www.castlesfortsbattles.co.uk/yorkshire/pickering_castle.html"),
 ("Pontefract Castle","pontefract-castle","http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html"),
 ("Richmond Castle","richmond-castle","http://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html"),
 ("Sandal Castle","sandal-castle","http://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html"),
 ("Warkworth Castle","warkworth-castle","http://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html"),
 ("Whittington Castle","whittington-castle","http://www.castlesfortsbattles.co.uk/north_west/whittington_castle_lancashire.html"),
]

rows=[];bad=[]
for name,slug,orig in PAGES:
    rpath=Path("page-audit")/f"{slug}.json"
    if not rpath.exists():
        bad.append((name,"missing worker report"));continue
    row=json.loads(rpath.read_text(encoding="utf-8"))
    if row.get("status")!="built":
        bad.append((name,row));continue
    root=Path("recovered")/slug
    rep=json.loads((root/"recovery-report.json").read_text(encoding="utf-8"))
    recovered=rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]
    assert rep["original_image_positions_identified"]==recovered+rep["still_missing"],name
    html=(root/"index.html").read_text(encoding="utf-8")
    assert not any(x in html for x in ("â","Ã","�")),name
    soup=BeautifulSoup(html,"html.parser")
    imgs=[x["src"] for x in soup.find_all("img",src=True)]
    assert len(imgs)==recovered,(name,len(imgs),recovered)
    for rel in imgs:
        with Image.open(root/rel) as im:im.verify()
    row["missing_identities"]=[x["identity"] for x in rep.get("missing",[])]
    rows.append(row)
assert not bad,bad

# Replace every A-Z Wayback/direct target containing the original path.
replacements=0
for i in range(1,6):
    path=Path(f"atoz-part{i}.html")
    s=path.read_text(encoding="utf-8")
    for name,slug,orig in PAGES:
        tail=urlsplit(orig).path
        pat=r'href="[^"]*'+re.escape(tail)+r'"'
        s,n=re.subn(pat,f'href="recovered/{slug}/"',s,flags=re.I)
        replacements+=n
    path.write_text(s,encoding="utf-8")

allidx="".join(Path(f"atoz-part{i}.html").read_text(encoding="utf-8") for i in range(1,6))
for _,slug,_ in PAGES:
    assert f"recovered/{slug}/" in allidx,slug

summary={"pages":rows,"index_links_replaced":replacements}
Path("page-audit/castle-image-audit-batch-2026-09-13.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps(summary,indent=2,ensure_ascii=False))
