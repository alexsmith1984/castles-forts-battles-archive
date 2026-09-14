#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, re
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/conisbrough-castle")
IMG=ROOT/"images"; IMG.mkdir(parents=True, exist_ok=True)
REP=ROOT/"recovery-report.json"
TARGETS={
 "conisbrough_castle4b":"Conisbrough_Castle4B.JPG",
 "conisbrough_castle2":"Conisbrough_Castle2.JPG",
}
BASES=[
 "http://www.castlesfortsbattles.co.uk/",
 "https://www.castlesfortsbattles.co.uk/",
 "http://castlesfortsbattles.co.uk/",
 "https://castlesfortsbattles.co.uk/",
 "http://www.castlesfortsbattles.co.uk/yorkshire/",
 "https://www.castlesfortsbattles.co.uk/yorkshire/",
 "http://www.castlesfortsbattles.co.uk/yorkshire/images/",
 "https://www.castlesfortsbattles.co.uk/yorkshire/images/",
 "http://www.castlesfortsbattles.co.uk/images/",
 "https://www.castlesfortsbattles.co.uk/images/",
 "http://www.castlesfortsbattles.co.uk/wpimages/",
 "https://www.castlesfortsbattles.co.uk/wpimages/",
]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Conisbrough archival recovery)"

def get(u,t=10,headers=None):
    h=dict(S.headers)
    if headers: h.update(headers)
    try: return S.get(u,timeout=t,allow_redirects=True,headers=h)
    except Exception: return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify()
        return w,h,fmt
    except Exception: return None

def valid(b):
    z=info(b)
    return z if z and z[0]>=200 and z[1]>=120 else None

def name_variants(fn):
    stem=fn.rsplit(".",1)[0]
    return list(dict.fromkeys([
      fn, stem+".jpg", stem+".JPG",
      fn.lower(), stem.lower()+".jpg", stem.upper()+".JPG"
    ]))

def urls(fn):
    out=[]
    for b in BASES:
        for n in name_variants(fn): out.append(b+n)
    return list(dict.fromkeys(out))

def save(identity,b,meta):
    z=valid(b)
    if not z: return None
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(identity+ext); p.write_bytes(b)
    meta.update({
      "identity":identity,"file":"images/"+p.name,"dimensions":[z[0],z[1]],
      "format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":"full/near-full" if (z[0]>=700 or z[1]>=700) else "thumbnail/lower-resolution",
      "identification":"certain"
    })
    return meta

def wayback(identity,fn):
    for u in urls(fn):
        q="https://web.archive.org/cdx/search/cdx?url="+quote(u,safe=":/")+"&output=json&fl=timestamp,original,statuscode,mimetype&filter=statuscode:200&collapse=digest"
        r=get(q,8)
        if not r or r.status_code!=200: continue
        try: rows=r.json()[1:]
        except Exception: continue
        for row in rows[-12:]:
            if len(row)<2: continue
            ts,orig=row[0],row[1]
            for mod in ("id_","im_"):
                rr=get(f"https://web.archive.org/web/{ts}{mod}/{orig}",10)
                if rr and rr.status_code==200 and valid(rr.content):
                    return save(identity,rr.content,{"method":"wayback-exact-variant","archive_timestamp":ts,"archive_original":orig})
    return None

def arquivo(identity,fn):
    replays=[]
    for u in urls(fn):
        ep="https://arquivo.pt/wayback/cdx?url="+quote(u,safe=":/")+"&output=json"
        r=get(ep,8)
        if not r or r.status_code!=200: continue
        try: d=r.json()
        except Exception: continue
        if isinstance(d,list):
            rows=d[1:] if d and isinstance(d[0],list) else d
            for row in rows:
                if isinstance(row,list) and len(row)>=2:
                    ts,orig=str(row[0]),str(row[1])
                    replays.append((f"https://arquivo.pt/wayback/{ts}id_/{orig}",orig,ts))
                elif isinstance(row,dict):
                    ts=str(row.get("timestamp","")); orig=str(row.get("url") or row.get("original") or "")
                    link=row.get("linkToArchive")
                    if isinstance(link,str): replays.append((link,orig,ts))
    seen=set()
    for replay,orig,ts in replays[:100]:
        if replay in seen: continue
        seen.add(replay); r=get(replay,9)
        if r and r.status_code==200 and valid(r.content):
            return save(identity,r.content,{"method":"arquivo.pt-exact-variant","archive_replay":replay,"archive_original":orig,"archive_timestamp":ts})
    return None

