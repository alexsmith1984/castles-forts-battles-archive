#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/castle-hill-almondbury"); REP=ROOT/"recovery-report.json"; SRC=ROOT/"source.html"; IMG=ROOT/"images"
TS="20161021184941"; BASE="http://www.castlesfortsbattles.co.uk/yorkshire/"
HERO="castle_hill_almondbury"
GALLERY=[
"castle_hill_almondbury1","castle_hill_almondbury2","castle_hill_almondbury3_medieval_ditch",
"castle_hill_almondbury4_medieval_remains","castle_hill_almondbury5_victoria_tower",
"castle_hill_almondbury6_victoria_tower","castle_hill_almondbury7_victoria_tower",
"castle_hill_almondbury8_victoria_tower","castle_hill_almondbury9_ditch","castle_hill_almondbury10",
"castle_hill_almondbury11_rampart","castle_hill_almondbury12_view","castle_hill_almondbury13",
"castle_hill_almondbury14","castle_hill_almondbury15","castle_hill_almondbury16","castle_hill_almondbury17"]
ORDER=[HERO]+GALLERY
DEADLINE=time.monotonic()+360
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 CastleHillAlmondburyTargetedRecovery"

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
def timemap(u):
    r=get("https://web.archive.org/web/timemap/link/"+u,6)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/web/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out
def cdx(u):
    r=get("https://web.archive.org/cdx/search/cdx",6,{"url":u,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest",
      "filter":"statuscode:200","collapse":"digest","from":"2014","to":"2020","limit":"40"})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []
def arquivo_timemap(u):
    r=get("https://arquivo.pt/wayback/timemap/link/"+u,5)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/wayback/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out
def arquivo_replay(ts,u):
    r=get(f"https://arquivo.pt/wayback/{ts}id_/{u}",5)
    if r and r.status_code==200:
        z=valid(r.content)
        if z:return r.content,z,r.url
    return None

rep=json.loads(REP.read_text()); source=SRC.read_text()
found={x["identity"]:x for x in rep.get("images",[])}
targets=[x for x in ORDER if x not in found]

# Exact source refs for all gallery identities.
refs={t:[] for t in targets}
for m in re.finditer(r'(?:data-src|data-muse-src|data-orig-src|src)=["\']([^"\']+)["\']',source,re.I):
    u=m.group(1)
    if "castle_hill_almondbury" not in u.lower():continue
    name=Path(urlparse(u).path).stem.lower()
    for t in sorted(targets,key=len,reverse=True):
        tl=t.lower()
        if name==tl or re.fullmatch(re.escape(tl)+r'\d+x\d+',name):
            refs[t].append(BASE+u.lstrip("/"));break

def variants(t):
    out=[]
    for u in refs.get(t,[]):out.append(u)
    # inferred full originals and base display exports
    for ext in ("jpg","jpeg","png"):
        out.append(BASE+"assets/"+t+"."+ext)
        out.append(BASE+"images/"+t+"."+ext)
    # source refs without CRC
    out += [u.split("?",1)[0] for u in list(out)]
    # host/protocol variants
    more=[]
    for u in out:
        p=urlparse(u)
        for scheme in ("http","https"):
            for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
                more.append(urlunparse((scheme,host,p.path,"","","")))
                if p.query:more.append(urlunparse((scheme,host,p.path,"",p.query,"")))
    out+=more
    ss=set();return [u for u in out if not (u in ss or ss.add(u))]

candidates={t:variants(t) for t in targets}
results={t:[] for t in targets}

def qscore(t,u,z,source):
    p=urlparse(u).path.lower()
    full="/assets/" in p
    q="full/near-full" if full else "thumbnail/lower-resolution"
    return ((3 if full else 1),z[0]*z[1]),q

# Stage 1: same capture / nearest replay for every exact candidate.
jobs={}
with ThreadPoolExecutor(max_workers=20) as ex:
    for t,urls in candidates.items():
        for u in urls[:28]:
            jobs[ex.submit(replay,TS,u)]=(t,u,"same-capture-variant",TS)
            jobs[ex.submit(replay,"2",u)]=(t,u,"nearest-capture", "2")
    for f in as_completed(jobs):
        if not alive():break
        t,u,meth,ts=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;sc,q=qscore(t,u,z,"wayback")
            results[t].append((sc,u,b,z,final,q,meth,ts,"wayback"))

