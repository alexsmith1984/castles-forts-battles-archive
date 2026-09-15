#!/usr/bin/env python3
import io,json,re,hashlib
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image

ROOT=Path("recovered/richmond-castle");REP=ROOT/"recovery-report.json";IMG=ROOT/"images";IMG.mkdir(exist_ok=True)
CANON=[
 "richmond_castle","richmond_castle9","richmond_castle_plan","richmond_castle7","richmond_castle4c","richmond_castle6a","richmond_castle14b",
 "richmond_castle1","richmond_castle2b","richmond_castle3a","richmond_castle3b","richmond_castle4a","richmond_castle4b","richmond_castle4d",
 "richmond_castle5","richmond_castle8","richmond_castle10","richmond_castle11","richmond_castle12","richmond_castle13","richmond_castle14a",
 "richmond_castle14c","richmond_castle15","richmond_castle16a","richmond_castle16b","richmond_castle17","richmond_castle18"]
ALIASES={"richmond_castle7":["richmond_castle7","richmond_castle72"],"richmond_castle9":["richmond_castle9","richmond_castle92"],
"richmond_castle14b":["richmond_castle14b","richmond_castle14b2"],"richmond_castle4c":["richmond_castle4c","richmond_castle4c2"],
"richmond_castle6a":["richmond_castle6a","richmond_castle6a2"]}
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 RichmondCDXFamilyRecovery"

def info(b):
 try:
  im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
  return z if z[0]>=80 and z[1]>=80 else None
 except:return None

def canon(original):
 stem=Path(urlparse(original).path).stem.lower()
 for c in CANON:
  for a in ALIASES.get(c,[c]):
   if stem==a.lower() or re.fullmatch(re.escape(a.lower())+r'\d+x\d+',stem):return c
 return None

def cdx(pattern):
 u="https://web.archive.org/cdx/search/cdx"
 params={"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest","filter":["statuscode:200"],"collapse":"digest","limit":"3000"}
 try:
  r=S.get(u,params=params,timeout=25)
  if r.status_code!=200:return []
  j=r.json()
  if not j or len(j)<2:return []
  hdr=j[0];return [dict(zip(hdr,row)) for row in j[1:]]
 except:return []

patterns=[]
for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
 for d in ("yorkshire/images","yorkshire/assets","images","assets","m/images","m/assets"):
  patterns.append(f"{host}/{d}/richmond_castle*")

rows=[]
for p in patterns:
 rr=cdx(p);print("CDX",p,len(rr),flush=True);rows+=rr
seen=set();rows=[x for x in rows if not ((x["timestamp"],x["original"],x.get("digest")) in seen or seen.add((x["timestamp"],x["original"],x.get("digest"))))]
mapped={c:[] for c in CANON}
for x in rows:
 c=canon(x["original"])
 if c:mapped[c].append(x)

def replay(row):
 ts=row["timestamp"];orig=row["original"]
 for mode in ("id_","im_"):
  try:
   r=S.get(f"https://web.archive.org/web/{ts}{mode}/{orig}",timeout=10,allow_redirects=True)
   if r.status_code==200:
    z=info(r.content)
    if z:return row,r.content,z,r.url
  except:pass
 return None

found={x["identity"]:x for x in json.loads(REP.read_text()).get("images",[])}
jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
 for c,rr in mapped.items():
  if c in found:continue
  # try up to 12 distinct captures per identity; assets first, then chronological spread
  rr=sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x["original"]).path.lower() else 1,x["timestamp"]))
  if len(rr)>12:
   inds={0,len(rr)-1}
   for n in range(1,11):inds.add(round(n*(len(rr)-1)/11))
   rr=[rr[i] for i in sorted(inds)]
  for row in rr:jobs[ex.submit(replay,row)]=c
 results={c:[] for c in CANON}
 for fut in as_completed(jobs):
  c=jobs[fut];got=fut.result()
  if got:
   row,b,z,final=got
   q="full/near-full" if "/assets/" in urlparse(row["original"]).path.lower() else "thumbnail/lower-resolution"
   score=(2 if q=="full/near-full" else 1,z[0]*z[1])
   results[c].append((score,row,b,z,final,q))

new=[]
for c in CANON:
 if c in found or not results[c]:continue
 _,row,b,z,final,q=max(results[c],key=lambda x:x[0])
 ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
 found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":row["timestamp"],"archive_original":row["original"],
 "archive_replay":final,"method":"wayback-cdx-wildcard-filename-family","dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
 "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
 new.append(c);print("RECOVERED",c,row["timestamp"],row["original"],z,q,flush=True)

r=json.loads(REP.read_text())
r["images"]=[found[c] for c in CANON if c in found]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old.get(c,{"identity":c,"candidate_urls":[]}) for c in CANON if c not in found]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(CANON)-len(r["images"]);r["status"]="COMPLETE" if not r["still_missing"] else "PARTIAL"
r["cdx_wildcard_family_recovery_2026_09_15"]={"completed":True,"patterns":patterns,"rows_found":len(rows),
"mapped_capture_counts":{c:len(mapped[c]) for c in CANON},"recovered_now":new}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"rows":len(rows),"new":new,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"]},indent=2))
