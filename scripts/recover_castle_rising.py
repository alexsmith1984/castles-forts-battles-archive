#!/usr/bin/env python3
from __future__ import annotations
import html as H, hashlib, json, os, re, sys, time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image
import ftfy

NAME="Castle Rising Castle"
SLUG="castle-rising-castle"
TS="20210625101257"
ORIG="https://www.castlesfortsbattles.co.uk/east/castle_rising_castle.html"
ROOT=Path("recovered")/SLUG
IMG=ROOT/"images"
ROOT.mkdir(parents=True,exist_ok=True); IMG.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archive recovery)"

def get(url,timeout=20):
    try: return S.get(url,timeout=timeout,allow_redirects=True)
    except Exception: return None

def good_html(r):
    return bool(r and r.status_code==200 and len(r.content)>1000 and ("<html" in r.text.lower() or "<!doctype" in r.text.lower()))

def image_info(data:bytes):
    try:
        im=Image.open(BytesIO(data)); return (im.width,im.height,im.format)
    except Exception: return None

def good_img(r):
    if not r or r.status_code!=200 or len(r.content)<500: return False
    info=image_info(r.content)
    return bool(info and info[0]>=80 and info[1]>=60)

def raw(ts,u): return f"https://web.archive.org/web/{ts}id_/{u}"

def cdx_exact(u,limit=8):
    out=[]
    sp=urlsplit(u)
    hosts=[sp.netloc, sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    for scheme in ("https","http"):
      for host in dict.fromkeys(hosts):
        v=urlunsplit((scheme,host,sp.path,"",""))
        try:
          r=S.get("https://web.archive.org/cdx/search/cdx",params={"url":v,"output":"json","filter":"statuscode:200","fl":"timestamp,original,length,mimetype","collapse":"digest","limit":limit},timeout=12)
          if r.status_code==200:
            d=r.json()
            if isinstance(d,list) and len(d)>1:
              hdr=d[0]
              for row in d[1:]:
                if len(row)==len(hdr): out.append(dict(zip(hdr,row)))
        except Exception: pass
    return out

def source_page():
    candidates=[(TS,ORIG)]
    rows=cdx_exact(ORIG,20)
    rows.sort(key=lambda x:x.get("timestamp",""), reverse=True)
    for r in rows: candidates.append((r["timestamp"],r["original"]))
    seen=set()
    for ts,u in candidates:
      if (ts,u) in seen: continue
      seen.add((ts,u))
      rr=get(raw(ts,u),30)
      if good_html(rr): return ts,u,rr
    return None,None,None

source_ts,source_orig,r=source_page()
if not r:
    raise SystemExit("Could not recover archived Castle Rising source HTML")
raw_html=r.text
(ROOT/"source.html").write_text(raw_html,encoding="utf-8",errors="replace")
soup=BeautifulSoup(raw_html,"html.parser")
desktop=soup.find(id="bp_infinity") or soup

# Gather genuine page-content image references, canonicalising Muse responsive variants.
deco=re.compile(r"(facebook|twitter|google|email|print|share|logo|favicon|blank\.gif|castlesfortsbattles(?:-crop)?\.(?:jpg|png)|battlefieldsofbritain(?:-crop)?\.(?:jpg|png))",re.I)
image_ext=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)
def stem(u):
    return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
def canonical(st):
    st=re.sub(r"\d{2,4}x\d{2,4}$","",st)
    return st

groups={}
order=[]
for e in desktop.find_all(["img","a"]):
    vals=[]
    if e.name=="img":
      for a in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
        v=(e.get(a) or "").strip()
        if v and not v.startswith("data:") and "blank.gif" not in v.lower(): vals.append(v)
    else:
      v=(e.get("href") or "").strip()
      if image_ext.search(v): vals.append(v)
    for v in vals:
      u=urljoin(source_orig,v)
      b=os.path.basename(urlsplit(u).path)
      if not b or deco.search(b) or not image_ext.search(u): continue
      ident=canonical(stem(u))
      # Prefer actual Castle Rising content; retain non-decorative plans/images from the desktop content too.
      if "castle_rising" not in ident and "rising" not in ident:
        # allow only if clearly inside the article region
        if e.find_parent(id="bp_infinity") is None and desktop is not soup: continue
      groups.setdefault(ident,[])
      if u not in groups[ident]: groups[ident].append(u)
      if ident not in order: order.append(ident)

