#!/usr/bin/env python3
import json,re,os
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup

TS="20170208220118"
ORIG="http://www.castlesfortsbattles.co.uk/north_east/barnard_castle.html"
ROOT=Path("recovered/barnard-castle");ROOT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 (Barnard Castle archival audit)"
def get(u,t=25):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None
urls=[
 f"https://web.archive.org/web/{TS}id_/{ORIG}",
 f"https://web.archive.org/web/{TS}id_/https://www.castlesfortsbattles.co.uk/north_east/barnard_castle.html",
]
r=None;used=None
for u in urls:
    rr=get(u)
    if rr and rr.status_code==200 and "<html" in rr.text.lower():
        r=rr;used=u;break
if not r: raise SystemExit("source capture unavailable")
html=r.text
(ROOT/"source.html").write_text(html,encoding="utf-8",errors="replace")
soup=BeautifulSoup(html,"html.parser")
refs=[]
for e in soup.find_all(["img","a"]):
    vals=[]
    if e.name=="img":
        for a in ("src","data-src","data-orig-src","data-muse-src","data-hidpi-src"):
            v=(e.get(a) or "").strip()
            if v:vals.append((a,v))
    else:
        v=(e.get("href") or "").strip()
        if re.search(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",v,re.I):vals.append(("href",v))
    for attr,v in vals:
        if v.startswith("data:"):continue
        u=urljoin(ORIG,v)
        refs.append({"tag":e.name,"attr":attr,"raw":v,"resolved":u,"stem":os.path.splitext(os.path.basename(urlsplit(u).path))[0]})
# dedupe exact tuples
seen=set();out=[]
for x in refs:
    k=(x["tag"],x["attr"],x["resolved"])
    if k in seen:continue
    seen.add(k);out.append(x)
text=[]
for e in soup.find_all(["h1","h2","h3","h4","p","li"]):
    tx=" ".join(e.stripped_strings)
    if tx:text.append(tx)
report={"source_replay":used,"html_bytes":len(html.encode("utf-8",errors="ignore")),"image_refs":out,"image_ref_count":len(out),"text_block_count":len(text),"text_sample":text[:80]}
(ROOT/"source-audit.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps(report,indent=2,ensure_ascii=False))
