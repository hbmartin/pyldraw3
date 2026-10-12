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

