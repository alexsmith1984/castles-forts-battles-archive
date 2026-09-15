#!/usr/bin/env python3
import io,json,re,hashlib,time
from pathlib import Path
from urllib.parse import quote,urljoin
import requests
from PIL import Image

ROOT=Path("recovered/kenilworth-castle"); REP=ROOT/"recovery-report.json"; IMG=ROOT/"images"; IMG.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 KenilworthHistoricalRecovery"
PAGES=[
 "http://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "https://www.castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "http://castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
 "https://castlesfortsbattles.co.uk/midlands/kenilworth_castle.html",
]
def get(u,t=10):
    for n in range(3):
        try:
            r=S.get(u,timeout=t,allow_redirects=True)
            if r.status_code not in (429,500,502,503,504): return r
        except Exception:r=None
        time.sleep(0.8*(n+1))
    return r
def info(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify(); return z
    except Exception:return None
def wb_replay(ts,u):
    for mod in ("id_","im_"):
        r=get(f"https://web.archive.org/web/{ts}{mod}/{u}",8)
        if r and r.status_code==200 and info(r.content):return r.content
def arq_replay(ts,u):
    r=get(f"https://arquivo.pt/wayback/{ts}id_/{u}",8)
    if r and r.status_code==200 and info(r.content):return r.content
def save(i,b,ts,u,method,q):
    z=info(b); ext=".png" if z[2]=="PNG" else ".jpg"; p=IMG/(i+ext); p.write_bytes(b)
    return {"identity":i,"file":"images/"+p.name,"archive_timestamp":ts,"archive_original":u,
      "method":method,"dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
      "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}

def wayback_rows():
    rows=[]
    for page in PAGES:
        for attempt in range(4):
            q="https://web.archive.org/cdx/search/cdx?url="+quote(page,safe=":/")+"&output=json&fl=timestamp,original,statuscode&filter=statuscode:200&collapse=digest&from=2015&to=2022"
            x=get(q,12)
            if x and x.status_code==200:
                try:d=x.json()[1:]
                except Exception:d=[]
                if d:
                    rows.extend(d); break
            time.sleep(1.5*(attempt+1))
    out=[];seen=set()
    for row in rows:
        if len(row)<2:continue
        k=(str(row[0]),str(row[1]))
        if k not in seen:seen.add(k);out.append(k)
    return out

def arquivo_rows():
    rows=[]
    for page in PAGES:
        q="https://arquivo.pt/wayback/cdx?url="+quote(page,safe=":/")+"&output=json"
        x=get(q,12)
        if not x or x.status_code!=200:continue
        try:d=x.json()
        except Exception:continue
        if isinstance(d,list) and d and isinstance(d[0],list):d=d[1:]
        if not isinstance(d,list):continue
        for row in d:
            if isinstance(row,list) and len(row)>=2:
                rows.append((str(row[0]),str(row[1])))
            elif isinstance(row,dict):
                ts=str(row.get("timestamp") or "")
                u=str(row.get("url") or row.get("original") or "")
                if ts and u:rows.append((ts,u))
    out=[];seen=set()
    for k in rows:
        if k not in seen:seen.add(k);out.append(k)
    return out


def timemap_rows():
    out=[]
    endpoints=[]
    for page in PAGES:
        endpoints.append(("wayback","https://web.archive.org/web/timemap/link/"+page))
        endpoints.append(("arquivo","https://arquivo.pt/wayback/timemap/link/"+page))
    for source,ep in endpoints:
        x=get(ep,15)
        if not x or x.status_code!=200:continue
        for uri in re.findall(r'<([^>]+)>;\\s*rel="(?:first |last )?memento"',x.text,re.I):
            if source=="wayback":
                m=re.search(r'/web/(\\d{14})/(https?://.*)
gids=[x for x in order if x.startswith("gallery_")]
existing={x["identity"]:x for x in r.get("images",[])}
wb=wayback_rows(); arq=arquivo_rows()
captures=[("wayback",ts,u) for ts,u in wb]+[("arquivo",ts,u) for ts,u in arq]+timemap_rows()
# Diverse sampling, but preserve chronological range and cap work.
if len(captures)>24:
    captures=captures[:6]+captures[len(captures)//2-6:len(captures)//2+6]+captures[-6:]
seen=set(); captures=[x for x in captures if (x[0],x[1],x[2]) not in seen and not seen.add((x[0],x[1],x[2]))]
tm=timemap_rows(); print(json.dumps({"wayback_page_captures":len(wb),"arquivo_page_captures":len(arq),"timemap_captures":len(tm),"sampled":len(captures)}),flush=True)

checked=0
for source,ts,pu in captures:
    if source=="wayback":
        pr=get(f"https://web.archive.org/web/{ts}id_/{pu}",10)
    else:
        pr=get(f"https://arquivo.pt/wayback/{ts}id_/{pu}",10)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1; h=pr.text
    hashes=re.findall(r'new wp_galleryimage\("wpimages/([0-9a-f]+)\.jpg"',h,re.I)
    for n,ident in enumerate(gids):
        if ident in existing or n>=len(hashes):continue
        hh=hashes[n]
        candidates=[(urljoin(pu,"wpimages/"+hh+".jpg"),"full/near-full"),(urljoin(pu,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution")]
        for u,qv in candidates:
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-historical-gallery-position",qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break
    for ident in ("kenilworth_castle1","kenilworth_castle9","kenilworth_castle15"):
        if ident in existing:continue
        num=ident.replace("kenilworth_castle","")
        m=re.search(r'<a[^>]+href="([^"]*Kenilworth_Castle'+re.escape(num)+r'\.(?:JPG|jpg))"[^>]*>\s*<img[^>]+src="([^"]+)"',h,re.I)
        if not m:continue
        orig=urljoin(pu,m.group(1)); disp=urljoin(pu,m.group(2))
        for u,qv,method in ((orig,"full/near-full","historical-original"),(disp,"thumbnail/lower-resolution","historical-display-export")):
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-"+method,qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break

r["images"]=[existing[i] for i in order if i in existing]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old[i] for i in order if i not in existing and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]); r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_page_mining_2026_09_14"]={"completed":True,"wayback_page_captures_found":len(wb),"arquivo_page_captures_found":len(arq),"timemap_captures_found":len(tm),"page_captures_checked":checked,"recovered":[i for i in order if i in existing]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"checked":checked,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"],"recovered":[i for i in order if i in existing]},indent=2))
,uri)
            else:
                m=re.search(r'/wayback/(\\d{14})/(https?://.*)
gids=[x for x in order if x.startswith("gallery_")]
existing={x["identity"]:x for x in r.get("images",[])}
wb=wayback_rows(); arq=arquivo_rows()
captures=[("wayback",ts,u) for ts,u in wb]+[("arquivo",ts,u) for ts,u in arq]
# Diverse sampling, but preserve chronological range and cap work.
if len(captures)>24:
    captures=captures[:6]+captures[len(captures)//2-6:len(captures)//2+6]+captures[-6:]
seen=set(); captures=[x for x in captures if (x[0],x[1],x[2]) not in seen and not seen.add((x[0],x[1],x[2]))]
print(json.dumps({"wayback_page_captures":len(wb),"arquivo_page_captures":len(arq),"sampled":len(captures)}),flush=True)

checked=0
for source,ts,pu in captures:
    if source=="wayback":
        pr=get(f"https://web.archive.org/web/{ts}id_/{pu}",10)
    else:
        pr=get(f"https://arquivo.pt/wayback/{ts}id_/{pu}",10)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1; h=pr.text
    hashes=re.findall(r'new wp_galleryimage\("wpimages/([0-9a-f]+)\.jpg"',h,re.I)
    for n,ident in enumerate(gids):
        if ident in existing or n>=len(hashes):continue
        hh=hashes[n]
        candidates=[(urljoin(pu,"wpimages/"+hh+".jpg"),"full/near-full"),(urljoin(pu,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution")]
        for u,qv in candidates:
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-historical-gallery-position",qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break
    for ident in ("kenilworth_castle1","kenilworth_castle9","kenilworth_castle15"):
        if ident in existing:continue
        num=ident.replace("kenilworth_castle","")
        m=re.search(r'<a[^>]+href="([^"]*Kenilworth_Castle'+re.escape(num)+r'\.(?:JPG|jpg))"[^>]*>\s*<img[^>]+src="([^"]+)"',h,re.I)
        if not m:continue
        orig=urljoin(pu,m.group(1)); disp=urljoin(pu,m.group(2))
        for u,qv,method in ((orig,"full/near-full","historical-original"),(disp,"thumbnail/lower-resolution","historical-display-export")):
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-"+method,qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break

r["images"]=[existing[i] for i in order if i in existing]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old[i] for i in order if i not in existing and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]); r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_page_mining_2026_09_14"]={"completed":True,"wayback_page_captures_found":len(wb),"arquivo_page_captures_found":len(arq),"page_captures_checked":checked,"recovered":[i for i in order if i in existing]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"checked":checked,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"],"recovered":[i for i in order if i in existing]},indent=2))
,uri)
            if m:out.append((source,m.group(1),m.group(2)))
    seen=set();res=[]
    for x in out:
        if x not in seen:seen.add(x);res.append(x)
    return res

