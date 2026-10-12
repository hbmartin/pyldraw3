# Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and ensure they pass (`uv run pytest`)
5. Format and lint your code (`uv run ruff format .` and `uv run ruff check --fix`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

See the [README](README.md#development) for how to set up a development environment.

## Verification policy

Coverage is configured only in `pyproject.toml`: production `ldraw` source, branch measurement, two decimal places, and a temporary 95% floor. The measured baseline before these fixes was 95.5%; restore the former 97% target once missing branches have meaningful regression tests. Exclusions supplement coverage defaults rather than replacing them. CI collects coverage and runs lint, formatting, complexity, metadata, dependencies, and Python-3.12-targeted type checks once on 3.12; unit tests run on 3.12, 3.13, and 3.14.

Default pytest discovery selects `tests/`. Integration tests require `--integration`; benchmarks require an explicit `benchmarks/` path. The integration matrix retains both the 2018-02 and complete libraries across all supported Python versions.

Production functions have an 80-NLOC budget, measured by Lizard. `scripts/function_budget.json` records existing exceptions and their current ceilings. New exceptions and growth are rejected; remove an exception as soon as its function is within budget. Run `uv run python scripts/check_function_budget.py` alongside the existing complexity check.

## Connection regression corpus

The fixed manifest in `tests/snapshots/connections-2018-02-manifest.json` selects 200 parts across categories, including connector/socket regressions. Snapshots include feature identities, kinds, roles, transforms, profiles, confidence, and provenance; library roots are normalized. Numbers compare with relative tolerance `1e-9` and absolute tolerance `1e-7`, while other fields compare exactly.

Downloads record the archive SHA-256 in `ldraw/_archive_sha256.txt`. A checksum mismatch fails before snapshot comparison. Only the 3.12/2018-02 integration entry runs the corpus:

```bash
uv run ldraw download --version 2018-02 --yes
uv run pytest --integration --connection-snapshots tests/test_connection_snapshots.py
```

Snapshots never update from a test. Regenerate explicitly and inspect the resulting diff:

```bash
uv run python scripts/connection_snapshots.py --parts-list /path/to/2018-02/ldraw/parts.lst
```

Pass `--archive /path/to/retained/archive.zip` if a checksum receipt is unavailable. `--select` deliberately recreates the manifest and archive identity; use it only when intentionally replacing the pinned corpus.

## Performance

Download 2018-02, then run `uv run pytest benchmarks/ --benchmark-only --benchmark-json=benchmark-results.json`. The synthetic workload expands six submodels, placed three times each, to 360 pieces, using twelve common parts and deterministic rotations. Geometry, inspection, and analysis distinguish cold recursive caches from warm caches. CI uses the pinned release; local Scout assets remain outside the repository.

Geometry changes require repeated measurements showing at least 20% end-to-end improvement and at most 5% regression elsewhere. See [performance measurements](docs/performance.md). Startup checks assert which dependencies are loaded, without wall-clock limits.

