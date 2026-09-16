#!/usr/bin/env python3
import io,json,re,hashlib,time,gzip
from pathlib import Path
from urllib.parse import urlparse,urljoin,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

BASE=Path(".")
DEADLINE=time.monotonic()+540   # 9 minutes search; workflow hard stop is 12 minutes
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 FinalDeepCastleRecovery"

CFG={
 "almondbury":{
   "root":Path("recovered/castle-hill-almondbury"),
   "report":Path("recovered/castle-hill-almondbury/recovery-report.json"),
   "audit":Path("page-audit/castle-hill-almondbury.json"),
   "page_urls":[
     "http://www.castlesfortsbattles.co.uk/yorkshire/castle_hill_almondbury.html",
     "https://www.castlesfortsbattles.co.uk/yorkshire/castle_hill_almondbury.html",
     "http://castlesfortsbattles.co.uk/yorkshire/castle_hill_almondbury.html",
     "https://castlesfortsbattles.co.uk/yorkshire/castle_hill_almondbury.html",
     "http://www.castlesfortsbattles.co.uk/m/yorkshire/castle_hill_almondbury.html",
     "http://www.castlesfortsbattles.co.uk/m/castle_hill_almondbury.html"
   ],
   "families":["castle_hill_almondbury"],
   "dirs":["yorkshire/assets","yorkshire/images","assets","images","m/yorkshire/assets","m/yorkshire/images","m/assets","m/images","yorkshire/wpimages","wpimages"],
   "cc_patterns":[
     "www.castlesfortsbattles.co.uk/yorkshire/*castle_hill_almondbury*",
     "castlesfortsbattles.co.uk/yorkshire/*castle_hill_almondbury*"
   ]
 },
 "halton":{
   "root":Path("recovered/castle-hill-halton"),
   "report":Path("recovered/castle-hill-halton/recovery-report.json"),
   "audit":Path("page-audit/castle-hill-halton.json"),
   "page_urls":[
     "http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "http://castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "http://www.castlesfortsbattles.co.uk/m/north_west/halton_castle_motte.html",
     "http://www.castlesfortsbattles.co.uk/m/halton_castle_motte.html"
   ],
   "families":["halton_castle_motte","norman_castle_lune_valley_map"],
   "dirs":["north_west/assets","north_west/images","assets","images","m/north_west/assets","m/north_west/images","m/assets","m/images","north_west/wpimages","wpimages"],
   "cc_patterns":[
     "www.castlesfortsbattles.co.uk/north_west/*halton_castle_motte*",
     "castlesfortsbattles.co.uk/north_west/*halton_castle_motte*",
     "www.castlesfortsbattles.co.uk/north_west/*norman_castle_lune_valley_map*",
     "castlesfortsbattles.co.uk/north_west/*norman_castle_lune_valley_map*"
   ]
 }
}

