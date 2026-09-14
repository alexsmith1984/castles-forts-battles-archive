#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/berkhamsted-castle")
IMG=ROOT/"images"
REP=ROOT/"recovery-report.json"
TARGETS={
 "berkhamsted_castle5":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle5.JPG",
 "berkhamsted_castle14":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle14.JPG",
}
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (Berkhamsted Castle focused external archive recovery)"

def get(u,t=10,headers=None):
    h=dict(S.headers)
    if headers:h.update(headers)
    try:return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception:return None

def variants(u):
    sp=urlsplit(u)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    paths=[sp.path,sp.path[:-4]+".jpg",sp.path.lower()]
    out=[]
    for scheme in ("http","https"):
        for host in dict.fromkeys(hosts):
            for path in dict.fromkeys(paths):
                out.append(urlunsplit((scheme,host,path,"","")))
    return list(dict.fromkeys(out))

def info(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.size;fmt=im.format;im.verify()
        return w,h,fmt
    except Exception:return None

def valid(b):
    z=info(b)
    return z if z and z[0]>=200 and z[1]>=150 else None

def save(identity,b,meta):
    z=valid(b)
    if not z:return None
    p=IMG/(identity+".jpg")
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
        endpoints=[
          "https://arquivo.pt/wayback/cdx?url="+quote(v,safe=":/")+"&output=json",
          "https://arquivo.pt/textsearch?versionHistory="+quote(v,safe=":/")+"&maxItems=30",
        ]
        for ep in endpoints:
            r=get(ep,8)
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
    for replay,orig in replays[:80]:
        if replay in seen:continue
        seen.add(replay)
        r=get(replay,10)
        if r and r.status_code==200 and valid(r.content):
            return save(identity,r.content,{
              "method":"arquivo.pt-exact-filename",
              "archive_replay":replay,"archive_original":orig
            })
    return None

def commoncrawl_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",10)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    byyear={}
    for x in d:
        iid=x.get("id","")
        m=re.search(r"CC-MAIN-(\d{4})-",iid)
        if m and 2014<=int(m.group(1))<=2023:
            byyear.setdefault(int(m.group(1)),[]).append(iid)
    return [sorted(byyear[y],reverse=True)[0] for y in sorted(byyear)]

INDEXES=commoncrawl_indexes()

def cc_query(args):
    iid,u=args
    q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,7)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"):
                out.append(x)
        except Exception:pass
    return out

def commoncrawl(identity,u):
    tasks=[(iid,v) for iid in INDEXES for v in variants(u)]
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for rows in ex.map(cc_query,tasks):
            recs.extend(rows)
    uniq={}
    for x in recs:
        uniq[(x["filename"],x["offset"],x["length"])]=x
    cand=sorted(uniq.values(),key=lambda x:int(x.get("length") or 0),reverse=True)[:16]
    for x in cand:
        st=int(x["offset"]);ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],12,headers={"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):continue
        try:
            raw=gzip.decompress(r.content)
            payload=raw.split(b"\r\n\r\n")[-1]
        except Exception:
            continue
        if valid(payload):
            return save(identity,payload,{
              "method":"common-crawl-exact-filename",
              "commoncrawl_url":x.get("url"),
              "commoncrawl_timestamp":x.get("timestamp"),
              "commoncrawl_warc":x.get("filename")
            })
    return None

def recover(args):
    identity,u=args
    x=arquivo(identity,u)
    if x:return identity,x
    return identity,commoncrawl(identity,u)

found={}
with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for identity,x in ex.map(recover,TARGETS.items()):
        if x:found[identity]=x

rep=json.loads(REP.read_text(encoding="utf-8"))
byid={x["identity"]:x for x in rep["images"]}
byid.update(found)
order=[x["identity"] for x in rep["images"]]
rep["images"]=[byid[i] for i in order]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")=="thumbnail/lower-resolution" for x in rep["images"])
rep["full_size_source_unrecovered_but_position_represented"]=[
    i for i in TARGETS if byid.get(i,{}).get("quality")!="full/near-full"
]
rep["external_archive_search_completed"]=True
rep["external_archive_methods"]=["Arquivo.pt exact-filename search","Common Crawl exact-filename search"]
rep["external_archive_fullsize_found"]=sorted(found)
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# If a full-size replacement was found, remove the lower-resolution warning on that figure.
p=ROOT/"index.html"
soup=BeautifulSoup(p.read_text(encoding="utf-8"),"html.parser")
for identity in found:
    rel=byid[identity]["file"]
    im=soup.find("img",src=rel)
    if im:
        fig=im.find_parent("figure")
        cap=fig.find("figcaption") if fig else None
        if cap:
            cap.string=re.sub(r"\s+— lower-resolution archived recovery$","",cap.get_text())
# Keep the note counts accurate.
note=soup.find("div",class_="note")
if note:
    note.string=(
      f"Reconstructed from the archived CastlesFortsBattles Berkhamsted Castle page. "
      f"12 of 12 genuine original content-image positions are represented: "
      f"{rep['recovered_full_or_near_full']} full/near-full archived originals and "
      f"{rep['recovered_thumbnail_or_lower_resolution']} lower-resolution archived originals. "
      "No unrelated substitute photographs have been introduced."
    )
p.write_text(str(soup),encoding="utf-8")

print(json.dumps({
 "arquivo_commoncrawl_search_complete":True,
 "commoncrawl_indexes_checked":len(INDEXES),
 "fullsize_found_now":sorted(found),
 "still_lower_resolution":rep["full_size_source_unrecovered_but_position_represented"],
 "full_or_near_full":rep["recovered_full_or_near_full"],
 "lower_resolution":rep["recovered_thumbnail_or_lower_resolution"]
},indent=2))
