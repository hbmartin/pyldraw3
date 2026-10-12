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

CI checks package metadata on Python 3.12, 3.13, and 3.14 using
`pyroma621==6.1.0`, which provides the `pyroma` command. Run the same check locally
with `uv run --locked pyroma --min 10 .`. CI saves a JSON report for each Python
version, including advisory findings, as a `pyroma621-report-python-*` artifact.

The checker is pinned while we evaluate it. The existing 10/10 rating requirement
still applies, and checker errors fail the step. A five-minute timeout bounds the
check if it stalls. New rules remain advisory by omitting `--strict`; review their
findings and any rule changes before upgrading the pin.
