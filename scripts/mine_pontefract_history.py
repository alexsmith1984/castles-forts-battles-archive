#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/pontefract-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(parents=True,exist_ok=True)
PAGES=[
 "http://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html",
 "https://www.castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html",
 "http://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html",
 "https://castlesfortsbattles.co.uk/yorkshire/pontefract_castle.html",
]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 PontefractHistoricalRecovery"

def get(u,t=12):
    r=None
    for n in range(3):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504):return r
        except Exception:r=None
        time.sleep(0.7*(n+1))
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify();return z
    except Exception:return None

def page_replay(source,ts,u):
    ep=("https://web.archive.org/web/"+ts+"id_/"+u) if source=="wayback" else ("https://arquivo.pt/wayback/"+ts+"id_/"+u)
    return get(ep,10)

def image_replay(source,ts,u):
    urls=[("https://web.archive.org/web/"+ts+m+"/"+u) for m in ("id_","im_")] if source=="wayback" else ["https://arquivo.pt/wayback/"+ts+"id_/"+u]
    for x in urls:
        r=get(x,8)
        if r and r.status_code==200 and info(r.content):return r.content
    return None

def save(identity,b,source,ts,u,method,quality):
    z=info(b);ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(identity+ext);p.write_bytes(b)
    return {"identity":identity,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
      "method":source+"-"+method,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),"quality":quality,"identification":"certain"}

def timemap_rows(source,page):
    if source=="wayback":
        ep="https://web.archive.org/web/timemap/link/"+page; marker="/web/"
    else:
        ep="https://arquivo.pt/wayback/timemap/link/"+page; marker="/wayback/"
    r=get(ep,18)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line or ">" not in line:continue
        uri=line.split("<",1)[1].split(">",1)[0]
        if marker not in uri:continue
        rest=uri.split(marker,1)[1]
        if "/" not in rest:continue
        ts,orig=rest.split("/",1);ts=ts[:14]
        if len(ts)==14 and ts.isdigit() and orig.startswith(("http://","https://")):
            out.append((source,ts,orig))
    return out

captures=[]
for p in PAGES:
    captures+=timemap_rows("wayback",p)
    captures+=timemap_rows("arquivo",p)
seen=set();captures=[x for x in captures if x not in seen and not seen.add(x)]
captures.sort(key=lambda x:x[1])
if len(captures)>28:
    idx={0,len(captures)-1}
    for n in range(1,27):idx.add(round(n*(len(captures)-1)/27))
    captures=[captures[i] for i in sorted(idx)]

r=json.loads(REP.read_text())
order=r["desktop_image_identities"]
gids=[x for x in order if x.startswith("gallery_")]
found={x["identity"]:x for x in r.get("images",[])}
checked=0
print(json.dumps({"timemap_captures_found":len(captures)}),flush=True)

for source,ts,pageurl in captures:
    pr=page_replay(source,ts,pageurl)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1;h=pr.text

    hashes=[]
    key='new wp_galleryimage("wpimages/'
    for line in h.splitlines():
        if key not in line:continue
        tail=line.split(key,1)[1]
        if '.jpg"' not in tail:continue
        hh=tail.split('.jpg"',1)[0]
        if hh and hh not in hashes:hashes.append(hh)

    for n,identity in enumerate(gids):
        if identity in found or n>=len(hashes):continue
        hh=hashes[n]
        # WebPlus paths are relative to the historical page folder.
        candidates=[
          (urljoin(pageurl,"wpimages/"+hh+".jpg"),"full/near-full"),
          (urljoin(pageurl,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution"),
          ("http://www.castlesfortsbattles.co.uk/wpimages/"+hh+".jpg","full/near-full"),
          ("http://www.castlesfortsbattles.co.uk/wpimages/"+hh+"t.jpg","thumbnail/lower-resolution")
        ]
        for u,q in candidates:
            b=image_replay(source,ts,u)
            if b:
                found[identity]=save(identity,b,source,ts,u,"historical-gallery-position",q)
                print("RECOVERED",identity,source,ts,u,info(b),q,flush=True)
                break

    # Try to upgrade the hero from display export to its full original.
    hero=found.get("pontefract_castle15")
    if not hero or hero.get("quality")!="full/near-full":
        soup=BeautifulSoup(h,"html.parser")
        for a in soup.find_all("a",href=True):
            if a["href"].split("/")[-1].lower()=="pontefract_castle15.jpg":
                u=urljoin(pageurl,a["href"])
                b=image_replay(source,ts,u)
                if b:
                    found["pontefract_castle15"]=save("pontefract_castle15",b,source,ts,u,"historical-original","full/near-full")
                    print("UPGRADED HERO",source,ts,u,info(b),flush=True)
                break

old={x["identity"]:x for x in r.get("missing",[])}
r["images"]=[found[i] for i in order if i in found]
r["missing"]=[old[i] for i in order if i not in found and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]);r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_timemap_mining_2026_09_15"]={"completed":True,"captures_found":len(captures),"captures_checked":checked,"recovered":[i for i in order if i in found]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"captures_found":len(captures),"captures_checked":checked,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
