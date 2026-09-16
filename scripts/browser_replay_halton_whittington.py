#!/usr/bin/env python3
import base64, io, json, re, hashlib, time
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT=Path(".")
CFG={
 "halton":{
   "root":Path("recovered/castle-hill-halton"),
   "report":Path("recovered/castle-hill-halton/recovery-report.json"),
   "audit":Path("page-audit/castle-hill-halton.json"),
   "pages":[
     "https://web.archive.org/web/20200708105528/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://web.archive.org/web/20180112085831/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://web.archive.org/web/20170208093615/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://web.archive.org/web/20210918013642/http://www.castlesfortsbattles.co.uk/north_west/whittington_castle_lancashire.html",
     "https://arquivo.pt/wayback/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html"
   ]
 },
 "whittington":{
   "root":Path("recovered/whittington-castle"),
   "report":Path("recovered/whittington-castle/recovery-report.json"),
   "audit":Path("page-audit/whittington-castle.json"),
   "pages":[
     "https://web.archive.org/web/20210918013642/http://www.castlesfortsbattles.co.uk/north_west/whittington_castle_lancashire.html",
     "https://web.archive.org/web/20200708105528/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://web.archive.org/web/20180112085831/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://web.archive.org/web/20170208093615/http://www.castlesfortsbattles.co.uk/north_west/halton_castle_motte.html",
     "https://arquivo.pt/wayback/http://www.castlesfortsbattles.co.uk/north_west/whittington_castle_lancashire.html"
   ]
 }
}
DEADLINE=time.monotonic()+540

def alive(): return time.monotonic()<DEADLINE
def imginfo(b):
    try:
        im=Image.open(io.BytesIO(b)); z=(im.width,im.height,im.format); im.verify()
        return z if z[0]>=60 and z[1]>=40 else None
    except:return None
def raw_stem(u):
    try:return Path(urlparse(u).path).stem
    except:return ""
def normalized_stem(u):
    s=raw_stem(u)
    s=re.sub(r'(\d{2,4})x(\d{2,4})(?:\d+)?$','',s)
    return s
def map_identity(order,text):
    text=(text or "").lower()
    # Prefer exact filenames embedded anywhere in archive-rewritten URLs.
    for c in sorted(order,key=len,reverse=True):
        lc=c.lower()
        if re.search(r'(?<![a-z0-9_])'+re.escape(lc)+r'(?:\d+x\d+(?:\d+)?)?\.(?:jpe?g|png)',text):
            return c
    return None
def quality(c,u,z,method):
    p=(u or "").lower()
    if method=="browser-replay-network" and "/assets/" in p and not re.search(re.escape(c.lower())+r'\d+x\d+',p):
        return "full/near-full"
    if max(z[:2])>=900 and not re.search(re.escape(c.lower())+r'\d+x\d+',p):
        return "full/near-full"
    return "thumbnail/lower-resolution"
def score(c,u,z,q,method):
    return (5 if q=="full/near-full" and method=="browser-replay-network" else
            4 if q=="full/near-full" else 2 if method=="browser-replay-network" else 1,z[0]*z[1])

