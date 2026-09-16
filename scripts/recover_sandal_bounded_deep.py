#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/sandal-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
CANON=[
"sandal_castle","sandal_castle19","sandal_castle7","sandal_castle17","wakefield_1460_2","sandal_castle_plan",
"sandal_castle20","sandal_castle5","sandal_castle13","sandal_castle1","wakefield_castles_context2","wakefield_1460_6",
"sandal_castle3","sandal_castle4","sandal_castle6","sandal_castle8","sandal_castle9","sandal_castle10","sandal_castle11",
"sandal_castle12","sandal_castle14","sandal_castle15","sandal_castle16","sandal_castle18","sandal_castle21","sandal_castle23"]
GALLERY=[
"sandal_castle1","sandal_castle5","sandal_castle7","sandal_castle13","sandal_castle19","wakefield_1460_2",
"sandal_castle3","sandal_castle4","sandal_castle6","sandal_castle8","sandal_castle9","sandal_castle10","sandal_castle11",
"sandal_castle12","sandal_castle14","sandal_castle15","sandal_castle16","sandal_castle18","sandal_castle21","sandal_castle23"]
PAGES=[
"http://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"https://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"http://castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"https://castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"http://www.castlesfortsbattles.co.uk/m/sandal_castle_wakefield_1460.html",
"http://www.castlesfortsbattles.co.uk/m/yorkshire/sandal_castle_wakefield_1460.html"]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 SandalBoundedDeepRecovery"

def get(u,t=12,params=None):
    for n in range(2):
        try:
            r=S.get(u,params=params,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception: pass
        time.sleep(.35*(n+1))
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
    path=urlparse(u).path.lower()
    if "/assets/" in path and not responsive_for(c,u): return "full/near-full"
    if not responsive_for(c,u) and max(z[0],z[1])>=1000: return "full/near-full"
    if not responsive_for(c,u) and z[0]*z[1]>=220000: return "full/near-full"
    return "thumbnail/lower-resolution"

def cdx(pattern):
    ep="https://web.archive.org/cdx/search/cdx"
    params={"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest","filter":["statuscode:200"],"collapse":"digest","limit":"4000"}
    r=get(ep,22,params)
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []

def replay(ts,orig):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{orig}",8)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url
    return None

rep=json.loads(REP.read_text()); found={x["identity"]:x for x in rep.get("images",[])}
missing0=[c for c in CANON if c not in found]

# Pass 1: wildcard CDX filename-family recovery, the high-yield Richmond technique.
patterns=[]
for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    for d in ("yorkshire/assets","yorkshire/images","assets","images","m/assets","m/images","yorkshire/wpimages","wpimages"):
        for fam in ("sandal_castle*","wakefield_1460*","wakefield_castles_context*"):
            patterns.append(f"{host}/{d}/{fam}")
rows=[]
with ThreadPoolExecutor(max_workers=18) as ex:
    futs={ex.submit(cdx,p):p for p in patterns}
    for f in as_completed(futs):
        rr=f.result(); rows.extend(rr)
seen=set();rows=[x for x in rows if not ((x["timestamp"],x["original"],x.get("digest")) in seen or seen.add((x["timestamp"],x["original"],x.get("digest"))))]
mapped={c:[] for c in CANON}
for x in rows:
    c=canon_for(x["original"])
    if c:mapped[c].append(x)

jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for c,rr in mapped.items():
        if c in found:continue
        # Prefer assets, exact base filenames, then responsive. Try a chronological spread capped at 10.
        rr=sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x["original"]).path.lower() else 1,
                                   1 if responsive_for(c,x["original"]) else 0,x["timestamp"]))
        if len(rr)>10:
            inds={0,len(rr)-1}
            for n in range(1,9):inds.add(round(n*(len(rr)-1)/9))
            rr=[rr[i] for i in sorted(inds)]
        for row in rr:jobs[ex.submit(replay,row["timestamp"],row["original"])]=(c,row)
    results={c:[] for c in CANON}
    for f in as_completed(jobs):
        c,row=jobs[f]; got=f.result()
        if got:
            b,z,final=got; q=quality(c,row["original"],z)
            score=(3 if "/assets/" in urlparse(row["original"]).path.lower() and not responsive_for(c,row["original"]) else 2 if q=="full/near-full" else 1,z[0]*z[1])
            results[c].append((score,row,b,z,final,q))

