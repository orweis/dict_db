# Contributing

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

All of these run in CI and must pass:

```bash
pytest --cov              # coverage must stay >= 90%
ruff check .
ruff format --check .
mypy
python -m build           # optional: check that the package builds
```

The tests use [fakeredis](https://github.com/cunla/fakeredis-py) and a small
fake Elasticsearch client (`tests/conftest.py`), so no servers are needed.
When you change how `ElasticDocDict` talks to Elasticsearch, also run the
integration tests against a disposable cluster:
`DICT_DB_ELASTIC_URL=http://localhost:9200 pytest -m integration`
(`DICT_DB_REDIS_URL` does the same for Redis; CI runs the Redis ones).

## Guidelines

- Add a test for every bug fix and feature.
- Keep the public API backwards compatible. If a breaking change is
  unavoidable, bump the major version and document it in `CHANGELOG.md` and in
  the README's migration section.
- Never deserialize untrusted data with `pickle`, and never commit credentials.
