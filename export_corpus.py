import argparse
import csv
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone

SOURCE_TAG = "v1.0.0"
SOURCE_URL = (
    "https://raw.githubusercontent.com/pengyin-shan/provenance-audit/"
    f"{SOURCE_TAG}/registry/corpus_keep.yaml"
)
ZENODO_DOI = "10.5281/zenodo.21443211"

def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "rda-corpus-export/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def parse_corpus_yaml(text: str):
    """Minimal parser for the flat corpus_keep.yaml list-of-dicts layout.
    Avoids a PyYAML dependency; the file is a simple '- key: value' list."""
    rows, cur = [], None
    for line in text.splitlines():
        if line.startswith("- "):
            if cur:
                rows.append(cur)
            cur = {}
            line = "  " + line[2:]
        if cur is not None and ":" in line and line.strip():
            k, _, v = line.strip().partition(":")
            cur[k.strip()] = v.strip()
    if cur:
        rows.append(cur)
    return rows

def canonical_repo(repo: str) -> str:
    """owner/name -> canonical lowercase form; used as the join key everywhere."""
    r = repo.strip().lower()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if r.startswith(prefix):
            r = r[len(prefix):]
    if r.endswith(".git"):
        r = r[:-4]
    return r.strip("/")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus.csv")
    args = ap.parse_args()

    raw = fetch(SOURCE_URL)
    sha = hashlib.sha256(raw).hexdigest()
    rows = parse_corpus_yaml(raw.decode("utf-8"))

    n_hpc = sum(1 for r in rows if r.get("domain") == "hpc")
    n_qc = len(rows) - n_hpc
    if len(rows) != 87:
        sys.exit(f"REFUSING TO WRITE: expected 87 projects, parsed {len(rows)}. "
                 "Inspect the source file before proceeding.")

    seen = set()
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "repo", "repo_canonical", "stratum", "discipline",
                    "ecosystem", "source"])
        for r in rows:
            canon = canonical_repo(r["repo"])
            if canon in seen:
                sys.exit(f"REFUSING TO WRITE: duplicate repo {canon}")
            seen.add(canon)
            w.writerow([r.get("name", ""), r["repo"], canon,
                        r.get("domain", ""), r.get("discipline", ""),
                        r.get("ecosystem", ""), "sc26_corpus"])

    prov = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": SOURCE_URL,
        "source_tag": SOURCE_TAG,
        "source_sha256": sha,
        "zenodo_doi": ZENODO_DOI,
        "n_total": len(rows), "n_hpc": n_hpc, "n_qc": n_qc,
    }
    with open(args.out + ".provenance.json", "w") as f:
        json.dump(prov, f, indent=2)

    print(f"Wrote {args.out}: {len(rows)} rows ({n_hpc} hpc, {n_qc} qc)")
    print(f"Source sha256: {sha}")
    print(f"Provenance sidecar: {args.out}.provenance.json")

if __name__ == "__main__":
    main()
