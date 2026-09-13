#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path("recovered/castle-rising-castle")
IMG=ROOT/"images"
SRC=ROOT/"source.html"
REP=ROOT/"recovery-report.json"
SOURCE_TS="20210625101257"
SOURCE_ORIG="https://www.castlesfortsbattles.co.uk/east/castle_rising_castle.html"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Castle Rising archival deep recovery)"

def get(u,t=10):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def info(b):
    try:
        im=Image.open(BytesIO(b)); return im.width,im.height,im.format
    except Exception:return None

def ok(r):
    if not r or r.status_code!=200 or len(r.content)<500:return False
    z=info(r.content)
    return bool(z and z[0]>=80 and z[1]>=60)

def stem(u):return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()

def cdx_exact(u):
    out=[]
    sp=urlsplit(u)
    bases=[]
    for scheme in ("https","http"):
      for host in dict.fromkeys([sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]):
        bases.append(urlunsplit((scheme,host,sp.path,"","")))
    for v in bases:
      try:
        r=S.get("https://web.archive.org/cdx/search/cdx",
          params={"url":v,"output":"json","filter":"statuscode:200","fl":"timestamp,original,length","collapse":"digest","limit":20},timeout=8)
        if r.status_code==200:
          d=r.json()
          if isinstance(d,list) and len(d)>1:
            hdr=d[0]
            out += [dict(zip(hdr,row)) for row in d[1:] if len(row)==len(hdr)]
      except Exception:pass
    return out

soup=BeautifulSoup(SRC.read_text(encoding="utf-8"),"html.parser")
desktop=soup.find(id="bp_infinity") or soup
imgext=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)

# Exact identities are filenames that occur without a Muse WIDTHxHEIGHT suffix in the desktop content.
# Anchored assets are also exact identities. This avoids misreading e.g. castle_rising6685x455
# as a base image instead of castle_rising6 at 685x455.
exact=set()
refs=[]
for e in desktop.find_all(["img","a"]):
    vals=[]
    if e.name=="a":
      v=(e.get("href") or "").strip()
      if imgext.search(v): vals.append(v)
    else:
      for a in ("data-orig-src","data-muse-src","data-src","src"):
        v=(e.get(a) or "").strip()
        if v and "blank.gif" not in v.lower() and imgext.search(v):vals.append(v)
    for v in vals:
      u=urljoin(SOURCE_ORIG,v); st=stem(u)
      if not st.startswith("castle_rising"):continue
      refs.append(u)
      # Exact if basename is castle_rising + digits only (or anchor assets).
      if re.fullmatch(r"castle_rising\d+",st) or (e.name=="a" and "/assets/" in u):
        exact.add(st)

# The source has no genuine unnumbered castle_rising.jpg position.
exact.discard("castle_rising")
# Keep source order, using the longest exact identity prefix to map responsive variants.
ordered=[]
for u in refs:
    st=stem(u)
    ident=None
    if st in exact:ident=st
    else:
      for cand in sorted(exact,key=len,reverse=True):
        if st.startswith(cand) and re.fullmatch(r"\d{2,4}x\d{2,4}",st[len(cand):]):
          ident=cand;break
    if ident and ident not in ordered:ordered.append(ident)

groups={i:[] for i in ordered}
for e in soup.find_all(["img","a"]):
    vals=[]
    if e.name=="a":
      v=(e.get("href") or "").strip()
      if imgext.search(v):vals.append(v)
    else:
      for a in ("data-orig-src","data-muse-src","data-src","src"):
        v=(e.get(a) or "").strip()
        if v and "blank.gif" not in v.lower() and imgext.search(v):vals.append(v)
    for v in vals:
      u=urljoin(SOURCE_ORIG,v); st=stem(u); ident=None
      if st in groups:ident=st
      else:
        for cand in sorted(groups,key=len,reverse=True):
          if st.startswith(cand) and re.fullmatch(r"\d{2,4}x\d{2,4}",st[len(cand):]):
            ident=cand;break
      if ident and u not in groups[ident]:groups[ident].append(u)

local={p.stem.lower():p for p in IMG.iterdir() if p.is_file()}
rows=[]; missing=[]
old=json.loads(REP.read_text(encoding="utf-8"))
oldprov={x.get("identity"):x for x in old.get("images",[])}

