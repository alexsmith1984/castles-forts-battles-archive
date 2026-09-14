#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf
import hashlib, html as H, io, json, os, re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image
import ftfy

NAME="Castle Acre"
SLUG="castle-acre"
TS="20210918022557"
ORIG="http://www.castlesfortsbattles.co.uk/east/castle_acre.html"
BASE="http://www.castlesfortsbattles.co.uk/east/"
ROOT=Path("recovered")/SLUG
IMG=ROOT/"images"
IMG.mkdir(parents=True,exist_ok=True)
AUDIT=Path("page-audit")/SLUG
SOURCE=AUDIT/"source.html"
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archival recovery; Castle Acre)"

def item(identity, full, fallbacks, kind="photograph"):
    return {"identity":identity,"full":full,"fallbacks":fallbacks,"kind":kind}

CONTENT=[
    item("castle_acre", BASE+"assets/castle_acre.jpg", [BASE+"images/castle_acre.jpg"]),
    item("castle_acre2", BASE+"assets/castle_acre2.jpg", [BASE+"images/castle_acre2.jpg"]),
    item("castle_acre3", BASE+"assets/castle_acre3.jpg", [BASE+"images/castle_acre3.jpg"]),
    item("castle_acre4", BASE+"assets/castle_acre4.jpg", [BASE+"images/castle_acre4.jpg"]),
    item("castle_acre5", BASE+"assets/castle_acre5.jpg", [BASE+"images/castle_acre5.jpg"]),
    item("castle_acre6", BASE+"assets/castle_acre6.jpg", [BASE+"images/castle_acre6.jpg"]),
    item("castle_acre7", BASE+"assets/castle_acre7.jpg", [BASE+"images/castle_acre7.jpg"]),
    item("castle_acre8", BASE+"assets/castle_acre8.jpg", [BASE+"images/castle_acre8.jpg", BASE+"images/castle_acre8502x333.jpg"]),
    item("castle_acre9", BASE+"assets/castle_acre9.jpg", [BASE+"images/castle_acre9.jpg"]),
    item("castle_acre10", BASE+"assets/castle_acre10.jpg", [BASE+"images/castle_acre10.jpg"]),
    item("castle_acre11", BASE+"assets/castle_acre11.jpg", [BASE+"images/castle_acre11.jpg"]),
    item("castle_acre12", BASE+"assets/castle_acre12.jpg", [BASE+"images/castle_acre12.jpg"]),
    item("castle_acre13", BASE+"assets/castle_acre13.jpg", [BASE+"images/castle_acre13.jpg"]),
    item("castle_acre14", BASE+"assets/castle_acre14.jpg", [BASE+"images/castle_acre14.jpg"]),
    item("castle_acre15", BASE+"assets/castle_acre15.jpg", [BASE+"images/castle_acre15.jpg"]),
    item("castle_acre16", BASE+"assets/castle_acre16.jpg", [BASE+"images/castle_acre16.jpg"]),
    item("castle_acre_layout", BASE+"assets/castle_acre_layout.png", [BASE+"images/castle_acre_layout.jpg"], "plan"),
]

def get(u,t=12):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def raw(ts,u): return f"https://web.archive.org/web/{ts}id_/{u}"

def variants(u):
    sp=urlsplit(u)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    paths=[sp.path]
    ext=os.path.splitext(sp.path)[1]
    if ext.lower() in (".jpg",".jpeg"):
        root=sp.path[:-len(ext)]
        paths += [root+".jpg",root+".JPG",root+".jpeg",root+".JPEG"]
    out=[]
    for scheme in ("http","https"):
        for host in dict.fromkeys(hosts):
            for path in dict.fromkeys(paths):
                out.append(urlunsplit((scheme,host,path,"","")))
    return list(dict.fromkeys(out))

def iminfo(b):
    try:
        im=Image.open(io.BytesIO(b)); w,h=im.size; fmt=im.format; im.verify()
        return w,h,fmt
    except Exception:return None

