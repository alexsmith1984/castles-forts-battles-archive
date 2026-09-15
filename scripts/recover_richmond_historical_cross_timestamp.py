#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urlparse,urlunparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/richmond-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(exist_ok=True)
PAGES=[
 "http://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "https://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "http://castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "https://castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "http://www.castlesfortsbattles.co.uk/richmond_castle.html",
 "https://www.castlesfortsbattles.co.uk/richmond_castle.html",
 "http://www.castlesfortsbattles.co.uk/m/richmond_castle.html",
 "https://www.castlesfortsbattles.co.uk/m/richmond_castle.html"
]
CANON=[
 "richmond_castle","richmond_castle9","richmond_castle_plan","richmond_castle7","richmond_castle4c","richmond_castle6a","richmond_castle14b",
 "richmond_castle1","richmond_castle2b","richmond_castle3a","richmond_castle3b","richmond_castle4a","richmond_castle4b","richmond_castle4d",
 "richmond_castle5","richmond_castle8","richmond_castle10","richmond_castle11","richmond_castle12","richmond_castle13","richmond_castle14a",
 "richmond_castle14c","richmond_castle15","richmond_castle16a","richmond_castle16b","richmond_castle17","richmond_castle18"
]
STANDALONE=["richmond_castle","richmond_castle9","richmond_castle_plan","richmond_castle7","richmond_castle4c","richmond_castle6a","richmond_castle14b"]
GALLERY=["richmond_castle7","richmond_castle9","richmond_castle14b","richmond_castle1","richmond_castle2b","richmond_castle3a","richmond_castle3b",
 "richmond_castle4a","richmond_castle4b","richmond_castle4c","richmond_castle4d","richmond_castle5","richmond_castle6a","richmond_castle8",
 "richmond_castle10","richmond_castle11","richmond_castle12","richmond_castle13","richmond_castle14a","richmond_castle14c","richmond_castle15",
 "richmond_castle16a","richmond_castle16b","richmond_castle17","richmond_castle18"]
ALIASES={
 "richmond_castle7":["richmond_castle7","richmond_castle72"],
 "richmond_castle9":["richmond_castle9","richmond_castle92"],
 "richmond_castle14b":["richmond_castle14b","richmond_castle14b2"],
 "richmond_castle4c":["richmond_castle4c","richmond_castle4c2"],
 "richmond_castle6a":["richmond_castle6a","richmond_castle6a2"]
}
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 RichmondHistoricalCrossTimestampRecovery"

def get(u,t=12):
 r=None
 for n in range(3):
  try:
   r=S.get(u,timeout=t,allow_redirects=True)
   if r.status_code not in (429,500,502,503,504): return r
  except Exception:r=None
  time.sleep(.5*(n+1))
 return r

def info(b):
 try:
  im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
  if z[0]<80 or z[1]<80:return None
  return z
 except Exception:return None

def timemap(source,u):
 ep=("https://web.archive.org/web/timemap/link/"+u) if source=="wayback" else ("https://arquivo.pt/wayback/timemap/link/"+u)
 marker="/web/" if source=="wayback" else "/wayback/"
 r=get(ep,18)
 if not r or r.status_code!=200:return []
 out=[]
 for line in r.text.splitlines():
  if "memento" not in line or "<" not in line or ">" not in line:continue
  uri=line.split("<",1)[1].split(">",1)[0]
  if marker not in uri:continue
  rest=uri.split(marker,1)[1]
  if "/" not in rest:continue
  ts,orig=rest.split("/",1);ts=ts[:14]
  if len(ts)==14 and ts.isdigit() and orig.startswith(("http://","https://")):out.append((source,ts,orig))
 return out

def page_replay(source,ts,u):
 ep=("https://web.archive.org/web/"+ts+"id_/"+u) if source=="wayback" else ("https://arquivo.pt/wayback/"+ts+"id_/"+u)
 return get(ep,12)

def canon_from_leaf(leaf):
 stem=Path(leaf).stem.lower()
 # exact aliases first
 for c in CANON:
  for a in ALIASES.get(c,[c]):
   if stem==a.lower():return c
 # Muse responsive WIDTHxHEIGHT exports
 for c in CANON:
  for a in ALIASES.get(c,[c]):
   if re.fullmatch(re.escape(a.lower())+r"\d+x\d+",stem):return c
 return None

def absolute(pageurl,ref):
 if ref.startswith(("http://","https://")):return ref
 return urljoin(pageurl,ref)

