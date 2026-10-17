# precogly-security-lab

A security-scan orchestration platform on AWS: a control plane that fans scan jobs
out as ephemeral containers, runs them against a target, and lands every finding in
a self-hosted DefectDojo. Off-the-shelf scanners and a hand-written pentest harness
are equal citizens — each is a job the platform runs.

## What this is, and is not

This is a **personal learning and portfolio project**, not part of Precogly. It
borrows Precogly as the target it scans and the subject its harness attacks; Precogly
does not adopt it, and its own issue [#66][66] scopes hosting out of the project. The
primary goal is learning AWS by building a real multi-service system on it — VPCs,
load-balancer classes, security groups, routing between services, IAM. AppSec
capability and a defensible resume artifact are secondary.

## Design

The architecture, the decisions with their rejected alternatives, the AWS-service to
learning-goal map, and the phased build live in the design doc, which sits with its
sibling plans in the Precogly working tree (gitignored scratch there):

    precogly/docs/design/security-orchestration-platform.md

Read it before adding anything here. Two anti-goals from it are worth repeating,
because both are cheap to walk into:

- **Do not reinvent DefectDojo.** A findings database, cross-tool dedup, or a triage
  UI is solved upstream. Building any of them is CRUD that teaches neither AWS nor
  AppSec.
- **Do not let the AI layer become the project.** An autonomous LLM pentest agent is
  a sandboxed job type, not the point — the isolation around it is the AWS lesson.

## Status

Nothing applied yet. Phase A is two EC2 boxes on a tailnet: a Precogly instance
deployed from Precogly's own AWS guide, and a scanner box where scanners and AI
pentest agents run against it. Neither accepts a connection from the internet; the
tailnet policy decides who reaches what (`docs/tailnet-setup.md`). Phase A is done
when the cross-tenant harness, run from the scanner box, finds a real open Precogly
authz bug ([#226][226], [#227][227], [#405][405]). DefectDojo and Fargate scan jobs
come in Phase B.

[66]: https://github.com/precogly/precogly/issues/66
[226]: https://github.com/precogly/precogly/issues/226
[227]: https://github.com/precogly/precogly/issues/227
[405]: https://github.com/precogly/precogly/issues/405