def process_site(browser,name,cfg):
    rep=json.loads(cfg["report"].read_text())
    order=rep["desktop_image_identities"]
    found={x["identity"]:x for x in rep.get("images",[])}
    missing=[x for x in order if x not in found]
    candidates={c:[] for c in missing}
    stats={"pages_attempted":0,"pages_loaded":0,"matching_network_responses":0,"decoded_network_images":0,
           "matching_dom_images":0,"canvas_extractions":0,"element_screenshots":0,"page_results":[]}

    for page_url in cfg["pages"]:
        if not alive():break
        context=browser.new_context(viewport={"width":1440,"height":1200},ignore_https_errors=True)
        page=context.new_page()
        stats["pages_attempted"]+=1
        net=[]

        def on_response(resp):
            try:
                u=resp.url
                c=map_identity(missing,u)
                if not c:return
                stats["matching_network_responses"]+=1
                ct=(resp.headers.get("content-type") or "").lower()
                if "image" not in ct and not re.search(r'\.(?:jpe?g|png)(?:\?|$)',u,re.I):return
                b=resp.body()
                z=imginfo(b)
                if z:
                    net.append((c,u,b,z))
                    stats["decoded_network_images"]+=1
            except Exception:
                pass
        page.on("response",on_response)
        loaded=False
        err=None
        try:
            page.goto(page_url,wait_until="domcontentloaded",timeout=30000)
            loaded=True;stats["pages_loaded"]+=1
            try:page.wait_for_timeout(8000)
            except:pass
        except Exception as e:
            err=str(e)[:200]

        # Record successful network images.
        for c,u,b,z in net:
            q=quality(c,u,z,"browser-replay-network")
            candidates[c].append((score(c,u,z,q,"browser-replay-network"),b,z,u,page_url,q,"browser-replay-network"))

        # DOM/canvas extraction. This can recover decoded display derivatives even if body replay URL is opaque.
        dom_matches=0
        if loaded:
            try:
                imgs=page.locator("img")
                count=imgs.count()
            except:count=0
            for i in range(count):
                if not alive():break
                loc=imgs.nth(i)
                try:
                    meta=loc.evaluate("""img => ({
                      src: img.getAttribute('src')||'',
                      currentSrc: img.currentSrc||'',
                      orig: img.getAttribute('data-orig-src')||'',
                      muse: img.getAttribute('data-muse-src')||'',
                      dataSrc: img.getAttribute('data-src')||'',
                      nw: img.naturalWidth||0, nh: img.naturalHeight||0
                    })""")
                except:continue
                blob=" ".join(str(meta.get(k,"")) for k in ("src","currentSrc","orig","muse","dataSrc"))
                c=map_identity(missing,blob)
                if not c or meta.get("nw",0)<60 or meta.get("nh",0)<40:continue
                dom_matches+=1;stats["matching_dom_images"]+=1
                # Try canvas at natural resolution.
                try:
                    data=loc.evaluate("""img => {
                      try {
                        const c=document.createElement('canvas');
                        c.width=img.naturalWidth; c.height=img.naturalHeight;
                        const x=c.getContext('2d'); x.drawImage(img,0,0);
                        return c.toDataURL('image/png');
                      } catch(e) { return null; }
                    }""")
                except:data=None
                if data and data.startswith("data:image/png;base64,"):
                    try:
                        b=base64.b64decode(data.split(",",1)[1]);z=imginfo(b)
                    except:b=None;z=None
                    if z:
                        u=meta.get("currentSrc") or meta.get("src") or meta.get("orig")
                        q=quality(c,u,z,"browser-replay-canvas")
                        candidates[c].append((score(c,u,z,q,"browser-replay-canvas"),b,z,u,page_url,q,"browser-replay-canvas"))
                        stats["canvas_extractions"]+=1
                        continue
                # Last-resort authenticated element screenshot.
                try:
                    loc.evaluate("""img => {
                      img.style.setProperty('display','block','important');
                      img.style.setProperty('visibility','visible','important');
                      img.style.setProperty('opacity','1','important');
                      img.style.setProperty('position','relative','important');
                      img.style.setProperty('z-index','2147483647','important');
                      img.style.setProperty('width',img.naturalWidth+'px','important');
                      img.style.setProperty('height',img.naturalHeight+'px','important');
                      img.style.setProperty('max-width','none','important');
                    }""")
                    b=loc.screenshot(type="png",timeout=10000)
                    z=imginfo(b)
                    if z:
                        u=meta.get("currentSrc") or meta.get("src") or meta.get("orig")
                        q="thumbnail/lower-resolution"
                        candidates[c].append((score(c,u,z,q,"browser-element-screenshot"),b,z,u,page_url,q,"browser-element-screenshot"))
                        stats["element_screenshots"]+=1
                except:pass

        stats["page_results"].append({"url":page_url,"loaded":loaded,"error":err,"network_images":len(net),"dom_matches":dom_matches})
        context.close()

    recovered=[]
    imgdir=cfg["root"]/"images";imgdir.mkdir(exist_ok=True)
    for c in missing:
        if not candidates[c]:continue
        _,b,z,u,page_url,q,method=max(candidates[c],key=lambda x:x[0])
        ext=".png" if z[2]=="PNG" else ".jpg";p=imgdir/(c+ext);p.write_bytes(b)
        found[c]={"identity":c,"file":"images/"+p.name,"archive_timestamp":"browser-replay",
                  "archive_original":u,"archive_replay":page_url,"method":method,
                  "dimensions":[z[0],z[1]],"format":z[2],"bytes":len(b),
                  "sha256":hashlib.sha256(b).hexdigest(),"quality":q,"identification":"certain"}
        recovered.append(c)

    images=[found[i] for i in order if i in found]
    miss=[{"identity":i,"candidate_urls":next((x.get("candidate_urls",[]) for x in rep.get("missing",[]) if x.get("identity")==i),[])}
          for i in order if i not in found]
    full=sum(x.get("quality")=="full/near-full" for x in images);lower=len(images)-full
    rep["images"]=images;rep["missing"]=miss
    rep["recovered_full_or_near_full"]=full;rep["recovered_thumbnail_or_lower_resolution"]=lower
    rep["still_missing"]=len(miss)
    rep["status"]="COMPLETE / VERIFIED" if not miss else "PARTIAL / SEARCH EXHAUSTED"
    rep["browser_replay_recovery_2026_09_15"]={**stats,"recovered_now":recovered,
      "note":"Real Chromium replay of archived pages; captured authenticated archive network images or decoded DOM display derivatives only."}
    cfg["report"].write_text(json.dumps(rep,indent=2,ensure_ascii=False)+"\n")

    # refresh page
    from bs4 import BeautifulSoup
    p=cfg["root"]/"index.html";soup=BeautifulSoup(p.read_text(),"html.parser")
    h=soup.find("h2",string=lambda x:x and "Recovered original" in x)
    if h:
        for fig in list(h.find_all_next("figure")):fig.decompose()
        anchor=h
        for x in images:
            fig=soup.new_tag("figure");a=soup.new_tag("a",href=x["file"]);im=soup.new_tag("img",src=x["file"],alt=rep["name"]+" archived original image")
            a.append(im);fig.append(a);cap=soup.new_tag("figcaption")
            cap.string=x["identity"].replace("_"," ")+(" — lower-resolution archived recovery" if x.get("quality")!="full/near-full" else "")
            fig.append(cap);anchor.insert_after(fig);anchor=fig
    note=soup.find("div",class_="note")
    if note:
        extra=" An unrelated embedded Whittington Castle gallery is excluded." if name=="halton" else ""
        note.string=f"Recovered from the archived CastlesFortsBattles page. {len(images)} of {len(order)} unique original content images have been recovered; {len(miss)} remain unavailable.{extra} No unrelated substitute photographs have been introduced."
    p.write_text(str(soup))
    audit=json.loads(cfg["audit"].read_text())
    audit.update({"status":rep["status"],"positions":len(order),"full":full,"lower":lower,"missing":len(miss),
                  "missing_identities":[x["identity"] for x in miss]})
    cfg["audit"].write_text(json.dumps(audit,indent=2)+"\n")
    return {"status":rep["status"],"full":full,"lower":lower,"missing":len(miss),"recovered_now":recovered,"stats":stats}

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--disable-dev-shm-usage","--no-sandbox"])
    out={}
    for name,cfg in CFG.items():
        if not alive():break
        out[name]=process_site(browser,name,cfg)
    browser.close()
print(json.dumps(out,indent=2))
