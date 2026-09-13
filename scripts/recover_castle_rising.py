#!/usr/bin/env python3
from __future__ import annotations
import html as H, hashlib, json, os, re, time
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
S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles Castle Rising recovery)"

def get(url,timeout=12):
    try: return S.get(url,timeout=timeout,allow_redirects=True)
    except Exception: return None

def raw(ts,u): return f"https://web.archive.org/web/{ts}id_/{u}"

def image_info(data):
    try:
        im=Image.open(BytesIO(data)); return im.width,im.height,im.format
    except Exception: return None

def good_img(r):
    if not r or r.status_code!=200 or len(r.content)<500: return False
    info=image_info(r.content)
    return bool(info and info[0]>=80 and info[1]>=60)

def cdx_exact(u,limit=6):
    rows=[]
    sp=urlsplit(u)
    hosts=[sp.netloc,sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc]
    for scheme in ("https","http"):
        for host in dict.fromkeys(hosts):
            v=urlunsplit((scheme,host,sp.path,"",""))
            try:
                rr=S.get("https://web.archive.org/cdx/search/cdx",
                    params={"url":v,"output":"json","filter":"statuscode:200",
                            "fl":"timestamp,original,length","collapse":"digest","limit":limit},
                    timeout=7)
                if rr.status_code==200:
                    d=rr.json()
                    if isinstance(d,list) and len(d)>1:
                        hdr=d[0]
                        for row in d[1:]:
                            if len(row)==len(hdr): rows.append(dict(zip(hdr,row)))
            except Exception:
                pass
    return rows

# Source HTML: supplied capture first; then exact-page CDX fallbacks.
candidates=[(TS,ORIG)]
for row in cdx_exact(ORIG,12):
    if row.get("timestamp") and row.get("original"):
        candidates.append((row["timestamp"],row["original"]))
seen=set(); source=None
for ts,u in candidates:
    if (ts,u) in seen: continue
    seen.add((ts,u))
    r=get(raw(ts,u),20)
    if r and r.status_code==200 and len(r.content)>1000 and "<html" in r.text.lower():
        source=(ts,u,r.text); break
if not source:
    raise RuntimeError("No usable archived Castle Rising HTML capture found")
source_ts,source_orig,raw_html=source
(ROOT/"source.html").write_text(raw_html,encoding="utf-8",errors="replace")

soup=BeautifulSoup(raw_html,"html.parser")
desktop=soup.find(id="bp_infinity") or soup
image_ext=re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",re.I)
deco=re.compile(r"(facebook|twitter|google|email|print|share|logo|favicon|blank\.gif|castlesfortsbattles(?:-crop)?\.(?:jpg|png))",re.I)
resize_re=re.compile(r"\d{2,4}x\d{2,4}$")
def stem(u): return os.path.splitext(os.path.basename(urlsplit(u).path))[0].lower()
def canonical(st): return resize_re.sub("",st)

def refs_from(tag):
    vals=[]
    if tag.name=="img":
        for a in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
            v=(tag.get(a) or "").strip()
            if v and not v.startswith("data:") and "blank.gif" not in v.lower():
                vals.append(v)
    elif tag.name=="a":
        v=(tag.get("href") or "").strip()
        if image_ext.search(v): vals.append(v)
    return vals

# Genuine desktop Castle Rising identities only.
order=[]; groups={}
for e in desktop.find_all(["img","a"]):
    for v in refs_from(e):
        u=urljoin(source_orig,v)
        b=os.path.basename(urlsplit(u).path)
        if not b or deco.search(b) or not image_ext.search(u): continue
        st=stem(u)
        if "castle_rising" not in st and "rising_castle" not in st:
            continue
        ident=canonical(st)
        groups.setdefault(ident,[])
        if u not in groups[ident]: groups[ident].append(u)
        if ident not in order: order.append(ident)

# Add responsive variants from every breakpoint to the genuine identities.
for e in soup.find_all(["img","a"]):
    for v in refs_from(e):
        u=urljoin(source_orig,v)
        st=stem(u)
        for ident in order:
            if st==ident or (st.startswith(ident) and resize_re.fullmatch(st[len(ident):])):
                if u not in groups[ident]: groups[ident].append(u)
                break

