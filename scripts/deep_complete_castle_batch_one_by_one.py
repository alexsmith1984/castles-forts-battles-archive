#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, os, re, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
import requests
from bs4 import BeautifulSoup
from PIL import Image

PAGES=[
 ("Bolingbroke Castle","bolingbroke-castle"),
 ("Conisbrough Castle","conisbrough-castle"),
 ("Pembroke Castle","pembroke-castle"),
 ("Kenilworth Castle","kenilworth-castle"),
 ("Goodrich Castle","goodrich-castle"),
 ("Fotheringhay Castle","fotheringhay-castle"),
 ("Framlingham Castle","framlingham-castle"),
 ("Pevensey Castle","pevensey-castle"),
 ("Pickering Castle","pickering-castle"),
 ("Pontefract Castle","pontefract-castle"),
 ("Richmond Castle","richmond-castle"),
 ("Sandal Castle","sandal-castle"),
 ("Warkworth Castle","warkworth-castle"),
 ("Whittington Castle","whittington-castle"),
]
ROOT=Path("recovered")
OUT=Path("page-audit/deep-complete");OUT.mkdir(parents=True,exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (CastlesFortsBattles deep archival recovery)"}
DIM=re.compile(r"\d{2,4}x\d{2,4}$")
IMGEXT=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)

def req(u,t=12,headers=None):
    h=dict(UA)
    if headers:h.update(headers)
    for n in range(3):
      try:
        r=requests.get(u,timeout=t,allow_redirects=True,headers=h)
        if r.status_code not in (429,500,502,503,504):return r
      except Exception:r=None
      time.sleep(.35*(n+1))
    return r

def info(b):
    try:
      im=Image.open(io.BytesIO(b));w,h=im.width,im.height;fmt=im.format;im.verify();return w,h,fmt
    except Exception:return None

def good(r):
    if not r or r.status_code!=200 or len(r.content)<500:return None
    z=info(r.content)
    return z if z and z[0]>=80 and z[1]>=60 else None