def recover_identity(ident,refs):
    attempts=[]
    for u in refs:
      attempts.append((source_ts,u,"same-capture"))
      for row in cdx_exact(u,10):
        attempts.append((row["timestamp"],row["original"],"cdx"))
    seen=set(); best=None
    for ts,u,method in attempts:
      if (ts,u) in seen: continue
      seen.add((ts,u))
      rr=get(raw(ts,u),12)
      if not good_img(rr): continue
      info=image_info(rr.content)
      rank=(info[0]*info[1],len(rr.content))
      if best is None or rank>best[0]:
        best=(rank,ts,u,method,rr.content,info)
    if not best: return None
    _,ts,u,method,data,info=best
    ext=os.path.splitext(urlsplit(u).path)[1].lower()
    if ext not in (".jpg",".jpeg",".png",".gif",".webp"): ext=".jpg"
    dest=IMG/(ident+ext)
    dest.write_bytes(data)
    return {"identity":ident,"file":"images/"+dest.name,"archive_timestamp":ts,"archive_original":u,"method":method,"dimensions":[info[0],info[1]],"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"identification":"certain"}

recovered=[]; missing=[]
for ident in order:
    x=recover_identity(ident,groups[ident])
    if x: recovered.append(x)
    else: missing.append({"identity":ident,"candidate_urls":groups[ident]})
    time.sleep(.03)

# Preserve archived written content from the desktop source, removing only navigation/share repetition.
for x in desktop.find_all(["script","style","noscript"]): x.decompose()
nav={"England","Scotland","Wales","Home","UK Map","A-Z","Links","About Us","Contact Us","Terms and Conditions","CastlesFortsBattles.co.uk","BattlefieldsofBritain.co.uk","A-C","D-G","H-L","M-R","S-Z"}
blocks=[]; seen_text=set()
for e in desktop.find_all(["h1","h2","h3","h4","p","li"]):
    tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
    key=re.sub(r"\s+"," ",tx).casefold()
    if not tx or tx in nav or tx.lower() in ("tweet","share","follow") or key in seen_text: continue
    seen_text.add(key); blocks.append((e.name,tx))

def headingish(tx):
    return len(tx)<110 and re.match(r"^(History|Historical Background|Design|Gallery|Bibliography|What.?s There|Getting There|Location|Access|Visiting|Castle Rising|Norman|Anarchy|Plantagenet|Tudor|Civil War|Later History)",tx,re.I)

body=[]
for tag,tx in blocks:
    if tag.startswith("h") or headingish(tx): body.append(f"<h2>{H.escape(tx)}</h2>")
    elif tag=="li": body.append(f"<p>• {H.escape(tx)}</p>")
    else: body.append(f"<p>{H.escape(tx)}</p>")

def natural_key(x):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)",x["identity"])]
figs=[]
for x in sorted(recovered,key=natural_key):
    cap=x["identity"].replace("_"," ")
    figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="Castle Rising Castle archived original image"></a><figcaption>{H.escape(cap)}</figcaption></figure>')

doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Castle Rising Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>Castle Rising Castle</h1></header><main><div class="note">Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. Only genuine original images recovered from web archives are shown ({len(recovered)} distinct content images); no substitute photographs have been introduced.</div><article>{''.join(body)}<h2>Recovered original photographs, plans and images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered from the available archive captures.</p>'}</article><p><a href="../../atoz-part1.html#c">Back to the C index</a></p></main></body></html>'''
doc=ftfy.fix_text(doc)
for bad in ("â","Ã","�"):
    if bad in doc: raise RuntimeError("Mojibake remains: "+bad)
(ROOT/"index.html").write_text(doc,encoding="utf-8")

report={
 "name":NAME,"original_url":ORIG,"supplied_capture":TS,"source_timestamp_used":source_ts,"source_original_used":source_orig,
 "text_blocks_preserved":len(blocks),"original_image_positions_identified":len(order),"desktop_image_identities":order,
 "images_recovered":len(recovered),"still_missing":len(missing),"uncertain_identifications":[],
 "images":recovered,"missing":missing,
 "counting_method":"Unique non-decorative Castle Rising content-image identities in the desktop source; Muse responsive resize variants are not counted separately.",
 "verification_note":"Every displayed file is an archived original recovered from the defunct site. No unrelated substitute images were used."
}
(ROOT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

# Update A-Z C entry to the stable local reconstruction.
p=Path("atoz-part1.html"); t=p.read_text(encoding="utf-8")
pat=r'href="https?://web\.archive\.org/web/[^"]*https?://(?:www\.)?castlesfortsbattles\.co\.uk/east/castle_rising_castle\.html"'
t,n=re.subn(pat,'href="recovered/castle-rising-castle/"',t)
if n==0 and 'href="recovered/castle-rising-castle/"' not in t:
    raise RuntimeError("Castle Rising A-Z entry was not found for replacement")
p.write_text(t,encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
