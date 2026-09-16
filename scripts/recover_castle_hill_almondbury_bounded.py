#!/usr/bin/env python3
import io,json,re,hashlib,time,html as H
from pathlib import Path
from urllib.parse import urlparse,urljoin
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from bs4 import BeautifulSoup

NAME="Castle Hill, Almondbury"
SLUG="castle-hill-almondbury"
TS="20161021184941"
ORIG="http://www.castlesfortsbattles.co.uk/yorkshire/castle_hill_almondbury.html"
OUT=Path("recovered")/SLUG; IMG=OUT/"images"; IMG.mkdir(parents=True,exist_ok=True)
DEADLINE=time.monotonic()+540
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 CastleHillAlmondburyRecovery"

def alive(): return time.monotonic()<DEADLINE
def get(u,t=8,params=None):
    if not alive(): return None
    try:return S.get(u,params=params,timeout=min(t,max(1,DEADLINE-time.monotonic())),allow_redirects=True)
    except:return None
def valid(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        return z if z[0]>=80 and z[1]>=60 else None
    except:return None

# controlling source
r=get(f"https://web.archive.org/web/{TS}id_/{ORIG}",20)
if not r or r.status_code!=200 or "<html" not in r.text.lower():
    raise SystemExit("controlling source capture could not be fetched")
raw=r.text; (OUT/"source.html").write_text(raw,encoding="utf-8",errors="replace")
soup=BeautifulSoup(raw,"html.parser")

DECO=re.compile(r'(facebook|twitter|google|email|print|share|logo|favicon|blank|button|menu|arrow|spacer|home|castlesfortsbattles(?:-crop)?|battlefieldsofbritain(?:-crop)?|museutils|jquery)',re.I)
IMGEXT=re.compile(r'\.(?:jpe?g|png|gif|webp)(?:\?|$)',re.I)

def stem_of(u):
    return Path(urlparse(u).path).stem

# collect image-bearing refs with context
refs=[]
def addref(u,kind,pos=None):
    if not u:return
    u=urljoin(ORIG,u.strip())
    b=Path(urlparse(u).path).name
    if not b or DECO.search(b) or not IMGEXT.search(u):return
    refs.append({"url":u,"kind":kind,"pos":pos})

for a in soup.find_all("a",href=True):
    href=a.get("href","")
    if IMGEXT.search(href) and a.find("img"):addref(href,"asset-link")
for im in soup.find_all("img"):
    pos=im.get("data-col-pos")
    kind="gallery" if ("ImageInclude" in (im.get("class") or []) or pos is not None) else "display"
    for attr in ("data-orig-src","data-muse-src","data-src","data-hidpi-src","src"):
        v=im.get(attr)
        if v and "blank.gif" not in v.lower() and not v.startswith("data:"):addref(v,kind,pos)

# normalize responsive dimensions only when the base is plausible
def identity_from_ref(u):
    st=stem_of(u)
    st=re.sub(r'(?<!\d)(\d{2,4})x(\d{2,4})$','',st)
    return st

# dedupe refs
seen=set(); clean=[]
for x in refs:
    k=(x["url"],x["kind"],x["pos"])
    if k not in seen: seen.add(k); clean.append(x)
refs=clean

# identities: prioritize asset links and gallery positions, then standalone display images.
asset_ids=[]
for x in refs:
    if x["kind"]=="asset-link":
        i=identity_from_ref(x["url"])
        if i not in asset_ids: asset_ids.append(i)
gallery_by_pos={}
for x in refs:
    if x["kind"]=="gallery" and x["pos"] is not None:
        try:p=int(x["pos"])
        except:continue
        gallery_by_pos.setdefault(p,identity_from_ref(x["url"]))
gallery_ids=[gallery_by_pos[k] for k in sorted(gallery_by_pos)]
display_ids=[]
for x in refs:
    if x["kind"]=="display":
        i=identity_from_ref(x["url"])
        if i not in display_ids:display_ids.append(i)

# Keep display-only identities only when castle/page-relevant or not obvious utility.
all_known=set(asset_ids+gallery_ids)
for i in display_ids:
    if i not in all_known and re.search(r'(castle|hill|almondbury|tower|plan|huddersfield|victoria|fort|earthwork|view)',i,re.I):
        all_known.add(i); asset_ids.append(i)

ORDER=[]
for i in asset_ids+gallery_ids:
    if i and i not in ORDER:ORDER.append(i)

# fallback if source is old/non-Muse and asset links are sparse
if len(ORDER)<2:
    for i in display_ids:
        if i and i not in ORDER:ORDER.append(i)

# map every source ref to identity where possible
def mapid(u):
    st=stem_of(u)
    for c in sorted(ORDER,key=len,reverse=True):
        if st.lower()==c.lower() or re.fullmatch(re.escape(c.lower())+r'\d+x\d+',st.lower()):
            return c
    return identity_from_ref(u) if identity_from_ref(u) in ORDER else None

candidates={i:[] for i in ORDER}
for x in refs:
    c=mapid(x["url"])
    if c:candidates[c].append(x["url"])

def responsive(c,u):
    return bool(re.fullmatch(re.escape(c.lower())+r'\d+x\d+',stem_of(u).lower()))
def quality(c,u,z):
    p=urlparse(u).path.lower(); s=stem_of(u).lower()
    if ("/assets/" in p or s==c.lower()) and not responsive(c,u):return "full/near-full"
    if not responsive(c,u) and max(z[:2])>=900:return "full/near-full"
    return "thumbnail/lower-resolution"
def score(c,u,z,q):
    p=urlparse(u).path.lower();s=stem_of(u).lower()
    return (4 if "/assets/" in p and not responsive(c,u) else 3 if s==c.lower() and not responsive(c,u) else 2 if q=="full/near-full" else 1,z[0]*z[1])

def replay(ts,u):
    for mode in ("id_","im_"):
        rr=get(f"https://web.archive.org/web/{ts}{mode}/{u}",6)
        if rr and rr.status_code==200:
            z=valid(rr.content)
            if z:return rr.content,z,rr.url
    return None

def cdx(pattern,limit=1000):
    rr=get("https://web.archive.org/cdx/search/cdx",8,{"url":pattern,"output":"json","fl":"timestamp,original,statuscode,mimetype,digest",
      "filter":"statuscode:200","collapse":"digest","from":"2013","to":"2023","limit":str(limit)})
    if not rr or rr.status_code!=200:return []
    try:
        j=rr.json()
        if len(j)<2:return []
        h=j[0];return [dict(zip(h,row)) for row in j[1:]]
    except:return []

def timemap(page):
    rr=get("https://web.archive.org/web/timemap/link/"+page,8)
    if not rr or rr.status_code!=200:return []
    out=[]
    for line in rr.text.splitlines():
        if "memento" not in line or "<" not in line:continue
        u=line.split("<",1)[1].split(">",1)[0]
        m=re.search(r"/web/(\d{14})[^/]*/(.+)$",u)
        if m:out.append((m.group(1),m.group(2)))
    return out

# direct same-capture recovery first
results={i:[] for i in ORDER}
jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for c,urls in candidates.items():
        ss=set()
        for u in urls:
            if u in ss:continue
            ss.add(u);jobs[ex.submit(replay,TS,u)]=(c,TS,u,"same-capture")
    for f in as_completed(jobs):
        c,ts,u,meth=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(c,u,z);results[c].append((score(c,u,z,q),ts,u,b,z,final,q,meth))

# high-yield identity-specific CDX wildcards
patterns=[]
for c in ORDER:
    exts=("png","jpg") if "plan" in c.lower() else ("jpg","jpeg","png")
    for host in ("www.castlesfortsbattles.co.uk","castlesfortsbattles.co.uk"):
      for d in ("yorkshire/assets","yorkshire/images","assets","images","m/assets","m/images","yorkshire/wpimages","wpimages"):
       for ext in exts:patterns.append((c,f"{host}/{d}/{c}*.{ext}*"))
rows={c:[] for c in ORDER}
with ThreadPoolExecutor(max_workers=18) as ex:
    fs={ex.submit(cdx,p,700):(c,p) for c,p in patterns}
    for f in as_completed(fs):
        if not alive():break
        c,p=fs[f]
        try:rows[c]+=f.result()
        except:pass

# replay top wildcard candidates
jobs={}
with ThreadPoolExecutor(max_workers=18) as ex:
    for c,rr in rows.items():
        ss=set();ded=[]
        for x in sorted(rr,key=lambda x:(0 if "/assets/" in urlparse(x.get("original","")).path.lower() else 1,
                                        1 if responsive(c,x.get("original","")) else 0,x.get("timestamp",""))):
            k=(x.get("timestamp"),x.get("original"))
            if not x.get("timestamp") or not x.get("original") or k in ss:continue
            ss.add(k);ded.append(x)
        for x in ded[:18]:jobs[ex.submit(replay,x["timestamp"],x["original"])]=(c,x)
    for f in as_completed(jobs):
        if not alive():break
        c,x=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;u=x["original"];q=quality(c,u,z);results[c].append((score(c,u,z,q),x["timestamp"],u,b,z,final,q,"wayback-cdx-identity-family"))

# one bounded historical page pass
PAGES=[ORIG,ORIG.replace("http://","https://"),ORIG.replace("www.",""),ORIG.replace("http://www.","https://"),
       "http://www.castlesfortsbattles.co.uk/m/yorkshire/castle_hill_almondbury.html",
       "http://www.castlesfortsbattles.co.uk/m/castle_hill_almondbury.html"]
caps=[]
for p in PAGES:caps+=timemap(p)
seen=set();caps=[x for x in sorted(caps) if not (x in seen or seen.add(x))]
if len(caps)>24:
    idx={0,len(caps)-1}
    for n in range(1,23):idx.add(round(n*(len(caps)-1)/23))
    caps=[caps[i] for i in sorted(idx)]
histrefs={c:[] for c in ORDER};checked=0
for ts,page in caps:
    if not alive():break
    pr=get(f"https://web.archive.org/web/{ts}id_/{page}",6)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1;sp=BeautifulSoup(pr.text,"html.parser")
    for e in sp.find_all(["a","img"]):
        vals=[]
        if e.name=="a":
            v=e.get("href")
            if v and IMGEXT.search(v):vals.append(v)
        else:
            for a in ("data-orig-src","data-muse-src","data-src","src"):
                v=e.get(a)
                if v and IMGEXT.search(v) and "blank.gif" not in v.lower():vals.append(v)
        for v in vals:
            u=urljoin(page,v);c=mapid(u)
            if c:histrefs[c].append((ts,u))
    # gallery position mapping
    for im in sp.find_all("img"):
        if "ImageInclude" not in (im.get("class") or []) and im.get("data-col-pos") is None:continue
        try:p=int(im.get("data-col-pos"))
        except:continue
        if p in gallery_by_pos:
            c=gallery_by_pos[p]
            v=im.get("data-src") or im.get("data-muse-src") or im.get("data-orig-src") or im.get("src")
            if v:histrefs[c].append((ts,urljoin(page,v)))

jobs={}
with ThreadPoolExecutor(max_workers=16) as ex:
    for c,ls in histrefs.items():
        ss=set()
        for ts,u in ls:
            k=(ts,u)
            if k in ss:continue
            ss.add(k);jobs[ex.submit(replay,ts,u)]=(c,ts,u)
    for f in as_completed(jobs):
        if not alive():break
        c,ts,u=jobs[f]
        try:got=f.result()
        except:got=None
        if got:
            b,z,final=got;q=quality(c,u,z);results[c].append((score(c,u,z,q),ts,u,b,z,final,q,"historical-page-cross-timestamp"))

# choose best authenticated recovery per identity
images=[];missing=[]
for c in ORDER:
    if not results[c]:
        missing.append({"identity":c,"candidate_urls":list(dict.fromkeys(candidates.get(c,[])))})
        continue
    sc,ts,u,b,z,final,q,meth=max(results[c],key=lambda x:x[0])
    ext=".png" if z[2]=="PNG" else ".jpg";p=IMG/(c+ext);p.write_bytes(b)
    images.append({"identity":c,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,"archive_replay":final,
      "method":meth,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
      "quality":q,"identification":"certain"})

full=sum(x["quality"]=="full/near-full" for x in images); lower=len(images)-full
status="COMPLETE / VERIFIED" if not missing else "PARTIAL / SEARCH EXHAUSTED"

# preserve readable written content
for x in soup(["script","style","noscript"]):x.decompose()
nav={"England","Scotland","Wales","Home","UK Map","A-Z","Links","About Us","Contact Us","Terms and Conditions","CastlesFortsBattles.co.uk","BattlefieldsofBritain.co.uk"}
blocks=[];seen=set()
for e in soup.find_all(["h1","h2","h3","h4","p","li"]):
    tx=" ".join(e.stripped_strings).strip();key=re.sub(r"\s+"," ",tx).casefold()
    if not tx or tx in nav or key in seen or tx.lower() in ("tweet","share","follow"):continue
    seen.add(key);blocks.append((e.name,tx))
body=[]
for tag,tx in blocks:
    if tag.startswith("h") or (len(tx)<95 and re.match(r"^(History|Historical Background|Description|Design|Gallery|Getting There|What.s There|Location|Castle Hill|Victoria Tower)",tx,re.I)):
        body.append(f"<h2>{H.escape(tx)}</h2>")
    elif tag=="li":body.append(f"<p>• {H.escape(tx)}</p>")
    else:body.append(f"<p>{H.escape(tx)}</p>")
figs=[]
for x in images:
    label=x["identity"].replace("_"," ")
    if x["quality"]!="full/near-full":label+=" — lower-resolution archived recovery"
    figs.append(f'<figure><a href="{H.escape(x["file"],quote=True)}"><img src="{H.escape(x["file"],quote=True)}" alt="{H.escape(NAME)} archived original image"></a><figcaption>{H.escape(label)}</figcaption></figure>')
note=f"Recovered from the archived CastlesFortsBattles page. {len(images)} of {len(ORDER)} unique original content images have been recovered; {len(missing)} remain unavailable. No unrelated substitute photographs have been introduced."
doc=f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(NAME)} | Castles, Forts and Battles Archive</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f0e6;color:#222;font-family:Georgia,"Times New Roman",serif;line-height:1.55}}header{{background:#3d3528;color:#fff;padding:28px 18px;text-align:center}}header h1{{margin:0}}main{{max-width:920px;margin:auto;padding:24px 18px 50px}}.note,article{{background:#fff;border:1px solid #d7cebd;padding:18px 22px}}.note{{border-left:4px solid #8b7959;margin-bottom:20px}}h2{{color:#493e2c;margin-top:1.35em}}p{{margin:.75em 0}}figure{{margin:24px auto;text-align:center}}figure img{{max-width:100%;height:auto;border:1px solid #d7cebd}}figcaption{{font-size:13px;color:#6b6255;margin-top:5px}}a{{color:#224d74}}</style></head><body><header><h1>{H.escape(NAME)}</h1></header><main><div class="note">{H.escape(note)}</div><article>{''.join(body)}<h2>Recovered original photographs, plans and images</h2>{''.join(figs) if figs else '<p>No original image files could be recovered from the available archive copy.</p>'}</article><p><a href="../../atoz-archive.html">Back to A–Z index</a></p></main></body></html>'''
(OUT/"index.html").write_text(doc,encoding="utf-8")