def recover(ident,refs):
    attempts=[]
    # Same-capture probes first.
    for u in refs:
        attempts.append((source_ts,u,"same-capture"))
    # Only if needed, limited exact-CDX probes.
    best=None
    seen=set()
    def try_attempts(atts):
        nonlocal best
        for ts,u,method in atts:
            if (ts,u) in seen: continue
            seen.add((ts,u))
            rr=get(raw(ts,u),8)
            if not good_img(rr): continue
            info=image_info(rr.content)
            rank=(info[0]*info[1],len(rr.content))
            if best is None or rank>best[0]:
                best=(rank,ts,u,method,rr.content,info)
    try_attempts(attempts)
    if best is None:
        fallback=[]
        for u in refs[:8]:
            for row in cdx_exact(u,4):
                fallback.append((row["timestamp"],row["original"],"cdx"))
        try_attempts(fallback)
    if best is None: return None
    _,ts,u,method,data,info=best
    ext=os.path.splitext(urlsplit(u).path)[1].lower()
    if ext not in (".jpg",".jpeg",".png",".gif",".webp"): ext=".jpg"
    p=IMG/(ident+ext)
    p.write_bytes(data)
    return {"identity":ident,"file":"images/"+p.name,"archive_timestamp":ts,
            "archive_original":u,"method":method,"dimensions":[info[0],info[1]],
            "bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "identification":"certain"}

recovered=[]; missing=[]
for ident in order:
    x=recover(ident,groups[ident])
    if x: recovered.append(x)
    else: missing.append({"identity":ident,"candidate_urls":groups[ident]})
    time.sleep(.02)

# Extract written content from desktop source, preserving original order while removing navigation/share repetition.
for x in desktop.find_all(["script","style","noscript"]): x.decompose()
nav={"England","Scotland","Wales","Home","UK Map","A-Z","Links","About Us","Contact Us",
     "Terms and Conditions","CastlesFortsBattles.co.uk","BattlefieldsofBritain.co.uk",
     "A-C","D-G","H-L","M-R","S-Z"}
blocks=[]; seen_text=set()
for e in desktop.find_all(["h1","h2","h3","h4","p","li"]):
    tx=ftfy.fix_text(" ".join(e.stripped_strings).strip())
    key=re.sub(r"\s+"," ",tx).casefold()
    if not tx or tx in nav or tx.lower() in ("tweet","share","follow") or key in seen_text:
        continue
    seen_text.add(key); blocks.append((e.name,tx))

def headingish(tx):
    return len(tx)<110 and re.match(
        r"^(History|Historical Background|Design|Gallery|Bibliography|What.?s There|Getting There|Location|Access|Visiting|Castle Rising|Norman|Anarchy|Plantagenet|Tudor|Civil War|Later History)",
        tx,re.I)

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
    figs.append(
      f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="Castle Rising Castle archived original image"></a><figcaption>{H.escape(cap)}</figcaption></figure>'
    )

doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Castle Rising Castle | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}@media(max-width:700px){{main{{padding:16px 10px 36px}}.note,article{{padding:15px}}}}</style></head><body><header><h1>Castle Rising Castle</h1></header><main><div class="note">Recovered from the archived CastlesFortsBattles page. The archived written content is preserved. Only genuine original images recovered from web archives are shown ({len(recovered)} distinct content images); no substitute photographs have been introduced.</div><article>{''.join(body)}<h2>Recovered original photographs, plans and images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered from the available archive captures.</p>'}</article><p><a href="../../atoz-part1.html#c">Back to the C index</a></p></main></body></html>'''
doc=ftfy.fix_text(doc)
for bad in ("â","Ã","�"):
    if bad in doc: raise RuntimeError("Mojibake remains: "+bad)
(ROOT/"index.html").write_text(doc,encoding="utf-8")

report={
  "name":NAME,"original_url":ORIG,"supplied_capture":TS,
  "source_timestamp_used":source_ts,"source_original_used":source_orig,
  "text_blocks_preserved":len(blocks),
  "original_image_positions_identified":len(order),
  "desktop_image_identities":order,
  "images_recovered":len(recovered),
  "still_missing":len(missing),
  "uncertain_identifications":[],
  "images":recovered,"missing":missing,
  "counting_method":"Unique Castle Rising content-image identities in the desktop source; Muse responsive resize variants are not counted separately.",
  "verification_note":"Every displayed image is an archived original from the defunct site. No substitute photographs were used."
}
(ROOT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

p=Path("atoz-part1.html"); t=p.read_text(encoding="utf-8")
pat=r'href="https?://web\.archive\.org/web/[^"]*https?://(?:www\.)?castlesfortsbattles\.co\.uk/east/castle_rising_castle\.html"'
t,n=re.subn(pat,'href="recovered/castle-rising-castle/"',t)
if n==0 and 'href="recovered/castle-rising-castle/"' not in t:
    raise RuntimeError("Castle Rising A-Z entry not found")
p.write_text(t,encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("images","missing")},indent=2,ensure_ascii=False))
