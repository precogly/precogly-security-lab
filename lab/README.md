# lab

The lab's one run path: run a scan job against an instance and reimport its report into DefectDojo

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependencies and
tooling.

```bash
uv sync                    # create .venv and install deps + dev tools
uv run pytest              # run tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy src            # type-check (strict)
uv run pip-audit           # scan dependencies for CVEs
```

