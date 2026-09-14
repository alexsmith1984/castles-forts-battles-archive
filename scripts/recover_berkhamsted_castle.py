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

NAME="Berkhamsted Castle"
SLUG="berkhamsted-castle"
TS="20220826203529"
ORIG="http://www.castlesfortsbattles.co.uk/east/berkhamsted_castle.html"
ROOT=Path("recovered")/SLUG
IMG=ROOT/"images"
IMG.mkdir(parents=True,exist_ok=True)
AUDIT=Path("page-audit")/SLUG
SOURCE=AUDIT/"source.html"
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archival recovery; Berkhamsted Castle)"

CONTENT=[
 {"identity":"berkhamsted_castle5","full":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle5.JPG","fallback":"http://www.castlesfortsbattles.co.uk/wpimages/wp734492f9_05_06.jpg","kind":"principal"},
 {"identity":"berkhamsted_castle3","full":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle3.JPG","fallback":"http://www.castlesfortsbattles.co.uk/wpimages/wp83d787a1_05_06.jpg","kind":"principal"},
 {"identity":"berkhamsted_castle14","full":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle14.JPG","fallback":"http://www.castlesfortsbattles.co.uk/wpimages/wp9e5df471_05_06.jpg","kind":"principal"},
 {"identity":"berkhamsted_castle6","full":"http://www.castlesfortsbattles.co.uk/Berkhamsted_Castle6.JPG","fallback":"http://www.castlesfortsbattles.co.uk/wpimages/wpf5aee51a_05_06.jpg","kind":"principal"},
 {"identity":"gallery_1c563b6235e0","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/1c563b6235e0.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/1c563b6235e0t.jpg","kind":"gallery"},
 {"identity":"gallery_5697528b7cfc","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/5697528b7cfc.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/5697528b7cfct.jpg","kind":"gallery"},
 {"identity":"gallery_232291f8a2ce","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/232291f8a2ce.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/232291f8a2cet.jpg","kind":"gallery"},
 {"identity":"gallery_ee9d87824b02","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/ee9d87824b02.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/ee9d87824b02t.jpg","kind":"gallery"},
 {"identity":"gallery_71d26cb4d558","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/71d26cb4d558.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/71d26cb4d558t.jpg","kind":"gallery"},
 {"identity":"gallery_b3c35290128f","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/b3c35290128f.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/b3c35290128ft.jpg","kind":"gallery"},
 {"identity":"gallery_ebf86048229c","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/ebf86048229c.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/ebf86048229ct.jpg","kind":"gallery"},
 {"identity":"gallery_bbb915593e82","full":"http://www.castlesfortsbattles.co.uk/east/wpimages/bbb915593e82.jpg","fallback":"http://www.castlesfortsbattles.co.uk/east/wpimages/bbb915593e82t.jpg","kind":"gallery"},
]

def get(u,t=12):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def raw(ts,u): return f"https://web.archive.org/web/{ts}id_/{u}"

def variants(u):
    sp=urlsplit(u)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    paths=[sp.path]
    # Principal originals sometimes appear in Wayback with extension/case normalised.
    if re.search(r"\.JPG$",sp.path):
        paths += [sp.path[:-4]+".jpg",sp.path.lower()]
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
    if not r or r.status_code!=200 or len(r.content)<500:return None
    z=iminfo(r.content)
    return z if z and z[0]>=80 and z[1]>=60 else None

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

def recover(item):
    ident=item["identity"]; full=item["full"]; fallback=item["fallback"]
    # 1. Supplied snapshot exact/full URL variants.
    for u in variants(full):
        r=get(raw(TS,u),8); z=good(r)
        if z:return save_image(ident,u,r.content,z,TS,"same-capture-full","full/near-full")

    # 2. Exact Wayback CDX history for the intended full-size file.
    rows=cdx_exact(full)
    rows.sort(key=lambda x:(int(x.get("length") or 0),x.get("timestamp","")),reverse=True)
    best=None
    for x in rows[:40]:
        r=get(raw(x["timestamp"],x["original"]),8); z=good(r)
        if not z:continue
        rank=(z[0]*z[1],len(r.content))
        if best is None or rank>best[0]:best=(rank,x,r.content,z)
    if best:
        _,x,b,z=best
        return save_image(ident,x["original"],b,z,x["timestamp"],"cdx-exact-full","full/near-full")

    # 3. Archived display/thumbnail of the same underlying photograph.
    if fallback:
        # supplied capture first
        for u in variants(fallback):
            r=get(raw(TS,u),8); z=good(r)
            if z:return save_image(ident,u,r.content,z,TS,"same-capture-display-fallback","thumbnail/lower-resolution")
        # exact CDX fallback history
        rows=cdx_exact(fallback)
        rows.sort(key=lambda x:(int(x.get("length") or 0),x.get("timestamp","")),reverse=True)
        for x in rows[:20]:
            r=get(raw(x["timestamp"],x["original"]),8); z=good(r)
            if z:return save_image(ident,x["original"],r.content,z,x["timestamp"],"cdx-display-fallback","thumbnail/lower-resolution")
    return None

recovered={}
missing=[]
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(recover,item):item for item in CONTENT}
    for fut in cf.as_completed(futs):
        item=futs[fut]
        try:x=fut.result()
        except Exception:x=None
        if x:recovered[item["identity"]]=x
        else:missing.append({"identity":item["identity"],"full_url":item["full"],"fallback_url":item["fallback"]})

images=[recovered[item["identity"]] for item in CONTENT if item["identity"] in recovered]
if not SOURCE.exists():
    raise RuntimeError("Berkhamsted inspection source.html is missing")
src=SOURCE.read_text(encoding="utf-8",errors="replace")
(ROOT/"source.html").write_text(src,encoding="utf-8")
soup=BeautifulSoup(src,"html.parser")

headings={
 "GETTING THERE","WHAT IS THERE TO SEE?","ADDITIONAL NOTES",
 "HISTORY OF BERKHAMSTED CASTLE"
}
exclude={"VISIT OFFICIAL SITE (Opens in new window)"}
blocks=[];seen=set()
for e in soup.find_all(["p","h1","h2","h3","h4","li"]):
    tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
    tx=re.sub(r"\s+([,.;:?!])",r"\1",tx)
    tx=re.sub(r"\s+"," ",tx).strip()
    key=tx.casefold()
    if not tx or key in seen or tx in exclude or "Copyright 2016" in tx:continue
    # Suppress stray navigation/share strings if present.
    if tx in {"Home","UK Map","A-Z","England","Scotland","Wales","Articles","Links","About Us","Contact Us","Terms and Conditions"}:continue
    seen.add(key)
    if tx in headings:blocks.append(("h2",tx))
    elif tx=="BERKHAMSTED CASTLE, HP4 1HD":blocks.append(("h2",tx))
    elif e.name=="li":blocks.append(("p","• "+tx))
    else:blocks.append(("p",tx))

body=[]
for tag,tx in blocks:
    body.append(f"<{tag}>{H.escape(tx)}</{tag}>")

figs=[]
for x in images:
    ident=x["identity"]
    if ident.startswith("berkhamsted_castle"):
        num=re.search(r"(\d+)$",ident)
        cap=f"Berkhamsted Castle {num.group(1) if num else ''}".strip()
    else:
        cap="Berkhamsted Castle — archived gallery photograph"
    if x["quality"]!="full/near-full":
        cap += " — lower-resolution archived recovery"
    figs.append(
        f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" '
        f'alt="Berkhamsted Castle archived original photograph"></a><figcaption>{H.escape(cap)}</figcaption></figure>'
    )

full_count=sum(x["quality"]=="full/near-full" for x in images)
low_count=sum(x["quality"]!="full/near-full" for x in images)
status="COMPLETE" if len(images)==len(CONTENT) else "PARTIAL"
note=(
    f"Reconstructed from the archived CastlesFortsBattles Berkhamsted Castle page. "
    f"{len(images)} of {len(CONTENT)} genuine original content-image positions are represented: "
    f"{full_count} full/near-full archived originals and {low_count} lower-resolution archived originals. "
    "No unrelated substitute photographs have been introduced."
)

page=ftfy.fix_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Berkhamsted Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>Berkhamsted Castle</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original photographs</h2>{''.join(figs) if figs else '<p>No original image files could be recovered.</p>'}</article><p><a href="../../atoz-part1.html#b">Back to the B index</a></p></main></body></html>''')
(ROOT/"index.html").write_text(page,encoding="utf-8")

full_size_missing=[x["identity"] for x in images if x["quality"]!="full/near-full"]
report={
 "name":NAME,"status":status,"original_url":ORIG,"supplied_capture":TS,
 "original_image_positions_identified":len(CONTENT),
 "recovered_full_or_near_full":full_count,
 "recovered_thumbnail_or_lower_resolution":low_count,
 "still_missing":len(missing),
 "images":images,"missing":missing,
 "full_size_source_unrecovered_but_position_represented":full_size_missing,
 "image_identity_basis":"Four principal photographs explicitly linked from the page plus eight full-size WebPlus gallery photographs declared in wp_imgArray_pg_6. Their eight 100x100 thumbnails, WebPlus gallery controls, navigation/header graphics and share icons are not counted as separate content images.",
 "searches_attempted":["supplied Wayback capture","exact full-size image URL","HTTP/HTTPS variants","www/non-www variants","filename case/extension variants for principal originals","exact Wayback CDX history","same-image archived display/thumbnail fallback"],
 "verification_note":"Every displayed image is an archived original from the defunct site or an archived display export of the same underlying original photograph. No unrelated substitute photographs were used."
}
(ROOT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Update the Berkhamsted A-Z entry only.
p=Path("atoz-part1.html")
s=p.read_text(encoding="utf-8")
pat=r'href="[^"]*berkhamsted_castle\.html"'
s2,n=re.subn(pat,'href="recovered/berkhamsted-castle/"',s,flags=re.I)
if n==0 and 'href="recovered/berkhamsted-castle/"' not in s:
    raise RuntimeError("Berkhamsted Castle A-Z entry not found")
p.write_text(s2,encoding="utf-8")
print(json.dumps(report,indent=2,ensure_ascii=False))
