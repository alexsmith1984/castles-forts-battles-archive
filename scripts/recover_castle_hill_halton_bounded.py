#!/usr/bin/env python3
import io,json,re,hashlib,time,html as H
from pathlib import Path
from urllib.parse import urlparse,urljoin,urlunparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

NAME="Castle Hill, Halton (Halton Castle)"
SLUG="castle-hill-halton"
TS="20200708105528"
ORIG="http://www.castlesfortsbattles.co.uk:80/north_west/halton_castle_motte.html"
OUT=Path("recovered")/SLUG; IMG=OUT/"images"; IMG.mkdir(parents=True,exist_ok=True)
DEADLINE=time.monotonic()+420
S=requests.Session();S.headers["User-Agent"]="Mozilla/5.0 HaltonCastleRecovery"

def alive(): return time.monotonic()<DEADLINE
def get(u,t=7,params=None):
    if not alive():return None
    try:return S.get(u,params=params,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None
def valid(b):
    try:
        im=Image.open(io.BytesIO(b));z=(im.width,im.height,im.format);im.verify()
        return z if z[0]>=80 and z[1]>=60 else None
    except:return None
def stem(u):
    s=Path(urlparse(u).path).stem
    s=re.sub(r'(\d{2,4})x(\d{2,4})$','',s)
    return s
def relevant(s):
    sl=s.lower()
    return sl.startswith("halton_castle_motte") or sl.startswith("norman_castle_lune_valley_map")
def replay(ts,u):
    for mode in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mode}/{u}",5)
        if r and r.status_code==200:
            z=valid(r.content)
            if z:return r.content,z,r.url
    return None
def cdx(pattern,limit=1000):
    r=get("https://web.archive.org/cdx/search/cdx",7,{"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest",
      "filter":"statuscode:200","collapse":"digest","from":"2014","to":"2023","limit":str(limit)})
    if not r or r.status_code!=200:return []
    try:
        j=r.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []
def timemap(u):
    r=get("https://web.archive.org/web/timemap/link/"+u,6)
    if not r or r.status_code!=200:return []
    out=[]
    for line in r.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        v=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/web/(\d{14})[^/]*/(.+)$",v)
        if m:out.append((m.group(1),m.group(2)))
    return out

r=get(f"https://web.archive.org/web/{TS}id_/{ORIG}",15)
if not r or r.status_code!=200 or "<html" not in r.text.lower():raise SystemExit("Halton source unavailable")
raw=r.text;(OUT/"source.html").write_text(raw,encoding="utf-8",errors="replace")
soup=BeautifulSoup(raw,"html.parser")

# Only Halton/Motte and Lune Valley map identities. Explicitly exclude unrelated embedded Whittington gallery.
refs=[]
IMGEXT=re.compile(r'\.(?:jpe?g|png|gif|webp)(?:\?|$)',re.I)
for a in soup.find_all("a",href=True):
    v=a.get("href","")
    if a.find("img") and IMGEXT.search(v):
        u=urljoin(ORIG,v);s=stem(u)
        if relevant(s):refs.append(("asset-link",u,s))
for im in soup.find_all("img"):
    for attr in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
        v=im.get(attr)
        if not v or v.startswith("data:") or "blank.gif" in v.lower() or not IMGEXT.search(v):continue
        u=urljoin(ORIG,v);s=stem(u)
        if relevant(s):refs.append(("display",u,s))

ORDER=[]
for kind,u,s in refs:
    if s not in ORDER:ORDER.append(s)

# Ensure source-page identities are in stable content order.
candidates={i:[] for i in ORDER}
for kind,u,s in refs:
    if s in candidates:candidates[s].append(u)

