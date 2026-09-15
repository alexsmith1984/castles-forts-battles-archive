#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/pickering-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
PAGES=[
 "http://www.castlesfortsbattles.co.uk/yorkshire/pickering_castle.html",
 "https://www.castlesfortsbattles.co.uk/yorkshire/pickering_castle.html",
 "http://castlesfortsbattles.co.uk/yorkshire/pickering_castle.html",
 "https://castlesfortsbattles.co.uk/yorkshire/pickering_castle.html",
]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 PickeringHistoricalRecovery"

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

def image_replay(source,ts,u):
    urls=[("https://web.archive.org/web/"+ts+m+"/"+u) for m in ("id_","im_")] if source=="wayback" else ["https://arquivo.pt/wayback/"+ts+"id_/"+u]
    for x in urls:
        r=get(x,8)
        if r and r.status_code==200 and info(r.content):return r.content
    return None

def page_replay(source,ts,u):
    ep=("https://web.archive.org/web/"+ts+"id_/"+u) if source=="wayback" else ("https://arquivo.pt/wayback/"+ts+"id_/"+u)
    return get(ep,10)

def save(identity,b,source,ts,u,quality):
    z=info(b);ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(identity+ext);p.write_bytes(b)
    return {"identity":identity,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
      "method":source+"-historical-page-asset","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
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
        if len(ts)==14 and ts.isdigit() and orig.startswith(("http://","https://")):out.append((source,ts,orig))
    return out

def classify(u):
    leaf=u.split("/")[-1].split("?")[0]
    lo=leaf.lower()
    if re.fullmatch(r"pickering_castle_plan(?:\d{2,4}x\d{2,4})?\.(?:jpg|jpeg|png)",lo):
        q="thumbnail/lower-resolution" if re.search(r"\d{2,4}x\d{2,4}\.",lo) else "full/near-full"
        return "pickering_castle_plan",q
    if re.fullmatch(r"pickering_castle(?:\d{2,4}x\d{2,4})?\.(?:jpg|jpeg|png)",lo):
        q="thumbnail/lower-resolution" if re.search(r"\d{2,4}x\d{2,4}\.",lo) else "full/near-full"
        return "pickering_castle",q
    if re.fullmatch(r"pickering_castle_plan\.(?:jpg|jpeg|png)",lo):
        return "pickering_castle_plan","full/near-full"
    return None,None

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

r=json.loads(REP.read_text()); order=r["desktop_image_identities"]
found={x["identity"]:x for x in r["images"]}
targets={"pickering_castle","pickering_castle_plan"}-set(found)
checked=0
print(json.dumps({"timemap_captures_found":len(captures),"targets":sorted(targets)}),flush=True)

for source,ts,pageurl in captures:
    if not targets:break
    pr=page_replay(source,ts,pageurl)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1;soup=BeautifulSoup(pr.text,"html.parser")
    candidates=[]
    for tag in soup.find_all(["img","a","source"]):
        for attr in ("src","href","data-src","data-orig-src","data-muse-src"):
            v=tag.get(attr)
            if not v:continue
            u=urljoin(pageurl,v)
            ident,q=classify(u)
            if ident in targets:candidates.append((ident,u,q))
    # Legacy root-level candidates, tested at every valid page capture.
    for ident in list(targets):
        if ident=="pickering_castle":
            stems=["Pickering_Castle.JPG","Pickering_Castle.jpg","pickering_castle.JPG","pickering_castle.jpg"]
        else:
            stems=["Pickering_Castle_Plan.png","Pickering_Castle_Plan.jpg","pickering_castle_plan.png","pickering_castle_plan.jpg"]
        for stem in stems:
            candidates.append((ident,urljoin(pageurl,"/"+stem),"full/near-full"))
            candidates.append((ident,urljoin(pageurl,stem),"full/near-full"))
    best={}
    for ident,u,q in candidates:
        b=image_replay(source,ts,u)
        if not b:continue
        z=info(b);score=(2 if q=="full/near-full" else 1,z[0]*z[1])
        if ident not in best or score>best[ident][0]:best[ident]=(score,b,u,q)
    for ident,(score,b,u,q) in best.items():
        found[ident]=save(ident,b,source,ts,u,q);targets.discard(ident)
        print("RECOVERED",ident,source,ts,u,info(b),q,flush=True)

old={x["identity"]:x for x in r.get("missing",[])}
r["images"]=[found[i] for i in order if i in found]
r["missing"]=[old[i] for i in order if i not in found and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]);r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_timemap_mining_2026_09_15"]={"completed":True,"captures_found":len(captures),"captures_checked":checked,"recovered":[i for i in ("pickering_castle","pickering_castle_plan") if i in found]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"checked":checked,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