def cc_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",8)
    if not r or r.status_code!=200: return []
    try: d=r.json()
    except Exception: return []
    keep=[]
    for x in d:
        iid=x.get("id","")
        m=re.search(r"CC-MAIN-(\d{4})-",iid)
        if m and 2016<=int(m.group(1))<=2023: keep.append(iid)
    # one representative crawl per year, newest first
    by={}
    for iid in keep:
        y=re.search(r"(\d{4})",iid).group(1); by.setdefault(y,[]).append(iid)
    return [sorted(by[y],reverse=True)[0] for y in sorted(by,reverse=True)]

INDEXES=cc_indexes()

def cc_query(iid,u):
    q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
    r=get(q,7)
    if not r or r.status_code!=200: return []
    out=[]
    for line in r.text.splitlines():
        try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"): out.append(x)
        except Exception: pass
    return out

def commoncrawl(identity,fn):
    cc_urls=list(dict.fromkeys([
      "http://www.castlesfortsbattles.co.uk/"+fn,
      "https://www.castlesfortsbattles.co.uk/"+fn,
      "http://castlesfortsbattles.co.uk/"+fn,
      "https://castlesfortsbattles.co.uk/"+fn,
      "http://www.castlesfortsbattles.co.uk/"+fn.lower(),
      "https://www.castlesfortsbattles.co.uk/"+fn.lower(),
    ]))
    tasks=[(iid,u) for iid in INDEXES for u in cc_urls]
    recs=[]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futs=[ex.submit(cc_query,iid,u) for iid,u in tasks]
        for fut in cf.as_completed(futs):
            try: recs.extend(fut.result())
            except Exception: pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    for x in sorted(uniq.values(),key=lambda x:int(x.get("length") or 0),reverse=True)[:20]:
        st=int(x["offset"]); ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],12,headers={"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206): continue
        try:
            raw=gzip.decompress(r.content); payload=raw.split(b"\r\n\r\n")[-1]
        except Exception: continue
        if valid(payload):
            return save(identity,payload,{"method":"common-crawl-exact-variant","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")})
    return None

def recover(item):
    identity,fn=item
    for f in (wayback,arquivo,commoncrawl):
        x=f(identity,fn)
        if x: return identity,x
    return identity,None

found={}
with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for identity,x in ex.map(recover,TARGETS.items()):
        if x: found[identity]=x

rep=json.loads(REP.read_text(encoding="utf-8"))
byid={x["identity"]:x for x in rep.get("images",[])}
byid.update(found)
order=["conisbrough_castle4b","conisbrough_castle2"]
rep["images"]=[byid[i] for i in order if i in byid]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=2-len(rep["images"])
rep["missing"]=[{"identity":i,"candidate_urls":urls(TARGETS[i])} for i in order if i not in byid]
rep["fresh_deep_search_2026_09_14"]={
 "completed":True,
 "methods":["Wayback CDX exact filename/case/path variants","Arquivo.pt exact filename/case/path variants","Common Crawl representative 2016-2023 indexes"],
 "found":sorted(found),
 "commoncrawl_indexes_checked":INDEXES
}
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

p=ROOT/"index.html"
soup=BeautifulSoup(p.read_text(encoding="utf-8"),"html.parser")
h=soup.find("h2",string=lambda s:s and "Recovered original photographs" in s)
if h:
    for identity in order:
        if identity in byid and not soup.find("img",src=byid[identity]["file"]):
            fig=soup.new_tag("figure"); a=soup.new_tag("a",href=byid[identity]["file"])
            im=soup.new_tag("img",src=byid[identity]["file"],alt="Conisbrough Castle archived original image")
            a.append(im); fig.append(a); cap=soup.new_tag("figcaption"); cap.string=identity.replace("_"," "); fig.append(cap); h.insert_after(fig)
note=soup.find("div",class_="note")
if note:
    note.string=(f"Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. "
                 f"{len(rep['images'])} of 2 identified original content-image positions have been recovered; "
                 f"{rep['still_missing']} remain unavailable. No unrelated substitute photographs have been introduced.")
p.write_text(str(soup),encoding="utf-8")
print(json.dumps(rep["fresh_deep_search_2026_09_14"],indent=2))
