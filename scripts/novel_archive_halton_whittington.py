#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urlunparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

DEADLINE=time.monotonic()+540
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 NovelArchiveRecovery"

CFG={
 "halton":{
   "root":Path("recovered/castle-hill-halton"),
   "report":Path("recovered/castle-hill-halton/recovery-report.json"),
   "audit":Path("page-audit/castle-hill-halton.json"),
   "queries":["halton_castle_motte","halton castle motte","norman_castle_lune_valley_map"],
   "families":["halton_castle_motte","norman_castle_lune_valley_map"],
 },
 "whittington":{
   "root":Path("recovered/whittington-castle"),
   "report":Path("recovered/whittington-castle/recovery-report.json"),
   "audit":Path("page-audit/whittington-castle.json"),
   "queries":["whittington_castle_lancashire","whittington castle lancashire","norman_castle_lune_valley_map"],
   "families":["whittington_castle_lancashire","norman_castle_lune_valley_map"],
 }
}

def alive(): return time.monotonic()<DEADLINE
def get(u,t=8,params=None,headers=None):
    if not alive(): return None
    try:return S.get(u,params=params,headers=headers,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None
def imginfo(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        return z if z[0]>=60 and z[1]>=40 else None
    except:return None
def stem(u):
    s=Path(urlparse(u).path).stem
    s=re.sub(r'(\d{2,4})x(\d{2,4})(?:\d+)?$','',s)
    return s
def map_identity(order,u):
    st=stem(u).lower()
    for c in sorted(order,key=len,reverse=True):
        lc=c.lower()
        if st==lc:return c
        raw=Path(urlparse(u).path).stem.lower()
        if re.fullmatch(re.escape(lc)+r'\d+x\d+(?:\d+)?',raw): return c
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
            3 if q=="full/near-full" else 1,z[0]*z[1])

def replay_wayback(ts,u):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",6)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url
    return None
def replay_arquivo(ts,u):
    for mode in ("id_",""):
        r=get(f"https://arquivo.pt/wayback/{ts}{mode}/{u}",6)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url
    return None

def parse_cdx_response(r):
    if not r or r.status_code!=200:return []
    txt=r.text.strip()
    if not txt:return []
    try:
        j=r.json()
        if isinstance(j,list) and j and isinstance(j[0],list):
            h=j[0];return [dict(zip(h,row)) for row in j[1:]]
        if isinstance(j,list) and all(isinstance(x,dict) for x in j):return j
    except:pass
    out=[]
    for line in txt.splitlines():
        line=line.strip()
        if not line:continue
        # CDXJ: urlkey timestamp {json}
        m=re.match(r'\S+\s+(\d{14})\s+(\{.*\})$',line)
        if m:
            try:
                d=json.loads(m.group(2));d.setdefault("timestamp",m.group(1));out.append(d)
            except:pass
            continue
        parts=line.split()
        if len(parts)>=3 and re.fullmatch(r'\d{14}',parts[1]):
            out.append({"timestamp":parts[1],"original":parts[2]})
    return out

def arquivo_prefix(prefix):
    r=get("https://arquivo.pt/wayback/cdx",10,params={
        "url":prefix,"matchType":"prefix","output":"json",
        "filter":"statuscode:200","limit":"3000"
    })
    return parse_cdx_response(r)

def wayback_prefix(prefix):
    r=get("https://web.archive.org/cdx/search/cdx",10,params={
        "url":prefix,"matchType":"prefix","output":"json",
        "fl":"timestamp,original,statuscode,mimetype,digest",
        "filter":"statuscode:200","collapse":"digest","limit":"3000"
    })
    return parse_cdx_response(r)

def arquivo_image_search(q):
    r=get("https://arquivo.pt/imagesearch",10,params={
        "q":q,"siteSearch":"castlesfortsbattles.co.uk","maxItems":"200",
        "from":"2014","to":"2025","safeSearch":"off","prettyPrint":"false",
        "more":"imgSrc,imgTimestamp,pageURL,imgLinkToArchive,pageLinkToArchive,imgWidth,imgHeight,imgMimeType"
    })
    if not r or r.status_code!=200:return []
    try:
        j=r.json();return j.get("responseItems",[]) if isinstance(j,dict) else []
    except:return []

def arquivo_text_search(q):
    r=get("https://arquivo.pt/textsearch",10,params={
        "q":q,"siteSearch":"castlesfortsbattles.co.uk","maxItems":"100",
        "from":"2014","to":"2025","prettyPrint":"false"
    })
    if not r or r.status_code!=200:return []
    try:
        j=r.json();return j.get("responseItems",[]) if isinstance(j,dict) else []
    except:return []

def fetch_image_search_item(item):
    # Prefer archive replay URL if supplied.
    urls=[]
    for k in ("imgLinkToArchive","imgLink","imgSrc"):
        v=item.get(k)
        if v:urls.append(v)
    ts=str(item.get("imgTimestamp") or item.get("timestamp") or "")
    src=item.get("imgSrc") or ""
    if ts and src:
        urls += [f"https://arquivo.pt/wayback/{ts}id_/{src}",f"https://arquivo.pt/wayback/{ts}/{src}"]
    seen=set()
    for u in urls:
        if u in seen:continue
        seen.add(u)
        r=get(u,7)
        if r and r.status_code==200:
            z=imginfo(r.content)
            if z:return r.content,z,r.url,src or u,ts
    return None

def process(name,cfg):
    rep=json.loads(cfg["report"].read_text())
    order=rep["desktop_image_identities"]
    found={x["identity"]:x for x in rep.get("images",[])}
    targets=[i for i in order if i not in found]
    results={t:[] for t in targets}
    stats={"arquivo_image_results":0,"arquivo_image_matches":0,"arquivo_prefix_rows":0,
           "wayback_prefix_rows":0,"textsearch_pages":0,"textsearch_image_refs":0}

    # 1) Arquivo Image Search API — novel, independent image index.
    items=[]
    for q in cfg["queries"]:
        if not alive():break
        items+=arquivo_image_search(q)
    stats["arquivo_image_results"]=len(items)
    jobs={}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for item in items:
            src=item.get("imgSrc") or item.get("imageUrl") or item.get("url") or ""
            c=map_identity(targets,src)
            if not c:continue
            stats["arquivo_image_matches"]+=1
            jobs[ex.submit(fetch_image_search_item,item)]=(c,item,src)
        for f in as_completed(jobs):
            if not alive():break
            c,item,src=jobs[f]
            try:got=f.result()
            except:got=None
            if got:
                b,z,final,orig,ts=got;q=quality(c,orig or src,z)
                results[c].append((score(c,orig or src,z,q),b,z,orig or src,ts,final,q,"arquivo-image-search-api"))

    # 2) Prefix CDX in Arquivo and Wayback — no wildcard syntax.
    prefixes=[]
    for fam in cfg["families"]:
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
            for scheme in ("http","https"):
                for d in ("north_west/images","north_west/assets","images","assets","m/north_west/images","m/north_west/assets"):
                    prefixes.append(f"{scheme}://{host}/{d}/{fam}")
    ap_rows=[]; wb_rows=[]
    with ThreadPoolExecutor(max_workers=18) as ex:
        af=[ex.submit(arquivo_prefix,p) for p in prefixes]
        wf=[ex.submit(wayback_prefix,p) for p in prefixes]
        for f in as_completed(af):
            if not alive():break
            try:ap_rows+=f.result()
            except:pass
        for f in as_completed(wf):
            if not alive():break
            try:wb_rows+=f.result()
            except:pass
    # dedup
    def dedup(rows):
        out=[];seen=set()
        for x in rows:
            ts=str(x.get("timestamp") or x.get("ts") or "")
            u=x.get("original") or x.get("url") or x.get("uri") or ""
            if not ts or not u:continue
            k=(ts,u)
            if k in seen:continue
            seen.add(k);out.append((ts,u))
        return out
    ap=dedup(ap_rows);wb=dedup(wb_rows)
    stats["arquivo_prefix_rows"]=len(ap);stats["wayback_prefix_rows"]=len(wb)

    jobs={}
    with ThreadPoolExecutor(max_workers=18) as ex:
        by={t:[] for t in targets}
        for ts,u in ap:
            c=map_identity(targets,u)
            if c:by[c].append((ts,u,"arquivo"))
        for ts,u in wb:
            c=map_identity(targets,u)
            if c:by[c].append((ts,u,"wayback"))
        for t,ls in by.items():
            ls=sorted(ls,key=lambda x:(0 if "/assets/" in urlparse(x[1]).path.lower() else 1,
                                       1 if responsive(t,x[1]) else 0,x[0]))
            for ts,u,src in ls[:40]:
                fn=replay_arquivo if src=="arquivo" else replay_wayback
                jobs[ex.submit(fn,ts,u)]=(t,ts,u,src)
        for f in as_completed(jobs):
            if not alive():break
            t,ts,u,src=jobs[f]
            try:got=f.result()
            except:got=None
            if got:
                b,z,final=got;q=quality(t,u,z)
                results[t].append((score(t,u,z,q),b,z,u,ts,final,q,f"{src}-prefix-cdx"))

    # 3) Arquivo text-search cross-reference pages containing the exact filename families.
    pages=[]
    for q in cfg["families"]:
        if not alive():break
        pages+=arquivo_text_search(q)
    stats["textsearch_pages"]=len(pages)
    page_jobs={}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for item in pages:
            link=item.get("linkToArchive") or item.get("pageLinkToArchive") or ""
            if not link:continue
            page_jobs[ex.submit(get,link,7)]=item
        for f in as_completed(page_jobs):
            if not alive():break
            item=page_jobs[f]
            try:r=f.result()
            except:r=None
            if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
            soup=BeautifulSoup(r.text,"html.parser")
            base=item.get("originalURL") or item.get("url") or item.get("pageURL") or "http://www.castlesfortsbattles.co.uk/"
            for e in soup.find_all(["img","a"]):
                vals=[]
                if e.name=="img":
                    for a in ("data-orig-src","data-muse-src","data-src","src"):
                        v=e.get(a)
                        if v:vals.append(v)
                else:
                    v=e.get("href")
                    if v:vals.append(v)
                for v in vals:
                    if not re.search(r'\.(?:jpe?g|png)(?:\?|$)',v,re.I):continue
                    u=urljoin(base,v);c=map_identity(targets,u)
                    if not c:continue
                    stats["textsearch_image_refs"]+=1
                    # Use the image-search API around exact filename stem as the safest replay route.
                    for ii in arquivo_image_search(Path(urlparse(u).path).stem):
                        src=ii.get("imgSrc") or ""
                        if map_identity([c],src)==c:
                            got=fetch_image_search_item(ii)
                            if got:
                                b,z,final,orig,ts=got;q=quality(c,orig or src,z)
                                results[c].append((score(c,orig or src,z,q),b,z,orig or src,ts,final,q,"arquivo-textsearch-crossref"))

    # Select only authenticated exact-identity images.
    imgdir=cfg["root"]/"images";imgdir.mkdir(exist_ok=True)
    recovered=[]
    for t in targets:
        if not results[t]:continue
        _,b,z,u,ts,final,q,meth=max(results[t],key=lambda x:x[0])
        ext=".png" if z[2]=="PNG" else ".jpg";p=imgdir/(t+ext);p.write_bytes(b)
        found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
                  "archive_replay":final,"method":meth,"dimensions":[z[0],z[1]],"format":z[2],
                  "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
        recovered.append(t)

    images=[found[i] for i in order if i in found]
    missing=[{"identity":i,"candidate_urls":next((x.get("candidate_urls",[]) for x in rep.get("missing",[]) if x.get("identity")==i),[])}
             for i in order if i not in found]
    full=sum(x["quality"]=="full/near-full" for x in images);lower=len(images)-full
    rep["images"]=images;rep["missing"]=missing
    rep["recovered_full_or_near_full"]=full;rep["recovered_thumbnail_or_lower_resolution"]=lower
    rep["still_missing"]=len(missing)
    rep["status"]="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"
    rep["novel_archive_methods_2026_09_15"]={**stats,"recovered_now":recovered,
       "methods":["Arquivo Image Search API","Arquivo CDX matchType=prefix","Wayback CDX matchType=prefix","Arquivo text-search cross-reference mining"]}
    cfg["report"].write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

    # Refresh page
    p=cfg["root"]/"index.html";soup=BeautifulSoup(p.read_text(),"html.parser")
    h=soup.find("h2",string=lambda x:x and "Recovered original" in x)
    if h:
        for fig in list(h.find_all_next("figure")):fig.decompose()
        anchor=h
        for x in images:
            fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt=rep["name"]+" archived original image")
            a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
            cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x["quality"]!="full/near-full" else "")
            fig.append(cap);anchor.insert_after(fig);anchor=fig
    note=soup.find("div",class_="note")
    if note:
        extra=" An unrelated embedded Whittington Castle gallery is excluded." if name=="halton" else ""
        note.string=f"Recovered from the archived CastlesFortsBattles page. {len(images)} of {len(order)} unique original content images have been recovered; {len(missing)} remain unavailable.{extra} No unrelated substitute photographs have been introduced."
    p.write_text(str(soup))
    audit=json.loads(cfg["audit"].read_text())
    audit.update({"status":rep["status"],"positions":len(order),"full":full,"lower":lower,"missing":len(missing),
                  "missing_identities":[x["identity"] for x in missing]})
    cfg["audit"].write_text(json.dumps(audit,indent=2)+"\n")
    return {"status":rep["status"],"positions":len(order),"full":full,"lower":lower,"missing":len(missing),
            "recovered_now":recovered,"missing_ids":[x["identity"] for x in missing],"stats":stats}

out={}
for name,cfg in CFG.items():
    if not alive():break
    out[name]=process(name,cfg)
print(json.dumps(out,indent=2))
