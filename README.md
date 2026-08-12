# baseline-sampler

Implements the pre-registered JOSS/pyOpenSci baseline draw.

Details come later.

## Env
```bash
export GITHUB_TOKEN=xxx
export AUDIT_CONTACT=xxx
python3 tests/test_comparators.py # run for tests before start
```
## Run
```bash
python3 fetch_frames.py
python3 export_corpus.py --out corpus.csv
python3 sample_baseline.py --seed <SEED> --oversample 30
python3 -m rda_audit adapt-corpus --sampler-corpus ../baseline-sampler/corpus.csv --out corpus.csv --detected-registry ../baseline-sampler/out/candidate_availability.csv
```

## Notes

- 202608121338 seed: [corresponding commit# here once available]
- R1 repository comparison normalized across corpus and frame canonical forms, corrected 2026-08-12 before registration; the pre-fix draw contained no overlaps.