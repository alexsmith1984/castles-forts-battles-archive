#!/usr/bin/env python3
import io,json,re,gzip,hashlib
from pathlib import Path
from urllib.parse import quote,urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image

ROOT=Path("recovered/richmond-castle");REP=ROOT/"recovery-report.json";IMG=ROOT/"images"
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 RichmondCommonCrawlFinal"

def get(u,t=10,headers=None):
    try:return S.get(u,timeout=t,headers=headers or {},allow_redirects=True)
    except:return None
def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=80 else None
    except:return None
def urls(names,dirs):
    out=[]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
       for d in dirs:
        for n in names:out.append(f"{scheme}://{host}/{d}/{n}")
    return list(dict.fromkeys(out))

targets={
 "richmond_castle":urls(
   ["richmond_castle.jpg","Richmond_Castle.jpg","Richmond_Castle.JPG","RICHMOND_CASTLE.JPG","richmond-castle.jpg","richmond_castle665x281.jpg"],
   ["yorkshire/assets","yorkshire/images","assets","images","yorkshire/wpimages","wpimages"]),
 "richmond_castle_plan":urls(
   ["richmond_castle_plan.png","Richmond_Castle_Plan.png","Richmond_Castle_Plan.PNG","RICHMOND_CASTLE_PLAN.PNG","richmond-castle-plan.png","richmond_castle_plan322x239.png","richmond_castle_plan321x239.png","richmond_castle_plan242x180.png"],
   ["yorkshire/assets","yorkshire/images","assets","images","yorkshire/wpimages","wpimages"]),
 "richmond_castle4c":urls(["richmond_castle4c.jpg","richmond_castle4c2.jpg"],["yorkshire/assets","assets","yorkshire/images","images"]),
 "richmond_castle6a":urls(["richmond_castle6a.jpg","richmond_castle6a2.jpg"],["yorkshire/assets","assets","yorkshire/images","images"])
}

rr=get("https://index.commoncrawl.org/collinfo.json",10);indexes=[]
if rr and rr.status_code==200:
    try:
        by={}
        for x in rr.json():
            m=re.search(r"CC-MAIN-(\d{4})-",x.get("id",""))
            if m and 2014<=int(m.group(1))<=2023:by.setdefault(m.group(1),[]).append(x["id"])
        indexes=[sorted(by[y],reverse=True)[0] for y in sorted(by)]
    except:pass

def query(iid,u):
    ep=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/?=&")+"&output=json"
    r=get(ep,7)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        try:
            x=json.loads(line)
            if str(x.get("status"))=="200" and all(x.get(k) for k in ("filename","offset","length")):out.append(x)
        except:pass
    return out

def payload(x):
    try:
        st=int(x["offset"]);ln=int(x["length"])
        r=get("https://data.commoncrawl.org/"+x["filename"],15,{"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):return None
        raw=gzip.decompress(r.content)
        for part in reversed(raw.split(b"\r\n\r\n")):
            z=valid(part)
            if z:return part,z
    except:pass
    return None

rep=json.loads(REP.read_text());found={x["identity"]:x for x in rep.get("images",[])}
meta={};updates=[]
for identity,cands in targets.items():
    recs=[]
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs=[ex.submit(query,i,u) for i in indexes for u in cands]
        for f in as_completed(futs):
            try:recs.extend(f.result())
            except:pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs}
    recs=list(uniq.values());meta[identity]={"candidate_urls":len(cands),"records":len(recs)}
    best=None
    for x in sorted(recs,key=lambda q:int(q.get("length") or 0),reverse=True)[:40]:
        got=payload(x)
        if not got:continue
        b,z=got;orig=x.get("url") or "";stem=Path(urlparse(orig).path).stem
        q="full/near-full" if ("/assets/" in urlparse(orig).path.lower() and not re.search(r"\d+x\d+$",stem)) else "thumbnail/lower-resolution"
        if max(z[:2])>=1500 and not re.search(r"\d+x\d+$",stem):q="full/near-full"
        score=(2 if q=="full/near-full" else 1,z[0]*z[1])
        if best is None or score>best[0]:best=(score,x,b,z,q)
    if not best:continue
    _,x,b,z,q=best;cur=found.get(identity);curarea=0 if not cur else cur["dimensions"][0]*cur["dimensions"][1]
    accept=cur is None or (cur.get("quality")!="full/near-full" and q=="full/near-full") or (q==cur.get("quality") and z[0]*z[1]>curarea)
    if not accept:continue
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(identity+ext);p.write_bytes(b)
    found[identity]={"identity":identity,"file":"images/"+p.name,"archive_timestamp":x.get("timestamp"),"archive_original":x.get("url"),
      "method":"common-crawl-exact-filename-family","commoncrawl_warc":x.get("filename"),"dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    updates.append(identity);print("RECOVERED/UPGRADED",identity,x.get("url"),z,q,flush=True)

# Correct the known CDX quality classification from actual recovered dimensions/Muse role.
for ident,x in found.items():
    if ident in ("richmond_castle4c","richmond_castle6a") and ident not in updates:
        x["quality"]="thumbnail/lower-resolution"
    elif ident not in ("richmond_castle","richmond_castle_plan") and max(x.get("dimensions",[0,0]))>=1500:
        x["quality"]="full/near-full"

order=rep["desktop_image_identities"]
rep["images"]=[found[i] for i in order if i in found]
old={x["identity"]:x for x in rep.get("missing",[])}
rep["missing"]=[old.get(i,{"identity":i,"candidate_urls":targets.get(i,[])}) for i in order if i not in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(order)-len(rep["images"]);rep["status"]="COMPLETE" if rep["still_missing"]==0 else "PARTIAL"
rep["commoncrawl_final_recovery_2026_09_15"]={"completed":True,"indexes_checked":indexes,"targets":meta,"recovered_or_upgraded":updates}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"indexes":indexes,"updates":updates,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],"missing":rep["still_missing"]},indent=2))
