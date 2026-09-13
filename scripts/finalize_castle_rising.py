#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path("recovered/castle-rising-castle"); IMG=ROOT/"images"; SRC=ROOT/"source.html"; REP=ROOT/"recovery-report.json"
SOURCE_TS="20210625101257"
SOURCE_ORIG="https://www.castlesfortsbattles.co.uk/east/castle_rising_castle.html"
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (Castle Rising archival final audit)"

def get(u,t=8):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def info(b):
    try:
        im=Image.open(BytesIO(b)); return im.width,im.height,im.format
    except Exception:return None

def ok(r):
    if not r or r.status_code!=200 or len(r.content)<500:return False
    z=info(r.content); return bool(z and z[0]>=80 and z[1]>=60)

def stem(u): return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()

def cdx(pattern,limit=1500):
    q="https://web.archive.org/cdx/search/cdx?url="+quote(pattern,safe=":/_*")+"&output=json&fl=timestamp,original,length&filter=statuscode:200&collapse=digest&limit="+str(limit)
    r=get(q,10)
    if not r or r.status_code!=200:return []
    try:d=r.json()
    except Exception:return []
    if not isinstance(d,list) or len(d)<2:return []
    hdr=d[0]
    return [dict(zip(hdr,row)) for row in d[1:] if len(row)==len(hdr)]

soup=BeautifulSoup(SRC.read_text(encoding="utf-8"),"html.parser")
desktop=soup.find(id="bp_infinity") or soup
imgext=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)
dimre=re.compile(r"\d{2,4}x\d{2,4}$")

# Establish genuine identities only from exact desktop filenames and full-size asset links.
exact=set(); desktop_refs=[]
for e in desktop.find_all(["img","a"]):
    vals=[]
    if e.name=="a":
        v=(e.get("href") or "").strip()
        if imgext.search(v):vals.append(v)
    else:
        for a in ("data-orig-src","data-muse-src","data-src","src"):
            v=(e.get(a) or "").strip()
            if v and "blank.gif" not in v.lower() and imgext.search(v):vals.append(v)
    for v in vals:
        u=urljoin(SOURCE_ORIG,v); st=stem(u)
        if not st.startswith("castle_rising"):continue
        desktop_refs.append(u)
        if re.fullmatch(r"castle_rising\d+",st) or (e.name=="a" and "/assets/" in u):
            exact.add(st)
exact.discard("castle_rising")

# Preserve the order in which exact identities first occur. Map responsive names by longest exact prefix.
def identify(st):
    if st in exact:return st
    for cand in sorted(exact,key=len,reverse=True):
        if st.startswith(cand) and dimre.fullmatch(st[len(cand):]):return cand
    return None

ordered=[]
for u in desktop_refs:
    ident=identify(stem(u))
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
        u=urljoin(SOURCE_ORIG,v); ident=identify(stem(u))
        if ident in groups and u not in groups[ident]:groups[ident].append(u)

old=json.loads(REP.read_text(encoding="utf-8"))
oldprov={x.get("identity"):x for x in old.get("images",[])}
local={p.stem.lower():p for p in IMG.iterdir() if p.is_file()}
rows=[]; missing=[]

# Reuse already recovered exact files.
for ident in ordered:
    p=local.get(ident)
    if not p:
        missing.append(ident);continue
    with Image.open(p) as im:dims=[im.width,im.height]
    q=oldprov.get(ident,{})
    row={"identity":ident,"file":"images/"+p.name,"dimensions":dims,"quality":"full/near-full","identification":"certain"}
    for k in ("archive_timestamp","archive_original","method","bytes","sha256"):
        if k in q:row[k]=q[k]
    rows.append(row)

# First try all source-referenced variants at the supplied capture for genuinely missing identities.
newly={}
for ident in list(missing):
    best=None
    for u in groups[ident]:
        rr=get(f"https://web.archive.org/web/{SOURCE_TS}id_/{u}",7)
        if not ok(rr):continue
        z=info(rr.content); st=stem(u); exactfile=(st==ident)
        rank=(1 if exactfile else 0,z[0]*z[1],len(rr.content))
        if best is None or rank>best[0]:best=(rank,SOURCE_TS,u,"same-capture",rr.content,z,exactfile)
    if best:newly[ident]=best

