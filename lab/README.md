# lab

The one way scans run in the lab: `lab run` starts a scan job against the
Precogly instance, then uploads its report to SecObserve. It runs on the
scanner box.

```text
lab jobs                    list jobs; fail on any that do not load
lab run <job>... | --all    run jobs, then upload each report
lab run <job> --dry-run     read the real tailnet, address and commit; print every
                            change a run would make; make none
```

A run's files land in `/var/lib/lab/runs/<run-id>/<job>/`: the report, the
container's `job.log`, and `meta.json` with the status, exit code, and how many
findings SecObserve counted as new, updated and resolved.

## Adding a job

A job is a TOML file in `src/lab/jobs/`. The contract every job gets, and the
reasoning behind it, is in [`docs/design.md`](../docs/design.md), D14.

```toml
name      = "zap-baseline"                     # must match the file name
image     = "ghcr.io/zaproxy/zaproxy:2.17.0"   # a pinned tag or digest
out_mount = "/zap/wrk"                         # optional; default /out
command   = ["zap-baseline.py", "-t", "{target_url}", "-J", "report.json"]
report    = "report.json"                      # relative to out_mount
timeout   = "30m"                              # optional; default 1h
# inputs  = ["precogly-images"]                # built from Precogly at the run's commit
# assets  = "harness"                          # lab/src/lab/<name>, mounted at /job
# secrets = ["anthropic-api-key"]              # from precogly-seclab/jobs/ in Secrets Manager
# scans_image = "precogly-backend"             # labels image findings with the commit
```

The report must be in a format SecObserve parses, which it detects from the file:
SARIF for code findings, CycloneDX for image findings (SARIF loses which package),
or a format with its own parser such as ZAP's JSON. Check the job loads with
`lab jobs`, and see exactly what it would run with `lab run <job> --dry-run`.

## How it is built

```text
src/lab/
  main.py        the CLI
  job.py         job definitions and their validation
  target.py      the target definition (targets/pentest.toml)
  container.py   the `docker run` every job gets
  inputs.py      Precogly's source and images, for jobs that scan them
  run.py         one run: jobs, report checks, uploads, meta.json
  sarif.py       rewrites SARIF paths to repository paths before upload
  command/       every external effect, a process or an HTTP request, as a READ
                 or a WRITE; --dry-run performs the reads and prints the writes
    core/        the effect types and the runners that perform them
  harness/       the cross-tenant harness
```

## Development

```bash
uv sync
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy src tests  # type-check (strict)
```
