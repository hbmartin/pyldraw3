# Performance measurements

Measured locally on macOS ARM64, CPython 3.12, using the pinned 2018-02
library and seven rounds per operation. The deterministic synthetic model
contains 360 leaf pieces, repeated submodels, twelve common part types, and
rotations. Cold runs clear recursive part geometry caches; warm runs reuse them.
Catalog loading and model construction happen outside the timed operation.

| Operation | Before median | After median | Improvement |
| --- | ---: | ---: | ---: |
| Geometry, cold (12 common parts) | 46.33 ms | 28.94 ms | 37.5% |
| Geometry, warm | 12.67 µs | 12.63 µs | 0.3% |
| Inspection, cold (360 pieces) | 860.83 ms | 209.85 ms | 75.6% |
| Inspection, warm | 802.33 ms | 177.49 ms | 77.9% |
| Analysis, cold | 859.92 ms | 216.64 ms | 74.8% |
| Analysis, warm | 810.76 ms | 179.20 ms | 77.9% |

Mean timings also passed the acceptance limits: at least 20% end-to-end
improvement, with no operation regressing more than 5% (warm geometry varied
by +1.8% in the mean). The optimization transforms all expanded vertices in
NumPy batches and reduces actual vertex bounds; it retains public `Vector`
results and does not substitute transformed bounding-box corners.

Local Scout profiling identified matrix/vector transforms and bounds folding
as substantial costs. Its 360-piece analysis decreased from 3.333 s to 1.073 s
under `cProfile` (67.8%). Profiling includes instrumentation overhead and uses
the locally installed complete library; it is supporting evidence, not a CI
fixture. The generator, MPD, inventory, and images are not repository artifacts.

Fresh-process startup medians over seven runs, excluding interpreter launch:

| Operation | Before | After |
| --- | ---: | ---: |
| `import ldraw` | 93.67 ms | 13.43 ms |
| CLI `--help` | 100.52 ms | 22.92 ms |

The package uses cached PEP 562 exports with typing declarations and `__dir__`.
The import hook still registers immediately; the lightweight legacy
`ldraw.generate` module is preloaded so later module imports cannot replace the
public generation function. Bare imports and help are checked in fresh
processes for absence of NumPy and HTTPX2, without fragile timing assertions.

Reproduce the synthetic measurements with:

```bash
uv run ldraw download --version 2018-02 --yes
uv run pytest benchmarks/test_model.py --benchmark-only --benchmark-json=results.json
```

Results depend on the host and environment. CI retains timing data through the
benchmark workflow and downloads the same dated library.

## Instruction construction and structural discovery

Measured locally on macOS ARM64, CPython 3.13.14, comparing `b685879` with
these fixes using identical workloads. Timings are medians of nine batches of
ten operations; model construction is outside the timed operations. No external
parts library is needed.

| Operation | Before median | After median | Improvement |
| --- | ---: | ---: | ---: |
| Build instructions: 50 submodels, 501 steps | 6.65 ms | 4.74 ms | 28.8% |
| Analyze 5,001 uniquely named sections | 18.40 ms | 16.62 ms | 9.7% |

Initial instruction construction previously allocated 501 replacement steps
and 51 replacement sections; it now retains the initially built instances.
A separate `tracemalloc` run measured peak document-construction allocation
falling from 1,007,713 to 889,066 bytes (11.8%). Document replacements still
receive independent correspondence maps and rebind steps when required.
Structural discovery skips ambiguity-specific adjacency construction for unique
names, while retaining the identity graph needed for cycle reporting.

Run the persistent timing workloads with:

```bash
uv run pytest benchmarks/test_instruction_workloads.py --benchmark-only --benchmark-json=instructions-results.json
```

Timing changes are local observations; unit tests verify document ownership,
instance retention, and graph behavior without wall-clock thresholds.
