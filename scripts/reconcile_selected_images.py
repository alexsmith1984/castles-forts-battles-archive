#!/usr/bin/env python3
"""Reconcile selected recovery reports with already-verified local images."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from urllib.parse import unquote, urlsplit
from PIL import Image

SELECTED = ["hopton-heath-1643", "hopton-castle", "montgomery-castle",
 "moreton-corbet-castle", "nantwich-1644", "old-oswestry-hillfort",
 "peveril-castle", "seckington-castle", "stokesay-castle", "ludlow-castle"]

def requested_url(item):
    return item.get("requested") or item.get("url") or item.get("original") or ""

def basename(url):
    return os.path.basename(unquote(urlsplit(url).path))

def image_info(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        dimensions = [image.width, image.height]
    return digest, dimensions

def main():
    summaries = []
    for slug in SELECTED:
        report_path = Path("recovered") / slug / "recovery-report.json"
        if not report_path.exists():
            summaries.append({"slug": slug, "status": "missing-report"}); continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        image_dir = report_path.parent / "images"
        local = {p.name: p for p in image_dir.glob("*") if p.is_file()}
        reconciled, invalid_local = [], []
        for item in report.get("images", []):
            if item.get("status") == "recovered": continue
            url = requested_url(item); name = basename(url); candidate = local.get(name)
            if not candidate: continue
            try: digest, dimensions = image_info(candidate)
            except Exception as exc:
                invalid_local.append({"file": f"images/{name}", "error": type(exc).__name__}); continue
            item.update({"status":"recovered", "file":f"images/{name}", "sha256":digest,
                         "dimensions":dimensions, "method":"exact-local-basename-reconciliation"})
            reconciled.append({"requested":url, "file":f"images/{name}", "sha256":digest})
        unresolved = [requested_url(i) for i in report.get("images", []) if i.get("status") != "recovered"]
        report["second_pass"] = {"exact_local_references_reconciled":len(reconciled),
          "remaining_unresolved_references":len(unresolved), "invalid_local_files":invalid_local,
          "note":"Exact filenames only; no substitute images were used."}
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        summaries.append({"slug":slug, "reconciled":len(reconciled), "remaining":len(unresolved),
                          "reconciled_items":reconciled, "unresolved":unresolved})
        print(f"{slug}: reconciled {len(reconciled)}, remaining {len(unresolved)}")
    output = Path("page-audit/selected-second-pass-summary.json"); output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summaries, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")

if __name__ == "__main__": main()