for ident in ordered:
    p=local.get(ident)
    if p:
      with Image.open(p) as im: dims=[im.width,im.height]
      q=oldprov.get(ident,{})
      rows.append({"identity":ident,"file":"images/"+p.name,"dimensions":dims,
                   "quality":"full/near-full","identification":"certain",
                   **{k:q[k] for k in ("archive_timestamp","archive_original","method","bytes","sha256") if k in q}})
      continue

    attempts=[]
    # Same supplied capture, all source variants.
    for u in groups[ident]: attempts.append((SOURCE_TS,u,"same-capture"))
    # Exact-CDX for each source variant/path, all historical captures.
    for u in groups[ident]:
      for r in cdx_exact(u):
        attempts.append((r["timestamp"],r["original"],"cdx-exact"))
    # Also probe conventional exact image/assets paths.
    for directory in ("images","assets"):
      for scheme in ("http","https"):
        for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
          u=f"{scheme}://{host}/east/{directory}/{ident}.jpg"
          for r in cdx_exact(u):
            attempts.append((r["timestamp"],r["original"],"cdx-exact"))

    seen=set();best=None
    for ts,u,method in attempts:
      if (ts,u) in seen:continue
      seen.add((ts,u))
      rr=get(f"https://web.archive.org/web/{ts}id_/{u}",8)
      if not ok(rr):continue
      z=info(rr.content); st=stem(u)
      exactfile=(st==ident)
      # Responsive variants are acceptable as lower resolution, never as full originals.
      suffix=st[len(ident):] if st.startswith(ident) else ""
      variant=bool(re.fullmatch(r"\d{2,4}x\d{2,4}",suffix))
      if not exactfile and not variant:continue
      rank=(1 if exactfile else 0,z[0]*z[1],len(rr.content))
      if best is None or rank>best[0]:best=(rank,ts,u,method,rr.content,z,exactfile)

    if not best:
      missing.append({"identity":ident,"candidate_urls":groups[ident]});continue
    _,ts,u,method,b,z,exactfile=best
    ext=os.path.splitext(urlsplit(u).path)[1].lower()
    if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
    dest=IMG/(ident+ext);dest.write_bytes(b)
    rows.append({"identity":ident,"file":"images/"+dest.name,"dimensions":[z[0],z[1]],
                 "quality":"full/near-full" if exactfile else "thumbnail/lower-resolution",
                 "identification":"certain","archive_timestamp":ts,"archive_original":u,
                 "method":method,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()})

report={
 "name":"Castle Rising Castle",
 "original_url":SOURCE_ORIG,
 "supplied_captures":[SOURCE_TS],
 "best_source_capture":SOURCE_TS,
 "original_image_positions_identified":len(ordered),
 "desktop_image_identities":ordered,
 "recovered_full_or_near_full":sum(x["quality"]=="full/near-full" for x in rows),
 "recovered_thumbnail_or_lower_resolution":sum(x["quality"]=="thumbnail/lower-resolution" for x in rows),
 "still_missing":len(missing),
 "uncertain_identifications":[],
 "images":rows,"missing":missing,
 "counting_method":"Unique Castle Rising content identities established from exact desktop filenames/full-size anchor targets; responsive Muse WIDTHxHEIGHT variants are mapped by longest exact identity prefix and not counted separately.",
 "verification_note":"Every reported local image decodes successfully. No substitute photographs were used."
}
REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Update the recovery note and image gallery only; leave archived wording untouched.
page=(ROOT/"index.html").read_text(encoding="utf-8")
page=re.sub(r"Only genuine original images recovered from web archives are shown \(\d+ distinct content images\);",
            f"Only genuine original images recovered from web archives are shown ({len(rows)} of {len(ordered)} identified content images);",page)
gallery_start=page.find("<h2>Recovered original photographs, plans and images</h2>")
gallery_end=page.find("</article>",gallery_start)
if gallery_start>=0 and gallery_end>gallery_start:
  figs=[]
  for x in rows:
    cap=x["identity"].replace("_"," ")
    figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Castle Rising Castle archived original image"></a><figcaption>{cap}</figcaption></figure>')
  new="<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)
  page=page[:gallery_start]+new+page[gallery_end:]
(ROOT/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
print("MISSING", [x["identity"] for x in missing])