def good(r):
    if not r or r.status_code!=200 or len(r.content)<300:return None
    z=iminfo(r.content)
    return z if z and z[0]>=40 and z[1]>=40 else None

def cdx_exact(u):
    rows=[]
    for v in variants(u):
        try:
            q=S.get("https://web.archive.org/cdx/search/cdx",params={
                "url":v,"output":"json","filter":"statuscode:200",
                "fl":"timestamp,original,length,mimetype,digest",
                "collapse":"digest","limit":100
            },timeout=12)
            if q.status_code==200:
                d=q.json()
                if isinstance(d,list) and len(d)>1:
                    hdr=d[0]
                    rows += [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
        except Exception:pass
    uniq={}
    for x in rows:
        if x.get("timestamp") and x.get("original"):
            uniq[(x["timestamp"],x["original"])]=x
    return list(uniq.values())

def save_image(ident,u,b,z,ts,method,quality):
    ext=os.path.splitext(urlsplit(u).path)[1].lower()
    if ext==".jpeg":ext=".jpg"
    if ext not in (".jpg",".png",".gif",".webp"):ext=".jpg"
    p=IMG/(ident+ext)
    p.write_bytes(b)
    return {
        "identity":ident,"file":"images/"+p.name,
        "archive_timestamp":ts,"archive_original":u,
        "method":method,"dimensions":[z[0],z[1]],"format":z[2],
        "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
        "quality":quality,"identification":"certain"
    }

def best_from_rows(rows, limit=50):
    rows.sort(key=lambda x:(int(x.get("length") or 0),x.get("timestamp","")),reverse=True)
    best=None
    for x in rows[:limit]:
        r=get(raw(x["timestamp"],x["original"]),8); z=good(r)
        if not z:continue
        rank=(z[0]*z[1],len(r.content))
        if best is None or rank>best[0]:best=(rank,x,r.content,z)
    return best

def recover(item):
    ident=item["identity"]; full=item["full"]
    for u in variants(full):
        r=get(raw(TS,u),8); z=good(r)
        if z:return save_image(ident,u,r.content,z,TS,"same-capture-full","full/near-full")
    best=best_from_rows(cdx_exact(full),50)
    if best:
        _,x,b,z=best
        return save_image(ident,x["original"],b,z,x["timestamp"],"cdx-exact-full","full/near-full")
    for fallback in item["fallbacks"]:
        for u in variants(fallback):
            r=get(raw(TS,u),8); z=good(r)
            if z:return save_image(ident,u,r.content,z,TS,"same-capture-display-fallback","thumbnail/lower-resolution")
        best=best_from_rows(cdx_exact(fallback),30)
        if best:
            _,x,b,z=best
            return save_image(ident,x["original"],b,z,x["timestamp"],"cdx-display-fallback","thumbnail/lower-resolution")
    return None

recovered={}
missing=[]
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(recover,x):x for x in CONTENT}
    for fut in cf.as_completed(futs):
        item_=futs[fut]
        try:x=fut.result()
        except Exception:x=None
        if x:recovered[item_["identity"]]=x
        else:missing.append({"identity":item_["identity"],"full_url":item_["full"],"fallback_urls":item_["fallbacks"]})

images=[recovered[x["identity"]] for x in CONTENT if x["identity"] in recovered]

if not SOURCE.exists():
    raise RuntimeError("Castle Acre inspection source.html is missing")
src=SOURCE.read_text(encoding="utf-8",errors="replace")
(ROOT/"source.html").write_text(src,encoding="utf-8")
soup=BeautifulSoup(src,"html.parser")

