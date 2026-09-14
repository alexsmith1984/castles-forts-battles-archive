#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, hashlib, html as H, io, json, os, re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image
import ftfy

TS="20170208220118"
ORIG="http://www.castlesfortsbattles.co.uk/north_east/barnard_castle.html"
ROOT=Path("recovered/barnard-castle"); IMG=ROOT/"images"; IMG.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/"source.html"
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 (Barnard Castle archival recovery)"

CONTENT=[
 ("barnard_castle1","http://www.castlesfortsbattles.co.uk/Barnard_Castle1.jpg",None),
 ("barnard_castle4","http://www.castlesfortsbattles.co.uk/Barnard_Castle4.jpg",None),
 ("gallery_63b957bcfce4","http://www.castlesfortsbattles.co.uk/wpimages/63b957bcfce4.jpg","http://www.castlesfortsbattles.co.uk/wpimages/63b957bcfce4t.jpg"),
 ("gallery_19f116199cea","http://www.castlesfortsbattles.co.uk/wpimages/19f116199cea.jpg","http://www.castlesfortsbattles.co.uk/wpimages/19f116199ceat.jpg"),
 ("gallery_437bac9c274a","http://www.castlesfortsbattles.co.uk/wpimages/437bac9c274a.jpg","http://www.castlesfortsbattles.co.uk/wpimages/437bac9c274at.jpg"),
 ("gallery_444adbef8dfa","http://www.castlesfortsbattles.co.uk/wpimages/444adbef8dfa.jpg","http://www.castlesfortsbattles.co.uk/wpimages/444adbef8dfat.jpg"),
 ("gallery_160c94cfc368","http://www.castlesfortsbattles.co.uk/wpimages/160c94cfc368.jpg","http://www.castlesfortsbattles.co.uk/wpimages/160c94cfc368t.jpg"),
]
THUMB_FALLBACK={
 "barnard_castle1":"http://www.castlesfortsbattles.co.uk/wpimages/wp4b7673d8_05_06.jpg",
 "barnard_castle4":"http://www.castlesfortsbattles.co.uk/wpimages/wp844ca2d6_05_06.jpg",
}

def get(u,t=15):
    try:return S.get(u,timeout=t,allow_redirects=True)
    except Exception:return None

def raw(ts,u):return f"https://web.archive.org/web/{ts}id_/{u}"

def iminfo(b):
    try:
      im=Image.open(io.BytesIO(b));w,h=im.width,im.height;fmt=im.format;im.verify();return w,h,fmt
    except Exception:return None

def good(r):
    if not r or r.status_code!=200 or len(r.content)<500:return None
    z=iminfo(r.content)
    return z if z and z[0]>=80 and z[1]>=60 else None

def variants(u):
    sp=urlsplit(u);hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    out=[]
    for scheme in ("http","https"):
      for host in dict.fromkeys(hosts):
        out.append(urlunsplit((scheme,host,sp.path,"","")))
    return out

def cdx(u):
    out=[]
    for v in variants(u):
      try:
        r=S.get("https://web.archive.org/cdx/search/cdx",params={
          "url":v,"output":"json","filter":"statuscode:200","fl":"timestamp,original,length,mimetype",
          "collapse":"digest","limit":100
        },timeout=10)
        if r.status_code==200:
          d=r.json()
          if isinstance(d,list) and len(d)>1:
            hdr=d[0];out += [dict(zip(hdr,x)) for x in d[1:] if len(x)==len(hdr)]
      except Exception:pass
    uniq={}
    for x in out:
      if x.get("timestamp") and x.get("original"):uniq[(x["timestamp"],x["original"])]=x
    return list(uniq.values())

def recover(ident,full,thumb):
    # Fast path: try the supplied page timestamp first.
    same=[]
    for u in variants(full):
      r=get(raw(TS,u),8);z=good(r)
      if z:same.append((z[0]*z[1],u,r.content,z))
    if same:
      same.sort(key=lambda x:(x[0],len(x[2])),reverse=True)
      _,u,b,z=same[0]
      ext=os.path.splitext(urlsplit(u).path)[1].lower()
      if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
      p=IMG/(ident+ext);p.write_bytes(b)
      return {"identity":ident,"file":"images/"+p.name,"archive_timestamp":TS,"archive_original":u,
              "method":"same-capture","dimensions":[z[0],z[1]],"bytes":len(b),
              "sha256":hashlib.sha256(b).hexdigest(),"quality":"full/near-full","identification":"certain"}

    # Slow path only for a genuinely missing full-size original.
    rows=cdx(full)
    rows.sort(key=lambda x:(int(x.get("length") or 0),x.get("timestamp","")),reverse=True)
    best=None
    for x in rows:
      r=get(raw(x["timestamp"],x["original"]),8);z=good(r)
      if not z:continue
      rank=(z[0]*z[1],len(r.content))
      if best is None or rank>best[0]:best=(rank,x,r.content,z)
    if best:
      _,x,b,z=best
      ext=os.path.splitext(urlsplit(x["original"]).path)[1].lower()
      if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
      p=IMG/(ident+ext);p.write_bytes(b)
      return {"identity":ident,"file":"images/"+p.name,"archive_timestamp":x["timestamp"],"archive_original":x["original"],
              "method":"cdx-exact","dimensions":[z[0],z[1]],"bytes":len(b),
              "sha256":hashlib.sha256(b).hexdigest(),"quality":"full/near-full","identification":"certain"}

    # Last resort: an archived on-page thumbnail of the same photograph.
    fallback=thumb or THUMB_FALLBACK.get(ident)
    if fallback:
      for u in variants(fallback):
        r=get(raw(TS,u),8);z=good(r)
        if z:
          ext=os.path.splitext(urlsplit(u).path)[1].lower()
          if ext not in (".jpg",".jpeg",".png",".gif",".webp"):ext=".jpg"
          p=IMG/(ident+ext);p.write_bytes(r.content)
          return {"identity":ident,"file":"images/"+p.name,"archive_timestamp":TS,"archive_original":u,
                  "method":"same-capture-thumbnail","dimensions":[z[0],z[1]],"bytes":len(r.content),
                  "sha256":hashlib.sha256(r.content).hexdigest(),"quality":"thumbnail/lower-resolution","identification":"certain"}
    return None

