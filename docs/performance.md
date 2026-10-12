# Performance measurements

The adoption roadmap was measured against commit `08a5cc9`, using the same
verified 2018-02 library and synthetic workload described below. Three paired
baseline/current runs each timed seven rounds; this table reports the median
of the three per-run means. Library loading and document construction remained
outside the timed operations.

| Operation | Baseline | Adoption implementation | Change |
| --- | ---: | ---: | ---: |
| Geometry, cold | 32.49 ms | 33.49 ms | +3.1% |
| Geometry, warm | 13.21 µs | 13.82 µs | +4.6% |
| Inspection, cold | 219.67 ms | 131.69 ms | −40.1% |
| Inspection, warm | 187.45 ms | 94.59 ms | −49.5% |
| Analysis, cold | 221.30 ms | 135.39 ms | −38.8% |
| Analysis, warm | 187.47 ms | 97.41 ms | −48.0% |

The main additional gain comes from reusing validated part-local connection
frames during rigid occurrence placement. Reflections, scale, shear, and invalid
frames continue through the general transform path. Document overlays reuse
library geometry caches when they cannot shadow part definitions. The full
18-operation benchmark suite also checks matrix operations, catalog loading,
search, and visual registration.

Single-part loading improved 21.1%, and multiple-part loading improved 6.9%.
All measured operations met the 5% regression limit. The roughly 120 ns catalog
access benchmark required longer timing blocks: single-operation rounds showed
a noisy 10.1% mean difference while their medians differed by less than 1%.
Three paired runs with 100,000 operations per round measured a 0.4% improvement.
Reproduce that resolution check with
`uv run pytest benchmarks/test_parts_loading.py::test_parts_catalog_access --benchmark-only --benchmark-min-time=0.01 --benchmark-max-time=1 --benchmark-min-rounds=7`.

The earlier geometry and startup optimization measurements follow for context.

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
