#!/usr/bin/env python3
from __future__ import annotations
import hashlib, io, json, os, re, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image

NAME="Castle Acre"
SLUG="castle-acre"
TS="20210918022557"
ORIG="http://www.castlesfortsbattles.co.uk/east/castle_acre.html"
OUT=Path("page-audit")/SLUG
OUT.mkdir(parents=True, exist_ok=True)

S=requests.Session()
S.headers["User-Agent"]="Mozilla/5.0 (CastlesFortsBattles archival audit; Castle Acre)"

def get(u,t=15):
    try:
        return S.get(u,timeout=t,allow_redirects=True)
    except Exception:
        return None

def raw(ts,u):
    return f"https://web.archive.org/web/{ts}id_/{u}"

def variants(u):
    sp=urlsplit(u)
    hosts=[sp.netloc]
    hosts.append(sp.netloc[4:] if sp.netloc.startswith("www.") else "www."+sp.netloc)
    out=[]
    for scheme in ("http","https"):
        for host in dict.fromkeys(hosts):
            out.append(urlunsplit((scheme,host,sp.path,"","")))
    return out

def good_html(r):
    return bool(r and r.status_code==200 and len(r.content)>800 and "<html" in r.text.lower())

def image_info(b):
    try:
        im=Image.open(io.BytesIO(b))
        return {"width":im.width,"height":im.height,"format":im.format}
    except Exception:
        return None

def find_source():
    candidates=[(TS,ORIG)]
    for v in variants(ORIG):
        try:
            q=S.get("https://web.archive.org/cdx/search/cdx",params={
                "url":v,"output":"json","filter":["statuscode:200","mimetype:text/html"],
                "fl":"timestamp,original,digest,length","collapse":"digest","limit":50
            },timeout=15)
            if q.status_code==200:
                d=q.json()
                if isinstance(d,list) and len(d)>1:
                    hdr=d[0]
                    for row in d[1:]:
                        x=dict(zip(hdr,row))
                        candidates.append((x["timestamp"],x["original"]))
        except Exception:
            pass
    seen=set()
    # Prefer supplied capture, then newest alternate.
    for cts,cu in [candidates[0]] + sorted(candidates[1:],reverse=True):
        if (cts,cu) in seen: continue
        seen.add((cts,cu))
        r=get(raw(cts,cu),20)
        if good_html(r):
            return cts,cu,r.text
    raise SystemExit("No usable archived HTML source found")

cts,corig,html=find_source()
(OUT/"source.html").write_text(html,encoding="utf-8",errors="replace")
soup=BeautifulSoup(html,"html.parser")

# Collect image-looking references from attributes, CSS and JS. Keep provenance/context.
refs={}
def add_ref(v, where, context=""):
    if not v or v.startswith("data:") or v.startswith("#"): return
    v=v.strip().strip("'\"")
    if not re.search(r"\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$",v,re.I): return
    u=urljoin(corig,v)
    u=u.split("#")[0]
    rec=refs.setdefault(u,{"url":u,"where":[],"contexts":[]})
    if where not in rec["where"]: rec["where"].append(where)
    c=re.sub(r"\s+"," ",context).strip()[:260]
    if c and c not in rec["contexts"]: rec["contexts"].append(c)

for e in soup.find_all(True):
    for a in ("src","href","data-src","data-orig-src","data-muse-src","data-hidpi-src"):
        v=e.get(a)
        if v: add_ref(v,f"{e.name}[{a}]",str(e)[:500])
    style=e.get("style") or ""
    for m in re.finditer(r"url\(([^)]+)\)",style,re.I):
        add_ref(m.group(1),f"{e.name}[style]",style)

# Raw HTML catches WebPlus/Muse JS arrays and lazy assets not represented as DOM attrs.
for m in re.finditer(r"""(?P<q>['\"])(?P<v>[^'\"]+\.(?:jpe?g|png|gif|webp)(?:[?#][^'\"]*)?)(?P=q)""",html,re.I):
    st=max(0,m.start()-140); en=min(len(html),m.end()+140)
    add_ref(m.group("v"),"raw-html",html[st:en])

# Determine whether each exact resource is archived and inspect dimensions.
# We only fetch exact same-capture/nearest exact URL; no broad wildcard pass yet.
decorative_name=re.compile(r"(facebook|twitter|pinterest|google|email|print|share|logo|favicon|blank|arrow|button|menu|nav|search|icon|sprite)",re.I)
for i,(u,rec) in enumerate(list(refs.items()),1):
    sp=urlsplit(u); base=os.path.basename(sp.path)
    rec["basename"]=base
    rec["path"]=sp.path
    rec["name_decorative_hint"]=bool(decorative_name.search(base))
    found=None
    attempts=[]
    for v in variants(u):
        rr=get(raw(cts,v),8)
        attempts.append({"timestamp":cts,"url":v,"status":getattr(rr,"status_code",None),"bytes":len(rr.content) if rr else 0})
        if rr and rr.status_code==200:
            info=image_info(rr.content)
            if info:
                found={"timestamp":cts,"archive_original":v,"bytes":len(rr.content),
                       "sha256":hashlib.sha256(rr.content).hexdigest(),**info}
                break
    rec["same_capture"]=found
    rec["attempts"]=attempts
    time.sleep(.03)

# Extract JS gallery declarations explicitly.
gallery=[]
for pat in [
    r"wp_imgArray[^=]*=\s*\[(.*?)\];",
    r"muse.*?\[(.*?)\]",
]:
    for gm in re.finditer(pat,html,re.I|re.S):
        block=gm.group(0)
        imgs=re.findall(r"[^'\"\s,]+\.(?:jpe?g|png|gif|webp)",block,re.I)
        if imgs:
            gallery.append({"pattern":pat,"images":imgs,"snippet":re.sub(r"\s+"," ",block)[:1200]})

# Save text inventory to help identify headings/paragraph structure.
texts=[]
seen=set()
for e in soup.find_all(["h1","h2","h3","h4","p","li"]):
    tx=" ".join(e.stripped_strings).strip()
    k=re.sub(r"\s+"," ",tx).casefold()
    if tx and k not in seen:
        seen.add(k)
        texts.append({"tag":e.name,"text":tx})

report={
    "name":NAME,"slug":SLUG,"supplied_capture":TS,"source_timestamp_used":cts,
    "source_original_used":corig,"source_sha256":hashlib.sha256(html.encode("utf-8",errors="replace")).hexdigest(),
    "image_reference_count_raw_unique":len(refs),"image_references":list(refs.values()),
    "gallery_declarations":gallery,"text_blocks":texts,
    "note":"Inspection only. Raw image-reference count is NOT the historic content-image count; responsive variants, thumbnails and interface graphics must be reconciled manually."
}
(OUT/"inspection.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"source_timestamp":cts,"refs":len(refs),"gallery_blocks":len(gallery),"text_blocks":len(texts)},indent=2))