def alive(): return time.monotonic()<DEADLINE
def get(u,t=8,params=None,headers=None):
    if not alive(): return None
    try:
        return S.get(u,params=params,headers=headers,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except Exception:
        return None

def imginfo(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        return z if z[0]>=60 and z[1]>=40 else None
    except Exception:return None

def stem(u):
    s=Path(urlparse(u).path).stem
    s=re.sub(r'(\d{2,4})x(\d{2,4})(?:\d+)?$','',s)
    return s

def identity_for(targets,u):
    st=stem(u).lower()
    for c in sorted(targets,key=len,reverse=True):
        lc=c.lower()
        if st==lc or re.fullmatch(re.escape(lc)+r'\d+x\d+(?:\d+)?',Path(urlparse(u).path).stem.lower()):
            return c
    # old case variants
    for c in sorted(targets,key=len,reverse=True):
        if st.replace("-","_")==c.lower().replace("-","_"): return c
    return None

def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+(?:\d+)?',Path(urlparse(u).path).stem.lower()))

def quality(c,u,z):
    p=urlparse(u).path.lower(); st=Path(p).stem.lower()
    if ("/assets/" in p or st==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=900:return "full/near-full"
    return "thumbnail/lower-resolution"

def score(c,u,z,q):
    p=urlparse(u).path.lower(); st=Path(p).stem.lower()
    return (5 if "/assets/" in p and not responsive(c,u) else
            4 if st==c.lower() and not responsive(c,u) else
            3 if q=="full/near-full" else 1, z[0]*z[1])

def cdx(pattern,limit=4000):
    r=get("https://web.archive.org/cdx/search/cdx",12,{
      "url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest",
      "filter":"statuscode:200","collapse":"digest","from":"2013","to":"2026","limit":str(limit)})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []

def replay_wayback(ts,u):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",6)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url
    return None

def timemap_wayback(u):
    r=get("https://web.archive.org/web/timemap/link/"+u,8)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/web/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out

def timemap_arquivo(u):
    r=get("https://arquivo.pt/wayback/timemap/link/"+u,7)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/wayback/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out

def replay_arquivo(ts,u):
    r=get(f"https://arquivo.pt/wayback/{ts}id_/{u}",6)
    if r and r.status_code==200:
        z=imginfo(r.content)
        if z:return r.content,z,r.url
    return None

def commoncrawl_indexes():
    r=get("https://index.commoncrawl.org/collinfo.json",8)
    if not r or r.status_code!=200:return []
    try:data=r.json()
    except:return []
    # one collection per year 2016-2023, closest to mid-year, max 8
    by={}
    for x in data:
        m=re.search(r'CC-MAIN-(20\d\d)-',x.get("id",""))
        if not m:continue
        y=int(m.group(1))
        if 2016<=y<=2023 and y not in by:by[y]=x["id"]
    return [by[y] for y in sorted(by)][:8]

def cc_query(index,pattern):
    r=get(f"https://index.commoncrawl.org/{index}-index",7,params={"url":pattern,"output":"json","filter":"status:200"})
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:out.append(json.loads(line))
        except:pass
    return out

def cc_payload(rec):
    fn=rec.get("filename"); off=rec.get("offset"); ln=rec.get("length")
    if not fn or off is None or ln is None:return None
    try:off=int(off);ln=int(ln)
    except:return None
    r=get("https://data.commoncrawl.org/"+fn,10,headers={"Range":f"bytes={off}-{off+ln-1}"})
    if not r or r.status_code not in (200,206):return None
    try:raw=gzip.decompress(r.content)
    except:
        raw=r.content
    # Strip WARC header then HTTP response header
    p=raw.find(b"\r\n\r\n")
    if p<0:return None
    payload=raw[p+4:]
    if payload.startswith(b"HTTP/"):
        p2=payload.find(b"\r\n\r\n")
        if p2>=0:payload=payload[p2+4:]
    z=imginfo(payload)
    if z:return payload,z,"commoncrawl:"+fn
    return None

def gather_page_captures(page_urls):
    rows=[]
    for p in page_urls:
        rows += cdx(p,500)
    seen=set();out=[]
    for x in rows:
        k=(x.get("timestamp"),x.get("original"))
        if not x.get("timestamp") or not x.get("original") or k in seen:continue
        seen.add(k);out.append((x["timestamp"],x["original"]))
    out.sort()
    if len(out)>40:
        idx={0,len(out)-1}
        for n in range(1,39):idx.add(round(n*(len(out)-1)/39))
        out=[out[i] for i in sorted(idx)]
    return out

def process(key,cfg):
    rep=json.loads(cfg["report"].read_text())
    targets=[x["identity"] for x in rep.get("missing",[])]
    # include lower-res identities for possible upgrades
    for x in rep.get("images",[]):
        if x.get("quality")!="full/near-full" and x["identity"] not in targets:targets.append(x["identity"])
    found={x["identity"]:x for x in rep.get("images",[])}
    oldmiss={x["identity"]:x for x in rep.get("missing",[])}
    candidates={t:list(oldmiss.get(t,{}).get("candidate_urls",[])) for t in targets}
    results={t:[] for t in targets}
    stats={"targets":targets,"page_captures":0,"wayback_family_rows":0,"arquivo_exact_hits":0,"commoncrawl_rows":0,"commoncrawl_images":0}

    # 1. BROAD Wayback filename-family sweep across old/root/mobile directories, case variants and wildcards.
    patterns=[]
    for fam in cfg["families"]:
        variants={fam,fam.upper(),fam.title(),fam.replace("_","-")}
        if fam=="halton_castle_motte":variants |= {"Halton_Castle_Motte","HALTON_CASTLE_MOTTE"}
        if fam=="norman_castle_lune_valley_map":variants |= {"Norman_Castle_Lune_Valley_Map"}
        for v in variants:
            for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
                for d in cfg["dirs"]:
                    patterns.append(f"{host}/{d}/{v}*")
    family_rows=[]
    with ThreadPoolExecutor(max_workers=18) as ex:
        fs=[ex.submit(cdx,p,2500) for p in patterns]
        for f in as_completed(fs):
            if not alive():break
            try:family_rows+=f.result()
            except:pass
    # Deduplicate and map
    seen=set();ded=[]
    for x in family_rows:
        k=(x.get("timestamp"),x.get("original"),x.get("digest"))
        if not x.get("timestamp") or not x.get("original") or k in seen:continue
        seen.add(k);ded.append(x)
    family_rows=ded;stats["wayback_family_rows"]=len(family_rows)
    for x in family_rows:
        c=identity_for(targets,x["original"])
        if c:
            candidates[c].append(x["original"])

    # Replay best family rows
    jobs={}
    with ThreadPoolExecutor(max_workers=20) as ex:
        by={t:[] for t in targets}
        for x in family_rows:
            c=identity_for(targets,x["original"])
            if c:by[c].append(x)
        for t,rr in by.items():
            rr=sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x["original"]).path.lower() else 1,
                                       1 if responsive(t,x["original"]) else 0,x["timestamp"]))
            if len(rr)>30:
                idx={0,len(rr)-1}
                for n in range(1,29):idx.add(round(n*(len(rr)-1)/29))
                rr=[rr[i] for i in sorted(idx)]
            for x in rr[:30]:
                jobs[ex.submit(replay_wayback,x["timestamp"],x["original"])]=(t,x)
        for f in as_completed(jobs):
            if not alive():break
            t,x=jobs[f]
            try:got=f.result()
            except:got=None
            if got:
                b,z,final=got;q=quality(t,x["original"],z)
                results[t].append((score(t,x["original"],z,q),b,z,x["original"],x["timestamp"],final,q,"wayback-deep-family"))

    # 2. Mine historical page captures for exact old source refs and page-position continuity.
    caps=gather_page_captures(cfg["page_urls"]);stats["page_captures"]=len(caps)
    historical={t:[] for t in targets}
    for ts,page in caps:
        if not alive():break
        r=get(f"https://web.archive.org/web/{ts}id_/{page}",7)
        if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
        soup=BeautifulSoup(r.text,"html.parser")
        refs=[]
        for e in soup.find_all(["a","img"]):
            vals=[]
            if e.name=="a":
                v=e.get("href")
                if v and re.search(r'\.(?:jpe?g|png)(?:\?|$)',v,re.I):vals.append(v)
            else:
                for a in ("data-orig-src","data-muse-src","data-src","src"):
                    v=e.get(a)
                    if v and re.search(r'\.(?:jpe?g|png)(?:\?|$)',v,re.I) and "blank.gif" not in v.lower():vals.append(v)
            for v in vals:refs.append(urljoin(page,v))
        for u in refs:
            c=identity_for(targets,u)
            if c: historical[c].append((ts,u))
        # Almondbury: direct slideshow order mapping is safe because names are same family.
        if key=="almondbury":
            imgs=[]
            for im in soup.find_all("img"):
                if "ImageInclude" not in (im.get("class") or []):continue
                v=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src") or im.get("src")
                if v:imgs.append(urljoin(page,v))
            gallery=rep.get("denominator_method",{}).get("gallery_identities",[])
            if len(imgs)>=len(gallery):
                for i,c in enumerate(gallery):
                    if c in historical:historical[c].append((ts,imgs[i]))
        # Halton: preserve exact old-name matches only. No speculative mapping of 3A/6 to newer identities.

    jobs={}
    with ThreadPoolExecutor(max_workers=18) as ex:
        for t,ls in historical.items():
            ss=set();ls=[x for x in ls if not (x in ss or ss.add(x))]
            for ts,u in ls[:40]:
                candidates[t].append(u)
                jobs[ex.submit(replay_wayback,ts,u)]=(t,ts,u)
        for f in as_completed(jobs):
            if not alive():break
            t,ts,u=jobs[f]
            try:got=f.result()
            except:got=None
            if got:
                b,z,final=got;q=quality(t,u,z)
                results[t].append((score(t,u,z,q),b,z,u,ts,final,q,"historical-page-cross-timestamp"))

    # 3. Exact TimeMap on all known candidate URLs in Wayback + Arquivo.
    def exact_probe(t,u):
        out=[]
        # Wayback
        wm=timemap_wayback(u)
        if wm:
            wm.sort()
            idx={0,len(wm)-1,len(wm)//2}
            if len(wm)>4:idx|={len(wm)//4,(3*len(wm))//4}
            for i in sorted(idx):
                ts,orig=wm[i];got=replay_wayback(ts,orig)
                if got:out.append(("wayback",ts,orig,got))
        # Arquivo
        am=timemap_arquivo(u)
        if am:
            am.sort()
            idx={0,len(am)-1,len(am)//2}
            if len(am)>4:idx|={len(am)//4,(3*len(am))//4}
            for i in sorted(idx):
                ts,orig=am[i];got=replay_arquivo(ts,orig)
                if got:out.append(("arquivo",ts,orig,got))
        return out
    jobs={}
    with ThreadPoolExecutor(max_workers=18) as ex:
        for t,urls in candidates.items():
            ss=set();urls=[u for u in urls if u and not (u in ss or ss.add(u))]
            candidates[t]=urls
            for u in urls[:70]:jobs[ex.submit(exact_probe,t,u)]=(t,u)
        for f in as_completed(jobs):
            if not alive():break
            t,u=jobs[f]
            try:outs=f.result()
            except:outs=[]
            for src,ts,orig,got in outs:
                b,z,final=got;q=quality(t,orig,z)
                results[t].append((score(t,orig,z,q),b,z,orig,ts,final,q,f"{src}-exact-timemap-deep"))
                if src=="arquivo":stats["arquivo_exact_hits"]+=1

    # 4. Small Common Crawl family scan: discover/recover only exact target filename identities.
    if alive():
        indexes=commoncrawl_indexes()
        ccrows=[]
        for idx in indexes:
            if not alive():break
            for pat in cfg["cc_patterns"]:
                if not alive():break
                ccrows += [(idx,x) for x in cc_query(idx,pat)]
        stats["commoncrawl_rows"]=len(ccrows)
        by={t:[] for t in targets}
        for idx,x in ccrows:
            u=x.get("url","")
            c=identity_for(targets,u)
            if c:by[c].append((idx,x))
        # only a few WARC records per target, favour non-responsive assets
        for t,ls in by.items():
            if not alive():break
            ls=sorted(ls,key=lambda ix:(0 if "/assets/" in urlparse(ix[1].get("url","")).path.lower() else 1,
                                        1 if responsive(t,ix[1].get("url","")) else 0))
            seen=set();count=0
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

    # Choose best new recovery/upgrade.
    imgdir=cfg["root"]/"images";imgdir.mkdir(exist_ok=True)
    recovered_now=[];upgraded_now=[]
    for t in targets:
        if not results[t]:continue
        best=max(results[t],key=lambda x:x[0])
        sc,b,z,u,ts,final,q,meth=best
        old=found.get(t)
        oldscore=(-1,0)
        if old:
            oz=old.get("dimensions",[0,0]);oq=old.get("quality","thumbnail/lower-resolution")
            oldscore=(3 if oq=="full/near-full" else 1,oz[0]*oz[1])
        if old and sc<=oldscore:continue
        ext=".png" if z[2]=="PNG" else ".jpg";p=imgdir/(t+ext);p.write_bytes(b)
        found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
          "archive_replay":final,"method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
          "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
        (upgraded_now if old else recovered_now).append(t)

    order=rep["desktop_image_identities"]
    images=[found[i] for i in order if i in found]
    missing=[oldmiss.get(i,{"identity":i,"candidate_urls":candidates.get(i,[])}) for i in order if i not in found]
    full=sum(x.get("quality")=="full/near-full" for x in images); lower=len(images)-full
    rep["images"]=images;rep["missing"]=missing
    rep["recovered_full_or_near_full"]=full;rep["recovered_thumbnail_or_lower_resolution"]=lower
    rep["still_missing"]=len(missing)
    rep["status"]="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"
    rep["final_deep_scan_2026_09_15"]={**stats,"recovered_now":recovered_now,"upgraded_now":upgraded_now,
      "note":"Final requested deep scan using broad Wayback families, historical page mining, Wayback/Arquivo exact TimeMaps, and bounded Common Crawl WARC retrieval."}
    cfg["report"].write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

    # Refresh public page figures/note.
    p=cfg["root"]/"index.html"; soup=BeautifulSoup(p.read_text(),"html.parser")
    h=soup.find("h2",string=lambda x:x and "Recovered original" in x)
    if h:
        for fig in list(h.find_all_next("figure")):fig.decompose()
        anchor=h
        for x in images:
            fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt=rep["name"]+" archived original image")
            a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
            cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x.get("quality")!="full/near-full" else "")
            fig.append(cap);anchor.insert_after(fig);anchor=fig
    note=soup.find("div",class_="note")
    if note:
        extra=" An unrelated embedded Whittington Castle gallery is excluded." if key=="halton" else ""
        note.string=f"Recovered from the archived CastlesFortsBattles page. {len(images)} of {len(order)} unique original content images have been recovered; {len(missing)} remain unavailable.{extra} No unrelated substitute photographs have been introduced."
    p.write_text(str(soup))

    audit=json.loads(cfg["audit"].read_text())
    audit.update({"status":rep["status"],"positions":len(order),"full":full,"lower":lower,"missing":len(missing),
      "missing_identities":[x["identity"] for x in missing]})
    cfg["audit"].write_text(json.dumps(audit,indent=2)+"\n")
    return {"status":rep["status"],"positions":len(order),"full":full,"lower":lower,"missing":len(missing),
      "recovered_now":recovered_now,"upgraded_now":upgraded_now,"missing_ids":[x["identity"] for x in missing],"stats":stats}

out={}
for key,cfg in CFG.items():
    if not alive():break
    out[key]=process(key,cfg)
print(json.dumps(out,indent=2))
