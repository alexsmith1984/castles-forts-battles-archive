#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, gzip, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image

ORIG="http://www.castlesfortsbattles.co.uk/north_east/barnard_castle.html"
ROOT=Path("recovered/barnard-castle"); IMG=ROOT/"images"; REP=ROOT/"recovery-report.json"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Barnard Castle second deep recovery)"
HASHES=["63b957bcfce4","19f116199cea","437bac9c274a","444adbef8dfa","160c94cfc368"]

def get(u,t=10,headers=None):
    h={"User-Agent":"Mozilla/5.0 (Barnard Castle second deep recovery)"}
    if headers:h.update(headers)
    for n in range(2):
        try:
            r=requests.get(u,timeout=t,allow_redirects=True,headers=h)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception: r=None
    return r

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.width,im.height; fmt=im.format; im.verify()
        return w,h,fmt
    except Exception:return None

def good_bytes(b):
    z=info(b)
    return z if z and z[0]>=80 and z[1]>=60 else None

def raw(ts,u): return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx(pattern,limit=2000):
    try:
        u="https://web.archive.org/cdx/search/cdx?url="+quote(pattern,safe=":/_*")+
          f"&output=json&fl=timestamp,original,length,mimetype,statuscode,digest&filter=statuscode:200&collapse=digest&limit={limit}"
        r=get(u,15)
        if not r or r.status_code!=200:return []
        d=r.json()
        if not isinstance(d,list) or len(d)<2:return []
        hdr=d[0]
        return [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
    except Exception:return []

def save(ident,b,meta):
    z=good_bytes(b)
    if not z:return None
    ext=meta.get("ext") or ".jpg"
    p=IMG/(ident+ext); p.write_bytes(b)
    meta.update({"identity":ident,"file":"images/"+p.name,"dimensions":[z[0],z[1]],
                 "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"identification":"certain"})
    return meta

def extract_gallery(html,base):
    # Parse WebPlus gallery declarations preserving order.
    items=[]
    rx=re.compile(r'wp_galleryimage\("([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]*)"',re.I)
    for m in rx.finditer(html):
        full=urljoin(base,m.group(1)); thumb=urljoin(base,m.group(4)) if m.group(4) else None
        items.append({"full":full,"thumb":thumb,"w":int(m.group(2)),"h":int(m.group(3)),"stem":Path(urlsplit(full).path).stem.lower()})
    return items

# 1) Examine every archived Barnard page capture for alternate gallery hashes/order and direct Barnard_Castle*.jpg refs.
page_rows=[]
for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    page_rows += cdx(f"{scheme}://{host}/north_east/barnard_castle.html",300)
uniq={}
for x in page_rows:
    if x.get("timestamp") and x.get("original"): uniq[(x["timestamp"],x["original"])]=x
page_rows=sorted(uniq.values(),key=lambda x:x["timestamp"])
captures=[]
for x in page_rows:
    r=get(raw(x["timestamp"],x["original"]),12)
    if not r or r.status_code!=200 or "<html" not in r.text.lower(): continue
    gal=extract_gallery(r.text,x["original"])
    directs=sorted(set(re.findall(r'https?://[^"\'\s<>]+Barnard_Castle\d+\.jpg',r.text,re.I)))
    captures.append({"timestamp":x["timestamp"],"original":x["original"],"gallery":gal,"directs":directs})

# Map target 2017 gallery positions to alternate hashes by position when a capture has the same 5-image gallery geometry.
alt_by_target={h:[] for h in HASHES}
for cap in captures:
    gal=cap["gallery"]
    if len(gal)==5 and all((g["w"],g["h"])==(470,313) for g in gal):
        for idx,target in enumerate(HASHES):
            g=gal[idx]
            alt_by_target[target].append((cap["timestamp"],g["full"],g.get("thumb"),"same-gallery-position"))

# 2) Gather root Barnard_Castle*.jpg captures (maybe original gallery exports before hashing).
barnard_rows=[]
for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    barnard_rows += cdx(f"{scheme}://{host}/Barnard_Castle*.jpg",1000)
# retain for audit; not auto-map unless exact page capture links them.

# 3) Recover alternate-hash position equivalents from Wayback.
found={}
def recover_target(item):
    target,alts=item
    attempts=[]
    # exact target full + thumb, all protocols/hosts
    for suffix in (".jpg","t.jpg"):
      for scheme in ("http","https"):
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
          u=f"{scheme}://{host}/wpimages/{target}{suffix}"
          for row in cdx(u,100):
            attempts.append((row["timestamp"],row["original"],"wayback-exact-hash", suffix==".jpg"))
    # same gallery position in another Barnard page capture
    for ts,full,thumb,method in alts:
      attempts.append((ts,full,method,True))
      if thumb: attempts.append((ts,thumb,method+"-thumbnail",False))
      for u,isfull in ((full,True),(thumb,False)):
        if not u:continue
        for row in cdx(u,80):
          attempts.append((row["timestamp"],row["original"],"wayback-alt-hash",isfull))
    seen=set(); best=None
    for ts,u,method,isfull in attempts:
      if not u or (ts,u) in seen:continue
      seen.add((ts,u))
      r=get(raw(ts,u),9)
      if not r or r.status_code!=200:continue
      z=good_bytes(r.content)
      if not z:continue
      # position gallery images are declared 470x313; accept same aspect within 3%.
      if abs((z[0]/z[1])-(470/313))/(470/313)>.03:continue
      rank=(1 if isfull else 0,z[0]*z[1],len(r.content))
      if best is None or rank>best[0]: best=(rank,ts,u,method,isfull,r.content,z)
    return target,best

with cf.ThreadPoolExecutor(max_workers=5) as ex:
    for target,best in ex.map(recover_target,alt_by_target.items()):
        if best:
            _,ts,u,method,isfull,b,z=best
            meta={"archive_timestamp":ts,"archive_original":u,"method":method,
                  "quality":"full/near-full" if isfull else "thumbnail/lower-resolution","ext":".jpg",
                  "recovery_basis":"Same ordered five-image WebPlus Barnard Castle gallery position across archived Barnard Castle page captures."}
            found[target]=save("gallery_"+target,b,meta)

# 4) Common Crawl fallback for exact hashes.
try:
    cr=get("https://index.commoncrawl.org/collinfo.json",12)
    indexes=cr.json() if cr and cr.status_code==200 else []
except Exception:indexes=[]
chosen=[]
for x in indexes:
    iid=x.get("id",""); m=re.search(r"CC-MAIN-(\d{4})-",iid)
    if m and 2014<=int(m.group(1))<=2020: chosen.append(iid)
# one index per year
tmp={}
for iid in chosen:
    y=re.search(r"(\d{4})",iid).group(1); tmp.setdefault(y,iid)
chosen=list(tmp.values())

def cc_search(target):
    recs=[]
    for iid in chosen:
      for u in [f"http://www.castlesfortsbattles.co.uk/wpimages/{target}.jpg",
                f"http://www.castlesfortsbattles.co.uk/wpimages/{target}t.jpg",
                f"https://www.castlesfortsbattles.co.uk/wpimages/{target}.jpg",
                f"https://www.castlesfortsbattles.co.uk/wpimages/{target}t.jpg"]:
        q=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/")+"&output=json"
        r=get(q,7)
        if not r or r.status_code!=200:continue
        for line in r.text.splitlines():
          try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and x.get("filename") and x.get("offset") and x.get("length"): recs.append(x)
          except Exception:pass
    recs=sorted(recs,key=lambda x:int(x.get("length") or 0),reverse=True)[:12]
    for x in recs:
      st=int(x["offset"]); ln=int(x["length"])
      r=get("https://data.commoncrawl.org/"+x["filename"],14,headers={"Range":f"bytes={st}-{st+ln-1}"})
      if not r or r.status_code not in (200,206):continue
      try:
        rawb=gzip.decompress(r.content)
        payload=rawb.split(b"\r\n\r\n")[-1]
      except Exception:continue
      z=good_bytes(payload)
      if not z:continue
      if abs((z[0]/z[1])-(470/313))/(470/313)>.03:continue
      return target,payload,z,x
    return target,None,None,None

remaining=[h for h in HASHES if h not in found]
with cf.ThreadPoolExecutor(max_workers=5) as ex:
  for target,b,z,x in ex.map(cc_search,remaining):
    if b:
      found[target]=save("gallery_"+target,b,{"method":"common-crawl-exact-hash",
        "quality":"full/near-full","commoncrawl_url":x.get("url"),"commoncrawl_timestamp":x.get("timestamp"),
        "commoncrawl_warc":x.get("filename"),"ext":".jpg"})

# 5) Update report/page.
rep=json.loads(REP.read_text(encoding="utf-8"))
images={x["identity"]:x for x in rep.get("images",[])}
images.update({x["identity"]:x for x in found.values() if x})
order=["barnard_castle1","barnard_castle4"]+["gallery_"+h for h in HASHES]
rep["images"]=[images[i] for i in order if i in images]
rep["missing"]=[m for m in rep.get("missing",[]) if m["identity"] not in images]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")=="thumbnail/lower-resolution" for x in rep["images"])
rep["still_missing"]=len(rep["missing"])
rep["second_deep_search_completed"]=True
rep["second_deep_search_capture_count"]=len(captures)
rep["alternate_gallery_hashes_by_position"]={k:[{"timestamp":a,"full":b,"thumb":c} for a,b,c,_ in v] for k,v in alt_by_target.items()}
rep["barnard_castle_root_asset_candidates"]=[{"timestamp":x.get("timestamp"),"original":x.get("original"),"length":x.get("length")} for x in barnard_rows]
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

page=(ROOT/"index.html").read_text(encoding="utf-8")
rec=len(rep["images"]); total=rep["original_image_positions_identified"]
page=re.sub(r"\d+ of \d+ identified original content-image positions have been recovered",f"{rec} of {total} identified original content-image positions have been recovered",page)
page=re.sub(r"; \d+ remain unavailable",f"; {rep['still_missing']} remain unavailable" if rep["still_missing"] else "",page)
a=page.find("<h2>Recovered original photographs</h2>"); b=page.find("</article>",a)
if a>=0 and b>a:
    figs=[]
    for x in rep["images"]:
      note="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
      label=x["identity"].replace("_"," ")+note
      figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Barnard Castle archived original image"></a><figcaption>{label}</figcaption></figure>')
    page=page[:a]+"<h2>Recovered original photographs</h2>"+"".join(figs)+page[b:]
(ROOT/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({"captures_examined":len(captures),"found_now":sorted(found.keys()),
                  "still_missing":[m["identity"] for m in rep["missing"]],
                  "root_asset_candidates":len(barnard_rows)},indent=2))