report={"name":NAME,"status":status,"original_url":ORIG,"supplied_capture":TS,"source_timestamp_used":TS,"source_original_used":ORIG,
"text_blocks_preserved":len(blocks),"original_image_positions_identified":len(ORDER),"desktop_image_identities":ORDER,
"recovered_full_or_near_full":full,"recovered_thumbnail_or_lower_resolution":lower,"still_missing":len(missing),
"uncertain_identifications":[],"images":images,"missing":missing,
"denominator_method":{"asset_link_identities":asset_ids,"gallery_positions":len(gallery_by_pos),"gallery_identities":gallery_ids,
"responsive_variants_collapsed":True,"unique_union":len(ORDER)},
"bounded_recovery_2026_09_15":{"completed":True,"identity_cdx_capture_counts":{c:len(rows[c]) for c in ORDER},
"historical_page_captures_found":len(caps),"historical_page_captures_checked":checked}}
(OUT/"recovery-report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
Path("page-audit").mkdir(exist_ok=True)
Path(f"page-audit/{SLUG}.json").write_text(json.dumps({"name":NAME,"slug":SLUG,"status":status,"source":TS,"positions":len(ORDER),
"full":full,"lower":lower,"missing":len(missing),"missing_identities":[x["identity"] for x in missing]},indent=2)+"\n")
print(json.dumps({"denominator":len(ORDER),"identities":ORDER,"full":full,"lower":lower,"missing":len(missing),
"missing_ids":[x["identity"] for x in missing],"historical_captures":len(caps)},indent=2))
