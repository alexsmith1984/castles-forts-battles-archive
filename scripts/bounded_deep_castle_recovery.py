#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf
import hashlib, io, json, os, re, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path("recovered")
AUD=Path("page-audit/bounded-deep"); AUD.mkdir(parents=True,exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (CastlesFortsBattles bounded deep recovery)"}
DIM=re.compile(r"\d{2,4}x\d{2,4}$")
IMGEXT=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)

def req(u,t=8):
    r=None
    for n in range(2):
        try:
            r=requests.get(u,timeout=t,allow_redirects=True,headers=UA)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception:
            r=None
        time.sleep(.25*(n+1))
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.width,im.height; fmt=im.format; im.verify()
        return w,h,fmt
    except Exception:
        return None

def good(r):
    if not r or r.status_code!=200 or len(r.content)<500: return None
    z=info(r.content)
    if not z or z[0]<80 or z[1]<60: return None
    return z

def stem(u):
    return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()

def raw(ts,u):
    return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx(pattern,limit=2000):
    url=("https://web.archive.org/cdx/search/cdx?url="+quote(pattern,safe=":/_*")+
         f"&output=json&fl=timestamp,original,length,mimetype,statuscode&filter=statuscode:200&collapse=digest&limit={limit}")
    r=req(url,10)
    if not r or r.status_code!=200: return []
    try: d=r.json()
    except Exception: return []
    if not isinstance(d,list) or len(d)<2: return []
    hdr=d[0]
    return [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]

def host_variants(orig):
    sp=urlsplit(orig)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    return list(dict.fromkeys(hosts))

def source_refs(html,base):
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for e in soup.find_all(["img","a"]):
        vals=[]
        if e.name=="img":
            for a in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
                v=(e.get(a) or "").strip()
                if v and not v.startswith("data:") and "blank.gif" not in v.lower() and IMGEXT.search(v):
                    vals.append(v)
        else:
            v=(e.get("href") or "").strip()
            if IMGEXT.search(v): vals.append(v)
        for v in vals:
            u=urljoin(base,v)
            if u not in out: out.append(u)
    return out

def matches(st,ident):
    if st==ident: return True
    if st.startswith(ident):
        suf=st[len(ident):]
        if DIM.fullmatch(suf) or suf.startswith("-crop-u"): return True
    # If report identity itself is a crop-export, accept the uncropped base.
    m=re.match(r"^(.*)-crop-u\d+$",ident,re.I)
    if m and st==m.group(1): return True
    return False

def identity_from_stem(st,missing):
    exact=[i for i in missing if st==i]
    if exact:return exact[0]
    candidates=[i for i in missing if matches(st,i)]
    if not candidates:return None
    return max(candidates,key=len)

def family(i):
    x=re.sub(r"-crop-u\d+$","",i,flags=re.I)
    # Keep descriptive names intact, but strip trailing simple numeric variant.
    x=re.sub(r"\d+[a-z]?$","",x,flags=re.I).rstrip("_-")
    return x or i

def page_capture_rows(rep):
    orig=rep["original_url"]; rows=[]
    for scheme in ("http","https"):
      for host in host_variants(orig):
        sp=urlsplit(orig); u=urlunsplit((scheme,host,sp.path,"",""))
        rows += cdx(u,100)
    uniq={}
    for x in rows:
        if x.get("timestamp") and x.get("original"):
            uniq[(x["timestamp"],x["original"])]=x
    rows=list(uniq.values())
    supplied=str(rep.get("supplied_capture") or rep.get("source_timestamp_used") or "")
    def score(x):
        try:return abs(int(x["timestamp"])-int(supplied))
        except:return 10**30
    # Diverse set: closest, earliest, latest. Maximum 18 page replays.
    chosen=sorted(rows,key=score)[:8]+sorted(rows,key=lambda x:x["timestamp"])[:5]+sorted(rows,key=lambda x:x["timestamp"],reverse=True)[:5]
    out=[];seen=set()
    for x in chosen:
        k=(x["timestamp"],x["original"])
        if k not in seen:seen.add(k);out.append(x)
    return out[:18]

def historical_source_candidates(rep,missing):
    mapped={i:[] for i in missing}
    rows=page_capture_rows(rep)
    for x in rows:
        r=req(raw(x["timestamp"],x["original"]),10)
        if not r or r.status_code!=200 or "<html" not in r.text.lower(): continue
        for u in source_refs(r.text,x["original"]):
            ident=identity_from_stem(stem(u),missing)
            if ident and u not in mapped[ident]: mapped[ident].append(u)
    return mapped

def wildcard_rows(rep,missing):
    orig=rep["original_url"]; sp=urlsplit(orig)
    fams=sorted(set(family(i) for i in missing))
    mapped={i:[] for i in missing}
    rows=[]
    for fam in fams:
        for scheme in ("http","https"):
          for host in host_variants(orig):
            for directory in ("images","assets"):
              pat=urlunsplit((scheme,host,os.path.dirname(sp.path)+f"/{directory}/{fam}*","",""))
              rows += cdx(pat,2000)
    uniq={}
    for x in rows:
        if x.get("timestamp") and x.get("original"):
            uniq[(x["timestamp"],x["original"])]=x
    for x in uniq.values():
        ident=identity_from_stem(stem(x["original"]),missing)
        if ident: mapped[ident].append(x)
    return mapped