headings={"History","Gallery","Getting There","Bibliography","What's There?"}
skip_exact={"Home","UK Map","A-Z","Links","England","Scotland","Wales","About Us","Contact Us","Terms and Conditions","(c) Copyright 2019 CastlesFortsBattles.co.uk"}
blocks=[];seen=set()
for e in soup.find_all(["p","h1","h2","h3","h4","li"]):
    tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
    tx=re.sub(r"\s+([,.;:?!])",r"\1",tx)
    tx=re.sub(r"\s+"," ",tx).strip()
    key=tx.casefold()
    if not tx or key in seen or tx in skip_exact:continue
    seen.add(key)
    if tx in headings or tx=="CASTLE ACRE":blocks.append(("h2",tx))
    elif e.name=="li":blocks.append(("p","• "+tx))
    else:blocks.append(("p",tx))

body=[f"<{tag}>{H.escape(tx)}</{tag}>" for tag,tx in blocks]
figs=[]
for x in images:
    ident=x["identity"]
    if ident=="castle_acre":
        cap="Castle Acre — lead photograph"
    elif ident=="castle_acre_layout":
        cap="Castle Acre — layout plan"
    else:
        m=re.search(r"(\d+)$",ident)
        cap=f"Castle Acre {m.group(1)}" if m else "Castle Acre"
    if x["quality"]!="full/near-full":
        cap += " — lower-resolution archived recovery"
    figs.append(
        f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" '
        f'alt="Castle Acre archived original image"></a><figcaption>{H.escape(cap)}</figcaption></figure>'
    )

full_count=sum(x["quality"]=="full/near-full" for x in images)
low_count=sum(x["quality"]!="full/near-full" for x in images)
status="COMPLETE" if len(images)==len(CONTENT) else "PARTIAL"
note=(
    f"Reconstructed from the archived CastlesFortsBattles Castle Acre page. "
    f"{len(images)} of {len(CONTENT)} genuine original content-image identities are represented: "
    f"{full_count} full/near-full archived originals and {low_count} lower-resolution archived originals. "
    "Responsive Muse crops and thumbnails are not counted separately. No unrelated substitute images have been introduced."
)
page=ftfy.fix_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Castle Acre | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>Castle Acre</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered.</p>'}</article><p><a href="../../atoz-part1.html#c">Back to the C index</a></p></main></body></html>''')
(ROOT/"index.html").write_text(page,encoding="utf-8")

report={
 "name":NAME,"status":status,"original_url":ORIG,"supplied_capture":TS,
 "original_image_positions_identified":len(CONTENT),
 "recovered_full_or_near_full":full_count,
 "recovered_thumbnail_or_lower_resolution":low_count,
 "still_missing":len(missing),
 "images":images,
 "missing":sorted(missing,key=lambda x:x["identity"]),
 "full_size_source_unrecovered_but_position_represented":[x["identity"] for x in images if x["quality"]!="full/near-full"],
 "image_identity_basis":"Sixteen unique Castle Acre photographic identities (the unnumbered lead image plus castle_acre2 through castle_acre16) and one Castle Acre layout plan. Adobe Muse responsive crops, repeated display exports and 60x40 slideshow thumbnails are duplicate derivatives and are not counted as additional historic content images.",
 "searches_attempted":["supplied Wayback capture","exact assets full-size image URL","HTTP/HTTPS variants","www/non-www variants","filename extension/case variants","exact Wayback CDX history","same-image Muse display/crop fallback","exact CDX history for Muse display/crop fallback"],
 "verification_note":"Every displayed image is an archived original from the defunct site or an archived Muse export of the same underlying original. No unrelated substitute images were used."
}
(ROOT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

p=Path("atoz-part1.html")
s=p.read_text(encoding="utf-8")
pat=r'href="[^"]*castle_acre\.html"'
s2,n=re.subn(pat,'href="recovered/castle-acre/"',s,flags=re.I)
if n==0 and 'href="recovered/castle-acre/"' not in s:
    raise RuntimeError("Castle Acre A-Z entry not found")
p.write_text(s2,encoding="utf-8")
print(json.dumps(report,indent=2,ensure_ascii=False))
