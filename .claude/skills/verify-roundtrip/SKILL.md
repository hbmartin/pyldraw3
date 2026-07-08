---
name: verify-roundtrip
description: Fetch a small corpus of real LDraw OMR models and verify pyldraw3 parse/serialize round-trip fidelity and validation against a locally downloaded parts library, inside an isolated HOME so the user's real config and caches are untouched. Use after changing the parser (ldraw/part.py, ldraw/model.py, ldraw/lines.py), the serializers (to_ldraw methods, ldraw/serialization.py), or the validator (ldraw/validation.py).
---

# Verify round-trip fidelity against real OMR models

This repo's unit tests cover two synthetic fixture files; this skill checks
the parser and serializer against real files from the LDraw Official Model
Repository, plus the validator against a real downloaded parts library.
Everything runs locally — CI never downloads the corpus or the library.

## Steps

1. Activate the venv first (required by CLAUDE.md):

   ```bash
   source .venv/bin/activate
   ```

2. Isolate HOME so platformdirs-derived config/cache/data paths never touch
   the user's real `~/Library` or `~/.config`:

   ```bash
   WORK=$(mktemp -d)
   export HOME="$WORK/home"
   export XDG_CACHE_HOME="$HOME/.cache" XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share"
   mkdir -p "$HOME"
   ```

   Run every following command in a shell that has these exports.

3. Download the small versioned parts library (~10 MB, not `complete`):

   ```bash
   ldraw download --version 2018-02 --yes
   ```

4. Fetch the curated corpus (~5 MB, 8 models; skips files already present):

   ```bash
   python scripts/fetch_omr_corpus.py --dest "$WORK/corpus"
   ```

   If a model reports `FAILED`, the OMR may have moved it — note it and
   continue with the rest; update `CURATED_MODELS` in the script if a URL
   is permanently gone.

5. Run the checker with validation:

   ```bash
   python scripts/check_roundtrip.py "$WORK/corpus" --validate --verbose
   ```

## Interpreting results

- `PASS` — clean round-trip. A `known-lossy:` suffix lists normalized,
  documented behaviors (`0 NOFILE` emission differences, junk between
  sections, blank lines, preamble relocation) — these are expected and fine.
- `FAIL ... L0/L1/L2` — a parser or serializer regression. Reproduce with
  `read_model`/`parse_model` on that file and fix before merging.
- `FAIL ... L3 unexplained diff` — the serializer changed content in a way
  the comparator cannot classify. Inspect the printed hunks: either it is a
  real regression, or a newly discovered lossy behavior that should be
  discussed (and, if accepted, added to the comparator's buckets).
- `validate: N error(s)` on official OMR files usually means validator
  false positives — check `KNOWN_META_COMMANDS` in `ldraw/validation.py`
  first (editors add new bang-metas over time), then colour-table coverage
  for the downloaded library version. Warnings on real files are common
  and acceptable (scaled parts, legacy colours).

## Cleanup

```bash
rm -rf "$WORK"
```

Never write into the real HOME; if a command unexpectedly prompts about
paths outside `$WORK`, stop and check the environment exports.