def stem(u):return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
def raw(ts,u):return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx(query,limit=1000):
    try:
      r=req("https://web.archive.org/cdx/search/cdx?url="+quote(query,safe=":/_*")+
            f"&output=json&fl=timestamp,original,length,mimetype,statuscode&filter=statuscode:200&collapse=digest&limit={limit}",15)
      if not r or r.status_code!=200:return []
      d=r.json()
      if not isinstance(d,list) or len(d)<2:return []
      hdr=d[0]
      return [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
    except Exception:return []

def variants(u):
    sp=urlsplit(u);hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    out=[]
    for scheme in ("http","https"):
      for host in dict.fromkeys(hosts):
        out.append(urlunsplit((scheme,host,sp.path,"","")))
    return out

def family(identity):
    # preserve descriptive stems such as warkworth_bridge, wakefield_1460 and norman_castle...
    m=re.match(r"^(.*?)(?:\d+[a-z]?|_plan|_layout)?$",identity,re.I)
    f=m.group(1).rstrip("_-") if m else identity
    # for numbered castle series, family should end in castle/bridge/etc rather than stripping meaningful words
    f=re.sub(r"(?:_)?\d+[a-z]?$","",identity,re.I).rstrip("_-")
    return f or identity

def extract_image_urls(html,base):
    soup=BeautifulSoup(html,"html.parser");out=[]
    for e in soup.find_all(["img","a"]):
      vals=[]
      if e.name=="img":
        for a in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
          v=(e.get(a) or "").strip()
          if v and not v.startswith("data:") and "blank.gif" not in v.lower() and IMGEXT.search(v):vals.append(v)
      else:
        v=(e.get("href") or "").strip()
        if IMGEXT.search(v):vals.append(v)
      for v in vals:
        u=urljoin(base,v)
        if u not in out:out.append(u)
    return out

def map_to_identity(st,identities):
    if st in identities:return st
    for i in sorted(identities,key=len,reverse=True):
      if st.startswith(i):
        suf=st[len(i):]
        if DIM.fullmatch(suf):return i
        if suf.startswith("-crop-u"):return i
    return None

def historical_candidates(rep,missing):
    orig=rep["original_url"]
    page_rows=[]
    for v in variants(orig):
      page_rows += cdx(v,80)
    # closest, newest, oldest mix, capped
    supplied=str(rep.get("supplied_capture",""))
    def closeness(x):
      try:return abs(int(x.get("timestamp","0"))-int(supplied or 0))
      except:return 10**20
    uniq={}
    for x in page_rows:
      if x.get("timestamp") and x.get("original"):uniq[(x["timestamp"],x["original"])]=x
    rows=list(uniq.values())
    rows_sorted=sorted(rows,key=closeness)[:10]+sorted(rows,key=lambda x:x["timestamp"])[:5]+sorted(rows,key=lambda x:x["timestamp"],reverse=True)[:8]
    seen=set();chosen=[]
    for x in rows_sorted:
      k=(x["timestamp"],x["original"])
      if k not in seen:seen.add(k);chosen.append(x)
    mapped={i:[] for i in missing}
    for x in chosen[:22]:
      r=req(raw(x["timestamp"],x["original"]),15)
      if not r or r.status_code!=200:continue
      for u in extract_image_urls(r.text,x["original"]):
        ident=map_to_identity(stem(u),missing)
        if ident and u not in mapped[ident]:mapped[ident].append(u)
    return mapped

def wildcard_candidates(rep,missing):
    orig=rep["original_url"];sp=urlsplit(orig)
    fams=sorted(set(family(i) for i in missing if family(i)))
    rows=[]
    for f in fams:
      for directory in ("images","assets"):
        for scheme in ("http","https"):
          for host in dict.fromkeys([sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]):
            pat=urlunsplit((scheme,host,os.path.dirname(sp.path)+f"/{directory}/{f}*","",""))
            rows += cdx(pat,1500)
    uniq={}
    for x in rows:
      if x.get("timestamp") and x.get("original"):uniq[(x["timestamp"],x["original"])]=x
    mapped={i:[] for i in missing}
    for x in uniq.values():
      ident=map_to_identity(stem(x["original"]),missing)
      if ident:mapped[ident].append(x)
    return mapped

def exact_rows(urls):
    rows=[]
    for u in urls:
      for v in variants(u):
        rows+=cdx(v,30)
    uniq={}
    for x in rows:
      if x.get("timestamp") and x.get("original"):uniq[(x["timestamp"],x["original"])]=x
    return list(uniq.values())

def recover_one(identity,base_urls,historical,wildrows,source_ts):
    attempts=[]
    # 1. supplied capture exact/source references
    for u in base_urls+historical:
      attempts.append((source_ts,u,"same-capture"))
    # 2. all exact CDX captures of known URLs
    erows=exact_rows((base_urls+historical)[:20])
    for x in erows:attempts.append((x["timestamp"],x["original"],"cdx-exact"))
    # 3. wildcard page-family captures, largest objects first
    wr=sorted(wildrows,key=lambda x:int(x.get("length") or 0),reverse=True)
    for x in wr[:35]:attempts.append((x["timestamp"],x["original"],"cdx-wildcard"))
    seen=set();best=None
    for ts,u,method in attempts:
      if not ts or not u or (ts,u) in seen:continue
      seen.add((ts,u))
      r=req(raw(ts,u),9);z=good(r)
      if not z:continue
      st=stem(u); exact=(st==identity)
      variant=st.startswith(identity) and (bool(DIM.fullmatch(st[len(identity):])) or st[len(identity):].startswith("-crop-u"))
      if not exact and not variant:continue
      rank=(1 if exact else 0,z[0]*z[1],len(r.content))
      if best is None or rank>best[0]:best=(rank,ts,u,method,r.content,z,exact)
    return best

def commoncrawl_for_remaining(rep,missing):
    # Conservative fallback: exact known original URLs across a small historical spread.
    if not missing:return {}
    r=req("https://index.commoncrawl.org/collinfo.json",15)
    if not r or r.status_code!=200:return {}
    try:indexes=r.json()
    except:return {}
    chosen=[]
    peryear={}
    for x in indexes:
      iid=x.get("id","");m=re.search(r"CC-MAIN-(\d{4})-",iid)
      if m and 2015<=int(m.group(1))<=2022:peryear.setdefault(int(m.group(1)),[]).append(iid)
    for y in sorted(peryear,reverse=True):chosen.extend(sorted(peryear[y],reverse=True)[:1])
    orig=rep["original_url"];sp=urlsplit(orig)
    out={}
    for ident in missing:
      urls=[]
      for directory in ("images","assets"):
        for ext in (".jpg",".jpeg",".png"):
          urls.append(urlunsplit((sp.scheme,sp.netloc,os.path.dirname(sp.path)+f"/{directory}/{ident}{ext}","","")))
      records=[]
      for iid in chosen:
        for u in urls:
          q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
          rr=req(q,6)
          if not rr or rr.status_code!=200:continue
          for line in rr.text.splitlines():
            try:
              x=json.loads(line)
              if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"):records.append(x)
            except:pass
      records=sorted(records,key=lambda x:int(x.get("length") or 0),reverse=True)[:12]
      for x in records:
        st=int(x["offset"]);ln=int(x["length"])
        rr=req("https://data.commoncrawl.org/"+x["filename"],14,headers={"Range":f"bytes={st}-{st+ln-1}"})
        if not rr or rr.status_code not in (200,206):continue
        payloads=[]
        try:
          rawb=gzip.decompress(rr.content);payloads=[rawb.split(b"\r\n\r\n")[-1]]
        except:pass
        for b in payloads:
          z=info(b)
          if z and z[0]>=80 and z[1]>=60:
            out[ident]=(b,z,x);break
        if ident in out:break
    return out

def rebuild_gallery(root,rep):
    page=root/"index.html";html=page.read_text(encoding="utf-8")
    recovered=rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]
    total=rep["original_image_positions_identified"]
    html=re.sub(r"\d+ of \d+ identified original content-image positions have been recovered",f"{recovered} of {total} identified original content-image positions have been recovered",html)
    if rep["still_missing"]==0:
      html=re.sub(r"; \d+ remain unavailable","",html)
    else:
      if re.search(r"; \d+ remain unavailable",html):
        html=re.sub(r"; \d+ remain unavailable",f"; {rep['still_missing']} remain unavailable",html)
    a=html.find("<h2>Recovered original photographs, plans and images</h2>");b=html.find("</article>",a)
    if a>=0 and b>a:
      figs=[]
      for x in rep["images"]:
        q="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
        label=x["identity"].replace("_"," ")+q
        figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="{rep["name"]} archived original image"></a><figcaption>{label}</figcaption></figure>')
      html=html[:a]+"<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)+html[b:]
    page.write_text(html,encoding="utf-8")