images=[];missing=[]
with cf.ThreadPoolExecutor(max_workers=7) as ex:
    futs={ex.submit(recover,ident,full,thumb):(ident,full,thumb) for ident,full,thumb in CONTENT}
    recovered={}
    for fut in cf.as_completed(futs):
        ident,full,thumb=futs[fut]
        try:x=fut.result()
        except Exception:x=None
        if x:recovered[ident]=x
        else:missing.append({"identity":ident,"original_url":full,"thumbnail_url":thumb or THUMB_FALLBACK.get(ident)})
images=[recovered[i] for i,_,_ in CONTENT if i in recovered]

html=SOURCE.read_text(encoding="utf-8",errors="replace")
soup=BeautifulSoup(html,"html.parser")
# Extract source-authored content only, excluding navigation/footer.
nav={"Home","UK Map","A-Z","England","Scotland","Wales","Articles","Links","About Us","Contact Us","Terms and Conditions"}
blocks=[];seen=set()
for e in soup.find_all(["h1","h2","h3","h4","p","li"]):
    tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
    key=re.sub(r"\s+"," ",tx).casefold()
    if not tx or tx in nav or "Copyright 2016" in tx or key in seen:continue
    if tx in ("VISIT OFFICIAL SITE (Opens in new window)",):continue
    seen.add(key);blocks.append((e.name,tx))

body=[]
headish=re.compile(r"^(GETTING THERE|WHAT IS THERE TO SEE\?|ADDITIONAL NOTES|HISTORY OF BARNARD CASTLE)$",re.I)
for tag,tx in blocks:
    if tag.startswith("h") or headish.match(tx):body.append(f"<h2>{H.escape(tx)}</h2>")
    elif tag=="li":body.append(f"<p>• {H.escape(tx)}</p>")
    else:body.append(f"<p>{H.escape(tx)}</p>")

figs=[]
for x in images:
    note="" if x["quality"]=="full/near-full" else " — lower-resolution archived recovery"
    figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="Barnard Castle archived original image"></a><figcaption>{H.escape(x["identity"].replace("_"," ")+note)}</figcaption></figure>')

note=f"Recovered from the archived CastlesFortsBattles Barnard Castle page. {len(images)} of {len(CONTENT)} identified original content-image positions have been recovered"
if missing:note+=f"; {len(missing)} remain unavailable"
note+=". No unrelated substitute photographs have been introduced."

page=ftfy.fix_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Barnard Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>Barnard Castle</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original photographs</h2>{''.join(figs) if figs else '<p>No original image files could be recovered.</p>'}</article><p><a href="../../atoz-part1.html#b">Back to the B index</a></p></main></body></html>''')
(ROOT/"index.html").write_text(page,encoding="utf-8")

report={"name":"Barnard Castle","original_url":ORIG,"supplied_capture":TS,
 "original_image_positions_identified":len(CONTENT),
 "recovered_full_or_near_full":sum(x["quality"]=="full/near-full" for x in images),
 "recovered_thumbnail_or_lower_resolution":sum(x["quality"]=="thumbnail/lower-resolution" for x in images),
 "still_missing":len(missing),"images":images,"missing":missing,
 "image_identity_basis":"Two full-size image links embedded in the page plus five WebPlus gallery originals declared in wp_imgArray_pg_39. WebPlus navigation/UI PNGs and gallery thumbnails are not counted as separate content images.",
 "verification_note":"Every displayed image is an archived original from the defunct site. No unrelated substitute photographs were used."}
(ROOT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Replace Barnard Castle A-Z target only.
p=Path("atoz-part1.html");s=p.read_text(encoding="utf-8")
pat=r'href="[^"]*castlesfortsbattles\.co\.uk/north_east/barnard_castle\.html"'
s,n=re.subn(pat,'href="recovered/barnard-castle/"',s,flags=re.I)
if n==0 and 'href="recovered/barnard-castle/"' not in s:raise RuntimeError("Barnard Castle A-Z entry not found")
p.write_text(s,encoding="utf-8")
print(json.dumps(report,indent=2,ensure_ascii=False))
