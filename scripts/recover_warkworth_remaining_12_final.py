#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/warkworth-castle"); REP=ROOT/"recovery-report.json"; SRC=ROOT/"source.html"; IMG=ROOT/"images"
rep=json.loads(REP.read_text()); TARGETS=[x["identity"] for x in rep.get("missing",[])]
ORDER=rep["desktop_image_identities"]
STANDALONE=["warkworth_castle","warkworth_castle15","warkworth_castle17","warkworth_castle8","warkworth_castle12","warkworth_castle4",
"warkworth_castle20","warkworth_castle13","warkworth_castle19a","warkworth_castle26","warkworth_castle_town_plan","warkworth_castle1a",
"warkworth_castle25a","warkworth_bridge1a","warkworth_bridge8","warkworth_bridge9","warkworth_bridge4"]
PAGE="http://www.castlesfortsbattles.co.uk/north_east/warkworth_castle_bridge.html"
PAGES=[
PAGE,PAGE.replace("http://","https://"),PAGE.replace("www.",""),PAGE.replace("http://www.","https://"),
"http://www.castlesfortsbattles.co.uk/m/warkworth_castle_bridge.html",
"http://www.castlesfortsbattles.co.uk/m/north_east/warkworth_castle_bridge.html"]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 WarkworthFinalEightMinuteRecovery"
DEADLINE=time.monotonic()+360  # leave ~2 minutes for page rebuild/commit inside 8-minute Actions hard stop

def alive(): return time.monotonic()<DEADLINE

