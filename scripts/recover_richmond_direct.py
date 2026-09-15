#!/usr/bin/env python3
import io, json, re, hashlib
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image

ROOT=Path("recovered/richmond-castle")
REP=ROOT/"recovery-report.json"
SRC=ROOT/"source.html"
IMG=ROOT/"images"
IMG.mkdir(parents=True,exist_ok=True)
TS="20211208101939"

ALIASES={
 "richmond_castle7":["richmond_castle7","richmond_castle72"],
 "richmond_castle9":["richmond_castle9","richmond_castle92"],
 "richmond_castle14b":["richmond_castle14b","richmond_castle14b2"],
 "richmond_castle4c":["richmond_castle4c","richmond_castle4c2"],
 "richmond_castle6a":["richmond_castle6a","richmond_castle6a2"],
}
CANONICAL=[
 "richmond_castle","richmond_castle9","richmond_castle_plan","richmond_castle7",
 "richmond_castle4c","richmond_castle6a","richmond_castle14b",
 "richmond_castle1","richmond_castle2b","richmond_castle3a","richmond_castle3b",
 "richmond_castle4a","richmond_castle4b","richmond_castle4d","richmond_castle5",
 "richmond_castle8","richmond_castle10","richmond_castle11","richmond_castle12",
 "richmond_castle13","richmond_castle14a","richmond_castle14c","richmond_castle15",
 "richmond_castle16a","richmond_castle16b","richmond_castle17","richmond_castle18"
]
UA="Mozilla/5.0 RichmondCastleArchiveRecovery"

def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        if z[0]<80 or z[1]<80:return None
        return z
    except Exception:return None

def fetch(probe):
    try:
        s=requests.Session(); s.headers["User-Agent"]=UA
        r=s.get(probe,timeout=8,allow_redirects=True)
        if r.status_code==200:
            z=info(r.content)
            if z:return (r.content,z,r.url)
    except Exception:pass
    return None

def variants(u):
    # preserve exact query and also query-free form; vary protocol/host and root/yorkshire paths
    p=urlparse(u)
    leaf=Path(p.path).name
    dirs=[]
    low=p.path.lower()
    if "/assets/" in low: dirs=["/yorkshire/assets/","/assets/"]
    elif "/images/" in low: dirs=["/yorkshire/images/","/images/"]
    else: dirs=[str(Path(p.path).parent).replace("\\","/")+"/"]
    out=[]
    queries=[p.query,""] if p.query else [""]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
       for d in dirs:
        for q in queries:
         x=urlunparse((scheme,host,d+leaf,"",q,""))
         if x not in out:out.append(x)
    return out

r=json.loads(REP.read_text())
html=SRC.read_text(errors="replace")
old_missing={x["identity"]:x for x in r.get("missing",[])}
# Exact source refs including CRC querystrings.
source_refs=set(re.findall(r'(?:href|data-orig-src|data-muse-src|data-src)=["\']([^"\']+)["\']',html,re.I))
source_refs={x for x in source_refs if re.search(r'richmond_castle[^/?#]*\.(?:jpg|jpeg|png)',x,re.I)}
base="http://www.castlesfortsbattles.co.uk/yorkshire/"
source_urls=[]
for ref in source_refs:
    if ref.startswith(("http://","https://")): source_urls.append(ref)
    else: source_urls.append(base+ref.lstrip("/"))

name_to_canonical={}
for c in CANONICAL:
    for a in ALIASES.get(c,[c]): name_to_canonical[a]=c

candidates={c:[] for c in CANONICAL}
# Existing report candidate URLs.
for item in r.get("missing",[]):
    raw=item["identity"]
    c=name_to_canonical.get(raw,raw if raw in candidates else None)
    if not c:continue
    for u in item.get("candidate_urls",[]): candidates[c].extend(variants(u))
