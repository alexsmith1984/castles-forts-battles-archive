#!/usr/bin/env python3
import io, json, hashlib, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/kenilworth-castle")
REP=ROOT/"recovery-report.json"
IMG=ROOT/"images"
IMG.mkdir(parents=True,exist_ok=True)

PAGES=[
 "http://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "https://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "http://castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "https://castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
]
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 KenilworthHistoricalRecovery"

def get(u,t=12):
    r=None
    for n in range(3):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504):
                return r
        except Exception:
            r=None
        time.sleep(0.7*(n+1))
    return r

def iminfo(b):
    try:
        im=Image.open(io.BytesIO(b))
        z=(im.width,im.height,im.format)
        im.verify()
        return z
    except Exception:
        return None

def page_replay(source,ts,u):
    if source=="wayback":
        return get("https://web.archive.org/web/"+ts+"id_/"+u,10)
    return get("https://arquivo.pt/wayback/"+ts+"id_/"+u,10)

def image_replay(source,ts,u):
    urls=[]
    if source=="wayback":
        urls=[
          "https://web.archive.org/web/"+ts+"id_/"+u,
          "https://web.archive.org/web/"+ts+"im_/"+u,
        ]
    else:
        urls=["https://arquivo.pt/wayback/"+ts+"id_/"+u]
    for x in urls:
        r=get(x,8)
        if r and r.status_code==200 and iminfo(r.content):
            return r.content
    return None

def save(identity,b,source,ts,u,method,quality):
    z=iminfo(b)
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(identity+ext)
    p.write_bytes(b)
    return {
      "identity":identity,
      "file":"images/"+p.name,
      "archive_timestamp":ts,
      "archive_original":u,
      "method":source+"-"+method,
      "dimensions":[z[0],z[1]],
      "format":z[2],
      "bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),
      "quality":quality,
      "identification":"certain"
    }

def timemap_rows(source,page):
    if source=="wayback":
        ep="https://web.archive.org/web/timemap/link/"+page
        marker="/web/"
    else:
        ep="https://arquivo.pt/wayback/timemap/link/"+page
        marker="/wayback/"
    r=get(ep,18)
    if not r or r.status_code!=200:
        return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line or ">" not in line:
            continue
        uri=line.split("<",1)[1].split(">",1)[0]
        if marker not in uri:
            continue
        rest=uri.split(marker,1)[1]
        if "/" not in rest:
            continue
        ts,orig=rest.split("/",1)
        ts=ts[:14]
        if len(ts)==14 and ts.isdigit() and orig.startswith(("http://","https://")):
            out.append((source,ts,orig))
    return out

captures=[]
for page in PAGES:
    captures += timemap_rows("wayback",page)
    captures += timemap_rows("arquivo",page)
seen=set()
captures=[x for x in captures if x not in seen and not seen.add(x)]
captures.sort(key=lambda x:x[1])

# Preserve earliest and latest history plus evenly spaced middle captures.
if len(captures)>24:
    idx={0,len(captures)-1}
    for n in range(1,23):
        idx.add(round(n*(len(captures)-1)/23))
    captures=[captures[i] for i in sorted(idx)]

r=json.loads(REP.read_text())
order=r["desktop_image_identities"]
gids=[x for x in order if x.startswith("gallery_")]
existing={x["identity"]:x for x in r.get("images",[])}
checked=0

print(json.dumps({"timemap_captures_found":len(captures)}),flush=True)

for source,ts,pageurl in captures:
    pr=page_replay(source,ts,pageurl)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():
        continue
    checked += 1
    h=pr.text

    hashes=[]
    key='new wp_galleryimage("wpimages/'
    for line in h.splitlines():
        if key not in line:
            continue
        tail=line.split(key,1)[1]
        if '.jpg"' not in tail:
            continue
        hh=tail.split('.jpg"',1)[0]
        if hh and hh not in hashes:
            hashes.append(hh)

    for n,identity in enumerate(gids):
        if identity in existing or n>=len(hashes):
            continue
        hh=hashes[n]
        for u,quality in (
          (urljoin(pageurl,"wpimages/"+hh+".jpg"),"full/near-full"),
          (urljoin(pageurl,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution"),
        ):
            b=image_replay(source,ts,u)
            if b:
                existing[identity]=save(identity,b,source,ts,u,"historical-gallery-position",quality)
                print("RECOVERED",identity,source,ts,u,flush=True)
                break

    soup=BeautifulSoup(h,"html.parser")
    for identity in ("kenilworth_castle1","kenilworth_castle9","kenilworth_castle15"):
        if identity in existing and existing[identity].get("quality")=="full/near-full":
            continue
        num=identity.replace("kenilworth_castle","")
        target=None
        for a in soup.find_all("a",href=True):
            href=a.get("href","")
            if ("Kenilworth_Castle"+num+".JPG").lower()==href.split("/")[-1].lower() or ("Kenilworth_Castle"+num+".jpg").lower()==href.split("/")[-1].lower():
                target=a
                break
        if not target:
            continue
        orig=urljoin(pageurl,target["href"])
        child=target.find("img")
        display=urljoin(pageurl,child.get("src")) if child and child.get("src") else None
        pairs=[(orig,"full/near-full","historical-original")]
        if display:
            pairs.append((display,"thumbnail/lower-resolution","historical-display-export"))
        for u,quality,method in pairs:
            b=image_replay(source,ts,u)
            if b:
                existing[identity]=save(identity,b,source,ts,u,method,quality)
                print("RECOVERED",identity,source,ts,u,flush=True)
                break

r["images"]=[existing[i] for i in order if i in existing]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old[i] for i in order if i not in existing and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"])
r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_timemap_mining_2026_09_14"]={
  "completed":True,
  "page_captures_found":len(captures),
  "page_captures_checked":checked,
  "recovered":[i for i in order if i in existing]
}
REP.write_text(json.dumps(r,indent=2)+"\n")

print(json.dumps({
  "captures_found":len(captures),
  "captures_checked":checked,
  "full":r["recovered_full_or_near_full"],
  "lower":r["recovered_thumbnail_or_lower_resolution"],
  "missing":r["still_missing"],
  "recovered":[i for i in order if i in existing]
},indent=2))
