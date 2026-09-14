#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, re
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/conisbrough-castle"); IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
REP=ROOT/"recovery-report.json"
TARGETS={"conisbrough_castle4b":"Conisbrough_Castle4B.JPG","conisbrough_castle2":"Conisbrough_Castle2.JPG"}
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 ConisbroughArchiveRecovery/2"

def get(u,t=5,headers=None):
    h=dict(S.headers)
    if headers: h.update(headers)
    try:return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception:return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify(); return w,h,fmt
    except Exception:return None

def valid(b):
    z=info(b); return z if z and z[0]>=180 and z[1]>=120 else None

def save(identity,b,meta):
    z=valid(b)
    if not z:return None
    ext=".png" if z[2]=="PNG" else ".jpg"; p=IMG/(identity+ext); p.write_bytes(b)
    meta.update({"identity":identity,"file":"images/"+p.name,"dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":"full/near-full" if max(z[0],z[1])>=700 else "thumbnail/lower-resolution","identification":"certain"})
    return meta

def url_variants(fn):
    stem=fn.rsplit(".",1)[0]
    names=list(dict.fromkeys([fn,stem+".jpg",fn.lower()]))
    bases=["http://www.castlesfortsbattles.co.uk/","https://www.castlesfortsbattles.co.uk/",
           "http://castlesfortsbattles.co.uk/","https://castlesfortsbattles.co.uk/",
           "http://www.castlesfortsbattles.co.uk/yorkshire/","https://www.castlesfortsbattles.co.uk/yorkshire/"]
    return [b+n for b in bases for n in names]

def cdx_rows(u):
    q="https://web.archive.org/cdx/search/cdx?url="+quote(u,safe=":/")+"&output=json&fl=timestamp,original,statuscode,mimetype&filter=statuscode:200&collapse=digest"
    r=get(q,4)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    return d[1:] if isinstance(d,list) and d else []

def wayback(identity,fn):
    allrows=[]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs={ex.submit(cdx_rows,u):u for u in url_variants(fn)}
        for fut in cf.as_completed(futs):
            try:
                for row in fut.result(): allrows.append(row)
            except Exception:pass
    seen=set()
    for row in reversed(allrows):
        if len(row)<2:continue
        ts,orig=row[0],row[1]
        key=(ts,orig)
        if key in seen:continue
        seen.add(key)
        r=get(f"https://web.archive.org/web/{ts}id_/{orig}",6)
        if r and r.status_code==200 and valid(r.content):
            return save(identity,r.content,{"method":"wayback-exact-variant","archive_timestamp":ts,"archive_original":orig})
    return None

def arquivo_rows(u):
    q="https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,4)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    return d[1:] if isinstance(d,list) and d and isinstance(d[0],list) else (d if isinstance(d,list) else [])

def arquivo(identity,fn):
    rows=[]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for part in ex.map(arquivo_rows,url_variants(fn)):
            rows.extend(part)
    for row in reversed(rows):
        if isinstance(row,list) and len(row)>=2:
            ts,orig=str(row[0]),str(row[1])
            r=get(f"https://arquivo.pt/wayback/{ts}id_/{orig}",6)
            if r and r.status_code==200 and valid(r.content):
                return save(identity,r.content,{"method":"arquivo.pt-exact-variant","archive_timestamp":ts,"archive_original":orig})
    return None

def cc_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",5)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    by={}
    for x in d:
        iid=x.get("id",""); m=re.search(r"CC-MAIN-(\d{4})-",iid)
        if m and 2017<=int(m.group(1))<=2022:by.setdefault(m.group(1),[]).append(iid)
    return [sorted(by[y],reverse=True)[0] for y in sorted(by)]

INDEXES=cc_indexes()

def cc_query(iid,u):
    q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,4)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and all(x.get(k) for k in ("filename","offset","length")):out.append(x)
        except Exception:pass
    return out

def commoncrawl(identity,fn):
    root_urls=url_variants(fn)[:12]  # root protocol/www + case variants only
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futs=[ex.submit(cc_query,i,u) for i in INDEXES for u in root_urls]
        for fut in cf.as_completed(futs):
            try:recs.extend(fut.result())
            except Exception:pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    for x in sorted(uniq.values(),key=lambda q:int(q.get("length") or 0),reverse=True)[:12]:
        st=int(x["offset"]); ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],8,{"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):continue
        try:payload=gzip.decompress(r.content).split(b"\r\n\r\n")[-1]
        except Exception:continue
        if valid(payload):
            return save(identity,payload,{"method":"common-crawl-exact-variant","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")})
    return None

def recover(pair):
    identity,fn=pair
    for method in (wayback,arquivo,commoncrawl):
        x=method(identity,fn)
        if x:return identity,x
    return identity,None

found={}
with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for identity,x in ex.map(recover,TARGETS.items()):
        if x:found[identity]=x

rep=json.loads(REP.read_text())
by={x["identity"]:x for x in rep.get("images",[])}; by.update(found)
order=["conisbrough_castle4b","conisbrough_castle2"]
rep["images"]=[by[i] for i in order if i in by]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=2-len(rep["images"])
rep["missing"]=[{"identity":i,"candidate_urls":url_variants(TARGETS[i])} for i in order if i not in by]
rep["fresh_deep_search_2026_09_14"]={"completed":True,
 "methods":["Wayback CDX exact root/Yorkshire filename and case variants","Arquivo.pt exact root/Yorkshire filename and case variants","Common Crawl representative 2017-2022 indexes"],
 "found":sorted(found),"commoncrawl_indexes_checked":INDEXES}
REP.write_text(json.dumps(rep,indent=2)+"\n")

p=ROOT/"index.html"; soup=BeautifulSoup(p.read_text(),"html.parser")
h=soup.find("h2",string=lambda x:x and "Recovered original photographs" in x)
if h:
    for identity in reversed(order):
        if identity in by and not soup.find("img",src=by[identity]["file"]):
            fig=soup.new_tag("figure"); a=soup.new_tag("a",href=by[identity]["file"])
            im=soup.new_tag("img",src=by[identity]["file"],alt="Conisbrough Castle archived original image")
            a.append(im); fig.append(a); cap=soup.new_tag("figcaption"); cap.string=identity.replace("_"," "); fig.append(cap); h.insert_after(fig)
note=soup.find("div",class_="note")
if note: note.string=f"Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. {len(rep['images'])} of 2 identified original content-image positions have been recovered; {rep['still_missing']} remain unavailable. No unrelated substitute photographs have been introduced."
p.write_text(str(soup))
print(json.dumps(rep["fresh_deep_search_2026_09_14"],indent=2))