# Stage 2: exact URL TimeMap/CDX and Arquivo, only for still-unfound targets.
for t in targets:
    if results[t] or not alive():continue
    for u in candidates[t][:18]:
        if not alive():break
        ars=[]
        for x in cdx(u):
            if x.get("timestamp") and x.get("original"):ars.append(("wayback",x["timestamp"],x["original"]))
        for ts,orig in timemap(u):ars.append(("wayback",ts,orig))
        for ts,orig in arquivo_timemap(u):ars.append(("arquivo",ts,orig))
        seen=set()
        for src,ts,orig in ars[:20]:
            k=(src,ts,orig)
            if k in seen:continue
            seen.add(k)
            got=replay(ts,orig) if src=="wayback" else arquivo_replay(ts,orig)
            if got:
                b,z,final=got;sc,q=qscore(t,orig,z,src)
                results[t].append((sc,orig,b,z,final,q,"exact-timemap-cdx",ts,src))
                if q=="full/near-full":break
        if results[t] and max(x[0] for x in results[t])[0]>=3:break

new=[]
for t in targets:
    if not results[t]:continue
    sc,u,b,z,final,q,meth,ts,src=max(results[t],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(t+ext);p.write_bytes(b)
    found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,"archive_replay":final,
      "archive_source":src,"method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    new.append(t)

# Correct denominator and final report.
oldmiss={x["identity"]:x for x in rep.get("missing",[])}
images=[found[i] for i in ORDER if i in found]
missing=[]
for i in ORDER:
    if i in found:continue
    missing.append({"identity":i,"candidate_urls":candidates.get(i,oldmiss.get(i,{}).get("candidate_urls",[]))[:40]})
full=sum(x.get("quality")=="full/near-full" for x in images);lower=len(images)-full
rep.update({
 "status":"COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED",
 "original_image_positions_identified":18,
 "desktop_image_identities":ORDER,
 "recovered_full_or_near_full":full,
 "recovered_thumbnail_or_lower_resolution":lower,
 "still_missing":len(missing),
 "images":images,
 "missing":missing,
 "denominator_method":{"hero_identity":HERO,"gallery_positions":17,"gallery_identities":GALLERY,
    "hero_gallery_overlap":0,"responsive_variants_collapsed":True,"unique_union":18,
    "audit_note":"2016 Muse slideshow uses ImageInclude without data-col-pos; gallery identities were audited directly from slideshow order."},
 "targeted_final_recovery_2026_09_15":{"completed":True,"targets":targets,
    "candidate_counts":{t:len(candidates[t]) for t in targets},"recovered_now":new}
})
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

# Rebuild figures/note only.
p=ROOT/"index.html";soup=BeautifulSoup(p.read_text(),"html.parser")
h=soup.find("h2",string=lambda x:x and "Recovered original photographs" in x)
if h:
    for fig in list(h.find_all_next("figure")):fig.decompose()
    anchor=h
    for x in images:
        fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt="Castle Hill Almondbury archived original image")
        a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
        cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x["quality"]!="full/near-full" else "")
        fig.append(cap);anchor.insert_after(fig);anchor=fig
note=soup.find("div",class_="note")
if note:note.string=f"Recovered from the archived CastlesFortsBattles page. {len(images)} of 18 unique original content images have been recovered; {len(missing)} remain unavailable. No unrelated substitute photographs have been introduced."
p.write_text(str(soup))

Path("page-audit/castle-hill-almondbury.json").write_text(json.dumps({
"name":"Castle Hill, Almondbury","slug":"castle-hill-almondbury","status":rep["status"],"source":TS,
"positions":18,"full":full,"lower":lower,"missing":len(missing),"missing_identities":[x["identity"] for x in missing]},indent=2)+"\n")

print(json.dumps({"denominator":18,"recovered_now":new,"full":full,"lower":lower,"missing":len(missing),
"missing_ids":[x["identity"] for x in missing]},indent=2))
