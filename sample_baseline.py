#!/usr/bin/env python3
"""sample_baseline.py — Sunday steps 3-6.

Applies the pre-registered dedup rules, assigns domain bins, and produces a
SEEDED, DOMAIN-STRATIFIED ordered candidate list per stratum (JOSS,
pyOpenSci), an exclusion log, and an auto-filled pre-registration document.

Design decisions implemented (locked per Aug 5 conversation):
  Stratification: DOMAIN-primary. Candidates are ordered by interleaving
  domain bins round-robin, each bin internally shuffled with the seed, so
  accepting candidates in order spreads acceptances across domains by
  construction. Acceptance YEAR is recorded and reported, not stratified on.

  Dedup rules (applied in this order, every exclusion logged):
    R1 corpus overlap: candidate repo matches one of the 87 -> EXCLUDE.
    R2 dual-listed:   repo appears in both JOSS and pyOpenSci frames ->
                      assigned to the PYOPENSCI stratum (pyOpenSci review is
                      the primary acceptance venue in the partnership; the
                      JOSS record is derivative), flagged dual_listed=1 and
                      EXCLUDED from the JOSS stratum. Reported count required
                      in methods: dual-listed rows carry a JOSS paper DOI, so
                      the DOI-by-construction confound partially extends to
                      the pyOpenSci stratum.
    R3 intra-frame duplicate: same repo, multiple JOSS papers (version
                      papers) -> keep the most recent accepted_date.
    R4 no repo URL / non-resolvable host -> EXCLUDE (logged).
    R5 if repo_canonical does not start with github.com/, exclude
  Domain bins come from domain_map.csv (keyword -> bin; first match wins,
  disciplinary keywords precede generic ones). Candidates matching no
  keyword form an "unmapped" bin that participates in the stratified draw
  rather than being excluded, so the draw does not depend on the coverage
  of the hand-written map. A frame-level ceiling (50% unmapped) keeps a
  broken or empty map fail-loud. (An earlier rule refusing to finalize on
  unmapped-in-window was unsatisfiable under round-robin interleaving and
  was corrected 2026-08-12, before the protocol was registered.)

Eligibility (>=2 of six surfaces) is NOT applied here: it depends on phase0
output, so the auditable order is sample -> probe -> filter -> accept
(accept_candidates.py).

Usage:
    python3 sample_baseline.py --seed 20261002 --oversample 30
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

DOMAIN_MAP = HERE / "domain_map.csv"   # columns: keyword,bin  (hand-curated, committed)

def _repo_key(s: str) -> str:
    s = (s or "").strip().lower()
    return s[len("github.com/"):] if s.startswith("github.com/") else s

def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))

def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_domain_map():
    if not DOMAIN_MAP.exists():
        sys.exit("domain_map.csv missing. Create it (keyword,bin) and commit it "
                 "before sampling; the mapping is part of the pre-registration.")
    m = []
    for row in load_csv(DOMAIN_MAP):
        m.append((row["keyword"].strip().lower(), row["bin"].strip()))
    return m

def assign_domain(raw_tags: str, name: str, mapping) -> str:
    hay = f"{raw_tags} {name}".lower()
    for kw, b in mapping:
        if kw and kw in hay:
            return b
    return "unmapped"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True,
                    help="pre-registered seed; pick once, write it down, never change it")
    ap.add_argument("--oversample", type=int, default=30,
                    help="ordered candidates per stratum (draw window)")
    ap.add_argument("--corpus", default="corpus.csv")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    corpus = load_csv(args.corpus)
    corpus_repos = {_repo_key(r["repo_canonical"]) for r in corpus}
    joss = load_csv(HERE / "frames" / "joss_frame.csv")
    pyos = load_csv(HERE / "frames" / "pyopensci_frame.csv")
    mapping = load_domain_map()

    exclusions = []

    def exclude(row, stratum, rule, note=""):
        exclusions.append({"stratum": stratum, "name": row.get("name", ""),
                           "repo_canonical": row.get("repo_canonical", ""),
                           "rule": rule, "note": note})

    by_repo = {}
    for r in joss:
        key = r["repo_canonical"]
        if not key:
            exclude(r, "joss", "R4_no_repo")
            continue
        prev = by_repo.get(key)
        if prev is None or r["accepted_date"] > prev["accepted_date"]:
            if prev is not None:
                exclude(prev, "joss", "R3_version_paper_superseded",
                        f"superseded by {r['accepted_date']}")
            by_repo[key] = r
        else:
            exclude(r, "joss", "R3_version_paper_superseded",
                    f"kept {prev['accepted_date']}")
    joss = list(by_repo.values())

    pyos_repos = {r["repo_canonical"] for r in pyos if r["repo_canonical"]}

    def prepare(rows, stratum):
        kept = []
        for r in rows:
            if not r["repo_canonical"]:
                exclude(r, stratum, "R4_no_repo")
                continue
            if not r["repo_canonical"].startswith("github.com/"):
                exclude(r, stratum, "R5_non_github_host")
                continue
            if _repo_key(r["repo_canonical"]) in corpus_repos:
                exclude(r, stratum, "R1_corpus_overlap")
                continue
            if stratum == "joss" and r["repo_canonical"] in pyos_repos:
                exclude(r, stratum, "R2_dual_listed_assigned_pyopensci")
                continue
            r = dict(r)
            r["stratum"] = stratum
            r["dual_listed"] = "1" if (stratum == "pyopensci"
                                       and r["repo_canonical"] in
                                       {j["repo_canonical"] for j in by_repo.values()}
                                       ) else "0"
            r["domain_bin"] = assign_domain(r["raw_tags"], r["name"], mapping)
            kept.append(r)
        return kept

    strata = {"joss": prepare(joss, "joss"), "pyopensci": prepare(pyos, "pyopensci")}

    ordered = {}
    for stratum, rows in strata.items():
        rng = random.Random(f"{args.seed}:{stratum}")
        bins = {}
        for r in rows:
            bins.setdefault(r["domain_bin"], []).append(r)
        for b in bins.values():
            b.sort(key=lambda r: r["repo_canonical"])  # stable pre-shuffle order
            rng.shuffle(b)
        order, names = [], sorted(bins)
        i = 0
        while any(bins[n] for n in names):
            n = names[i % len(names)]
            if bins[n]:
                order.append(bins[n].pop(0))
            i += 1
        ordered[stratum] = order
        
    UNMAPPED_CEILING = 0.50
    unmapped_share = {}
    for stratum, rows in strata.items():
        share = sum(1 for r in rows if r["domain_bin"] == "unmapped") / max(len(rows), 1)
        unmapped_share[stratum] = round(share, 3)
        print(f"{stratum}: unmapped domain bin = {100*share:.0f}% of frame after dedup")
        if share > UNMAPPED_CEILING:
            sys.exit(f"{stratum}: {100*share:.0f}% unmapped exceeds the "
                     f"{100*UNMAPPED_CEILING:.0f}% ceiling. domain_map.csv is "
                     "probably not being read or is badly under-specified.")

    fields = ["rank", "stratum", "name", "repo_url", "repo_canonical",
              "accepted_date", "accepted_year", "domain_bin", "dual_listed"]
    for stratum, order in ordered.items():
        path = OUT / f"candidates_{stratum}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for i, r in enumerate(order[:args.oversample], 1):
                r["rank"] = i
                w.writerow(r)
        print(f"{stratum}: {len(order)} eligible after dedup; "
              f"wrote first {min(args.oversample, len(order))} to {path}")

    with open(OUT / "exclusions_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stratum", "name", "repo_canonical",
                                          "rule", "note"])
        w.writeheader()
        w.writerows(exclusions)
    print(f"Exclusion log: {len(exclusions)} rows -> out/exclusions_log.csv")

    prereg = {
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "oversample_per_stratum": args.oversample,
        "target_per_stratum": 15,
        "cap_total": 30,
        "stratification": "domain-primary (round-robin over hand-mapped bins, "
                          "seeded shuffle within bin); acceptance year recorded "
                          "and reported, not stratified on",
        "eligibility_filter": ">=2 of six metadata surfaces present, applied "
                              "after phase0 probe, acceptance in rank order",
        "dedup_rules": ["R1 corpus overlap -> exclude",
                        "R2 dual-listed -> pyopensci stratum, flagged",
                        "R3 JOSS version papers -> most recent kept",
                        "R4 missing repo URL -> exclude",
                        "R5 non-GitHub host -> exclude (all six eligibility "
                        "surfaces are probed through the GitHub API)"],
        "known_confound": "every JOSS project carries a paper DOI by "
                          "construction; dual-listed pyOpenSci rows inherit "
                          "this; comparison presented as illustrative, not "
                          "inferential",
        "inputs": {
            "corpus_sha256": file_sha(args.corpus),
            "joss_frame_sha256": file_sha(HERE / "frames" / "joss_frame.csv"),
            "pyopensci_frame_sha256": file_sha(HERE / "frames" / "pyopensci_frame.csv"),
            "domain_map_sha256": file_sha(DOMAIN_MAP),
        },
        "domain_binning": "keyword map (domain_map.csv, committed; first match "
                          "wins, disciplinary keywords precede generic ones). "
                          "Candidates matching no keyword form an 'unmapped' "
                          "bin that participates in the stratified draw",
        "unmapped_share_by_stratum": unmapped_share,
    }
    with open(OUT / "preregistration.json", "w") as f:
        json.dump(prereg, f, indent=2)
    print("Pre-registration written -> out/preregistration.json "
          "(deposit/register this BEFORE running the eligibility probe).")

if __name__ == "__main__":
    main()
