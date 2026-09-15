#!/usr/bin/env python3
# Optimized Richmond deep recovery: historical page-position mining plus exact image TimeMap replay.
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
ALIASES={"richmond_castle7":["richmond_castle7","richmond_castle72"],"richmond_castle9":["richmond_castle9","richmond_castle92"],
"richmond_castle14b":["richmond_castle14b","richmond_castle14b2"],"richmond_castle4c":["richmond_castle4c","richmond_castle4c2"],
"richmond_castle6a":["richmond_castle6a","richmond_castle6a2"]}
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 RichmondOptimizedArchiveRecovery"

def get(u,t=12):
 r=None
 for n in range(2):
  try:
   r=S.get(u,timeout=t,allow_redirects=True)
   if r.status_code not in (429,500,502,503,504):return r
  except Exception:r=None
  time.sleep(.5*(n+1))
 return r

def info(b):
 try:
  im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
  return z if z[0]>=80 and z[1]>=80 else None
 except Exception:return None

def tm(source,u):
 ep=("https://web.archive.org/web/timemap/link/"+u) if source=="wayback" else ("https://arquivo.pt/wayback/timemap/link/"+u)
 marker="/web/" if source=="wayback" else "/wayback/"
 r=get(ep,14)
 if not r or r.status_code!=200:return []
 out=[]
 for line in r.text.splitlines():
  if "memento" not in line or "<" not in line or ">" not in line:continue
  uri=line.split("<",1)[1].split(">",1)[0]
  if marker not in uri:continue
  rest=uri.split(marker,1)[1]
  if "/" not in rest:continue
  ts,orig=rest.split("/",1);ts=ts[:14]
  if len(ts)==14 and ts.isdigit():out.append((source,ts,orig))
 return out

def replay(source,ts,u):
 eps=[f"https://web.archive.org/web/{ts}id_/{u}",f"https://web.archive.org/web/{ts}im_/{u}"] if source=="wayback" else [f"https://arquivo.pt/wayback/{ts}id_/{u}"]
 for ep in eps:
  r=get(ep,8)
  if r and r.status_code==200:
   z=info(r.content)
   if z:return r.content,z,r.url
 return None

def canon_leaf(path):
 stem=Path(path).stem.lower()
 for c in CANON:
  for a in ALIASES.get(c,[c]):
   if stem==a.lower():return c
   if re.fullmatch(re.escape(a.lower())+r"\d+x\d+",stem):return c
 return None

def extract(html,pageurl):
 soup=BeautifulSoup(html,"html.parser");m={c:[] for c in CANON}
 assets=[]
 for a in soup.find_all("a",href=True):
  ref=a["href"]
  if re.search(r"(?:^|/)assets/[^?#]+\.(?:jpe?g|png)(?:\?|$)",ref,re.I):
   u=urljoin(pageurl,ref)
   if u not in assets:assets.append(u)
 if len(assets)>=7:
  for i,c in enumerate(STANDALONE):m[c].append(assets[i])
 for tag in soup.find_all(["a","img"]):
  for attr in ("href","data-src","data-orig-src","data-muse-src"):
   ref=tag.get(attr)
   if not ref:continue
   c=canon_leaf(urlparse(ref).path)
   if c:m[c].append(urljoin(pageurl,ref))
 for im in soup.find_all("img"):
  if "ImageInclude" not in (im.get("class") or []):continue
  try:i=int(im.get("data-col-pos"))
  except:continue
  if 0<=i<len(GALLERY):
   ref=im.get("data-src") or im.get("data-muse-src")
   if ref:m[GALLERY[i]].append(urljoin(pageurl,ref))
 hashes=re.findall(r'new\s+wp_galleryimage\s*\(\s*["\']wpimages/([^"\']+?\.(?:jpg|jpeg|png))',html,re.I)
 if len(hashes)>=len(GALLERY):
  for i,c in enumerate(GALLERY):m[c].append(urljoin(pageurl,"wpimages/"+hashes[i]))
 return m

def family_key(u):
 p=urlparse(u);stem=Path(p.path).stem.lower()
 # collapse Muse WIDTHxHEIGHT responsive suffixes to filename family
 stem2=re.sub(r"\d+x\d+$","",stem)
 return (str(Path(p.path).parent).lower(),stem2,Path(p.path).suffix.lower(),p.query)

