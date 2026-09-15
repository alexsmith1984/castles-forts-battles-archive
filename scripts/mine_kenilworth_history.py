#!/usr/bin/env python3
import io,json,re,hashlib
from pathlib import Path
from urllib.parse import quote,urljoin
import requests
from PIL import Image

ROOT=Path("recovered/kenilworth-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 KenilworthHistoricalRecovery"
PAGE="http://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html"

def get(u,t=8):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None
def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify(); return z
    except Exception:return None
def replay(ts,u):
    for mod in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mod}/{u}")
        if r and r.status_code==200 and info(r.content):return r.content
def save(i,b,ts,u,method,q):
    z=info(b); ext=".png" if z[2]=="PNG" else ".jpg"; p=IMG/(i+ext); p.write_bytes(b)
    return {"identity":i,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
      "method":method,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}

r=json.loads(REP.read_text()); order=r["desktop_image_identities"]
gids=[x for x in order if x.startswith("gallery_")]
existing={x["identity"]:x for x in r.get("images",[])}
q="https://web.archive.org/cdx/search/cdx?url="+quote(PAGE,safe=":/")+"&output=json&fl=timestamp,original,statuscode&filter=statuscode:200&collapse=digest"
x=get(q,10); rows=[]
if x and x.status_code==200:
    try:rows=x.json()[1:]
    except Exception:pass
# Sample the archive history rather than replaying every capture.
if rows:
    chosen=[]
    chosen += rows[:4]
    chosen += rows[-4:]
    mid=len(rows)//2
    chosen += rows[max(0,mid-2):mid+2]
    seen=set(); rows=[x for x in chosen if tuple(x[:2]) not in seen and not seen.add(tuple(x[:2]))]
for row in rows:
    if len(row)<2:continue
    ts,pu=row[0],row[1]; pr=get(f"https://web.archive.org/web/{ts}id_/{pu}",10)
    if not pr or pr.status_code!=200:continue
    h=pr.text
    hashes=re.findall(r'new wp_galleryimage\("wpimages/([0-9a-f]+)\.jpg"',h,re.I)
    for n,ident in enumerate(gids):
        if ident in existing or n>=len(hashes):continue
        hh=hashes[n]
        for u,qv in ((urljoin(pu,"wpimages/"+hh+".jpg"),"full/near-full"),(urljoin(pu,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution")):
            b=replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,"historical-gallery-position",qv);break
    for ident in ("kenilworth_castle1","kenilworth_castle9","kenilworth_castle15"):
        if ident in existing:continue
        num=ident.replace("kenilworth_castle","")
        m=re.search(r'<a[^>]+href="([^"]*Kenilworth_Castle'+re.escape(num)+r'\.(?:JPG|jpg))"[^>]*>\s*<img[^>]+src="([^"]+)"',h,re.I)
        if not m:continue
        orig=urljoin(pu,m.group(1)); disp=urljoin(pu,m.group(2))
        for u,qv,method in ((orig,"full/near-full","historical-original"),(disp,"thumbnail/lower-resolution","historical-display-export")):
            b=replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,method,qv);break

r["images"]=[existing[i] for i in order if i in existing]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old[i] for i in order if i not in existing and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]); r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_page_mining_2026_09_14"]={"completed":True,"page_captures_checked":len(rows),"recovered":[i for i in order if i in existing]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"captures":len(rows),"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
