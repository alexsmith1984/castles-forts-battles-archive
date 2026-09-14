#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import urlsplit, quote
import requests
from PIL import Image

ROOT=Path("recovered/barnard-castle");IMG=ROOT/"images";REP=ROOT/"recovery-report.json"
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 (Barnard Castle deep archive recovery)"

def get(u,t=10):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def info(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.width,im.height;fmt=im.format;im.verify();return w,h,fmt
    except Exception:return None

def good(r):
    if not r or r.status_code!=200 or len(r.content)<300:return None
    z=info(r.content)
    return z if z and z[0]>=80 and z[1]>=60 else None

def raw(ts,u):return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx_pattern(pattern,limit=1000):
    try:
        r=get("https://web.archive.org/cdx/search/cdx?url="+quote(pattern,safe=":/_*")+
              f"&output=json&fl=timestamp,original,length,mimetype,statuscode&filter=statuscode:200&collapse=digest&limit={limit}",12)
        if not r or r.status_code!=200:return []
        d=r.json()
        if not isinstance(d,list) or len(d)<2:return []
        hdr=d[0]
        return [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
    except Exception:return []

def deep_one(m):
    ident=m["identity"];full=m["original_url"];thumb=m.get("thumbnail_url")
    fullstem=os.path.splitext(os.path.basename(urlsplit(full).path))[0].lower()
    patterns=[]
    for u in [full,thumb]:
      if not u:continue
      sp=urlsplit(u);host=sp.netloc
      hosts=[host,host[4:] if host.startswith("www.") else "www."+host]
      for scheme in ("http","https"):
        for h in dict.fromkeys(hosts):
          patterns.append(f"{scheme}://{h}{sp.path}")
    # hash wildcard catches both full and thumbnail captures, plus any WebPlus derivative.
    sp=urlsplit(full)
    for scheme in ("http","https"):
      for h in dict.fromkeys([sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]):
        patterns.append(f"{scheme}://{h}{os.path.dirname(sp.path)}/{fullstem}*")
    rows=[]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
      for rr in ex.map(cdx_pattern,patterns):
        rows.extend(rr)
    uniq={}
    for x in rows:
      if x.get("timestamp") and x.get("original"):uniq[(x["timestamp"],x["original"])]=x
    cand=list(uniq.values())
    cand.sort(key=lambda x:int(x.get("length") or 0),reverse=True)
    best=None
    for x in cand[:80]:
      u=x["original"];st=os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
      isfull=(st==fullstem)
      isthumb=(st==fullstem+"t")
      if not isfull and not isthumb:continue
      r=get(raw(x["timestamp"],u),8);z=good(r)
      if not z:continue
      rank=(1 if isfull else 0,z[0]*z[1],len(r.content))
      if best is None or rank>best[0]:best=(rank,x,r.content,z,isfull)
    if not best:return ident,None
    _,x,b,z,isfull=best
    ext=os.path.splitext(urlsplit(x["original"]).path)[1].lower()
    if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
    p=IMG/(ident+ext);p.write_bytes(b)
    return ident,{"identity":ident,"file":"images/"+p.name,"archive_timestamp":x["timestamp"],
      "archive_original":x["original"],"method":"deep-wayback-hash-search","dimensions":[z[0],z[1]],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":"full/near-full" if isfull else "thumbnail/lower-resolution","identification":"certain"}

rep=json.loads(REP.read_text(encoding="utf-8"))
missing=rep.get("missing",[])
found={}
with cf.ThreadPoolExecutor(max_workers=5) as ex:
    futs=[ex.submit(deep_one,m) for m in missing]
    for fut in cf.as_completed(futs):
        ident,x=fut.result()
        if x:found[ident]=x

images={x["identity"]:x for x in rep.get("images",[])}
images.update(found)
order=["barnard_castle1","barnard_castle4","gallery_63b957bcfce4","gallery_19f116199cea","gallery_437bac9c274a","gallery_444adbef8dfa","gallery_160c94cfc368"]
rep["images"]=[images[i] for i in order if i in images]
rep["missing"]=[m for m in missing if m["identity"] not in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]=="thumbnail/lower-resolution" for x in rep["images"])
rep["still_missing"]=len(rep["missing"])
rep["deep_wayback_search_completed"]=True
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# rebuild only the gallery/status note
page=(ROOT/"index.html").read_text(encoding="utf-8")
rec=len(rep["images"]);total=rep["original_image_positions_identified"]
page=re.sub(r"\d+ of \d+ identified original content-image positions have been recovered",f"{rec} of {total} identified original content-image positions have been recovered",page)
page=re.sub(r"; \d+ remain unavailable",f"; {rep['still_missing']} remain unavailable" if rep["still_missing"] else "",page)
a=page.find("<h2>Recovered original photographs</h2>");b=page.find("</article>",a)
if a>=0 and b>a:
    figs=[]
    for x in rep["images"]:
      note="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
      label=x["identity"].replace("_"," ")+note
      figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Barnard Castle archived original image"></a><figcaption>{label}</figcaption></figure>')
    page=page[:a]+"<h2>Recovered original photographs</h2>"+"".join(figs)+page[b:]
(ROOT/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({"found_now":list(found),"still_missing":[x["identity"] for x in rep["missing"]],
 "full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"]},indent=2))