def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',Path(urlparse(u).path).stem.lower()))
def quality(c,u,z):
    p=urlparse(u).path.lower();st=Path(p).stem.lower()
    if ("/assets/" in p or st==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=900:return "full/near-full"
    return "thumbnail/lower-resolution"
def score(c,u,z,q):
    p=urlparse(u).path.lower();st=Path(p).stem.lower()
    return (4 if "/assets/" in p and not responsive(c,u) else 3 if st==c.lower() and not responsive(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

results={i:[] for i in ORDER}
# Source capture direct replay.
jobs={}
with ThreadPoolExecutor(max_workers=16) as ex:
    for c,urls in candidates.items():
        for u in list(dict.fromkeys(urls)):
            jobs[ex.submit(replay,TS,u)]=(c,TS,u,"same-capture")
            # inferred original full asset
            base=urlparse(u)
            for ext in ("jpg","png"):
                iu=urlunparse(("http","www.castlesfortsbattles.co.uk",f"/north_west/assets/{c}.{ext}","","",""))
                jobs[ex.submit(replay,TS,iu)]=(c,TS,iu,"same-capture-inferred-asset")
    for f in as_completed(jobs):
        if not alive():break
        c,ts,u,meth=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(c,u,z);results[c].append((score(c,u,z,q),ts,u,b,z,final,q,meth))

# High-yield CDX filename-family search for only genuine Halton/map identities.
rows={c:[] for c in ORDER}
patterns=[]
for c in ORDER:
    for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
      for d in ("north_west/assets","north_west/images","assets","images","m/assets","m/images"):
       for ext in ("jpg","jpeg","png"):patterns.append((c,f"{host}/{d}/{c}*.{ext}*"))
with ThreadPoolExecutor(max_workers=16) as ex:
    fs={ex.submit(cdx,p,500):(c,p) for c,p in patterns}
    for f in as_completed(fs):
        if not alive():break
        c,p=fs[f]
        try:rows[c]+=f.result()
        except:pass

jobs={}
with ThreadPoolExecutor(max_workers=16) as ex:
    for c,rr in rows.items():
        seen=set();ded=[]
        for x in sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x.get("original","")).path.lower() else 1,
                                        1 if responsive(c,x.get("original","")) else 0,x.get("timestamp",""))):
            k=(x.get("timestamp"),x.get("original"))
            if not x.get("timestamp") or not x.get("original") or k in seen:continue
            seen.add(k);ded.append(x)
        for x in ded[:20]:jobs[ex.submit(replay,x["timestamp"],x["original"])]=(c,x)
    for f in as_completed(jobs):
        if not alive():break
        c,x=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;u=x["original"];q=quality(c,u,z);results[c].append((score(c,u,z,q),x["timestamp"],u,b,z,final,q,"wayback-cdx-identity-family"))

# One exact historical TimeMap pass for anything still unrecovered.
for c in ORDER:
    if results[c] or not alive():continue
    urls=list(dict.fromkeys(candidates[c]))
    for u in urls[:12]:
        for ts,orig in timemap(u)[:12]:
            got=replay(ts,orig)
            if got:
                b,z,final=got;q=quality(c,orig,z);results[c].append((score(c,orig,z,q),ts,orig,b,z,final,q,"exact-timemap"))
                if q=="full/near-full":break
        if results[c]:break