# Exact refs in HTML.
for u in source_urls:
    leaf=Path(urlparse(u).path).stem.lower()
    # remove responsive WIDTHxHEIGHT suffix only when it follows a known alias stem
    matched=None
    for a,c in sorted(name_to_canonical.items(),key=lambda kv:len(kv[0]),reverse=True):
        if leaf==a.lower() or re.fullmatch(re.escape(a.lower())+r'\d+x\d+',leaf):
            matched=c;break
    if matched:candidates[matched].extend(variants(u))
# Generated original and display URLs for every canonical+alias name.
for c in CANONICAL:
    ext=".png" if c=="richmond_castle_plan" else ".jpg"
    for a in ALIASES.get(c,[c]):
      for scheme in ("http","https"):
       for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
        for d in ("/yorkshire/assets/","/assets/","/yorkshire/images/","/images/"):
         candidates[c].append(f"{scheme}://{host}{d}{a}{ext}")

for c in candidates:
    seen=set(); candidates[c]=[u for u in candidates[c] if not (u in seen or seen.add(u))]

def quality_for(original,z):
    path=urlparse(original).path.lower()
    # Muse 'assets' links are the explicit source originals; 'images' are generated display exports.
    return "full/near-full" if "/assets/" in path else "thumbnail/lower-resolution"

def score(original,z):
    q=quality_for(original,z)
    return (2 if q=="full/near-full" else 1,z[0]*z[1])

found={x["identity"]:x for x in r.get("images",[]) if x["identity"] in CANONICAL}
results={c:[] for c in CANONICAL}
jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for c,urls in candidates.items():
        if c in found:continue
        for u in urls:
            for mode in ("id_","im_"):
                probe=f"https://web.archive.org/web/{TS}{mode}/{u}"
                jobs[ex.submit(fetch,probe)]=(c,u,probe)
    for fut in as_completed(jobs):
        c,u,probe=jobs[fut]
        got=fut.result()
        if not got:continue
        b,z,final=got
        results[c].append((score(u,z),u,probe,final,b,z))

recovered=[]
for c in CANONICAL:
    if c in found or not results[c]:continue
    best=max(results[c],key=lambda x:x[0])
    _,u,probe,final,b,z=best
    ext=".png" if z[2]=="PNG" else ".jpg"
    p=IMG/(c+ext); p.write_bytes(b)
    rec={
      "identity":c,"file":"images/"+p.name,"archive_timestamp":TS,
      "archive_original":u,"archive_replay":final,
      "method":"direct-supplied-capture-replay",
      "dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),
      "quality":quality_for(u,z),"identification":"certain"
    }
    found[c]=rec; recovered.append(c)
    print("RECOVERED",c,u,z,rec["quality"],flush=True)

# Build canonical missing entries, retaining all authentic source candidates.
missing=[]
for c in CANONICAL:
    if c in found:continue
    missing.append({"identity":c,"candidate_urls":candidates[c]})

r["status"]="COMPLETE" if len(found)==len(CANONICAL) else "PARTIAL"
r["original_image_positions_identified"]=len(CANONICAL)
r["desktop_image_identities"]=CANONICAL
r["duplicate_source_positions_collapsed"]={
 "richmond_castle72":"richmond_castle7",
 "richmond_castle92":"richmond_castle9",
 "richmond_castle14b2":"richmond_castle14b",
 "richmond_castle4c2":"richmond_castle4c",
 "richmond_castle6a2":"richmond_castle6a"
}
r["images"]=[found[c] for c in CANONICAL if c in found]
r["missing"]=missing
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(CANONICAL)-len(r["images"])
r["counting_method"]="27 unique non-decorative content images from the desktop source: 7 standalone positions plus 25 Muse slideshow positions, with five slideshow duplicate imports (7/72, 9/92, 14b/14b2, 4c/4c2, 6a/6a2) collapsed. Responsive WIDTHxHEIGHT derivatives, thumbnails and UI graphics are excluded."
r["direct_supplied_capture_search_2026_09_15"]={
 "completed":True,"capture":TS,"canonical_denominator":len(CANONICAL),
 "recovered_now":recovered
}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"denominator":len(CANONICAL),"recovered_now":recovered,
 "full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],
 "missing":r["still_missing"]},indent=2))
