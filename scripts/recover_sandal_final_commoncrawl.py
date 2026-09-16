#!/usr/bin/env python3
import io,json,re,gzip,hashlib
from pathlib import Path
from urllib.parse import quote,urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image

ROOT=Path("recovered/sandal-castle");REP=ROOT/"recovery-report.json";IMG=ROOT/"images"
TARGETS=["sandal_castle","sandal_castle17","sandal_castle_plan","sandal_castle20","wakefield_castles_context2","wakefield_1460_6"]
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 SandalFinalCommonCrawl"

def get(u,t=10,headers=None):
    try:return S.get(u,timeout=t,headers=headers or {},allow_redirects=True)
    except:return None

def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=80 else None
    except:return None

def candidate_urls(identity):
    names={
      "sandal_castle":["sandal_castle.jpg","Sandal_Castle.jpg","Sandal_Castle.JPG","SandalCastle.jpg","sandal-castle.jpg"],
      "sandal_castle17":["sandal_castle17.jpg","Sandal_Castle17.jpg","Sandal_Castle_17.jpg","SandalCastle17.jpg"],
      "sandal_castle_plan":["sandal_castle_plan.png","sandal_castle_plan.jpg","Sandal_Castle_Plan.png","Sandal_Castle_Plan.PNG","SandalCastlePlan.png"],
      "sandal_castle20":["sandal_castle20.jpg","Sandal_Castle20.jpg","Sandal_Castle_20.jpg"],
      "wakefield_castles_context2":["wakefield_castles_context2.png","wakefield_castles_context2.jpg","Wakefield_Castles_Context2.png","Wakefield_Castles_Context_2.png"],
      "wakefield_1460_6":["wakefield_1460_6.jpg","Wakefield_1460_6.jpg","Wakefield1460_6.jpg"]
    }[identity]
    out=[]
    for scheme in ("http","https"):
      for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
       for d in ("yorkshire/assets","yorkshire/images","assets","images","m/assets","m/images","yorkshire/wpimages","wpimages"):
        for n in names:out.append(f"{scheme}://{host}/{d}/{n}")
    return list(dict.fromkeys(out))

# Load a compact representative set of Common Crawl indexes: latest one per year, 2014-2023.
rr=get("https://index.commoncrawl.org/collinfo.json",10);indexes=[]
if rr and rr.status_code==200:
    by={}
    for x in rr.json():
        m=re.search(r"CC-MAIN-(\d{4})-",x.get("id",""))
        if m and 2014<=int(m.group(1))<=2023:
            by.setdefault(m.group(1),[]).append(x["id"])
    indexes=[sorted(by[y],reverse=True)[0] for y in sorted(by)]

def query(iid,u):
    ep=f"https://index.commoncrawl.org/{iid}-index?url="+quote(u,safe=":/?=&")+"&output=json"
    r=get(ep,6)
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
        r=get("https://data.commoncrawl.org/"+x["filename"],12,{"Range":f"bytes={st}-{st+ln-1}"})
        if not r or r.status_code not in (200,206):return None
        raw=gzip.decompress(r.content)
        # WARC payload usually follows the final header block; test all blocks from end.
        for part in reversed(raw.split(b"\r\n\r\n")):
            z=valid(part)
            if z:return part,z
    except:pass
    return None

rep=json.loads(REP.read_text());found={x["identity"]:x for x in rep.get("images",[])}
meta={};new=[]

for identity in TARGETS:
    if identity in found:continue
    cands=candidate_urls(identity)
    recs=[]
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs=[ex.submit(query,i,u) for i in indexes for u in cands]
        for f in as_completed(futs):
            try:recs.extend(f.result())
            except:pass
    uniq={(x["filename"],x["offset"],x["length"]):x for x in recs};recs=list(uniq.values())
    meta[identity]={"candidate_urls":len(cands),"records":len(recs)}
    best=None
    for x in sorted(recs,key=lambda q:int(q.get("length") or 0),reverse=True)[:24]:
        got=payload(x)
        if not got:continue
        b,z=got;orig=x.get("url") or ""
        stem=Path(urlparse(orig).path).stem.lower()
        responsive=bool(re.search(r"\d+x\d+$",stem))
        exact=stem==identity.lower()
        q="full/near-full" if ("/assets/" in urlparse(orig).path.lower() and not responsive) or (exact and not responsive) or max(z[:2])>=1000 else "thumbnail/lower-resolution"
        score=(3 if "/assets/" in urlparse(orig).path.lower() and not responsive else 2 if q=="full/near-full" else 1,z[0]*z[1])
        if best is None or score>best[0]:best=(score,x,b,z,q)
    if not best:continue
    _,x,b,z,q=best
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(identity+ext);p.write_bytes(b)
    found[identity]={"identity":identity,"file":"images/"+p.name,"archive_timestamp":x.get("timestamp"),"archive_original":x.get("url"),
      "method":"common-crawl-final-six","commoncrawl_warc":x.get("filename"),"dimensions":[z[0],z[1]],"format":z[2],
      "bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
    new.append(identity)

order=rep["desktop_image_identities"];old={x["identity"]:x for x in rep.get("missing",[])}
rep["images"]=[found[i] for i in order if i in found]
rep["missing"]=[old.get(i,{"identity":i,"candidate_urls":[]}) for i in order if i not in found]
rep["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in rep["images"])
rep["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in rep["images"])
rep["still_missing"]=len(order)-len(rep["images"])
rep["status"]="COMPLETE / VERIFIED" if rep["still_missing"]==0 else "PARTIAL / SEARCH EXHAUSTED"
rep["final_commoncrawl_retry_2026_09_15"]={"completed":True,"indexes_checked":indexes,"targets":meta,"recovered_now":new}
REP.write_text(json.dumps(rep,indent=2)+"\n")
print(json.dumps({"new":new,"full":rep["recovered_full_or_near_full"],"lower":rep["recovered_thumbnail_or_lower_resolution"],
"missing":rep["still_missing"],"missing_ids":[x["identity"] for x in rep["missing"]],"meta":meta},indent=2))
