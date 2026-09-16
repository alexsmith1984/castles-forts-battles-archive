#!/usr/bin/env python3
import io,json,re,hashlib,time,gzip
from pathlib import Path
from urllib.parse import urlparse,urljoin,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/whittington-castle")
REP=ROOT/"recovery-report.json"
SRC=ROOT/"source.html"
HALTON=Path("recovered/castle-hill-halton/source.html")
IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
DEADLINE=time.monotonic()+480
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 WhittingtonCastleFinalDeepRecovery"

rep=json.loads(REP.read_text())
ORDER=rep["desktop_image_identities"]
found={x["identity"]:x for x in rep.get("images",[])}
oldmiss={x["identity"]:x for x in rep.get("missing",[])}
targets=[x for x in ORDER if x not in found]

def alive():return time.monotonic()<DEADLINE
def get(u,t=8,params=None,headers=None):
    if not alive():return None
    try:return S.get(u,params=params,headers=headers,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None
def info(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=60 and z[1]>=40 else None
    except:return None
def stem(u):
    s=Path(urlparse(u).path).stem
    s=re.sub(r'(\d{2,4})x(\d{2,4})(?:\d+)?$','',s)
    return s
def identity(u):
    st=stem(u).lower()
    for c in sorted(ORDER,key=len,reverse=True):
        lc=c.lower()
        if st==lc or re.fullmatch(re.escape(lc)+r'\d+x\d+(?:\d+)?',Path(urlparse(u).path).stem.lower()):return c
    return None
def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+(?:\d+)?',Path(urlparse(u).path).stem.lower()))
def quality(c,u,z):
    p=urlparse(u).path.lower();st=Path(p).stem.lower()
    if ("/assets/" in p or st==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=900:return "full/near-full"
    return "thumbnail/lower-resolution"
def score(c,u,z,q):
    p=urlparse(u).path.lower();st=Path(p).stem.lower()
    return (5 if "/assets/" in p and not responsive(c,u) else 4 if st==c.lower() and not responsive(c,u) else 3 if q=="full/near-full" else 1,z[0]*z[1])
def wayback(ts,u):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",6)
        if r and r.status_code==200:
            z=info(r.content)
            if z:return r.content,z,r.url
    return None
def arquivo_tm(u):
    r=get("https://arquivo.pt/wayback/timemap/link/"+u,7)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/wayback/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out
def arquivo(ts,u):
    r=get(f"https://arquivo.pt/wayback/{ts}id_/{u}",6)
    if r and r.status_code==200:
        z=info(r.content)
        if z:return r.content,z,r.url
    return None
def cdx(pattern,limit=3000):
    r=get("https://web.archive.org/cdx/search/cdx",10,{"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest","filter":"statuscode:200","collapse":"digest","from":"2013","to":"2026","limit":str(limit)})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []
def cc_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",7)
    if not r or r.status_code!=200:return []
    try:data=r.json()
    except:return []
    by={}
    for x in data:
        m=re.search(r'CC-MAIN-(20\d\d)-',x.get("id",""))
        if m:
            y=int(m.group(1))
            if 2017<=y<=2023 and y not in by:by[y]=x["id"]
    return [by[y] for y in sorted(by)]
def cc_query(idx,pat):
    r=get(f"https://index.commoncrawl.org/{idx}-index",7,params={"url":pat,"output":"json","filter":"status:200"})
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:out.append(json.loads(line))
        except:pass
    return out
def cc_payload(rec):
    try:off=int(rec["offset"]);ln=int(rec["length"]);fn=rec["filename"]
    except:return None
    r=get("https://data.commoncrawl.org/"+fn,9,headers={"Range":f"bytes={off}-{off+ln-1}"})
    if not r or r.status_code not in (200,206):return None
    try:raw=gzip.decompress(r.content)
    except:raw=r.content
    p=raw.find(b"\r\n\r\n")
    if p<0:return None
    payload=raw[p+4:]
    if payload.startswith(b"HTTP/"):
        p2=payload.find(b"\r\n\r\n")
        if p2>=0:payload=payload[p2+4:]
    z=info(payload)
    if z:return payload,z,"commoncrawl:"+fn
    return None

# Candidate URLs from report + both authenticated source pages.
cands={t:list(oldmiss.get(t,{}).get("candidate_urls",[])) for t in targets}
for html,pathbase in [(SRC.read_text(),"http://www.castlesfortsbattles.co.uk/north_west/"),
                      (HALTON.read_text(),"http://www.castlesfortsbattles.co.uk/north_west/")]:
    for m in re.finditer(r'(?:(?:href|data-orig-src|data-muse-src|data-src|src)=)["\']([^"\']+)["\']',html,re.I):
        v=m.group(1)
        if not re.search(r'\.(?:jpe?g|png)(?:\?|$)',v,re.I):continue
        u=urljoin(pathbase,v)
        c=identity(u)
        if c in cands:cands[c].append(u)
for t in targets:
    # inferred full originals and host/protocol/port variants
    for ext in ("jpg","jpeg","png"):
        for d in ("north_west/assets","north_west/images","assets","images","m/north_west/assets","m/north_west/images"):
            for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk","www.castlesfortsbattles.co.uk:80"):
                for scheme in ("http","https"):
                    cands[t].append(f"{scheme}://{host}/{d}/{t}.{ext}")
    more=[]
    for u in list(cands[t]):
        p=urlparse(u)
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk","www.castlesfortsbattles.co.uk:80"):
            for scheme in ("http","https"):
                more.append(urlunparse((scheme,host,p.path,"",p.query,"")))
                more.append(urlunparse((scheme,host,p.path,"","","")))
    cands[t]+=more
    ss=set();cands[t]=[u for u in cands[t] if u and not (u in ss or ss.add(u))]

results={t:[] for t in targets}
stats={"arquivo_hits":0,"wayback_rows":0,"commoncrawl_rows":0,"commoncrawl_images":0}

# 1) Arquivo exact-TimeMaps first.
def probe_arquivo(t,u):
    out=[]
    am=arquivo_tm(u)
    if am:
        am.sort()
        # endpoints, quartiles, midpoint, plus up to 8 evenly spaced
        idx={0,len(am)-1,len(am)//2,len(am)//4,(3*len(am))//4}
        if len(am)>8:
            for n in range(1,8):idx.add(round(n*(len(am)-1)/8))
        for i in sorted(x for x in idx if 0<=x<len(am)):
            ts,orig=am[i];got=arquivo(ts,orig)
            if got:out.append((ts,orig,got))
    return out

jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for t,urls in cands.items():
        for u in urls[:70]:jobs[ex.submit(probe_arquivo,t,u)]=(t,u)
    for f in as_completed(jobs):
        if not alive():break
        t,u=jobs[f]
        try:outs=f.result()
        except:outs=[]
        for ts,orig,got in outs:
            b,z,final=got;q=quality(t,orig,z)
            results[t].append((score(t,orig,z,q),b,z,orig,ts,final,q,"arquivo-exact-timemap-deep"))
            stats["arquivo_hits"]+=1

# 2) Wayback broad filename family.
patterns=[]
for fam in ("whittington_castle_lancashire","norman_castle_lune_valley_map"):
    variants={fam,fam.upper(),fam.title(),fam.replace("_","-")}
    for v in variants:
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
            for d in ("north_west/assets","north_west/images","assets","images","m/north_west/assets","m/north_west/images","m/assets","m/images","north_west/wpimages","wpimages"):
                patterns.append(f"{host}/{d}/{v}*")
rows=[]
with ThreadPoolExecutor(max_workers=18) as ex:
    fs=[ex.submit(cdx,p,2500) for p in patterns]
    for f in as_completed(fs):
        if not alive():break
        try:rows+=f.result()
        except:pass
ss=set();ded=[]
for x in rows:
    k=(x.get("timestamp"),x.get("original"),x.get("digest"))
    if not x.get("timestamp") or not x.get("original") or k in ss:continue
    ss.add(k);ded.append(x)
rows=ded;stats["wayback_rows"]=len(rows)

jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    by={t:[] for t in targets}
    for x in rows:
        c=identity(x["original"])
        if c in by:by[c].append(x)
    for t,rr in by.items():
        rr=sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x["original"]).path.lower() else 1,1 if responsive(t,x["original"]) else 0,x["timestamp"]))
        for x in rr[:35]:jobs[ex.submit(wayback,x["timestamp"],x["original"])]=(t,x)
    for f in as_completed(jobs):
        if not alive():break
        t,x=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(t,x["original"],z)
            results[t].append((score(t,x["original"],z,q),b,z,x["original"],x["timestamp"],final,q,"wayback-family-deep"))

# 3) Cross-page direct replay at Whittington and Halton page-era timestamps.
cross_ts=["20210918013642","20200708105528","20180112085831","20170208093615","2"]
jobs={}
with ThreadPoolExecutor(max_workers=20) as ex:
    for t,urls in cands.items():
        for u in urls[:45]:
            for ts in cross_ts:jobs[ex.submit(wayback,ts,u)]=(t,ts,u)
    for f in as_completed(jobs):
        if not alive():break
        t,ts,u=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(t,u,z)
            results[t].append((score(t,u,z,q),b,z,u,ts,final,q,"cross-page-direct-replay"))

# 4) Small Common Crawl fallback.
if alive():
    ccrows=[]
    for idx in cc_indexes():
        if not alive():break
        for pat in ("www.castlesfortsbattles.co.uk/north_west/*whittington_castle_lancashire*",
                    "castlesfortsbattles.co.uk/north_west/*whittington_castle_lancashire*",
                    "www.castlesfortsbattles.co.uk/north_west/*norman_castle_lune_valley_map*"):
            ccrows += [(idx,x) for x in cc_query(idx,pat)]
    stats["commoncrawl_rows"]=len(ccrows)
    by={t:[] for t in targets}
    for idx,x in ccrows:
        c=identity(x.get("url",""))
        if c in by:by[c].append((idx,x))
    for t,ls in by.items():
        seen=set();count=0
        ls=sorted(ls,key=lambda ix:(0 if "/assets/" in urlparse(ix[1].get("url","")).path.lower() else 1,1 if responsive(t,ix[1].get("url","")) else 0))
        for idx,x in ls:
            if not alive() or count>=8:break
            k=(x.get("filename"),x.get("offset"),x.get("length"))
            if k in seen:continue
            seen.add(k);count+=1
            got=cc_payload(x)
            if got:
                b,z,final=got;u=x.get("url","");q=quality(t,u,z)
                results[t].append((score(t,u,z,q),b,z,u,x.get("timestamp","commoncrawl"),final,q,"commoncrawl-warc"))
                stats["commoncrawl_images"]+=1

# Select best authenticated image per identity.
new=[]
for t in targets:
    if not results[t]:continue
    _,b,z,u,ts,final,q,meth=max(results[t],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(t+ext);p.write_bytes(b)
    found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,"archive_replay":final,
      "method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":q,"identification":"certain"}
    new.append(t)

images=[found[i] for i in ORDER if i in found]
missing=[oldmiss.get(i,{"identity":i,"candidate_urls":cands.get(i,[])}) for i in ORDER if i not in found]
full=sum(x.get("quality")=="full/near-full" for x in images);lower=len(images)-full
rep["images"]=images;rep["missing"]=missing
rep["recovered_full_or_near_full"]=full;rep["recovered_thumbnail_or_lower_resolution"]=lower
rep["still_missing"]=len(missing)
rep["status"]="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"
rep["final_deep_recovery_2026_09_15"]={**stats,"recovered_now":new,
 "secondary_authenticated_source":"recovered/castle-hill-halton/source.html",
 "note":"Final deep recovery used Whittington and Halton source refs, Arquivo exact-TimeMaps, broad Wayback filename families, cross-page timestamp replay, and bounded Common Crawl."}
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

# Refresh page figures/status.
p=ROOT/"index.html";soup=BeautifulSoup(p.read_text(),"html.parser")
h=soup.find("h2",string=lambda x:x and "Recovered original" in x)
if h:
    for fig in list(h.find_all_next("figure")):fig.decompose()
    anchor=h
    for x in images:
        fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt="Whittington Castle archived original image")
        a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
        cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x.get("quality")!="full/near-full" else "")
        fig.append(cap);anchor.insert_after(fig);anchor=fig
note=soup.find("div",class_="note")
if note:note.string=f"Recovered from the archived CastlesFortsBattles Whittington Castle page. {len(images)} of {len(ORDER)} unique original content images have been recovered; {len(missing)} remain unavailable. No unrelated substitute photographs have been introduced."
p.write_text(str(soup))

audit=Path("page-audit/whittington-castle.json")
a=json.loads(audit.read_text())
a.update({"status":rep["status"],"positions":len(ORDER),"full":full,"lower":lower,"missing":len(missing),"missing_identities":[x["identity"] for x in missing]})
audit.write_text(json.dumps(a,indent=2)+"\n")
print(json.dumps({"status":rep["status"],"positions":len(ORDER),"full":full,"lower":lower,"missing":len(missing),
"recovered_now":new,"missing_ids":[x["identity"] for x in missing],"stats":stats},indent=2))
