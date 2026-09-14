#!/usr/bin/env python3
from pathlib import Path
from urllib.parse import urlsplit
import hashlib, io, json, re, requests
from PIL import Image
from bs4 import BeautifulSoup

TS="20210918022557"
BASE="http://www.castlesfortsbattles.co.uk/east/"
ROOT=Path("recovered/castle-acre")
IMG=ROOT/"images"
REPORT=ROOT/"recovery-report.json"
INDEX=ROOT/"index.html"
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archival recovery; Castle Acre exact Muse pass)"

TARGETS={
 "castle_acre2":["images/castle_acre2.jpg?crc=4293937263","images/castle_acre260x40.jpg?crc=3978859742"],
 "castle_acre4":["images/castle_acre4.jpg?crc=87800293","images/castle_acre460x40.jpg?crc=3886452555"],
 "castle_acre5":["images/castle_acre5.jpg?crc=4084861691","images/castle_acre501x212.jpg?crc=3761747450","images/castle_acre500x211.jpg?crc=4090056439","images/castle_acre560x40.jpg?crc=3760252947"],
 "castle_acre6":["images/castle_acre6.jpg?crc=792746","images/castle_acre665x281.jpg?crc=3860119824","images/castle_acre665x280.jpg?crc=4064561660","images/castle_acre660x40.jpg?crc=488745313"],
 "castle_acre9":["images/castle_acre9.jpg?crc=4047234631","images/castle_acre960x40.jpg?crc=4246555299"],
 "castle_acre11":["images/castle_acre11.jpg?crc=516046076","images/castle_acre1160x40.jpg?crc=4241104827"],
 "castle_acre12":["images/castle_acre12.jpg?crc=3839862586","images/castle_acre1260x40.jpg?crc=3803228514"],
 "castle_acre13":["images/castle_acre13.jpg?crc=3982903584","images/castle_acre1360x40.jpg?crc=284044959"],
 "castle_acre14":["images/castle_acre14.jpg?crc=13211031","images/castle_acre1460x40.jpg?crc=4106457123"],
 "castle_acre15":["images/castle_acre15.jpg?crc=4121071839","images/castle_acre1560x40.jpg?crc=3840880635"],
 "castle_acre16":["images/castle_acre16.jpg?crc=4250416419","images/castle_acre1642x45.jpg?crc=3982584948"],
}
ORDER=["castle_acre","castle_acre2","castle_acre3","castle_acre4","castle_acre5","castle_acre6","castle_acre7","castle_acre8","castle_acre9","castle_acre10","castle_acre11","castle_acre12","castle_acre13","castle_acre14","castle_acre15","castle_acre16","castle_acre_layout"]

def raw(u): return f"https://web.archive.org/web/{TS}id_/{u}"

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify()
        return w,h,fmt
    except Exception:return None

def try_url(u):
    try:r=S.get(raw(u),timeout=8,allow_redirects=True)
    except Exception:return None
    if r.status_code!=200 or len(r.content)<250:return None
    z=info(r.content)
    if not z or z[0]<40 or z[1]<40:return None
    return r.content,z

rep=json.loads(REPORT.read_text(encoding="utf-8"))
known={x["identity"]:x for x in rep["images"]}
results=[]
for ident,rels in TARGETS.items():
    if ident in known: continue
    found=None
    for rel in rels:
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
            for scheme in ("http","https"):
                u=f"{scheme}://{host}/east/{rel}"
                q=try_url(u)
                if q:
                    b,z=q; found=(u,b,z,rel); break
            if found:break
        if found:break
    if found:
        u,b,z,rel=found
        p=IMG/(ident+".jpg")
        p.write_bytes(b)
        quality="full/near-full" if z[0]>=1000 or z[1]>=1000 else "thumbnail/lower-resolution"
        x={
          "identity":ident,"file":"images/"+p.name,
          "archive_timestamp":TS,"archive_original":u,
          "method":"same-capture-exact-muse-crc",
          "dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
          "sha256":hashlib.sha256(b).hexdigest(),"quality":quality,
          "identification":"certain"
        }
        known[ident]=x
        results.append({"identity":ident,"recovered":True,"url":u,"dimensions":[z[0],z[1]],"quality":quality})
    else:
        results.append({"identity":ident,"recovered":False})

rep["images"]=[known[i] for i in ORDER if i in known]
missing_ids=[i for i in ORDER if i not in known]
rep["missing"]=[x for x in rep.get("missing",[]) if x.get("identity") in missing_ids]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(missing_ids)
rep["status"]="COMPLETE" if not missing_ids else "PARTIAL"
rep["full_size_source_unrecovered_but_position_represented"]=[x["identity"] for x in rep["images"] if x["quality"]!="full/near-full"]
search="exact supplied-capture Muse URLs including original CRC query strings"
if search not in rep["searches_attempted"]: rep["searches_attempted"].append(search)
REPORT.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

soup=BeautifulSoup(INDEX.read_text(encoding="utf-8"),"html.parser")
note=soup.select_one(".note")
if note:
    note.string=(f"Reconstructed from the archived CastlesFortsBattles Castle Acre page. "
      f"{len(rep['images'])} of 17 genuine original content-image identities are represented: "
      f"{rep['recovered_full_or_near_full']} full/near-full archived originals and "
      f"{rep['recovered_thumbnail_or_lower_resolution']} lower-resolution archived originals. "
      "Responsive Muse crops and thumbnails are not counted separately. No unrelated substitute images have been introduced.")
article=soup.find("article")
head=None
for h in article.find_all("h2"):
    if h.get_text(" ",strip=True)=="Recovered original images": head=h
if head:
    for sib in list(head.find_next_siblings()):
        sib.decompose()
    for x in rep["images"]:
        fig=soup.new_tag("figure")
        a=soup.new_tag("a",href=x["file"])
        im=soup.new_tag("img",src=x["file"],alt="Castle Acre archived original image")
        a.append(im); fig.append(a)
        cap=soup.new_tag("figcaption")
        ident=x["identity"]
        if ident=="castle_acre": label="Castle Acre — lead photograph"
        elif ident=="castle_acre_layout": label="Castle Acre — layout plan"
        else: label="Castle Acre "+re.search(r"(\d+)$",ident).group(1)
        if x["quality"]!="full/near-full": label+=" — lower-resolution archived recovery"
        cap.string=label; fig.append(cap); article.append(fig)
INDEX.write_text(str(soup),encoding="utf-8")
(Path("page-audit/castle-acre")/"exact-crc-results.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"status":rep["status"],"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"],"results":results},indent=2))