def reduce_urls(urls):
 # Keep base/original forms plus only the largest responsive export in each family.
 exact=[];resp={}
 for u in urls:
  p=urlparse(u);stem=Path(p.path).stem
  mm=re.search(r"(\d+)x(\d+)$",stem)
  if not mm:exact.append(u);continue
  key=(str(Path(p.path).parent).lower(),re.sub(r"\d+x\d+$","",stem.lower()),Path(p.path).suffix.lower(),p.query)
  area=int(mm.group(1))*int(mm.group(2))
  if key not in resp or area>resp[key][0]:resp[key]=(area,u)
 out=exact+[v[1] for v in resp.values()]
 # normalize to four host/protocol variants, preserving path and query
 expanded=[]
 for u in out:
  p=urlparse(u)
  for scheme in ("http","https"):
   for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
    expanded.append(urlunparse((scheme,host,p.path,"",p.query,"")))
    if p.query:expanded.append(urlunparse((scheme,host,p.path,"","","")))
 seen=set();return [u for u in expanded if not (u in seen or seen.add(u))]

def quality(u):return "full/near-full" if "/assets/" in urlparse(u).path.lower() else "thumbnail/lower-resolution"
def score(u,z):return (2 if quality(u)=="full/near-full" else 1,z[0]*z[1])

r=json.loads(REP.read_text());found={x["identity"]:x for x in r.get("images",[])}
cand={c:[] for c in CANON}
for x in r.get("missing",[]):
 if x["identity"] in cand:cand[x["identity"]]+=x.get("candidate_urls",[])
# Mine historical pages first.
pcaps=[]
for p in PAGES:pcaps+=tm("wayback",p)+tm("arquivo",p)
seen=set();pcaps=[x for x in pcaps if not (x in seen or seen.add(x))];pcaps.sort(key=lambda x:x[1])
if len(pcaps)>60:
 idx={0,len(pcaps)-1}
 for n in range(1,59):idx.add(round(n*(len(pcaps)-1)/59))
 pcaps=[pcaps[i] for i in sorted(idx)]
checked=0
for source,ts,page in pcaps:
 pr=get((f"https://web.archive.org/web/{ts}id_/{page}" if source=="wayback" else f"https://arquivo.pt/wayback/{ts}id_/{page}"),10)
 if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
 checked+=1;m=extract(pr.text,page)
 for c,urls in m.items():cand[c]+=urls
for c in cand:cand[c]=reduce_urls(cand[c])

def search_one(c,u):
 # Exact image TimeMaps first: this directly resolves page/image timestamp mismatch.
 caps=tm("wayback",u)+tm("arquivo",u)
 # Try newest then oldest and a middle sample, rather than every duplicate memento.
 pick=[]
 if caps:
  caps.sort(key=lambda x:x[1]);inds={0,len(caps)-1,len(caps)//2}
  if len(caps)>4:inds|={len(caps)//4,(3*len(caps))//4}
  pick=[caps[i] for i in sorted(inds)]
 for source,ts,orig in reversed(pick):
  got=replay(source,ts,orig)
  if got:return c,u,source,ts,orig,got
 # Wayback nearest/latest fallbacks.
 for a in ("2","0","20221231235959","20191231235959","20161231235959"):
  for mode in ("id_","im_"):
   ep=f"https://web.archive.org/web/{a}{mode}/{u}";rr=get(ep,7)
   if rr and rr.status_code==200:
    z=info(rr.content)
    if z:return c,u,"wayback","nearest",u,(rr.content,z,rr.url)
 return None

jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
 for c,urls in cand.items():
  if c in found:continue
  for u in urls:jobs[ex.submit(search_one,c,u)]=(c,u)
 results={c:[] for c in CANON}
 for fut in as_completed(jobs):
  got=fut.result()
  if not got:continue
  c,u,source,ts,orig,(b,z,final)=got
  results[c].append((score(u,z),u,source,ts,orig,b,z,final))

new=[]
for c in CANON:
 if c in found or not results[c]:continue
 best=max(results[c],key=lambda x:x[0]);_,u,source,ts,orig,b,z,final=best
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
 found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":orig,"archive_replay":final,
 "method":"exact-image-timemap-plus-historical-position-recovery","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
 "sha256":hashlib.sha256(b).hexdigest(),"quality":quality(u),"identification":"certain"}
 new.append(c);print("RECOVERED",c,u,z,quality(u),flush=True)

r["images"]=[found[c] for c in CANON if c in found]
r["missing"]=[{"identity":c,"candidate_urls":cand[c]} for c in CANON if c not in found]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(CANON)-len(r["images"]);r["status"]="COMPLETE" if not r["still_missing"] else "PARTIAL"
r["optimized_exact_image_timemap_recovery_2026_09_15"]={"completed":True,"page_captures_found":len(pcaps),"page_captures_checked":checked,
"candidate_url_counts":{c:len(cand[c]) for c in CANON},"recovered_now":new}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"page_captures":len(pcaps),"checked":checked,"new":new,"full":r["recovered_full_or_near_full"],
"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
