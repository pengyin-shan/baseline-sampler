import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
import yaml
from datetime import datetime, timezone
from pathlib import Path

FRAMES = Path(__file__).resolve().parent / "frames"

JOSS_API = "https://joss.theoj.org/papers/published.json?page={page}"
PYOS_CANDIDATES = [
    "https://raw.githubusercontent.com/pyOpenSci/pyopensci.github.io/main/data/packages.yml"
]

def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "rda-baseline-frames/0.1"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))

def canonical_repo(url: str) -> str:
    if not url:
        return ""
    r = url.strip().lower()
    r = re.sub(r"^https?://(www\.)?", "", r)
    if r.endswith(".git"):
        r = r[:-4]
    return r.strip("/")

def write_frame(path: Path, rows, source_desc):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "repo_url", "repo_canonical",
                                          "accepted_date", "accepted_year",
                                          "raw_tags", "source_record_url"])
        w.writeheader()
        w.writerows(rows)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prov = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": source_desc, "n_rows": len(rows), "sha256": digest}
    with open(str(path) + ".provenance.json", "w") as f:
        json.dump(prov, f, indent=2)
    print(f"Wrote {path} ({len(rows)} rows), sha256 {digest[:12]}...")

def fetch_joss():
    rows, page = [], 1
    while True:
        data = json.loads(fetch(JOSS_API.format(page=page)))
        if not data:
            break
        for p in data:
            pub = p.get("published_at") or ""
            tags = p.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            raw_tags = ";".join(t for t in (str(x).strip() for x in tags) if t)
            rows.append({
                "name": p.get("title", "").strip(),
                "repo_url": p.get("software_repository", "").strip(),
                "repo_canonical": canonical_repo(p.get("software_repository", "")),
                "accepted_date": pub[:10],
                "accepted_year": pub[:4],
                "raw_tags": raw_tags,
                "source_record_url": f"https://doi.org/{p.get('doi','')}",
            })
        page += 1
        time.sleep(0.5)
    print("writing to", (FRAMES / "joss_frame.csv").resolve())
    write_frame(FRAMES / "joss_frame.csv", rows, "JOSS published.json API")


def parse_pyos_yaml(text: str):
    data = yaml.safe_load(text)
    if not isinstance(data, list):
        sys.exit("pyOpenSci file did not parse as a YAML list; "
                 "verify PYOS_CANDIDATES points at packages.yml.")
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        repo = r.get("repository_link") or ""
        date = str(r.get("date_accepted") or "")
        cats = r.get("categories") or []
        if isinstance(cats, str):
            cats = [cats]
        desc = (r.get("package_description") or "").strip()
        tags = [str(c).strip() for c in cats if str(c).strip()]
        if desc:
            tags.append(desc)
        out.append({
            "name": r.get("package_name") or "",
            "repo_url": repo,
            "repo_canonical": canonical_repo(repo),
            "accepted_date": date[:10],
            "accepted_year": date[:4],
            "raw_tags": ";".join(tags),
            "source_record_url": r.get("issue_link") or "",
        })
    return out

def fetch_pyopensci():
    last_err = None
    for url in PYOS_CANDIDATES:
        try:
            raw = fetch(url)
            if raw[:3] == b"404" or b"404: Not Found" in raw[:40]:
                continue
            rows = parse_pyos_yaml(raw.decode("utf-8"))
            if rows:
                write_frame(FRAMES / "pyopensci_frame.csv", rows, url)
                return
        except Exception as e:  # try next candidate
            last_err = e
    raise SystemExit(
        "Could not retrieve the pyOpenSci package registry from the candidate "
        "URLs. Find the current data file (the website's package listing is "
        "generated from a YAML in the pyOpenSci/pyopensci.github.io repo, or "
        "ask in their Discourse), add its raw URL to PYOS_CANDIDATES, adjust "
        f"field names in parse_pyos_yaml, and re-run. Last error: {last_err}"
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["joss", "pyopensci"])
    args = ap.parse_args()
    FRAMES.mkdir(exist_ok=True)
    if args.only in (None, "joss"):
        fetch_joss()
    if args.only in (None, "pyopensci"):
        fetch_pyopensci()

if __name__ == "__main__":
    main()
