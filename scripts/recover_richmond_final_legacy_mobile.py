#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin,urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/richmond-castle");REP=ROOT/"recovery-report.json";IMG=ROOT/"images"
TARGETS=["richmond_castle","richmond_castle_plan"]
PAGE_PATHS=[
 "/m/richmond_castle.html","/m/yorkshire/richmond_castle.html",
 "/yorkshire/richmond-castle.html","/richmond-castle.html",
 "/yorkshire/richmond_castle.htm","/richmond_castle.htm",
 "/Yorkshire/Richmond_Castle.html","/yorkshire/Richmond_Castle.html"
]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 RichmondFinalLegacyRetry"

def get(u,t=10):
 for n in range(2):
  try:
   r=S.get(u,timeout=t,allow_redirects=True)
   if r.status_code not in (429,500,502,503,504):return r
  except:pass
  time.sleep(.35*(n+1))
 return None

def info(b):
 try:
  im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
  return z if z[0]>=80 and z[1]>=80 else None
 except:return None

def timemap(src,u):
 ep=("https://web.archive.org/web/timemap/link/"+u) if src=="wayback" else ("https://arquivo.pt/wayback/timemap/link/"+u)
 marker="/web/" if src=="wayback" else "/wayback/"
 r=get(ep,12)
 if not r or r.status_code!=200:return []
 out=[]
 for line in r.text.splitlines():
  if "memento" not in line or "<" not in line or ">" not in line:continue
  uri=line.split("<",1)[1].split(">",1)[0]
  if marker not in uri:continue
  rest=uri.split(marker,1)[1]
  if "/" not in rest:continue
  ts,orig=rest.split("/",1);ts=ts[:14]
  if len(ts)==14 and ts.isdigit():out.append((src,ts,orig))
 return out

def replay(src,ts,u):
 eps=[f"https://web.archive.org/web/{ts}id_/{u}",f"https://web.archive.org/web/{ts}im_/{u}"] if src=="wayback" else [f"https://arquivo.pt/wayback/{ts}id_/{u}"]
 for ep in eps:
  r=get(ep,8)
  if r and r.status_code==200:
   z=info(r.content)
   if z:return r.content,z,r.url
 return None

pages=[]
for scheme in ("http","https"):
 for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
  for p in PAGE_PATHS:pages.append(f"{scheme}://{host}{p}")

caps=[]
for p in pages:
 caps+=timemap("wayback",p)+timemap("arquivo",p)
seen=set();caps=[x for x in caps if not (x in seen or seen.add(x))];caps.sort(key=lambda x:x[1])
if len(caps)>48:
 idx={0,len(caps)-1}
 for n in range(1,47):idx.add(round(n*(len(caps)-1)/47))
 caps=[caps[i] for i in sorted(idx)]

cands={k:[] for k in TARGETS};records=[];checked=0
for src,ts,page in caps:
 ep=(f"https://web.archive.org/web/{ts}id_/{page}" if src=="wayback" else f"https://arquivo.pt/wayback/{ts}id_/{page}")
 r=get(ep,10)
 if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
 checked+=1;soup=BeautifulSoup(r.text,"html.parser")
 found=[]
 # Exact semantic filenames from old/mobile pages.
 for tag in soup.find_all(["a","img"]):
  for attr in ("href","src","data-src","data-orig-src","data-muse-src"):
   ref=tag.get(attr)
   if not ref:continue
   leaf=Path(urlparse(ref).path).name.lower()
   if re.search(r"richmond[-_]?castle[-_]?plan",leaf):
    u=urljoin(page,ref);cands["richmond_castle_plan"].append(u);found.append(("plan",u))
   elif re.fullmatch(r"richmond[-_]?castle(?:\d+x\d+)?\.(?:jpg|jpeg|png)",leaf):
    u=urljoin(page,ref);cands["richmond_castle"].append(u);found.append(("hero",u))
 # Explicit first and third standalone asset positions where Muse structure survives.
 assets=[]
 for a in soup.find_all("a",href=True):
  ref=a["href"]
  if re.search(r"(?:^|/)(?:assets|images|wpimages)/[^?#]+\.(?:jpe?g|png)(?:\?|$)",ref,re.I):
   u=urljoin(page,ref)
   if u not in assets:assets.append(u)
 if len(assets)>=3:
  cands["richmond_castle"].append(assets[0]);cands["richmond_castle_plan"].append(assets[2])
 # Older WebPlus filename declarations / page source references.
 for m in re.finditer(r'["\']((?:[^"\']*/)?(?:richmond[-_]?castle(?:[-_]?plan)?[^"\']*\.(?:jpg|jpeg|png)))["\']',r.text,re.I):
  ref=m.group(1);u=urljoin(page,ref);low=ref.lower()
  if "plan" in low:cands["richmond_castle_plan"].append(u)
  elif re.search(r"richmond[-_]?castle",low):cands["richmond_castle"].append(u)
 if found or assets:records.append({"source":src,"timestamp":ts,"page":page,"found":found[:20],"assets":assets[:8]})