images=[];missing=[]
for c in ORDER:
    if not results[c]:
        missing.append({"identity":c,"candidate_urls":list(dict.fromkeys(candidates[c]))})
        continue
    sc,ts,u,b,z,final,q,meth=max(results[c],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
    images.append({"identity":c,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,"archive_replay":final,
      "method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":q,"identification":"certain"})

# Collapse exact duplicate image bytes if map/map2 are actually the same archived image.
byhash={};dupes=[]
for x in images:
    h=x["sha256"]
    if h in byhash:
        dupes.append((x["identity"],byhash[h]["identity"]))
    else:byhash[h]=x
if dupes:
    duplicate_ids={a for a,b in dupes}
    images=[x for x in images if x["identity"] not in duplicate_ids]
    ORDER=[x for x in ORDER if x not in duplicate_ids]
    missing=[x for x in missing if x["identity"] not in duplicate_ids]

full=sum(x["quality"]=="full/near-full" for x in images);lower=len(images)-full
status="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"

# Preserve readable text from source.
for x in soup(["script","style","noscript"]):x.decompose()
nav={"England","Scotland","Wales","Home","UK Map","A-Z","Links","About Us","Contact Us","Terms and Conditions","CastlesFortsBattles.co.uk","BattlefieldsofBritain.co.uk"}
blocks=[];seen=set()
for e in soup.find_all(["h1","h2","h3","h4","p","li"]):
    tx=" ".join(e.stripped_strings).strip();key=re.sub(r"\s+"," ",tx).casefold()
    if not tx or tx in nav or key in seen or tx.lower() in ("tweet","share","follow"):continue
    seen.add(key);blocks.append((e.name,tx))
body=[]
for tag,tx in blocks:
    if tag.startswith("h") or (len(tx)<95 and re.match(r"^(History|Historical Background|Description|Design|Gallery|Getting There|What.s There|Location|Halton|Castle Hill)",tx,re.I)):
        body.append(f"<h2>{H.escape(tx)}</h2>")
    elif tag=="li":body.append(f"<p>• {H.escape(tx)}</p>")
    else:body.append(f"<p>{H.escape(tx)}</p>")
figs=[]
for x in images:
    cap=x["identity"].replace("_"," ")
    if x["quality"]!="full/near-full":cap+=" — lower-resolution archived recovery"
    figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="{H.escape(NAME)} archived original image"></a><figcaption>{H.escape(cap)}</figcaption></figure>')
note=f"Recovered from the archived CastlesFortsBattles Halton Castle page. {len(images)} of {len(ORDER)} unique Halton/map content images have been recovered; {len(missing)} remain unavailable. An unrelated embedded Whittington Castle gallery in the archived source is excluded. No substitute photographs have been introduced."
doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(NAME)} | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}</style></head><body><header><h1>{H.escape(NAME)}</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original photographs, plans and maps</h2>{''.join(figs) if figs else '<p>No original Halton image files could be recovered.</p>'}</article><p><a href="../../atoz-archive.html">Back to A–Z index</a></p></main></body></html>'''
(OUT/"index.html").write_text(doc,encoding="utf-8")
report={"name":NAME,"alternate_names":["Castle Hill, Halton","Halton Castle","Halton Castle Motte"],"status":status,
"original_url":"http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html","source_timestamp_used":TS,
"source_original_used":ORIG,"text_blocks_preserved":len(blocks),"original_image_positions_identified":len(ORDER),
"desktop_image_identities":ORDER,"recovered_full_or_near_full":full,"recovered_thumbnail_or_lower_resolution":lower,
"still_missing":len(missing),"uncertain_identifications":[],"images":images,"missing":missing,
"denominator_method":{"source_capture_candidates":["20170208093615","20180112085831","20200708105528"],
"selected_capture":"20200708105528","selected_because":"latest capture tied for strongest genuine Halton content coverage",
"embedded_whittington_gallery_excluded":True,"excluded_whittington_reason":"unrelated gallery identities embedded in Halton page",
"responsive_variants_collapsed":True,"duplicate_content_collapsed":dupes},
"bounded_recovery_2026_09_15":{"completed":True,"identity_cdx_capture_counts":{c:len(rows.get(c,[])) for c in ORDER}}}
(OUT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
Path("page-audit").mkdir(exist_ok=True)
Path(f"page-audit/{SLUG}.json").write_text(json.dumps({"name":NAME,"slug":SLUG,"status":status,"source":TS,
"positions":len(ORDER),"full":full,"lower":lower,"missing":len(missing),"missing_identities":[x["identity"] for x in missing],
"excluded_unrelated_gallery":"whittington_castle_lancashire*"},indent=2)+"\n")
print(json.dumps({"denominator":len(ORDER),"identities":ORDER,"duplicates_collapsed":dupes,"full":full,"lower":lower,
"missing":len(missing),"missing_ids":[x["identity"] for x in missing]},indent=2))