def recover_identity(ident,baseurls,histurls,wrows,source_ts):
    attempts=[]
    for u in list(dict.fromkeys(baseurls+histurls))[:16]:
        attempts.append((source_ts,u,"source-capture"))
    # Wildcard rows already represent historical CDX captures; largest first, bounded.
    wr=sorted(wrows,key=lambda x:int(x.get("length") or 0),reverse=True)[:16]
    attempts += [(x["timestamp"],x["original"],"wayback-family") for x in wr]
    # Exact CDX only for at most four known URLs, bounded.
    for u in list(dict.fromkeys(baseurls+histurls))[:4]:
        for x in cdx(u,20)[:8]:
            attempts.append((x["timestamp"],x["original"],"wayback-exact"))
    seen=set();best=None
    for ts,u,method in attempts:
        if not ts or not u or (ts,u) in seen:continue
        seen.add((ts,u))
        r=req(raw(ts,u),7); z=good(r)
        if not z:continue
        st=stem(u)
        if not matches(st,ident):continue
        exact=(st==ident) or bool(re.match(r"^(.*)-crop-u\d+$",ident,re.I) and st==re.sub(r"-crop-u\d+$","",ident,flags=re.I))
        rank=(1 if exact else 0,z[0]*z[1],len(r.content))
        if best is None or rank>best[0]:
            best=(rank,ts,u,method,r.content,z,exact)
    return best

def rebuild(root,rep):
    page=root/"index.html"
    html=page.read_text(encoding="utf-8")
    recovered=rep["recovered_full_or_near_full"]+rep["recovered_thumbnail_or_lower_resolution"]
    total=rep["original_image_positions_identified"]
    html=re.sub(r"\d+ of \d+ identified original content-image positions have been recovered",f"{recovered} of {total} identified original content-image positions have been recovered",html)
    if rep["still_missing"]==0:
        html=re.sub(r"; \d+ remain unavailable","",html)
    elif re.search(r"; \d+ remain unavailable",html):
        html=re.sub(r"; \d+ remain unavailable",f"; {rep['still_missing']} remain unavailable",html)
    a=html.find("<h2>Recovered original photographs, plans and images</h2>")
    b=html.find("</article>",a)
    if a>=0 and b>a:
        figs=[]
        for x in rep["images"]:
            note="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
            label=x["identity"].replace("_"," ")+note
            figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="{rep["name"]} archived original image"></a><figcaption>{label}</figcaption></figure>')
        html=html[:a]+"<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)+html[b:]
    page.write_text(html,encoding="utf-8")

def run(slug):
    root=ROOT/slug; rp=root/"recovery-report.json"
    rep=json.loads(rp.read_text(encoding="utf-8"))
    before=rep["still_missing"]
    if before==0:
        result={"name":rep["name"],"slug":slug,"before_missing":0,"after_missing":0,"status":"already-complete","recovered_now":[]}
        (AUD/f"{slug}.json").write_text(json.dumps(result,indent=2)+"\n")
        return result
    missing=[x["identity"] for x in rep["missing"]]
    base={x["identity"]:x.get("candidate_urls",[]) for x in rep["missing"]}
    hist=historical_source_candidates(rep,missing)
    wild=wildcard_rows(rep,missing)
    source_ts=str(rep.get("source_timestamp_used") or rep.get("supplied_capture") or "")
    got={}
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs={ex.submit(recover_identity,i,base.get(i,[]),hist.get(i,[]),wild.get(i,[]),source_ts):i for i in missing}
        for fut in cf.as_completed(futs):
            i=futs[fut]
            try:b=fut.result()
            except Exception:b=None
            if b:got[i]=b
    images={x["identity"]:x for x in rep["images"]}
    for ident,best in got.items():
        _,ts,u,method,data,z,exact=best
        ext=os.path.splitext(urlsplit(u).path)[1].lower()
        if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
        p=root/"images"/(ident+ext); p.write_bytes(data)
        images[ident]={
          "identity":ident,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
          "method":method,"dimensions":[z[0],z[1]],"bytes":len(data),
          "sha256":hashlib.sha256(data).hexdigest(),
          "quality":"full/near-full" if exact else "thumbnail/lower-resolution",
          "identification":"certain"
        }
    order=rep["desktop_image_identities"]
    rep["images"]=[images[i] for i in order if i in images]
    recovered_ids=set(images)
    rep["missing"]=[x for x in rep["missing"] if x["identity"] not in recovered_ids]
    rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
    rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]=="thumbnail/lower-resolution" for x in rep["images"])
    rep["still_missing"]=len(rep["missing"])
    rep.setdefault("deep_recovery_history",[]).append({
      "method":"bounded historical captures + Wayback family/exact CDX",
      "recovered":[i for i in missing if i in recovered_ids],
      "remaining":[x["identity"] for x in rep["missing"]]
    })
    rp.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    rebuild(root,rep)
    result={
      "name":rep["name"],"slug":slug,"before_missing":before,"after_missing":rep["still_missing"],
      "status":"complete" if rep["still_missing"]==0 else ("improved" if got else "no-further-recovery"),
      "recovered_now":[i for i in missing if i in recovered_ids],
      "still_missing":[x["identity"] for x in rep["missing"]]
    }
    (AUD/f"{slug}.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return result

slug=os.environ["ONLY_SLUG"]
run(slug)