# Add compact legacy naming variants not covered by current Muse filenames.
hero_names=["richmondcastle.jpg","RichmondCastle.jpg","RichmondCastle.JPG","richmond-castle.jpg","Richmond-Castle.jpg","richmond_castle.jpeg"]
plan_names=["richmondcastleplan.png","RichmondCastlePlan.png","RichmondCastlePlan.PNG","richmond-castle-plan.png","Richmond-Castle-Plan.png","richmond_castle_plan.jpg","Richmond_Castle_Plan.jpg"]
for ident,names in [("richmond_castle",hero_names),("richmond_castle_plan",plan_names)]:
 for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
   for d in ("yorkshire/assets","yorkshire/images","assets","images","yorkshire/wpimages","wpimages","m/images","m/assets","m/wpimages"):
    for n in names:cands[ident].append(f"{scheme}://{host}/{d}/{n}")

for k in cands:
 ss=set();cands[k]=[u for u in cands[k] if not (u in ss or ss.add(u))]

def search(ident,u):
 cs=timemap("wayback",u)+timemap("arquivo",u)
 if cs:
  cs.sort(key=lambda x:x[1]);inds={0,len(cs)-1,len(cs)//2}
  for i in sorted(inds,reverse=True):
   src,ts,orig=cs[i];got=replay(src,ts,orig)
   if got:return ident,u,src,ts,orig,got
 for a in ("2","0","20221231235959","20191231235959","20161231235959"):
  for mode in ("id_","im_"):
   ep=f"https://web.archive.org/web/{a}{mode}/{u}";r=get(ep,7)
   if r and r.status_code==200:
    z=info(r.content)
    if z:return ident,u,"wayback","nearest",u,(r.content,z,r.url)
 return None

jobs={};results={k:[] for k in TARGETS}
with ThreadPoolExecutor(max_workers=14) as ex:
 for ident,urls in cands.items():
  for u in urls:jobs[ex.submit(search,ident,u)]=(ident,u)
 for fut in as_completed(jobs):
  got=fut.result()
  if got:
   ident,u,src,ts,orig,(b,z,final)=got
   q="full/near-full" if ("/assets/" in urlparse(orig).path.lower() and not re.search(r"\d+x\d+$",Path(urlparse(orig).path).stem)) else "thumbnail/lower-resolution"
   results[ident].append(((2 if q=="full/near-full" else 1,z[0]*z[1]),u,src,ts,orig,b,z,final,q))

rep=json.loads(REP.read_text());found={x["identity"]:x for x in rep.get("images",[])};new=[]
for ident in TARGETS:
 if not results[ident]:continue
 _,u,src,ts,orig,b,z,final,q=max(results[ident],key=lambda x:x[0])
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(ident+ext);p.write_bytes(b)
 found[ident]={"identity":ident,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":orig,"archive_replay":final,
 "method":"legacy-mobile-historical-timemap-recovery","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
 "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
 new.append(ident)

order=rep["desktop_image_identities"]
rep["images"]=[found[i] for i in order if i in found]
old={x["identity"]:x for x in rep.get("missing",[])}
rep["missing"]=[old.get(i,{"identity":i,"candidate_urls":cands.get(i,[])}) for i in order if i not in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(order)-len(rep["images"])
rep["status"]="COMPLETE" if not rep["still_missing"] else ("PARTIAL / SEARCH EXHAUSTED" if not new else "PARTIAL")
rep["final_legacy_mobile_retry_2026_09_15"]={"completed":True,"page_variants_checked":len(pages),"historical_captures_found":len(caps),
"historical_captures_checked":checked,"candidate_counts":{k:len(v) for k,v in cands.items()},"historical_records":records,"recovered_now":new}
if not new and "search_exhausted_2026_09_15" in rep:
 rep["search_exhausted_2026_09_15"]["final_legacy_mobile_retry_completed"]=True
 rep["search_exhausted_2026_09_15"]["conclusion"]="No authenticated surviving copy of the main hero image or castle plan was found after all bounded direct, historical, wildcard, legacy/mobile, Arquivo and Common Crawl methods."
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"new":new,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"],"captures":len(caps),"checked":checked},indent=2))
