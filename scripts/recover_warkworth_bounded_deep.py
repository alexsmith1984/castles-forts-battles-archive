#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/warkworth-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
REP0=json.loads(REP.read_text())
CANON=REP0["desktop_image_identities"]
GALLERY=[
"warkworth_bridge9","warkworth_castle19a","warkworth_castle26","warkworth_castle15","warkworth_castle20",
"warkworth_bridge1","warkworth_bridge2","warkworth_bridge5","warkworth_bridge7","warkworth_bridge10",
"warkworth_bridge11","warkworth_bridge13","warkworth_castle1","warkworth_castle3","warkworth_castle5",
"warkworth_castle7","warkworth_castle8a","warkworth_castle10","warkworth_castle11","warkworth_castle14",
"warkworth_castle18","warkworth_castle21a","warkworth_castle22","warkworth_castle24","warkworth_castle25","warkworth_castle25b"]
PAGES=[
"http://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html",
"https://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html",
"http://castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html",
"https://castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html",
"http://www.castlesfortsbattles.co.uk/m/warkworth_castle_bridge.html",
"http://www.castlesfortsbattles.co.uk/m/north_east/warkworth_castle_bridge.html"]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 WarkworthBoundedDeepRecovery"

def get(u,t=12,params=None):
    for n in range(2):
        try:
            r=S.get(u,params=params,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception: pass
        time.sleep(.25*(n+1))
    return None

def imginfo(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        return z if z[0]>=80 and z[1]>=80 else None
    except Exception:return None

def canon_for(u):
    stem=Path(urlparse(u).path).stem.lower()
    for c in sorted(CANON,key=len,reverse=True):
        lc=c.lower()
        if stem==lc or re.fullmatch(re.escape(lc)+r'\d+x\d+',stem): return c
    return None

def responsive_for(c,u):
    stem=Path(urlparse(u).path).stem.lower()
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',stem))

def quality(c,u,z):
    path=urlparse(u).path.lower(); stem=Path(path).stem.lower()
    exact=(stem==c.lower())
    if "/assets/" in path and not responsive_for(c,u): return "full/near-full"
    if exact and not responsive_for(c,u): return "full/near-full"
    if not responsive_for(c,u) and max(z[0],z[1])>=1000: return "full/near-full"
    return "thumbnail/lower-resolution"

def score(c,u,z,q):
    path=urlparse(u).path.lower()
    return (4 if "/assets/" in path and not responsive_for(c,u) else 3 if Path(path).stem.lower()==c.lower() and not responsive_for(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

def cdx(pattern):
    ep="https://web.archive.org/cdx/search/cdx"
    params={"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest","filter":["statuscode:200"],"collapse":"digest","limit":"5000"}
    r=get(ep,20,params)
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []

def replay(ts,orig):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{orig}",7)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url
    return None

def timemap(page):
    r=get("https://web.archive.org/web/timemap/link/"+page,12)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        uri=line.split("<",1)[1].split(">",1)[0]
        if "/web/" not in uri:continue
        rest=uri.split("/web/",1)[1]
        if "/" not in rest:continue
        ts,orig=rest.split("/",1);ts=ts[:14]
        if len(ts)==14 and ts.isdigit():out.append((ts,orig))
    return out

rep=REP0
found={x["identity"]:x for x in rep.get("images",[])}
start_count=len(found)

# PASS 1: high-yield CDX wildcard filename-family search.
patterns=[]
for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    for d in ("north_east/assets","north_east/images","assets","images","m/assets","m/images","north_east/wpimages","wpimages"):
        for fam in ("warkworth_castle*","warkworth_bridge*"):
            patterns.append(f"{host}/{d}/{fam}")
rows=[]
with ThreadPoolExecutor(max_workers=16) as ex:
    futs=[ex.submit(cdx,p) for p in patterns]
    for f in as_completed(futs):
        try: rows.extend(f.result())
        except: pass
seen=set();ded=[]
for x in rows:
    k=(x.get("timestamp"),x.get("original"),x.get("digest"))
    if k in seen:continue
    seen.add(k);ded.append(x)
rows=ded
mapped={c:[] for c in CANON}
for x in rows:
    c=canon_for(x.get("original",""))
    if c:mapped[c].append(x)

jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for c,rr in mapped.items():
        # Search missing images and any existing lower-res image for upgrade.
        existing=found.get(c)
        if existing and existing.get("quality")=="full/near-full":continue
        rr=sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x["original"]).path.lower() else 1,
                                   1 if responsive_for(c,x["original"]) else 0,x["timestamp"]))
        if len(rr)>12:
            inds={0,len(rr)-1}
            for n in range(1,11):inds.add(round(n*(len(rr)-1)/11))
            rr=[rr[i] for i in sorted(inds)]
        for row in rr:jobs[ex.submit(replay,row["timestamp"],row["original"])]=(c,row)
    results={c:[] for c in CANON}
    for f in as_completed(jobs):
        c,row=jobs[f]
        try: got=f.result()
        except: got=None
        if got:
            b,z,final=got; q=quality(c,row["original"],z)
            results[c].append((score(c,row["original"],z,q),row,b,z,final,q))

new=[];upgraded=[]
for c in CANON:
    if not results[c]:continue
    best=max(results[c],key=lambda x:x[0]); sc,row,b,z,final,q=best
    old=found.get(c)
    oldscore=(-1,0)
    if old:
        oz=old.get("dimensions",[0,0]); oq=old.get("quality","thumbnail/lower-resolution"); oldscore=(3 if oq=="full/near-full" else 1,oz[0]*oz[1])
    if old and sc<=oldscore:continue
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
    found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":row["timestamp"],"archive_original":row["original"],
              "archive_replay":final,"method":"wayback-cdx-wildcard-filename-family","dimensions":[z[0],z[1]],"format":z[2],
              "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    (upgraded if old else new).append(c)

# PASS 2: historical page captures + gallery position mapping for remaining identities.
remain=[c for c in CANON if c not in found]
page_caps=[]
for p in PAGES:page_caps+=timemap(p)
seen=set();page_caps=[x for x in page_caps if not (x in seen or seen.add(x))];page_caps.sort()
if len(page_caps)>30:
    inds={0,len(page_caps)-1}
    for n in range(1,29):inds.add(round(n*(len(page_caps)-1)/29))
    page_caps=[page_caps[i] for i in sorted(inds)]
hist={c:[] for c in remain};checked=0
for ts,page in page_caps:
    r=get(f"https://web.archive.org/web/{ts}id_/{page}",9)
    if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
    checked+=1;soup=BeautifulSoup(r.text,"html.parser")
    for tag in soup.find_all(["a","img"]):
        for attr in ("href","data-src","data-orig-src","data-muse-src"):
            ref=tag.get(attr)
            if not ref:continue
            u=urljoin(page,ref);c=canon_for(u)
            if c in hist:hist[c].append(u)
    for im in soup.find_all("img"):
        if "ImageInclude" not in (im.get("class") or []):continue
        try:i=int(im.get("data-col-pos"))
        except:continue
        if 0<=i<len(GALLERY):
            c=GALLERY[i]
            if c in hist:
                ref=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src")
                if ref:hist[c].append(urljoin(page,ref))

exact_jobs={}
with ThreadPoolExecutor(max_workers=14) as ex:
    for c,urls in hist.items():
        ss=set();urls=[u for u in urls if not (u in ss or ss.add(u))]
        for u in urls[:28]:exact_jobs[ex.submit(cdx,u)]=(c,u)
    exact_rows={c:[] for c in remain}
    for f in as_completed(exact_jobs):
        c,u=exact_jobs[f]
        try:exact_rows[c]+=f.result()
        except:pass

replay_jobs={}
with ThreadPoolExecutor(max_workers=14) as ex:
    for c,rr in exact_rows.items():
        if c in found:continue
        rr=rr[:10]
        for row in rr:replay_jobs[ex.submit(replay,row["timestamp"],row["original"])]=(c,row)
    hist_results={c:[] for c in remain}
    for f in as_completed(replay_jobs):
        c,row=replay_jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(c,row["original"],z)
            hist_results[c].append((score(c,row["original"],z,q),row,b,z,final,q))

for c in remain:
    if c in found or not hist_results.get(c):continue
    _,row,b,z,final,q=max(hist_results[c],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
    found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":row["timestamp"],"archive_original":row["original"],
              "archive_replay":final,"method":"historical-page-position-plus-cdx","dimensions":[z[0],z[1]],"format":z[2],
              "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    new.append(c)

oldmiss={x["identity"]:x for x in rep.get("missing",[])}
rep["images"]=[found[c] for c in CANON if c in found]
rep["missing"]=[oldmiss.get(c,{"identity":c,"candidate_urls":[]}) for c in CANON if c not in found]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(CANON)-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL"
rep["bounded_deep_recovery_2026_09_15"]={
 "completed":True,"starting_recovered":start_count,"cdx_patterns":len(patterns),"cdx_rows_found":len(rows),
 "mapped_capture_counts":{c:len(mapped[c]) for c in CANON},"historical_page_captures_found":len(page_caps),
 "historical_page_captures_checked":checked,"recovered_now":new,"upgraded_now":upgraded}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"denominator":len(CANON),"starting_recovered":start_count,"recovered_now":new,"upgraded_now":upgraded,
 "full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"],
 "missing_ids":[x["identity"] for x in rep["missing"]]},indent=2))