def deep_page(name,slug):
    root=ROOT/slug;rp=root/"recovery-report.json"
    rep=json.loads(rp.read_text(encoding="utf-8"))
    before=rep["still_missing"]
    if before==0:
      return {"name":name,"slug":slug,"before_missing":0,"after_missing":0,"status":"already-complete","recovered_now":[]}
    missing=[x["identity"] for x in rep.get("missing",[])]
    base={x["identity"]:x.get("candidate_urls",[]) for x in rep.get("missing",[])}
    hist=historical_candidates(rep,missing)
    wild=wildcard_candidates(rep,missing)
    recovered_now={}
    source_ts=str(rep.get("source_timestamp_used") or rep.get("supplied_capture"))
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
      futs={}
      for ident in missing:
        futs[ex.submit(recover_one,ident,base.get(ident,[]),hist.get(ident,[]),wild.get(ident,[]),source_ts)]=ident
      for fut in cf.as_completed(futs):
        ident=futs[fut]
        try:best=fut.result()
        except Exception:best=None
        if best:recovered_now[ident]=best
    # Common Crawl only for still missing after Wayback deep pass.
    remain=[i for i in missing if i not in recovered_now]
    cc=commoncrawl_for_remaining(rep,remain[:18]) if remain else {}
    images={x["identity"]:x for x in rep.get("images",[])}
    for ident,best in recovered_now.items():
      _,ts,u,method,b,z,exact=best
      ext=os.path.splitext(urlsplit(u).path)[1].lower()
      if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
      p=root/"images"/(ident+ext);p.write_bytes(b)
      images[ident]={"identity":ident,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
                     "method":method,"dimensions":[z[0],z[1]],"bytes":len(b),
                     "sha256":hashlib.sha256(b).hexdigest(),"quality":"full/near-full" if exact else "thumbnail/lower-resolution",
                     "identification":"certain"}
    for ident,(b,z,x) in cc.items():
      p=root/"images"/(ident+".jpg");p.write_bytes(b)
      images[ident]={"identity":ident,"file":"images/"+p.name,"method":"common-crawl","dimensions":[z[0],z[1]],
                     "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":"full/near-full",
                     "identification":"certain","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),"commoncrawl_warc":x.get("filename")}
    order=rep["desktop_image_identities"]
    rep["images"]=[images[i] for i in order if i in images]
    recovered_ids=set(images)
    rep["missing"]=[x for x in rep.get("missing",[]) if x["identity"] not in recovered_ids]
    rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
    rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]=="thumbnail/lower-resolution" for x in rep["images"])
    rep["still_missing"]=len(rep["missing"])
    rep["deep_recovery_attempted"]=True
    rep["deep_recovery_methods"]=["all page captures","Wayback exact CDX","Wayback family wildcard CDX","Common Crawl exact fallback"]
    rp.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    rebuild_gallery(root,rep)
    got=[i for i in missing if i in recovered_ids]
    return {"name":name,"slug":slug,"before_missing":before,"after_missing":rep["still_missing"],
            "status":"complete" if rep["still_missing"]==0 else ("improved" if len(got)>0 else "no-further-recovery"),
            "recovered_now":got,"still_missing":[x["identity"] for x in rep["missing"]]}

only=os.environ.get("ONLY_SLUG")
if only:
    name,slug=next((n,s) for n,s in PAGES if s==only)
    print("\n===== DEEP RECOVERY:",name,"=====",flush=True)
    try:r=deep_page(name,slug)
    except Exception as e:r={"name":name,"slug":slug,"status":"error","error":repr(e)}
    print(json.dumps(r,indent=2,ensure_ascii=False),flush=True)
    Path(f"page-audit/deep-complete/{slug}.json").write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    if r.get("status")=="error":raise SystemExit(1)
else:
    results=[]
    for name,slug in PAGES:
        print("\n===== DEEP RECOVERY:",name,"=====",flush=True)
        try:r=deep_page(name,slug)
        except Exception as e:r={"name":name,"slug":slug,"status":"error","error":repr(e)}
        results.append(r);print(json.dumps(r,indent=2,ensure_ascii=False),flush=True)
    Path("page-audit/deep-complete/castle-deep-recovery-one-by-one.json").write_text(json.dumps(results,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("\nFINAL SUMMARY")
    print(json.dumps(results,indent=2,ensure_ascii=False))
