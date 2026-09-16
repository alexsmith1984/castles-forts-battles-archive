#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import urljoin,urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/richmond-castle");REP=ROOT/"recovery-report.json";IMG=ROOT/"images"
TARGETS={"richmond_castle":0,"richmond_castle_plan":2}
PAGES=[
 "http://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "https://www.castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "http://castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "https://castlesfortsbattles.co.uk/yorkshire/richmond_castle.html",
 "http://www.castlesfortsbattles.co.uk/richmond_castle.html",
 "https://www.castlesfortsbattles.co.uk/richmond_castle.html"
]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 RichmondTwoMissingRecovery"

def get(u,t=12):
 for n in range(2):
  try:
   r=S.get(u,timeout=t,allow_redirects=True)
   if r.status_code not in (429,500,502,503,504):return r
  except:pass
  time.sleep(.4*(n+1))
 return None
def info(b):
 try:
  im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
  return z if z[0]>=80 and z[1]>=80 else None
 except:return None
def timemap(source,u):
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
def replay(source,ts,orig):
 eps=[f"https://web.archive.org/web/{ts}id_/{orig}",f"https://web.archive.org/web/{ts}im_/{orig}"] if source=="wayback" else [f"https://arquivo.pt/wayback/{ts}id_/{orig}"]
 for ep in eps:
  r=get(ep,8)
  if r and r.status_code==200:
   z=info(r.content)
   if z:return r.content,z,r.url
 return None

cands={k:[] for k in TARGETS};page_records=[]
caps=[]
for p in PAGES:caps+=timemap("wayback",p)+timemap("arquivo",p)
seen=set();caps=[x for x in caps if not (x in seen or seen.add(x))];caps.sort(key=lambda x:x[1])
if len(caps)>50:
 idx={0,len(caps)-1}
 for n in range(1,49):idx.add(round(n*(len(caps)-1)/49))
 caps=[caps[i] for i in sorted(idx)]
checked=0
for source,ts,page in caps:
 pr=get((f"https://web.archive.org/web/{ts}id_/{page}" if source=="wayback" else f"https://arquivo.pt/wayback/{ts}id_/{page}"),10)
 if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
 checked+=1;soup=BeautifulSoup(pr.text,"html.parser")
 assets=[]
 for a in soup.find_all("a",href=True):
  ref=a["href"]
  if re.search(r"(?:^|/)assets/[^?#]+\.(?:jpe?g|png)(?:\?|$)",ref,re.I):
   u=urljoin(page,ref)
   if u not in assets:assets.append(u)
 if len(assets)>=3:
  cands["richmond_castle"].append(assets[0]);cands["richmond_castle_plan"].append(assets[2])
  page_records.append({"source":source,"timestamp":ts,"assets":assets[:7]})
 # semantic refs, including case variants
 for tag in soup.find_all(["a","img"]):
  for attr in ("href","data-src","data-orig-src","data-muse-src"):
   ref=tag.get(attr)
   if not ref:continue
   leaf=Path(urlparse(ref).path).name.lower()
   if leaf.startswith("richmond_castle_plan") and re.search(r"\.(png|jpg|jpeg)$",leaf):cands["richmond_castle_plan"].append(urljoin(page,ref))
   elif re.fullmatch(r"richmond_castle(?:\d+x\d+)?\.(?:jpg|jpeg|png)",leaf):cands["richmond_castle"].append(urljoin(page,ref))

# explicit current/legacy filename families and case variants
hero_names=["richmond_castle.jpg","Richmond_Castle.jpg","Richmond_Castle.JPG","RICHMOND_CASTLE.JPG","richmond-castle.jpg","richmond_castle665x281.jpg"]
plan_names=["richmond_castle_plan.png","Richmond_Castle_Plan.png","Richmond_Castle_Plan.PNG","RICHMOND_CASTLE_PLAN.PNG","richmond-castle-plan.png","richmond_castle_plan322x239.png","richmond_castle_plan321x239.png","richmond_castle_plan242x180.png"]
for ident,names in [("richmond_castle",hero_names),("richmond_castle_plan",plan_names)]:
 for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
   for d in ("yorkshire/assets","yorkshire/images","assets","images","yorkshire/wpimages","wpimages"):
    for name in names:cands[ident].append(f"{scheme}://{host}/{d}/{name}")
# dedupe
for k in cands:
 ss=set();cands[k]=[u for u in cands[k] if not (u in ss or ss.add(u))]

def search(ident,u):
 caps=timemap("wayback",u)+timemap("arquivo",u)
 if caps:
  caps.sort(key=lambda x:x[1]);inds={0,len(caps)-1,len(caps)//2}
  for i in sorted(inds,reverse=True):
   src,ts,orig=caps[i];got=replay(src,ts,orig)
   if got:return ident,u,src,ts,orig,got
 for a in ("2","0","20221231235959","20211208101939","20191231235959","20171231235959","20151231235959"):
  for mode in ("id_","im_"):
   ep=f"https://web.archive.org/web/{a}{mode}/{u}";r=get(ep,7)
   if r and r.status_code==200:
    z=info(r.content)
    if z:return ident,u,"wayback","nearest",u,(r.content,z,r.url)
 return None

jobs={}
with ThreadPoolExecutor(max_workers=16) as ex:
 for ident,urls in cands.items():
  for u in urls:jobs[ex.submit(search,ident,u)]=(ident,u)
 results={k:[] for k in TARGETS}
 for fut in as_completed(jobs):
  got=fut.result()
  if got:
   ident,u,src,ts,orig,(b,z,final)=got
   q="full/near-full" if ("/assets/" in urlparse(u).path.lower() and not re.search(r"\d+x\d+",Path(urlparse(u).path).stem)) else "thumbnail/lower-resolution"
   results[ident].append(((2 if q=="full/near-full" else 1,z[0]*z[1]),u,src,ts,orig,b,z,final,q))

r=json.loads(REP.read_text());found={x["identity"]:x for x in r.get("images",[])}
new=[]
for ident in TARGETS:
 if not results[ident]:continue
 _,u,src,ts,orig,b,z,final,q=max(results[ident],key=lambda x:x[0])
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(ident+ext);p.write_bytes(b)
 found[ident]={"identity":ident,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":orig,"archive_replay":final,
 "method":"historical-standalone-position-plus-exact-image-timemap","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
 "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
 new.append(ident);print("RECOVERED",ident,orig,z,q,flush=True)

# Correct quality classification for CDX base slideshow files: high-resolution base filenames are near-full originals;
# the two clear Muse retina display exports remain lower-resolution.
for ident,x in found.items():
 if ident in ("richmond_castle4c","richmond_castle6a"):x["quality"]="thumbnail/lower-resolution"
 elif ident not in ("richmond_castle","richmond_castle_plan") and max(x.get("dimensions",[0,0]))>=1500:x["quality"]="full/near-full"

order=r["desktop_image_identities"]
r["images"]=[found[c] for c in order if c in found]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old.get(c,{"identity":c,"candidate_urls":cands.get(c,[])}) for c in order if c not in found]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]);r["status"]="COMPLETE" if not r["still_missing"] else "PARTIAL"
r["targeted_two_missing_recovery_2026_09_15"]={"completed":True,"page_captures_found":len(caps),"page_captures_checked":checked,
"historical_asset_position_records":page_records,"candidate_counts":{k:len(v) for k,v in cands.items()},"recovered_now":new}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"new":new,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