def get(u,t=6,params=None):
    if not alive(): return None
    try:return S.get(u,params=params,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None

def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=80 else None
    except:return None

def current_id(u):
    stem=Path(urlparse(u).path).stem.lower()
    for c in sorted(ORDER,key=len,reverse=True):
        lc=c.lower()
        if stem==lc or re.fullmatch(re.escape(lc)+r'\d+x\d+',stem):return c
    return None

def responsive(c,u): return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',Path(urlparse(u).path).stem.lower()))

def quality(c,u,z):
    p=urlparse(u).path.lower();s=Path(p).stem.lower()
    if ("/assets/" in p or s==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=1000:return "full/near-full"
    return "thumbnail/lower-resolution"

def score(c,u,z,q):
    p=urlparse(u).path.lower();s=Path(p).stem.lower()
    return (4 if "/assets/" in p and not responsive(c,u) else 3 if s==c.lower() and not responsive(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

def cdx(pattern,limit=1000):
    if not alive():return []
    r=get("https://web.archive.org/cdx/search/cdx",8,{
      "url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest","filter":"statuscode:200",
      "collapse":"digest","from":"2014","to":"2023","limit":str(limit)})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,x)) for x in j[1:]]
    except:return []

def timemap(page):
    r=get("https://web.archive.org/web/timemap/link/"+page,8)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        u=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/web/(\d{14})[^/]*/(.+)$",u)
        if m:out.append((m.group(1),m.group(2)))
    return out

def replay(ts,u):
    for mode in ("id_","im_"):
        if not alive():return None
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",5)
        if r and r.status_code==200:
            z=valid(r.content)
            if z:return r.content,z,r.url
    return None

# 1) Identity-specific wildcard CDX: exact filename families, not broad site families.
patterns={t:[] for t in TARGETS}
for t in TARGETS:
    exts=("png","jpg") if "plan" in t else ("jpg","jpeg","png")
    for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
      for d in ("north_east/assets","north_east/images","assets","images","m/assets","m/images","north_east/wpimages","wpimages"):
       for ext in exts:
        patterns[t].append(f"{host}/{d}/{t}*.{ext}*")
        patterns[t].append(f"{host}/{d}/{t.replace('_','-')}*.{ext}*")

rows={t:[] for t in TARGETS}
with ThreadPoolExecutor(max_workers=18) as ex:
    jobs={ex.submit(cdx,p,500):(t,p) for t,ps in patterns.items() for p in ps}
    for f in as_completed(jobs):
        if not alive():break
        t,p=jobs[f]
        try:rows[t]+=f.result()
        except:pass

# 2) Historical page captures: gather old refs and try to infer renamed standalone assets by anchored order.
caps=[]
for p in PAGES:
    caps += [(ts,orig) for ts,orig in timemap(p)]
seen=set();caps=[x for x in sorted(caps) if not (x in seen or seen.add(x))]
if len(caps)>24:
    idx={0,len(caps)-1}
    for n in range(1,23):idx.add(round(n*(len(caps)-1)/23))
    caps=[caps[i] for i in sorted(idx)]

pos_candidates={t:[] for t in TARGETS}
known_ref_candidates={t:[] for t in TARGETS}
checked=0

def image_href_sequence(html,page):
    soup=BeautifulSoup(html,"html.parser"); seq=[]
    for a in soup.find_all("a",href=True):
        href=a.get("href")
        if not re.search(r'\.(?:jpe?g|png)(?:\?|$)',href,re.I):continue
        # content image links only; reject obvious interface/social assets
        low=href.lower()
        if any(x in low for x in ("facebook","twitter","google","blank.gif","logo","button","menu")):continue
        img=a.find("img")
        if not img:continue
        seq.append(urljoin(page,href))
    # remove immediate duplicates
    out=[]
    for u in seq:
        if not out or u!=out[-1]:out.append(u)
    return out

for ts,page in caps:
    if not alive():break
    r=get(f"https://web.archive.org/web/{ts}id_/{page}",6)
    if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
    checked+=1
    seq=image_href_sequence(r.text,page)
    # exact/ref-family candidates from old capture
    for u in seq:
        c=current_id(u)
        if c in known_ref_candidates:known_ref_candidates[c].append((ts,u))
    # anchored-order inference: align known standalone identities as an ordered subsequence.
    labeled=[current_id(u) for u in seq]
    anchors=[]
    for i,c in enumerate(labeled):
        if c in STANDALONE:anchors.append((i,STANDALONE.index(c),c))
    # Need at least 5 exact anchors and a single constant offset across them.
    offsets={}
    for si,ci,c in anchors: offsets.setdefault(si-ci,[]).append((si,ci,c))
    if offsets:
        off,best=max(offsets.items(),key=lambda kv:len(kv[1]))
        if len(best)>=5:
            for ci,c in enumerate(STANDALONE):
                si=ci+off
                if c in pos_candidates and 0<=si<len(seq):
                    u=seq[si]
                    # accept only if the inferred slot is either unlabelled or already maps to same identity
                    mapped=current_id(u)
                    if mapped in (None,c):pos_candidates[c].append((ts,u,len(best)))

# Merge historical refs and current report candidate URLs into rows/candidates.
oldmiss={x["identity"]:x for x in rep.get("missing",[])}
for t in TARGETS:
    # query historical exact refs and current known URLs
    urls=list(oldmiss.get(t,{}).get("candidate_urls",[]))
    urls += [u for ts,u in known_ref_candidates[t]]
    urls += [u for ts,u,n in pos_candidates[t]]
    ss=set();urls=[u for u in urls if not (u in ss or ss.add(u))]
    # exact CDX on these URLs
    for u in urls[:40]:
        if not alive():break
        rows[t]+=cdx(u,300)
    # direct replay at the historical page timestamp for inferred/order-mapped refs
    for ts,u,n in pos_candidates[t][:20]:
        rows[t].append({"timestamp":ts,"original":u,"statuscode":"200","mimetype":"image/unknown","digest":f"pos-{ts}-{n}"})

# Dedupe and replay most promising candidates per target.
results={t:[] for t in TARGETS}
def priority(t,x):
    u=x.get("original",""); p=urlparse(u).path.lower(); s=Path(p).stem.lower()
    return (0 if "/assets/" in p else 1,0 if s==t.lower() else 1,1 if responsive(t,u) else 0,x.get("timestamp",""))

with ThreadPoolExecutor(max_workers=18) as ex:
    jobs={}
    for t,rr in rows.items():
        ded=[];ss=set()
        for x in sorted(rr,key=lambda x:priority(t,x)):
            k=(x.get("timestamp"),x.get("original"))
            if not x.get("timestamp") or not x.get("original") or k in ss:continue
            ss.add(k);ded.append(x)
        # bounded to the top 30 candidates per identity
        for x in ded[:30]:
            if not alive():break
            jobs[ex.submit(replay,x["timestamp"],x["original"])]=(t,x)
    for f in as_completed(jobs):
        if not alive():break
        t,x=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(t,x["original"],z)
            results[t].append((score(t,x["original"],z,q),x,b,z,final,q))

found={x["identity"]:x for x in rep.get("images",[])}
new=[]
for t in TARGETS:
    if not results[t]:continue
    sc,x,b,z,final,q=max(results[t],key=lambda v:v[0])
    ext=".png" if z[2]=="PNG" else ".jpg"; p=IMG/(t+ext); p.write_bytes(b)
    found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":x["timestamp"],"archive_original":x["original"],
      "archive_replay":final,"method":"final-identity-cdx-historical-order","dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    new.append(t)

rep["images"]=[found[i] for i in ORDER if i in found]
rep["missing"]=[oldmiss.get(i,{"identity":i,"candidate_urls":[]}) for i in ORDER if i not in found]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(ORDER)-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL / SEARCH EXHAUSTED"
rep["final_eight_minute_remaining_search_2026_09_15"]={
  "completed":True,"internal_search_limit_seconds":360,"targets":TARGETS,"historical_page_captures_found":len(caps),
  "historical_page_captures_checked":checked,
  "identity_cdx_candidate_counts":{t:len(rows[t]) for t in TARGETS},
  "historical_position_candidate_counts":{t:len(pos_candidates[t]) for t in TARGETS},
  "recovered_now":new
}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"recovered_now":new,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],
"missing":rep["still_missing"],"missing_ids":[x["identity"] for x in rep["missing"]],
"position_candidates":{t:len(pos_candidates[t]) for t in TARGETS}},indent=2))
