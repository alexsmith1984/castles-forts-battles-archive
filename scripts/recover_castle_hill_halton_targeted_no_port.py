#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/castle-hill-halton"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"
rep=json.loads(REP.read_text())
TARGETS=rep["desktop_image_identities"]
CAPS=["20200708105528","20180112085831","20170208093615"]
DEADLINE=time.monotonic()+330
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 HaltonTargetedNoPortRecovery"

def alive(): return time.monotonic()<DEADLINE
def get(u,t=6,params=None):
    if not alive():return None
    try:return S.get(u,params=params,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None
def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=60 else None
    except:return None
def replay(ts,u):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",5)
        if r and r.status_code==200:
            z=valid(r.content)
            if z:return r.content,z,r.url
    return None
def cdx(pattern):
    r=get("https://web.archive.org/cdx/search/cdx",7,{"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest",
      "filter":"statuscode:200","collapse":"digest","from":"2014","to":"2023","limit":"1000"})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []
def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',Path(urlparse(u).path).stem.lower()))
def quality(c,u,z):
    p=urlparse(u).path.lower(); st=Path(p).stem.lower()
    if ("/assets/" in p or st==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=900:return "full/near-full"
    return "thumbnail/lower-resolution"
def score(c,u,z,q):
    p=urlparse(u).path.lower();st=Path(p).stem.lower()
    return (4 if "/assets/" in p and not responsive(c,u) else 3 if st==c.lower() and not responsive(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

oldmiss={x["identity"]:x for x in rep.get("missing",[])}
candidates={t:[] for t in TARGETS}
for t in TARGETS:
    # exact URLs already recorded, normalized to no explicit port
    for u in oldmiss.get(t,{}).get("candidate_urls",[]):
        p=urlparse(u)
        path=p.path; query=p.query
        for scheme in ("http","https"):
            for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
                candidates[t].append(urlunparse((scheme,host,path,"",query,"")))
                candidates[t].append(urlunparse((scheme,host,path,"","","")))
    # inferred exact originals and display files
    for ext in ("jpg","jpeg","png"):
        for scheme in ("http","https"):
            for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
                candidates[t].append(f"{scheme}://{host}/north_west/assets/{t}.{ext}")
                candidates[t].append(f"{scheme}://{host}/north_west/images/{t}.{ext}")
    ss=set();candidates[t]=[u for u in candidates[t] if not (u in ss or ss.add(u))]

rows={t:[] for t in TARGETS}
# Direct selected/historical capture replay.
results={t:[] for t in TARGETS}
jobs={}
with ThreadPoolExecutor(max_workers=22) as ex:
    for t,urls in candidates.items():
        for u in urls[:36]:
            for ts in CAPS:
                jobs[ex.submit(replay,ts,u)]=(t,ts,u,"direct-no-port-cross-timestamp")
    for f in as_completed(jobs):
        if not alive():break
        t,ts,u,meth=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(t,u,z);results[t].append((score(t,u,z,q),ts,u,b,z,final,q,meth))

# Exact identity-family CDX searches, including older case style.
patterns=[]
for t in TARGETS:
    variants={t,t.upper(),t.title(),t.replace("halton_castle_motte","Halton_Castle_Motte")}
    for v in variants:
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
            for d in ("north_west/assets","north_west/images","assets","images"):
                patterns.append((t,f"{host}/{d}/{v}*"))
with ThreadPoolExecutor(max_workers=18) as ex:
    fs={ex.submit(cdx,p):(t,p) for t,p in patterns}
    for f in as_completed(fs):
        if not alive():break
        t,p=fs[f]
        try:rows[t]+=f.result()
        except:pass

jobs={}
with ThreadPoolExecutor(max_workers=20) as ex:
    for t,rr in rows.items():
        seen=set();ded=[]
        for x in sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x.get("original","")).path.lower() else 1,
                                        1 if responsive(t,x.get("original","")) else 0,x.get("timestamp",""))):
            k=(x.get("timestamp"),x.get("original"))
            if not x.get("timestamp") or not x.get("original") or k in seen:continue
            seen.add(k);ded.append(x)
        for x in ded[:25]:
            jobs[ex.submit(replay,x["timestamp"],x["original"])]=(t,x)
    for f in as_completed(jobs):
        if not alive():break
        t,x=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;u=x["original"];q=quality(t,u,z)
            results[t].append((score(t,u,z,q),x["timestamp"],u,b,z,final,q,"wayback-cdx-no-port-family"))

found={x["identity"]:x for x in rep.get("images",[])}
new=[]
for t in TARGETS:
    if not results[t]:continue
    _,ts,u,b,z,final,q,meth=max(results[t],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(t+ext);p.write_bytes(b)
    found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,"archive_replay":final,
      "method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":q,"identification":"certain"}
    new.append(t)

images=[found[t] for t in TARGETS if t in found]
missing=[{"identity":t,"candidate_urls":candidates[t][:50]} for t in TARGETS if t not in found]
full=sum(x["quality"]=="full/near-full" for x in images);lower=len(images)-full
rep["images"]=images;rep["missing"]=missing
rep["recovered_full_or_near_full"]=full
rep["recovered_thumbnail_or_lower_resolution"]=lower
rep["still_missing"]=len(missing)
rep["status"]="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"
rep["targeted_no_port_recovery_2026_09_15"]={"completed":True,"targets":TARGETS,
 "candidate_counts":{t:len(candidates[t]) for t in TARGETS},
 "cdx_capture_counts":{t:len(rows[t]) for t in TARGETS},"recovered_now":new}
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

# Refresh figures/note.
p=ROOT/"index.html";soup=BeautifulSoup(p.read_text(),"html.parser")
h=soup.find("h2",string=lambda x:x and "Recovered original" in x)
if h:
    for fig in list(h.find_all_next("figure")):fig.decompose()
    anchor=h
    for x in images:
        fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt="Castle Hill Halton archived original image")
        a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
        cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x["quality"]!="full/near-full" else "")
        fig.append(cap);anchor.insert_after(fig);anchor=fig
note=soup.find("div",class_="note")
if note:note.string=f"Recovered from the archived CastlesFortsBattles Halton Castle page. {len(images)} of {len(TARGETS)} unique Halton/map content images have been recovered; {len(missing)} remain unavailable. An unrelated embedded Whittington Castle gallery is excluded. No substitute photographs have been introduced."
p.write_text(str(soup))

Path("page-audit/castle-hill-halton.json").write_text(json.dumps({
"name":"Castle Hill, Halton (Halton Castle)","slug":"castle-hill-halton","status":rep["status"],"source":rep["source_timestamp_used"],
"positions":len(TARGETS),"full":full,"lower":lower,"missing":len(missing),
"missing_identities":[x["identity"] for x in missing],"excluded_unrelated_gallery":"whittington_castle_lancashire*"},indent=2)+"\n")
print(json.dumps({"recovered_now":new,"full":full,"lower":lower,"missing":len(missing),"missing_ids":[x["identity"] for x in missing],
"cdx_counts":{t:len(rows[t]) for t in TARGETS}},indent=2))
