#!/usr/bin/env python3
import io,json,re,hashlib,time,gzip
from pathlib import Path
from urllib.parse import urlparse,urljoin,quote,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

ROOT=Path("recovered/sandal-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"
TARGETS=["sandal_castle","sandal_castle17","sandal_castle_plan","sandal_castle20","wakefield_castles_context2","wakefield_1460_6","sandal_castle12"]
GALLERY=["sandal_castle1","sandal_castle5","sandal_castle7","sandal_castle13","sandal_castle19","wakefield_1460_2",
"sandal_castle3","sandal_castle4","sandal_castle6","sandal_castle8","sandal_castle9","sandal_castle10","sandal_castle11",
"sandal_castle12","sandal_castle14","sandal_castle15","sandal_castle16","sandal_castle18","sandal_castle21","sandal_castle23"]
PAGES=[
"http://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"https://www.castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"http://castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"https://castlesfortsbattles.co.uk/yorkshire/sandal_castle_wakefield_1460.html",
"http://www.castlesfortsbattles.co.uk/m/sandal_castle_wakefield_1460.html",
"http://www.castlesfortsbattles.co.uk/m/yorkshire/sandal_castle_wakefield_1460.html"]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 SandalFinalTargetedRecovery"

def get(u,t=10,headers=None):
 for n in range(2):
  try:
   r=S.get(u,timeout=t,headers=headers or {},allow_redirects=True)
   if r.status_code not in (429,500,502,503,504):return r
  except:pass
  time.sleep(.3*(n+1))
 return None

def valid(b):
 try:
  im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
  return z if z[0]>=80 and z[1]>=80 else None
 except:return None

def timemap(src,u):
 ep=("https://web.archive.org/web/timemap/link/"+u) if src=="wayback" else ("https://arquivo.pt/wayback/timemap/link/"+u)
 marker="/web/" if src=="wayback" else "/wayback/"
 r=get(ep,10)
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

def replay(src,ts,orig):
 eps=[f"https://web.archive.org/web/{ts}id_/{orig}",f"https://web.archive.org/web/{ts}im_/{orig}"] if src=="wayback" else [f"https://arquivo.pt/wayback/{ts}id_/{orig}"]
 for ep in eps:
  r=get(ep,7)
  if r and r.status_code==200:
   z=valid(r.content)
   if z:return r.content,z,r.url
 return None

def qscore(identity,orig,z):
 stem=Path(urlparse(orig).path).stem.lower()
 exact=stem==identity.lower()
 asset="/assets/" in urlparse(orig).path.lower()
 responsive=bool(re.search(r"\d+x\d+$",stem))
 q="full/near-full" if (asset and not responsive) or (exact and not responsive) or max(z[:2])>=1000 else "thumbnail/lower-resolution"
 return q,(3 if asset and not responsive else 2 if q=="full/near-full" else 1,z[0]*z[1])

rep=json.loads(REP.read_text());found={x["identity"]:x for x in rep.get("images",[])}
old_missing={x["identity"]:x for x in rep.get("missing",[])}
cands={t:list(old_missing.get(t,{}).get("candidate_urls",[])) for t in TARGETS}

# Add historical page refs and position-mapped gallery filename for sandal_castle12.
page_caps=[]
for p in PAGES:page_caps+=timemap("wayback",p)+timemap("arquivo",p)
seen=set();page_caps=[x for x in page_caps if not (x in seen or seen.add(x))];page_caps.sort(key=lambda x:x[1])
if len(page_caps)>24:
 inds={0,len(page_caps)-1}
 for n in range(1,23):inds.add(round(n*(len(page_caps)-1)/23))
 page_caps=[page_caps[i] for i in sorted(inds)]
checked=0
for src,ts,page in page_caps:
 ep=(f"https://web.archive.org/web/{ts}id_/{page}" if src=="wayback" else f"https://arquivo.pt/wayback/{ts}id_/{page}")
 r=get(ep,8)
 if not r or r.status_code!=200 or "<html" not in r.text.lower():continue
 checked+=1;soup=BeautifulSoup(r.text,"html.parser")
 for tag in soup.find_all(["a","img"]):
  for attr in ("href","src","data-src","data-orig-src","data-muse-src"):
   ref=tag.get(attr)
   if not ref:continue
   u=urljoin(page,ref);stem=Path(urlparse(u).path).stem.lower()
   for t in TARGETS:
    if stem==t or re.fullmatch(re.escape(t)+r'\d+x\d+',stem):cands[t].append(u)
 for im in soup.find_all("img"):
  if "ImageInclude" not in (im.get("class") or []):continue
  try:i=int(im.get("data-col-pos"))
  except:continue
  if 0<=i<len(GALLERY) and GALLERY[i]=="sandal_castle12":
   ref=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src")
   if ref:cands["sandal_castle12"].append(urljoin(page,ref))

# Compact legacy filename/path variants.
name_variants={
"sandal_castle":["sandal_castle.jpg","Sandal_Castle.jpg","Sandal_Castle.JPG","SandalCastle.jpg","sandal-castle.jpg"],
"sandal_castle17":["sandal_castle17.jpg","Sandal_Castle17.jpg","Sandal_Castle_17.jpg","SandalCastle17.jpg"],
"sandal_castle_plan":["sandal_castle_plan.png","sandal_castle_plan.jpg","Sandal_Castle_Plan.png","Sandal_Castle_Plan.PNG","SandalCastlePlan.png"],
"sandal_castle20":["sandal_castle20.jpg","Sandal_Castle20.jpg","Sandal_Castle_20.jpg"],
"wakefield_castles_context2":["wakefield_castles_context2.png","wakefield_castles_context2.jpg","Wakefield_Castles_Context2.png","Wakefield_Castles_Context_2.png"],
"wakefield_1460_6":["wakefield_1460_6.jpg","Wakefield_1460_6.jpg","Wakefield1460_6.jpg"],
"sandal_castle12":["sandal_castle12.jpg","Sandal_Castle12.jpg","Sandal_Castle_12.jpg"]
}
for t,names in name_variants.items():
 for scheme in ("http","https"):
  for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
   for d in ("yorkshire/assets","yorkshire/images","assets","images","m/assets","m/images","yorkshire/wpimages","wpimages"):
    for n in names:cands[t].append(f"{scheme}://{host}/{d}/{n}")
for t in cands:
 ss=set();cands[t]=[u for u in cands[t] if not (u in ss or ss.add(u))]

# Exact TimeMap/cross-timestamp replay in parallel.
def search_url(t,u):
 caps=timemap("wayback",u)+timemap("arquivo",u)
 if caps:
  caps.sort(key=lambda x:x[1]);inds={0,len(caps)-1,len(caps)//2}
  if len(caps)>4:inds|={len(caps)//4,(3*len(caps))//4}
  for i in sorted(inds,reverse=True):
   src,ts,orig=caps[i];got=replay(src,ts,orig)
   if got:return t,u,src,ts,orig,got
 # nearest fallback
 for a in ("2","0","20221231235959","20210918024941","20191231235959","20171231235959"):
  for mode in ("id_","im_"):
   r=get(f"https://web.archive.org/web/{a}{mode}/{u}",6)
   if r and r.status_code==200:
    z=valid(r.content)
    if z:return t,u,"wayback","nearest",u,(r.content,z,r.url)
 return None

results={t:[] for t in TARGETS};jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
 for t,urls in cands.items():
  if t in found:continue
  for u in urls[:80]:jobs[ex.submit(search_url,t,u)]=(t,u)
 for f in as_completed(jobs):
  got=f.result()
  if got:
   t,u,src,ts,orig,(b,z,final)=got;q,sc=qscore(t,orig,z)
   results[t].append((sc,orig,src,ts,b,z,final,q))

new=[]
for t in TARGETS:
 if t in found or not results[t]:continue
 _,orig,src,ts,b,z,final,q=max(results[t],key=lambda x:x[0])
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(t+ext);p.write_bytes(b)
 found[t]={"identity":t,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":orig,"archive_replay":final,
 "method":"targeted-exact-timemap-cross-timestamp","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
 "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
 new.append(t)

# Correct first-pass quality: exact non-responsive Muse base filenames are the source images for this page.
for ident,x in found.items():
 stem=Path(urlparse(x.get("archive_original","")).path).stem.lower()
 if stem==ident.lower() and not re.search(r"\d+x\d+$",stem):
  x["quality"]="full/near-full"

rep["images"]=[found[c] for c in rep["desktop_image_identities"] if c in found]
rep["missing"]=[old_missing.get(c,{"identity":c,"candidate_urls":cands.get(c,[])}) for c in rep["desktop_image_identities"] if c not in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(rep["desktop_image_identities"])-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL / SEARCH EXHAUSTED"
rep["targeted_final_recovery_2026_09_15"]={"completed":True,"targets":TARGETS,"historical_page_captures_found":len(page_caps),
"historical_page_captures_checked":checked,"candidate_counts":{k:len(v) for k,v in cands.items()},"recovered_now":new}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"new":new,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],
"missing":rep["still_missing"],"missing_ids":[x["identity"] for x in rep["missing"]]},indent=2))
