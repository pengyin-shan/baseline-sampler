import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SURFACES = ["cff", "codemeta", "zenodo_json", "readme_citation",
            "doi_record", "registry"]
TARGET_PER_STRATUM = 15
CAP_TOTAL = 30

def truthy(v):
    return str(v).strip().lower() in {"1", "true", "yes", "y"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--availability", required=True)
    ap.add_argument("--corpus", default="corpus.csv")
    ap.add_argument("--min-surfaces", type=int, default=2)
    args = ap.parse_args()

    avail = {}
    with open(args.availability, newline="") as f:
        for row in csv.DictReader(f):
            avail[row["repo_canonical"]] = sum(
                1 for s in SURFACES if truthy(row.get(s, "0")))

    accepted, skipped = [], []
    for stratum in ("joss", "pyopensci"):
        n = 0
        with open(OUT / f"candidates_{stratum}.csv", newline="") as f:
            for row in csv.DictReader(f):
                if n >= TARGET_PER_STRATUM or len(accepted) >= CAP_TOTAL:
                    break
                key = row["repo_canonical"]
                if key not in avail:
                    skipped.append({**row, "skip_reason": "no_availability_record"})
                    continue
                if avail[key] < args.min_surfaces:
                    skipped.append({**row, "skip_reason":
                                    f"eligibility_lt_{args.min_surfaces}_surfaces"
                                    f"({avail[key]})"})
                    continue
                row["surfaces_present"] = avail[key]
                accepted.append(row)
                n += 1
        print(f"{stratum}: accepted {n}")

    # Append to corpus.csv
    with open(args.corpus, newline="") as f:
        reader = csv.DictReader(f)
        corpus_fields = reader.fieldnames

    with open(args.corpus, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=corpus_fields, extrasaction="ignore")
        for r in accepted:
            w.writerow({"name": r["name"], "repo": r["repo_url"],
                        "repo_canonical": r["repo_canonical"],
                        "stratum": r["stratum"],
                        "discipline": r["domain_bin"],
                        "ecosystem": "baseline",
                        "source": f"baseline_{r['stratum']}"})

    with open(OUT / "acceptance_log.json", "w") as f:
        json.dump({"accepted_at_utc": datetime.now(timezone.utc).isoformat(),
                   "accepted": accepted, "skipped": skipped}, f, indent=2)

    print(f"Appended {len(accepted)} baseline rows to {args.corpus}; "
          f"{len(skipped)} skips logged -> out/acceptance_log.json")
    print("Now LOCK the corpus: commit, tag, record the file hash in the "
          "lab notebook. Report skip counts in the methods section.")

if __name__ == "__main__":
    main()