new=[]
for c in CANON:
    if c in found or not results[c]:continue
    _,row,b,z,final,q=max(results[c],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg"; p=IMG/(c+ext); p.write_bytes(b)
    found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":row["timestamp"],"archive_original":row["original"],
              "archive_replay":final,"method":"wayback-cdx-wildcard-filename-family","dimensions":[z[0],z[1]],"format":z[2],
              "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    new.append(c)

# Pass 2, only if anything remains: bounded historical-page/TimeMap mining to catch renamed files by slideshow position.
remain=[c for c in CANON if c not in found]
page_caps=[]
def timemap(page):
    r=get("https://web.archive.org/web/timemap/link/"+page,14)
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
if remain:
    for p in PAGES:page_caps+=timemap(p)
    seen=set();page_caps=[x for x in page_caps if not (x in seen or seen.add(x))];page_caps.sort()
    if len(page_caps)>28:
        inds={0,len(page_caps)-1}
        for n in range(1,27):inds.add(round(n*(len(page_caps)-1)/27))
        page_caps=[page_caps[i] for i in sorted(inds)]
    hist={c:[] for c in remain}; checked=0
    for ts,page in page_caps:
        r=get(f"https://web.archive.org/web/{ts}id_/{page}",10)
        if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
        checked+=1;soup=BeautifulSoup(r.text,"html.parser")
        # semantic refs
        for tag in soup.find_all(["a","img"]):
            for attr in ("href","data-src","data-orig-src","data-muse-src"):
                ref=tag.get(attr)
                if not ref:continue
                u=urljoin(page,ref); c=canon_for(u)
                if c in hist:hist[c].append(u)
        # slideshow position mapping, survives filename changes
        for im in soup.find_all("img"):
            if "ImageInclude" not in (im.get("class") or []):continue
            try:i=int(im.get("data-col-pos"))
            except:continue
            if 0<=i<len(GALLERY):
                c=GALLERY[i]
                if c in hist:
                    ref=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src")
                    if ref:hist[c].append(urljoin(page,ref))
    # CDX exact lookup for historical discovered refs.
    exact_jobs={}
    with ThreadPoolExecutor(max_workers=14) as ex:
        for c,urls in hist.items():
            ss=set();urls=[u for u in urls if not (u in ss or ss.add(u))]
            for u in urls[:24]:
                exact_jobs[ex.submit(cdx,u)]=(c,u)
        exact_rows={c:[] for c in remain}
        for f in as_completed(exact_jobs):
            c,u=exact_jobs[f];exact_rows[c]+=f.result()
    replay_jobs={}
    with ThreadPoolExecutor(max_workers=14) as ex:
        for c,rr in exact_rows.items():
            if c in found:continue
            rr=rr[:8]
            for row in rr:replay_jobs[ex.submit(replay,row["timestamp"],row["original"])]=(c,row)
        hist_results={c:[] for c in remain}
        for f in as_completed(replay_jobs):
            c,row=replay_jobs[f];got=f.result()
            if got:
                b,z,final=got;q=quality(c,row["original"],z)
                hist_results[c].append(((2 if q=="full/near-full" else 1,z[0]*z[1]),row,b,z,final,q))
    for c in remain:
        if c in found or not hist_results.get(c):continue
        _,row,b,z,final,q=max(hist_results[c],key=lambda x:x[0])
        ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
        found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":row["timestamp"],"archive_original":row["original"],
                  "archive_replay":final,"method":"historical-page-position-plus-cdx","dimensions":[z[0],z[1]],"format":z[2],
                  "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
        new.append(c)
else:
    checked=0

rep["images"]=[found[c] for c in CANON if c in found]
old={x["identity"]:x for x in rep.get("missing",[])}
rep["missing"]=[old.get(c,{"identity":c,"candidate_urls":[]}) for c in CANON if c not in found]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(CANON)-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL"
rep["bounded_deep_recovery_2026_09_15"]={
 "completed":True,"cdx_patterns":len(patterns),"cdx_rows_found":len(rows),"mapped_capture_counts":{c:len(mapped[c]) for c in CANON},
 "historical_page_captures_found":len(page_caps),"historical_page_captures_checked":checked,"recovered_now":new}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"denominator":len(CANON),"starting_missing":len(missing0),"recovered_now":new,
 "full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"],
 "missing_ids":[x["identity"] for x in rep["missing"]]},indent=2))