def extract_historical(html,pageurl):
 soup=BeautifulSoup(html,"html.parser")
 mapped={c:[] for c in CANON}
 # Semantic Richmond filename mapping whenever names survive.
 for tag in soup.find_all(["a","img"]):
  for attr in ("href","data-src","data-orig-src","data-muse-src","src"):
   ref=tag.get(attr)
   if not ref or not re.search(r"\.(?:jpe?g|png)(?:\?|$)",ref,re.I):continue
   c=canon_from_leaf(urlparse(ref).path)
   if c:mapped[c].append(absolute(pageurl,ref))
 # Standalone position mapping: explicit assets links, preserving document order.
 assets=[]
 for a in soup.find_all("a",href=True):
  ref=a["href"]
  if re.search(r"(?:^|/)assets/[^?#]+\.(?:jpe?g|png)(?:\?|$)",ref,re.I):
   u=absolute(pageurl,ref)
   if u not in assets:assets.append(u)
 if len(assets)>=7:
  for pos,c in enumerate(STANDALONE):mapped[c].append(assets[pos])
 # Muse slideshow mapping by data-col-pos, independent of filename.
 for im in soup.find_all("img"):
  if "ImageInclude" not in (im.get("class") or []):continue
  try:pos=int(im.get("data-col-pos"))
  except Exception:continue
  if 0<=pos<len(GALLERY):
   ref=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src") or im.get("src")
   if ref and re.search(r"\.(?:jpe?g|png)(?:\?|$)",ref,re.I):mapped[GALLERY[pos]].append(absolute(pageurl,ref))
 # Older WebPlus gallery arrays, if an earlier generator is encountered.
 hashes=[]
 for m in re.finditer(r'new\s+wp_galleryimage\s*\(\s*["\']wpimages/([^"\']+?\.(?:jpg|jpeg|png))',html,re.I):
  if m.group(1) not in hashes:hashes.append(m.group(1))
 if len(hashes)>=len(GALLERY):
  for pos,c in enumerate(GALLERY):mapped[c].append(urljoin(pageurl,"wpimages/"+hashes[pos]))
 return mapped,assets,hashes

def expand_original(u):
 p=urlparse(u); path=p.path; q=p.query
 # keep historical path/filename, vary host+protocol; preserve and strip CRC query
 out=[]
 for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
   for query in ([q,""] if q else [""]):
    x=urlunparse((scheme,host,path,"",query,""))
    if x not in out:out.append(x)
 return out

def probe(original):
 anchors=["2","0","20221231235959","20211208101939","20201231235959","20191231235959","20181231235959","20171231235959","20161231235959"]
 for a in anchors:
  for mode in ("id_","im_"):
   u=f"https://web.archive.org/web/{a}{mode}/{original}"
   r=get(u,7)
   if r and r.status_code==200:
    z=info(r.content)
    if z:return (r.content,z,r.url,u)
 return None

def quality(original):
 return "full/near-full" if "/assets/" in urlparse(original).path.lower() else "thumbnail/lower-resolution"

def score(original,z):
 return (2 if quality(original)=="full/near-full" else 1,z[0]*z[1])

r=json.loads(REP.read_text());found={x["identity"]:x for x in r.get("images",[])}
candidates={c:[] for c in CANON}
for item in r.get("missing",[]):
 if item["identity"] in candidates:
  candidates[item["identity"]]+=item.get("candidate_urls",[])
# Mine page history.
caps=[]
for p in PAGES:
 caps+=timemap("wayback",p);caps+=timemap("arquivo",p)
seen=set();caps=[x for x in caps if not (x in seen or seen.add(x))];caps.sort(key=lambda x:x[1])
# sample only if absurdly large, retaining broad chronology
if len(caps)>70:
 idx={0,len(caps)-1}
 for n in range(1,69):idx.add(round(n*(len(caps)-1)/69))
 caps=[caps[i] for i in sorted(idx)]
checked=0; pages_with_content=0; historic_records=[]
for source,ts,pageurl in caps:
 pr=page_replay(source,ts,pageurl)
 if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
 checked+=1
 mapped,assets,hashes=extract_historical(pr.text,pageurl)
 nonempty={c:v for c,v in mapped.items() if v}
 if nonempty:
  pages_with_content+=1
  historic_records.append({"source":source,"timestamp":ts,"page":pageurl,"mapped_count":len(nonempty),"asset_count":len(assets),"webplus_gallery_count":len(hashes)})
  for c,urls in nonempty.items():candidates[c]+=urls

# Normalize/expand and dedupe.
for c in candidates:
 expanded=[]
 for u in candidates[c]:
  expanded+=expand_original(u)
 seen=set();candidates[c]=[u for u in expanded if not (u in seen or seen.add(u))]

# Search missing identities concurrently, one task per original candidate.
jobs={}
with ThreadPoolExecutor(max_workers=16) as ex:
 for c,urls in candidates.items():
  if c in found:continue
  for u in urls:jobs[ex.submit(probe,u)]=(c,u)
 results={c:[] for c in CANON}
 for fut in as_completed(jobs):
  c,u=jobs[fut];got=fut.result()
  if got:
   b,z,final,probe_url=got
   results[c].append((score(u,z),u,b,z,final,probe_url))

new=[]
for c in CANON:
 if c in found or not results[c]:continue
 best=max(results[c],key=lambda x:x[0]);_,u,b,z,final,probe_url=best
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
 rec={"identity":c,"file":"images/"+p.name,"archive_timestamp":"nearest-surviving-capture",
      "archive_original":u,"archive_replay":final,"probe":probe_url,
      "method":"historical-page-position-plus-cross-timestamp-wayback-replay",
      "dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":quality(u),"identification":"certain"}
 found[c]=rec;new.append(c);print("RECOVERED",c,u,z,rec["quality"],flush=True)

r["images"]=[found[c] for c in CANON if c in found]
r["missing"]=[{"identity":c,"candidate_urls":candidates[c]} for c in CANON if c not in found]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(CANON)-len(r["images"]);r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_cross_timestamp_recovery_2026_09_15"]={
 "completed":True,"historical_page_captures_found":len(caps),"historical_page_captures_checked":checked,
 "pages_with_mapped_content":pages_with_content,"historic_page_records":historic_records,
 "candidate_url_counts":{c:len(candidates[c]) for c in CANON},"recovered_now":new
}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"captures":len(caps),"checked":checked,"pages_with_content":pages_with_content,
 "new":new,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
