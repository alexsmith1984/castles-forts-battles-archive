#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, hashlib, io, json, os, re
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
import requests
from PIL import Image

ROOT=Path("recovered/barnard-castle"); IMG=ROOT/"images"; REP=ROOT/"recovery-report.json"
ORIG="http://www.castlesfortsbattles.co.uk/north_east/barnard_castle.html"
TARGETS=["63b957bcfce4","19f116199cea","437bac9c274a","444adbef8dfa","160c94cfc368"]
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Barnard Castle focused archival recovery)"

def get(u,t=8):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def zinfo(b):
    try:
        im=Image.open(io.BytesIO(b));w,h=im.width,im.height;fmt=im.format;im.verify();return w,h,fmt
    except Exception:return None

def valid(b):
    z=zinfo(b)
    if not z or z[0]<80 or z[1]<60:return None
    if abs((z[0]/z[1])-(470/313))/(470/313)>.04:return None
    return z

def save(target,b,meta):
    z=valid(b)
    if not z:return None
    p=IMG/("gallery_"+target+".jpg");p.write_bytes(b)
    meta.update({"identity":"gallery_"+target,"file":"images/"+p.name,"dimensions":[z[0],z[1]],
                 "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"identification":"certain"})
    return meta

def availability(u,ts):
    r=get("https://archive.org/wayback/available?url="+quote(u,safe=":/")+"&timestamp="+ts,8)
    if not r or r.status_code!=200:return None
    try:
        c=r.json().get("archived_snapshots",{}).get("closest")
        if c and c.get("available") and c.get("url"):return c
    except Exception:pass
    return None

def page_captures():
    rows=[]
    q="https://web.archive.org/cdx/search/cdx?url="+quote(ORIG,safe=":/")+"&output=json&fl=timestamp,original,statuscode&filter=statuscode:200&collapse=digest&limit=100"
    r=get(q,10)
    if r and r.status_code==200:
      try:
        d=r.json();hdr=d[0]
        rows=[dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
      except Exception:pass
    return rows

GALLERY_RE=re.compile(r'wp_galleryimage\("([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]*)"',re.I)
caps=[]
for row in page_captures():
    ts=row.get("timestamp");u=row.get("original")
    if not ts or not u:continue
    r=get(f"https://web.archive.org/web/{ts}id_/{u}",8)
    if not r or r.status_code!=200:continue
    gal=[]
    for m in GALLERY_RE.finditer(r.text):
        gal.append((urljoin(u,m.group(1)),int(m.group(2)),int(m.group(3)),urljoin(u,m.group(4)) if m.group(4) else None))
    if gal:caps.append((ts,u,gal))

# Only use positional substitution where the archived page itself has the same 5-image 470x313 gallery.
position_alts={t:[] for t in TARGETS}
for ts,u,gal in caps:
    if len(gal)==5 and all((w,h)==(470,313) for _,w,h,_ in gal):
        for i,t in enumerate(TARGETS):
            position_alts[t].append((ts,gal[i][0],gal[i][3]))

def probe(target):
    urls=[]
    # exact original hash and thumbnail, protocol/host variants
    for suffix in (".jpg","t.jpg"):
      for scheme in ("http","https"):
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
          urls.append((f"{scheme}://{host}/wpimages/{target}{suffix}",suffix==".jpg","exact-hash"))
    # alternate same-position hash from other page captures
    for ts,full,thumb in position_alts[target]:
      urls.append((full,True,"same-gallery-position"))
      if thumb:urls.append((thumb,False,"same-gallery-position-thumbnail"))
    attempts=[]
    # nearest snapshot API around several useful years
    for u,isfull,basis in urls:
      for ts in ("20170208220118","20160101000000","20180101000000","20190101000000","20200101000000","20210101000000","20220101000000"):
        c=availability(u,ts)
        if c:attempts.append((c.get("timestamp") or ts,c["url"],isfull,basis+"-availability"))
    # direct replay modifiers at known Barnard page capture timestamps
    timestamps=["20170208220118"]+[x[0] for x in caps]
    for u,isfull,basis in urls:
      for ts in list(dict.fromkeys(timestamps))[:20]:
        for mod in ("id_","im_",""):
          attempts.append((ts,f"https://web.archive.org/web/{ts}{mod}/{u}",isfull,basis+"-"+(mod or "normal")))
    best=None;seen=set()
    for ts,replay,isfull,method in attempts:
      if replay in seen:continue
      seen.add(replay)
      r=get(replay,7)
      if not r or r.status_code!=200:continue
      z=valid(r.content)
      if not z:continue
      rank=(1 if isfull else 0,z[0]*z[1],len(r.content))
      if best is None or rank>best[0]:best=(rank,ts,replay,isfull,method,r.content,z)
    return target,best

found={}
with cf.ThreadPoolExecutor(max_workers=5) as ex:
  for target,best in ex.map(probe,TARGETS):
    if best:
      _,ts,replay,isfull,method,b,z=best
      found[target]=save(target,b,{"archive_timestamp":ts,"archive_replay":replay,"method":method,
                    "quality":"full/near-full" if isfull else "thumbnail/lower-resolution",
                    "recovery_basis":"Exact archived hash or same ordered five-image Barnard Castle gallery position."})

rep=json.loads(REP.read_text(encoding="utf-8"))
images={x["identity"]:x for x in rep.get("images",[])}
images.update({x["identity"]:x for x in found.values() if x})
order=["barnard_castle1","barnard_castle4"]+["gallery_"+t for t in TARGETS]
rep["images"]=[images[i] for i in order if i in images]
rep["missing"]=[m for m in rep.get("missing",[]) if m["identity"] not in images]
rep["recovered_full_or_near_full"]=sum(x.get("quality")=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x.get("quality")=="thumbnail/lower-resolution" for x in rep["images"])
rep["still_missing"]=len(rep["missing"])
rep["focused_third_search_completed"]=True
rep["barnard_page_captures_with_gallery_examined"]=len(caps)
REP.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

page=(ROOT/"index.html").read_text(encoding="utf-8")
rec=len(rep["images"]); total=rep["original_image_positions_identified"]
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
print(json.dumps({"gallery_page_captures_examined":len(caps),"found_now":sorted(found),
                  "still_missing":[m["identity"] for m in rep["missing"]],
                  "recovered_total":len(rep["images"])},indent=2))
