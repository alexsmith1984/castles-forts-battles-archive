#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/warkworth-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"
rep=json.loads(REP.read_text()); CANON=rep["desktop_image_identities"]
TARGETS=[x["identity"] for x in rep.get("missing",[])]
for x in rep.get("images",[]):
    if x.get("quality")!="full/near-full" and x["identity"] not in TARGETS: TARGETS.append(x["identity"])
PAGE="http://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html"
PAGES=[PAGE,PAGE.replace("http://","https://"),PAGE.replace("www.",""),PAGE.replace("http://www.","https://"),
       "http://www.castlesfortsbattles.co.uk/m/warkworth_castle_bridge.html",
       "http://www.castlesfortsbattles.co.uk/m/north_east/warkworth_castle_bridge.html"]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 WarkworthTargetedFinalRecovery"

def get(u,t=7):
    for n in range(2):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504):return r
        except:pass
        time.sleep(.2*(n+1))
    return None

def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=80 else None
    except:return None

def mapid(u):
    stem=Path(urlparse(u).path).stem.lower()
    for c in sorted(CANON,key=len,reverse=True):
        lc=c.lower()
        if stem==lc or re.fullmatch(re.escape(lc)+r'\d+x\d+',stem):return c
    return None

def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',Path(urlparse(u).path).stem.lower()))