# One small set of wildcard CDX searches, rather than many exact queries.
remaining=[i for i in missing if i not in newly]
archive_rows=[]
if remaining:
    for pat in (
      "http://www.castlesfortsbattles.co.uk/east/images/castle_rising*",
      "https://www.castlesfortsbattles.co.uk/east/images/castle_rising*",
      "http://www.castlesfortsbattles.co.uk/east/assets/castle_rising*",
      "https://www.castlesfortsbattles.co.uk/east/assets/castle_rising*",
    ):
        archive_rows.extend(cdx(pat))
    # Deduplicate and map rows using longest exact identity prefix.
    uniq={}
    for r in archive_rows:
        if r.get("timestamp") and r.get("original"):uniq[(r["timestamp"],r["original"])]=r
    archive_rows=list(uniq.values())
    mapped={i:[] for i in remaining}
    for r in archive_rows:
        ident=identify(stem(r["original"]))
        if ident in mapped:mapped[ident].append(r)
    for ident in remaining:
        cand=sorted(mapped[ident],key=lambda r:int(r.get("length") or 0),reverse=True)[:30]
        best=None
        for r in cand:
            u=r["original"];ts=r["timestamp"];rr=get(f"https://web.archive.org/web/{ts}id_/{u}",7)
            if not ok(rr):continue
            z=info(rr.content); st=stem(u); exactfile=(st==ident)
            rank=(1 if exactfile else 0,z[0]*z[1],len(rr.content))
            if best is None or rank>best[0]:best=(rank,ts,u,"cdx-wildcard",rr.content,z,exactfile)
        if best:newly[ident]=best

for ident,best in newly.items():
    _,ts,u,method,b,z,exactfile=best
    ext=os.path.splitext(urlsplit(u).path)[1].lower()
    if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
    dest=IMG/(ident+ext);dest.write_bytes(b)
    rows.append({"identity":ident,"file":"images/"+dest.name,"dimensions":[z[0],z[1]],
                 "quality":"full/near-full" if exactfile else "thumbnail/lower-resolution",
                 "identification":"certain","archive_timestamp":ts,"archive_original":u,
                 "method":method,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()})

rows.sort(key=lambda x:ordered.index(x["identity"]))
missing_list=[{"identity":i,"candidate_urls":groups[i]} for i in ordered if i not in {x["identity"] for x in rows}]

report={
 "name":"Castle Rising Castle","original_url":SOURCE_ORIG,"supplied_captures":[SOURCE_TS],
 "best_source_capture":SOURCE_TS,"original_image_positions_identified":len(ordered),
 "desktop_image_identities":ordered,
 "recovered_full_or_near_full":sum(x["quality"]=="full/near-full" for x in rows),
 "recovered_thumbnail_or_lower_resolution":sum(x["quality"]=="thumbnail/lower-resolution" for x in rows),
 "still_missing":len(missing_list),"uncertain_identifications":[],
 "images":rows,"missing":missing_list,
 "counting_method":"Unique Castle Rising content identities established from exact desktop filenames/full-size anchor targets; responsive Muse WIDTHxHEIGHT variants are mapped by longest exact identity prefix and not counted separately.",
 "verification_note":"Every reported local image decodes successfully. No substitute photographs were used."
}
REP.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

page=(ROOT/"index.html").read_text(encoding="utf-8")
page=re.sub(r"Only genuine original images recovered from web archives are shown \([^)]*\);",
            f"Only genuine original images recovered from web archives are shown ({len(rows)} of {len(ordered)} identified content images);",page)
a=page.find("<h2>Recovered original photographs, plans and images</h2>");b=page.find("</article>",a)
if a>=0 and b>a:
    figs=[]
    for x in rows:
        cap=x["identity"].replace("_"," ")
        figs.append(f'<figure><a href="{x["file"]}"><img src="{x["file"]}" alt="Castle Rising Castle archived original image"></a><figcaption>{cap}</figcaption></figure>')
    page=page[:a]+"<h2>Recovered original photographs, plans and images</h2>"+"".join(figs)+page[b:]
(ROOT/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
print("MISSING", [x["identity"] for x in missing_list])
