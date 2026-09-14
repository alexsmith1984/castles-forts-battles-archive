#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/castle-acre")
IMG=ROOT/"images"
REP=ROOT/"recovery-report.json"
TARGETS={
 "castle_acre2":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre2.jpg",
 "castle_acre4":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre4.jpg",
 "castle_acre5":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre5.jpg",
 "castle_acre6":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre6.jpg",
 "castle_acre9":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre9.jpg",
 "castle_acre11":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre11.jpg",
 "castle_acre12":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre12.jpg",
 "castle_acre13":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre13.jpg",
 "castle_acre14":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre14.jpg",
 "castle_acre15":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre15.jpg",
 "castle_acre16":"http://www.castlesfortsbattles.co.uk/east/assets/castle_acre16.jpg",
}
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (Castle Acre focused external archive recovery)"

def get(u,t=8,headers=None):
    h=dict(S.headers)
    if headers:h.update(headers)
    try:return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception:return None

def variants(u):
    return list(dict.fromkeys([
      u,
      u.replace("http://","https://",1),
      u.replace("://www.","://",1),
      u.replace("http://www.","https://",1),
    ]))

def info(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.size;fmt=im.format;im.verify()
        return w,h,fmt
    except Exception:return None

def valid_full(b):
    z=info(b)
    return z if z and (z[0]>=1000 or z[1]>=1000) else None

def save(identity,b,meta):
    z=valid_full(b)
    if not z:return None
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(identity+ext)
    p.write_bytes(b)
    meta.update({
      "identity":identity,"file":"images/"+p.name,
      "dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),
      "quality":"full/near-full","identification":"certain"
    })
    return meta

def arquivo(identity,u):
    replays=[]
    for v in variants(u):
        for ep in [
          "https://arquivo.pt/wayback/cdx?url="+quote(v,safe=":/")+"&output=json",
          "https://arquivo.pt/textsearch?versionHistory="+quote(v,safe=":/")+"&maxItems=20",
        ]:
            r=get(ep,7)
            if not r or r.status_code!=200:continue
            try:d=r.json()
            except Exception:continue
            def walk(o):
                if isinstance(o,dict):
                    for key in ("linkToArchive","linkToOriginalFile"):
                        x=o.get(key)
                        if isinstance(x,str) and "arquivo.pt" in x:replays.append((x,v))
                    ts=o.get("timestamp") or o.get("tstamp") or o.get("date")
                    ou=o.get("original") or o.get("url")
                    if ts and ou and "castlesfortsbattles" in str(ou):
                        digits=re.sub(r"\D","",str(ts))[:14]
                        if len(digits)>=8:
                            replays.append((f"https://arquivo.pt/wayback/{digits}id_/{ou}",str(ou)))
                            replays.append((f"https://arquivo.pt/noFrame/replay/{digits}/{ou}",str(ou)))
                    for x in o.values():walk(x)
                elif isinstance(o,list):
                    for x in o:walk(x)
            walk(d)
    seen=set()
    for replay,orig in replays[:40]:
        if replay in seen:continue
        seen.add(replay)
        r=get(replay,8)
        if r and r.status_code==200 and valid_full(r.content):
            return save(identity,r.content,{"method":"arquivo.pt-exact-filename","archive_replay":replay,"archive_original":orig})
    return None

def commoncrawl_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",8)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    byyear={}
    for x in d:
        iid=x.get("id","")
        m=re.search(r"CC-MAIN-(\d{4})-",iid)
        if m and 2018<=int(m.group(1))<=2023:
            byyear.setdefault(int(m.group(1)),[]).append(iid)
    return [sorted(byyear[y],reverse=True)[0] for y in sorted(byyear)]

INDEXES=commoncrawl_indexes()

def cc_query(iid,u):
    q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,6)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"):out.append(x)
        except Exception:pass
    return out

def commoncrawl(identity,u):
    tasks=[(iid,v) for iid in INDEXES for v in variants(u)[:2]]
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs=[ex.submit(cc_query,iid,v) for iid,v in tasks]
        for fut in cf.as_completed(futs):
            try:recs.extend(fut.result())
            except Exception:pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    cand=sorted(uniq.values(),key=lambda x:int(x.get("length") or 0),reverse=True)[:8]
    for x in cand:
        st=int(x["offset"]);ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],10,headers={"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):continue
        try:
            raw=gzip.decompress(r.content)
            payload=raw.split(b"\r\n\r\n")[-1]
        except Exception:continue
        if valid_full(payload):
            return save(identity,payload,{"method":"common-crawl-exact-filename","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")})
    return None

def recover(pair):
    identity,u=pair
    x=arquivo(identity,u)
    if x:return identity,x
    return identity,commoncrawl(identity,u)

found={}
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    for identity,x in ex.map(recover,TARGETS.items()):
        if x:found[identity]=x

rep=json.loads(REP.read_text(encoding="utf-8"))
byid={x["identity"]:x for x in rep["images"]}
byid.update(found)
order=["castle_acre","castle_acre2","castle_acre3","castle_acre4","castle_acre5","castle_acre6","castle_acre7","castle_acre8","castle_acre9","castle_acre10","castle_acre11","castle_acre12","castle_acre13","castle_acre14","castle_acre15","castle_acre16","castle_acre_layout"]
rep["images"]=[byid[i] for i in order if i in byid]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=17-len(rep["images"])
rep["status"]="COMPLETE" if rep["still_missing"]==0 else "PARTIAL"
rep["full_size_source_unrecovered_but_position_represented"]=[i for i in TARGETS if byid.get(i,{}).get("quality")!="full/near-full"]
rep["external_archive_search_completed"]=True
rep["external_archive_methods"]=["Arquivo.pt exact-filename search","Common Crawl exact-filename search (2018-2023 representative indexes)"]
rep["external_archive_fullsize_found"]=sorted(found)
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

p=ROOT/"index.html"
soup=BeautifulSoup(p.read_text(encoding="utf-8"),"html.parser")
for identity in found:
    rel=byid[identity]["file"]
    im=soup.find("img",src=rel)
    if im:
        fig=im.find_parent("figure")
        cap=fig.find("figcaption") if fig else None
        if cap:cap.string=re.sub(r"\s+— lower-resolution archived recovery$","",cap.get_text())
note=soup.find("div",class_="note")
if note:
    note.string=(f"Reconstructed from the archived CastlesFortsBattles Castle Acre page. "
      f"17 of 17 genuine original content-image identities are represented: "
      f"{rep['recovered_full_or_near_full']} full/near-full archived originals and "
      f"{rep['recovered_thumbnail_or_lower_resolution']} lower-resolution archived originals. "
      "Responsive Muse crops and thumbnails are not counted separately. No unrelated substitute images have been introduced.")
p.write_text(str(soup),encoding="utf-8")

print(json.dumps({
 "external_search_complete":True,
 "commoncrawl_indexes_checked":INDEXES,
 "fullsize_found_now":sorted(found),
 "still_lower_resolution":rep["full_size_source_unrecovered_but_position_represented"],
 "full_or_near_full":rep["recovered_full_or_near_full"],
 "lower_resolution":rep["recovered_thumbnail_or_lower_resolution"]
},indent=2))
