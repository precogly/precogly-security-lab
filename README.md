# precogly-security-lab

Precogly's security lab: a Precogly deployment for scanners and pentest agents to
attack, with findings recorded in SecObserve.

It runs on AWS, reachable only over Tailscale. It is not a hosting offering
([#66][66]).

## How it works

```text
  you, teammates ──┐
                   ├── tailnet (policy decides) ──►  pentest       Precogly, as its AWS guide
  scanner box ─────┘                                 :443          deploys it; reaches nothing
       │
       │  scanners and agents run here; `lab` runs each one and
       │  uploads its report
       ▼
  secobserve   the findings record: one vulnerability check per scan job,
  :443         uploaded every run, so its history shows findings over time;
               backed up nightly to S3
```

- **pentest** is Precogly at the latest commit of `main`, deployed with Precogly's
  own [AWS self-hosting guide][guide] and its seed data: two organizations, so
  cross-tenant access can be tested.
- **scanner** is where every scanner and AI pentest agent runs, on its own box so
  that untrusted code stays off teammates' laptops. People reach it over Tailscale
  SSH.
- **secobserve** is [SecObserve][so], self-hosted. Filter findings by scanner or by
  job (its Service). The lab keeps no findings of its own.

Every scan runs through one command, `lab`, so adding a scanner is one definition
file, not another script. See [`lab/README.md`](lab/README.md).

## Repository layout

```text
  terraform/   the network and the three boxes, each with its first-boot script
  lab/         the `lab` CLI and the cross-tenant harness (Python, uv)
  docs/
    setup.md   standing the lab up: Tailscale, Terraform, auth keys, checks
    design.md  why it is built this way: decisions, rejected alternatives, phases
```

## Getting started

Follow [`docs/setup.md`](docs/setup.md): tailnet DNS and policy, `terraform apply`,
an auth key per box, then the checks.

## Status

| | |
|---|---|
| Network, Precogly, scanner box, SecObserve | running, with isolation checked |
| SecObserve backups and restore | nightly dump to S3; restore not yet tested |
| `lab` CLI | `lab jobs`, `lab run`, `--dry-run`; runs reaching SecObserve |
| Jobs | `semgrep`, `trivy-*`, `grype-*`, `zap-baseline`; the harness next |
| `lab auth`, `lab findings` (export for agent triage) | built; checked against the live record |
| `lab run --remote` | designed, not built |
| `lab run --check` | designed, not built |
| Cross-tenant harness | route walk built; replayer not yet written |
| Fargate scan jobs, orchestration | later phases, not started |

First milestone: the harness finds [#226][226], [#227][227] or [#405][405], open
Precogly authorization bugs, as a SecObserve finding.

## Design

Read [`docs/design.md`](docs/design.md) before adding anything. Two anti-goals:

- **Do not reinvent the findings store.** A findings database, cross-tool dedup or a
  triage UI is solved upstream.
- **Do not let the AI layer become the project.** An autonomous pentest agent is one
  more sandboxed job; the isolation around it is the work.

[66]: https://github.com/precogly/precogly/issues/66
[226]: https://github.com/precogly/precogly/issues/226
[227]: https://github.com/precogly/precogly/issues/227
[405]: https://github.com/precogly/precogly/issues/405
[guide]: https://github.com/precogly/precogly/blob/ac22b875c5542a9be1db73f53373f0fa5eac22cc/docs/guides/self-hosting-aws.md
[so]: https://github.com/SecObserve/SecObserve