r=json.loads(REP.read_text()); order=r["desktop_image_identities"]
gids=[x for x in order if x.startswith("gallery_")]
existing={x["identity"]:x for x in r.get("images",[])}
wb=wayback_rows(); arq=arquivo_rows()
captures=[("wayback",ts,u) for ts,u in wb]+[("arquivo",ts,u) for ts,u in arq]
# Diverse sampling, but preserve chronological range and cap work.
if len(captures)>24:
    captures=captures[:6]+captures[len(captures)//2-6:len(captures)//2+6]+captures[-6:]
seen=set(); captures=[x for x in captures if (x[0],x[1],x[2]) not in seen and not seen.add((x[0],x[1],x[2]))]
print(json.dumps({"wayback_page_captures":len(wb),"arquivo_page_captures":len(arq),"sampled":len(captures)}),flush=True)

checked=0
for source,ts,pu in captures:
    if source=="wayback":
        pr=get(f"https://web.archive.org/web/{ts}id_/{pu}",10)
    else:
        pr=get(f"https://arquivo.pt/wayback/{ts}id_/{pu}",10)
    if not pr or pr.status_code!=200 or "<html" not in pr.text.lower():continue
    checked+=1; h=pr.text
    hashes=re.findall(r'new wp_galleryimage\("wpimages/([0-9a-f]+)\.jpg"',h,re.I)
    for n,ident in enumerate(gids):
        if ident in existing or n>=len(hashes):continue
        hh=hashes[n]
        candidates=[(urljoin(pu,"wpimages/"+hh+".jpg"),"full/near-full"),(urljoin(pu,"wpimages/"+hh+"t.jpg"),"thumbnail/lower-resolution")]
        for u,qv in candidates:
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-historical-gallery-position",qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break
    for ident in ("kenilworth_castle1","kenilworth_castle9","kenilworth_castle15"):
        if ident in existing:continue
        num=ident.replace("kenilworth_castle","")
        m=re.search(r'<a[^>]+href="([^"]*Kenilworth_Castle'+re.escape(num)+r'\.(?:JPG|jpg))"[^>]*>\s*<img[^>]+src="([^"]+)"',h,re.I)
        if not m:continue
        orig=urljoin(pu,m.group(1)); disp=urljoin(pu,m.group(2))
        for u,qv,method in ((orig,"full/near-full","historical-original"),(disp,"thumbnail/lower-resolution","historical-display-export")):
            b=wb_replay(ts,u) if source=="wayback" else arq_replay(ts,u)
            if b:
                existing[ident]=save(ident,b,ts,u,source+"-"+method,qv)
                print("RECOVERED",ident,source,ts,u,flush=True);break

r["images"]=[existing[i] for i in order if i in existing]
old={x["identity"]:x for x in r.get("missing",[])}
r["missing"]=[old[i] for i in order if i not in existing and i in old]
r["recovered_full_or_near_full"]=sum(x["quality"]=="full/near-full" for x in r["images"])
r["recovered_thumbnail_or_lower_resolution"]=sum(x["quality"]!="full/near-full" for x in r["images"])
r["still_missing"]=len(order)-len(r["images"]); r["status"]="COMPLETE" if r["still_missing"]==0 else "PARTIAL"
r["historical_page_mining_2026_09_14"]={"completed":True,"wayback_page_captures_found":len(wb),"arquivo_page_captures_found":len(arq),"page_captures_checked":checked,"recovered":[i for i in order if i in existing]}
REP.write_text(json.dumps(r,indent=2)+"\n")
print(json.dumps({"checked":checked,"full":r["recovered_full_or_near_full"],"lower":r["recovered_thumbnail_or_lower_resolution"],"missing":r["still_missing"],"recovered":[i for i in order if i in existing]},indent=2))