def qual(c,u,z):
    stem=Path(urlparse(u).path).stem.lower(); path=urlparse(u).path.lower()
    if ("/assets/" in path or stem==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=1000:return "full/near-full"
    return "thumbnail/lower-resolution"

def score(c,u,z,q):
    stem=Path(urlparse(u).path).stem.lower();path=urlparse(u).path.lower()
    return (4 if "/assets/" in path and not responsive(c,u) else 3 if stem==c.lower() and not responsive(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

def timemap(src,u):
    ep=("https://web.archive.org/web/timemap/link/"+u) if src=="wayback" else ("https://arquivo.pt/wayback/timemap/link/"+u)
    marker="/web/" if src=="wayback" else "/wayback/"
    r=get(ep,8)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        uri=line.split("<",1)[1].split(">",1)[0]
        if marker not in uri:continue
        rest=uri.split(marker,1)[1]
        if "/" not in rest:continue
        ts,orig=rest.split("/",1);ts=ts[:14]
        if len(ts)==14 and ts.isdigit():out.append((src,ts,orig))
    return out

def replay(src,ts,u):
    eps=([f"https://web.archive.org/web/{ts}id_/{u}",f"https://web.archive.org/web/{ts}im_/{u}"] if src=="wayback"
         else [f"https://arquivo.pt/wayback/{ts}id_/{u}"])
    for ep in eps:
        r=get(ep,5)
        if r and r.status_code==200:
            z=valid(r.content)
            if z:return r.content,z,r.url
    return None

# Historical page captures: discover old references, CRC variants, and usable timestamps.
caps=[]
for p in PAGES:caps+=timemap("wayback",p)+timemap("arquivo",p)
seen=set();caps=[x for x in caps if not (x in seen or seen.add(x))];caps.sort(key=lambda x:x[1])
if len(caps)>28:
    inds={0,len(caps)-1}
    for n in range(1,27):inds.add(round(n*(len(caps)-1)/27))
    caps=[caps[i] for i in sorted(inds)]

oldmiss={x["identity"]:x for x in rep.get("missing",[])}
cands={t:list(oldmiss.get(t,{}).get("candidate_urls",[])) for t in TARGETS}
# existing lower-res provenance is also a candidate family
for x in rep.get("images",[]):
    if x["identity"] in cands and x.get("archive_original"):cands[x["identity"]].append(x["archive_original"])

checked_pages=0
for src,ts,page in caps:
    ep=(f"https://web.archive.org/web/{ts}id_/{page}" if src=="wayback" else f"https://arquivo.pt/wayback/{ts}id_/{page}")
    r=get(ep,6)
    if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
    checked_pages+=1
    soup=BeautifulSoup(r.text,"html.parser")
    for tag in soup.find_all(["a","img"]):
        for attr in ("href","src","data-src","data-orig-src","data-muse-src"):
            ref=tag.get(attr)
            if not ref:continue
            u=urljoin(page,ref);c=mapid(u)
            if c in cands:cands[c].append(u)

# Legacy path/case variants for the exact missing standalone identities.
for t in TARGETS:
    base=t
    ext="png" if "plan" in t else "jpg"
    names=[f"{base}.{ext}",f"{base}.jpg",f"{base}.png",
           f"{base.replace('warkworth_','Warkworth_')}.{ext}",
           f"{base.replace('_','-')}.{ext}"]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
       for d in ("north_east/assets","north_east/images","assets","images","m/assets","m/images","north_east/wpimages","wpimages"):
        for n in names:cands[t].append(f"{scheme}://{host}/{d}/{n}")
    ss=set();cands[t]=[u for u in cands[t] if not (u in ss or ss.add(u))]

found={x["identity"]:x for x in rep.get("images",[])}
results={t:[] for t in TARGETS}

def search_one(t,u,page_ts):
    attempts=[]
    # direct cross-timestamp replay at a bounded spread of page-capture timestamps
    for ts in page_ts:
        attempts.append(("wayback",ts,u))
    # exact TimeMaps can reveal asset captures detached from page captures
    for src in ("wayback","arquivo"):
        m=timemap(src,u)
        if m:
            m.sort(key=lambda x:x[1]);inds={0,len(m)-1,len(m)//2}
            if len(m)>4:inds|={len(m)//4,(3*len(m))//4}
            for i in sorted(inds):attempts.append(m[i])
    # nearest-capture fallback
    for ts in ("2","20220826205457","20220101000000","20210101000000","20190101000000"):
        attempts.append(("wayback",ts,u))
    seen=set()
    for src,ts,orig in attempts:
        k=(src,ts,orig)
        if k in seen:continue
        seen.add(k)
        got=replay(src,ts,orig)
        if got:return src,ts,orig,got
    return None

way_ts=sorted({ts for src,ts,p in caps if src=="wayback"})
if len(way_ts)>10:
    inds={0,len(way_ts)-1}
    for n in range(1,9):inds.add(round(n*(len(way_ts)-1)/9))
    way_ts=[way_ts[i] for i in sorted(inds)]

jobs={}
with ThreadPoolExecutor(max_workers=20) as ex:
    for t,urls in cands.items():
        for u in urls[:70]:
            jobs[ex.submit(search_one,t,u,way_ts)]=(t,u)
    for f in as_completed(jobs):
        t,u=jobs[f]
        try:got=f.result()
        except:got=None
        if not got:continue
        src,ts,orig,(b,z,final)=got;q=qual(t,orig,z)
        results[t].append((score(t,orig,z,q),src,ts,orig,b,z,final,q))

new=[];upgraded=[]
for t in TARGETS:
    if not results[t]:continue
    best=max(results[t],key=lambda x:x[0]);sc,src,ts,orig,b,z,final,q=best
    old=found.get(t)
    if old:
        oz=old.get("dimensions",[0,0]);oq=old.get("quality","thumbnail/lower-resolution")
        oldscore=(3 if oq=="full/near-full" else 1,oz[0]*oz[1])
        if sc<=oldscore:continue
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(t+ext);p.write_bytes(b)
    found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":orig,"archive_replay":final,
              "method":"targeted-cross-timestamp-wayback-arquivo","archive_source":src,"dimensions":[z[0],z[1]],"format":z[2],
              "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    (upgraded if old else new).append(t)

order=CANON
rep["images"]=[found[i] for i in order if i in found]
rep["missing"]=[oldmiss.get(i,{"identity":i,"candidate_urls":[]}) for i in order if i not in found]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(order)-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL / SEARCH EXHAUSTED"
rep["targeted_final_recovery_2026_09_15"]={"completed":True,"targets":TARGETS,"historical_page_captures_found":len(caps),
 "historical_page_captures_checked":checked_pages,"candidate_counts":{k:len(v) for k,v in cands.items()},
 "recovered_now":new,"upgraded_now":upgraded}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"new":new,"upgraded":upgraded,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],
 "missing":rep["still_missing"],"missing_ids":[x["identity"] for x in rep["missing"]]},indent=2))
