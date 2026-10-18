# Security orchestration platform

A lab on AWS for running Precogly deployments for different purposes. One
deployment is a target for security scanners and pentest agents. Another is where
the core team tries out a feature that needs real infrastructure, such as Entra ID
SSO ([#585](https://github.com/precogly/precogly/issues/585)). Access is a
tailnet: every box a person or a scanner has to reach joins it, and the tailnet
policy decides who reaches what. Nothing in AWS accepts a connection from the
internet.

Phase A is two boxes: a Precogly instance, and a scanner box where scanners and
AI pentest agents run against it. Later phases add what the platform was first
designed around: instances created by name from a small config, scan jobs as
ephemeral containers. SecObserve is where every finding lands, from Phase A.
Off-the-shelf scanners and a hand-written pentest harness are equal citizens:
each is a job the platform runs, reporting in a format SecObserve parses.

## Goals

Stated in priority order, because every decision below is resolved by which goal an
item serves, and two of them pull against each other.

1. **Learn AWS by building a real multi-service system on it.** Primary. Measured by
   which services get used for a reason — not name-checked — and whether the
   networking, IAM, and orchestration are things built and debugged rather than
   copied. The gap this closes is stated plainly: load-balancer classes, VPCs,
   security groups, and routing between services.
2. **Produce an application-security capability and the evidence for it.** The
   platform runs real tools against a real target and finds real defects. It is also
   the substrate for the AppSec pipeline's Phase 3 and Phase 5 work
   (`precogly/docs/design/appsec-pipeline-plan.md`, gitignored scratch in the
   Precogly working tree), which had no runner.
3. **Give the core team a lab.** Two or three people need a shared place to run
   Precogly the way users run it, in whatever configuration a piece of work needs,
   without hand-building a server each time. This goal arrived on 2026-10-13. It is
   what turned "a target" into "instances on a base" (D8).
4. **A resume artifact that survives scrutiny.** The bullets are in the tracker at
   the end. The test is the same one the AppSec plan uses: it can be defended cold —
   design owned, debuggable unaided.

Two anti-goals, because the failure modes here are specific and both are cheap to
walk into:

- **Do not reinvent the findings store.** A findings database, cross-tool dedup, and
  a triage UI are solved upstream. Building any of them is CRUD that teaches neither
  AWS nor AppSec. The moment a findings table or a dedup function is being written,
  stop — that is SecObserve's job, and it is better at it.
- **Do not let the AI layer become the project.** Autonomous LLM pentest agents are
  the least mature thing on this board. They are a hardened job type the platform can
  run, not its purpose. Debugging prompt loops is not learning AWS.

## Where this sits relative to Precogly

The code lives outside Precogly's repository, in `precogly-security-lab`. Hosting
Precogly as a product is still scoped out by
[#66](https://github.com/precogly/precogly/issues/66) ("not yet needed"), and this
lab does not change that: nothing here is a service Precogly offers its users.

What has changed is who uses it. Until 2026-10-13 this section said the platform
borrows Precogly as a subject without asking the project to adopt it. A lab the core
team tests features in is used by the project, even if the project does not own it.
Whoever deploys the lab owns it: it runs in their AWS account, and they decide who
creates instances in it.

Every instance deploys Precogly by following
[`docs/guides/self-hosting-aws.md`](https://github.com/precogly/precogly/blob/ac22b875c5542a9be1db73f53373f0fa5eac22cc/docs/guides/self-hosting-aws.md),
Precogly's own guide to self-hosting on AWS (D9). The custom harness exercises
Precogly's multi-tenant and BYOM surfaces on those instances.

## Requirements

Who uses the lab, and what each use needs from it. Every decision below should trace
back to a row here; one that does not is a patch.

| | Requirement | Comes from |
|---|---|---|
| R1 | Two or three people reach the lab over HTTPS, behind an identity check. Nobody else reaches it | The core team (goal 3) |
| R2 | An instance runs Precogly the way users run it, so behaviour seen in the lab is behaviour users would see | Feature testing (goal 3), and findings that apply to real installs (goal 2) |
| R3 | Instances differ by a small config, not by hand-built servers: the git ref (`main` for now), auth mode (local or Entra ID), seed data, extras | One lab, many purposes (goal 3) |
| R4 | Scanners and agents reach the instance they target, from the scanner box or a scan job, and no other instance | Scanning (goal 2); a team member's instance is not a target |
| R5 | An instance can be reset, and one that is forgotten is eventually removed | Pentest damage, and cost |
| R6 | An agent that escapes its job reaches nothing beyond its target: not other instances, not the base, not the internet | The agent sandbox (Phase E). Not met in Phase A: the scanner box has internet egress (D12) |

Not required for now: a Claude.ai MCP connector reaching an instance. It would need
Anthropic's servers to pass the access gate in R1, which conflicts with it. It is
revisited if the team needs it.

## Architecture

Phase A is two EC2 instances in one public subnet, each joined to the tailnet under
a tag. The tailnet policy is the access control: it names who may reach which tag on
which port, and denies everything else.

```text
  team member's laptop ──┐   (logged in to the tailnet as a named person)
                         │
  scanner box ───────────┤   tag:scanner, EC2: scanners, harness, AI agents (D12)
                         │
                         ▼   tailnet policy (D10): people → tag:precogly :443
                             and → tag:scanner :22 (Tailscale SSH);
                             tag:scanner → tag:precogly :443; nothing else
  ┌─ VPC, public subnet ───────────────────────────────────────────────────┐
  │                                                                        │
  │   instance "pentest"                     scanner box                   │
  │   tag:precogly                           tag:scanner                   │
  │   https://pentest.<tailnet>.ts.net       results on its own disk       │
  │   EC2: compose, Caddy, Django,                                         │
  │   nginx, Postgres (D9)                                                 │
  │                                                                        │
  │   security groups: no inbound rules on either box                      │
  └────────────────────────────────────────────────────────────────────────┘
          ▲
          └── the internet: no path in. Both boxes have public IPs only so
              Tailscale, packages and images can go out without a NAT.
```

Later phases add the platform the lab was first designed around. A **base** is
built once and lives as long as the lab does; **instances** are Precogly deployments
created on it and destroyed by name (D8). This is how security labs that offer many
configurations are built, rather than by listing the combinations: GOAD (labs ×
providers × extensions), Ludus (a range config of VM templates plus roles), Splunk
Attack Range (`config/<attack_range_id>.yml` per range), CloudGoat (one folder per
scenario, named with a unique ID), and per-pull-request preview environments (names
and state keys derived from the PR number).

What each part means for the system:

- **The tailnet is the only way in**, for people and scanners alike (D10). Each box
  runs `tailscaled`, joined with a one-off auth key that is deleted after it joins.
- **One name per box, everywhere.** `<name>.<tailnet>.ts.net` comes from MagicDNS.
  The certificate on it is a Let's Encrypt one that Tailscale obtains and Caddy
  serves, so every browser and scanner trusts it with no setup (D11).
- **Instances cannot reach anything on the tailnet.** `tag:precogly` is never a
  source in the policy. A stolen node key from a compromised instance reaches no
  other machine, laptops included (D10).
- **An instance is one Terraform module call** with its own state, named by the
  instance's name, once there is more than one (D8). Its name is where its hostname,
  its tag and its resource names come from. Resetting it means destroying it and
  creating it again. Phase A's single instance is written out literally.
- **Step Functions Map state** (Phase B) fans scan jobs out against one instance. It retries a
  failed job without failing the run, and waits for all of them before the collector
  starts.
- **Fargate task per scanner**, ephemeral, each with its own IAM role. Cost tracks use.
  A task reaches its target the way the scanner box does, as an ephemeral
  `tag:scanner` node on the tailnet; how a task gets an auth key is open (Open
  questions).
- **S3 is the handoff** between "a scanner finished" and "a finding was imported", so
  the collector can be retried and a run's raw output survives for re-import.
- **SecObserve parses the standard formats**: SARIF, CycloneDX and ZAP's JSON among
  them, detecting the parser from the file (`import_observations/parsers`, v1.61.0).
  Each job reports in one of those (D14); a tool with none, like Schemathesis, needs
  its output converted to SARIF. The collector uploads raw reports and does not
  normalize them. The custom harness writes SARIF.

**Nothing sits between a scanner and Precogly's own TLS and headers.** A scan has to
measure the thing being assessed. The AppSec plan withdrew ZAP's Reason A because it
scanned through a proxy whose security headers came from somewhere else. People and
scanners both reach the instance's own Caddy over the tailnet, and Tailscale carries
packets without terminating TLS, so there is no second path that would measure
something else. Under the Cloudflare design that rule needed stating, because the
tunnel was such a path.

**Scan jobs are scoped by what they measure.**

- *Application layer*: cross-tenant authorization, injection, mass assignment,
  malformed-input 500s, dependency CVEs. These live in the Django code and are the same
  whatever the network position. They run against a lab instance.
- *Deployment layer*: TLS configuration, response headers, exposed ports, what the app
  can reach from where it sits. Because an instance follows Precogly's own deployment
  guide (D9), the parts that come from Caddy, compose and Django settings are measured
  as users would have them. The internet exposure is not: the guide opens 22, 80 and 443
  to the world, and the lab does not (R1). Findings about that exposure come from
  reading the guide, not from scanning.

## AWS services, and the learning each one carries

The point of the table is the right column. A service is here because building with it
teaches something the goal names, not because the diagram needed a box.

| Service | Role in the platform | What it teaches |
|---|---|---|
| VPC, one public subnet | Phase A's network: both boxes. Private subnets and a NAT come back when Fargate jobs or SecObserve need them | Subnet as a routing fact, not a label |
| Route tables, IGW | The boxes reach Tailscale, packages and images through the internet gateway, with no NAT | The public/private split *is* the route table, and a public subnet with no inbound rule is still closed |
| **Security groups** | One per box, with no inbound rules and egress written out. Access between boxes is the tailnet policy's job, not the security groups' (D10) | A group as a label, default-deny ingress, and what a group cannot express (identity) |
| EC2 | The instance, as Precogly's guide deploys it (D9); the scanner box (D12); SecObserve until Phase D | User data, instance profiles, IMDSv2, what a box needs to come up unattended |
| **Terraform modules and per-instance state** | The instance stack, called once per instance | Base/instance layering, state isolation, safe create and destroy |
| ECS / Fargate | Every scan job | Task definitions, ephemeral vs. service, task networking |
| Step Functions | The scan workflow: fan out, wait, collect | Orchestration, Map state, retry/catch |
| EventBridge | Trigger source, schedule or manual; later the instance reaper (R5) | Decoupled triggers |
| SQS | Backpressure between trigger and workflow (added when concurrency matters) | Queues, retries, DLQs |
| S3 | Raw scanner output per run | Object storage, lifecycle, prefix-scoped access |
| **IAM task roles** | Each job gets only what it needs: its S3 prefix, its secrets, nothing else | Least privilege as a control, an AppSec lesson delivered as an AWS one |
| **ALB (L7)**, RDS | SecObserve when it goes native in Phase D (D1). No instance uses them | Load-balancer routing and managed data services, on the one service that is AWS-shaped |
| Secrets Manager | SecObserve upload token, each instance's `SECRET_KEY` and database password, provider keys for the AI jobs | Secret handling without baking into images or user data |

The ALB moved. Until 2026-10-13 it fronted the target, and teaching load balancers was
the target's job. A target deployed the way Precogly documents has no load balancer, so
that lesson now comes from SecObserve in Phase D. Phase A teaches less AWS than it did.
That is the cost of R2.

## Decisions

Each names what was chosen, what was rejected, and what disqualified it, so the
alternatives are not re-derived later.

### D1 — DefectDojo hosting: native, with an EC2-compose start

**Superseded 2026-10-17 by D14**, which replaced DefectDojo with SecObserve on one EC2.
The staging argument below still holds for SecObserve: Phase D moves it to ECS and RDS.

**Chosen:** start on a single EC2 running DefectDojo's own docker-compose, then migrate
to ECS Fargate + RDS Postgres + ElastiCache Redis behind an internal ALB as a
deliberate second AWS lesson.

- **EC2 + compose** — ~$15/mo, one box, DefectDojo ships the compose file. Gets the
  findings sink up on day one so the MVP thread can complete.
- **Native (ECS + RDS + ElastiCache + ALB)** — ~$60–90/mo before any scanner runs, and
  the most AWS in the whole platform: a real multi-service app deploy with managed data
  services and a service-to-service SG mesh. This is where goal 1 is served hardest.

Rejected as the *starting* point, not as the destination: going straight to native puts
the largest cost and setup ahead of the first finding. The migration itself — RDS
import, cutover, retiring the box — is a named AWS lesson, so staging it is free value
rather than rework.

### D2 — Compute and orchestration: Fargate + Step Functions

**Chosen:** Fargate for jobs, Step Functions for the workflow, EventBridge as the
trigger.

- **Fargate over Lambda** — scanners are containers and some run for minutes to hours;
  Lambda's 15-minute cap and packaging constraints do not fit. Fargate also teaches
  task networking, which Lambda hides.
- **Fargate over CodeBuild** — CodeBuild runs a container job cheaply but teaches less
  general AWS; it is a CI primitive, not a compute model.
- **Step Functions over a hand-rolled SQS-worker** — the Map state gives fan-out,
  wait-for-all, and per-branch retry natively. Hand-rolling that is the orchestration
  lesson skipped.
- **ECS over EKS** — Kubernetes is bigger and more marketable, but it is a detour from
  the networking-and-IAM learning that goal 1 names. Revisit if K8s becomes the goal
  itself.

### D3 — Infrastructure as code: Terraform

**Chosen:** Terraform over CDK.

Terraform makes the resource dependency graph explicit, which is how what-depends-on-what
in a VPC is actually learned, and it is the more-asked resume term. It also produces a
by-product the rest of the work wants: a real `.tf` corpus for the AWS-pack and
Terraform→DFD component-resolution work
([#294](https://github.com/precogly/precogly/issues/294)), which today has none — the
only corpus is docker-compose, 0% of which resolves. Two efforts feed each other.

### D4 — Aggregation: the findings store, no custom store

Settled above and restated as a decision because it is the one most likely to erode.
SecObserve is the findings sink (D14; DefectDojo until 2026-10-17). The collector imports; it does not aggregate. No
findings table, no dedup logic, no triage UI is written here. See the anti-goal.

### D5 — Access paths: an internal ALB in Phase A, a tunnel for DefectDojo

**Superseded 2026-10-13 by D8–D10.** D5–D7 each fixed a problem the one before it
created, all downstream of a target nobody runs (see the Log). They stay here so
their reasoning is not re-derived. What survives: scanners never go through the
tunnel, and SSM port-forwarding loses on first-run debuggability.

**Chosen:** the Phase A load balancer is `internal`, its only client is the scanner
security group, and DefectDojo's UI is reached by a second Cloudflare Tunnel rather than
a host route on it. No security group in Phase A admits the internet.

- **Rejected: an internet-facing ALB with a narrow security group.** A public load
  balancer *is* the internet-facing deployment this doc defers — restricting who may
  connect does not change which deployment exists. It would produce something shaped
  like the public tier, scanned as though it were the private one, and belonging to
  neither. The scan-tier split above holds only while exactly one deployment exists, so
  the honest scheme is the one that matches.
- **Why the ALB is there at all, with one internal client.** The harness has to meet the
  target the way an attacker does: through the load balancer, against its address and
  its `X-Forwarded-For` handling. Pointed at the task's port instead, it would be
  measuring Django on a socket, and the application-layer results would not carry over
  to the public deployment unchanged — which is the property the tier split depends on.
- **Why DefectDojo's UI is a tunnel and not a host route.** The tunnel decision above
  rests on scan fidelity: response headers must come from the thing being assessed.
  DefectDojo is never scanned, so that argument does not reach it, and what remains is
  cost and exposure. A host route needs a public listener, a domain and an ACM
  certificate in order to show a UI to two people. The tunnel needs none of them, adds
  no ingress rule, and reuses a mechanism already in place for the target.
- **Rejected: SSM Session Manager port-forwarding.** Zero ingress as well, and the
  AWS-native answer, which suits goal 1. It loses on first-run debuggability: the
  instance profile and the SSM agent both have to be working before the UI is visible at
  all, so the failure mode when DefectDojo will not come up is a blind one.

**What this defers, and it is not small.** Goal 1 names public ingress and TLS
termination. Public ingress is not built in Phase A; it arrives with the internet-facing
deployment, alongside the deployment-layer scan tier that has nothing to measure until
then. TLS termination was deferred here too, and D7 brought it forward. Two Cloudflare
Tunnels also means the only two human paths into the platform are
not AWS, in a project whose primary goal is learning AWS.

### D6 — Target routing: ALB path rules, not the frontend's nginx

**Superseded 2026-10-13 by D9.** An instance has no ALB, and Caddy does this routing
as the guide configures it.

**Chosen:** the ALB splits traffic by path, the way Precogly's own AWS guide does. A
backend target group on gunicorn's port 8000 takes `/api/*`, `/admin/*`, `/media/*`,
`/mcp`, `/o/*` and `/.well-known/*`. The listener's default action goes to a frontend
target group on nginx's port 80, which serves the SPA. Both target groups register the
same ECS service, one container port each.

The path list is copied from the Caddyfile in
[`docs/guides/self-hosting-aws.md`](https://github.com/precogly/precogly/blob/ac22b875c5542a9be1db73f53373f0fa5eac22cc/docs/guides/self-hosting-aws.md)
(Vikram, PR #558). That guide is the deployment Precogly tells people to run. The Caddy
`handle` blocks map onto listener rules one for one:

```text
                          ┌─ /api/* /admin/* /media/* ─┐
  scanner ──► ALB :443 ───┤                            ├──► backend TG  ──► gunicorn :8000
                          └─ /mcp /o/* /.well-known/* ─┘
                          └─ default ─────────────────────► frontend TG ──► nginx :80 (SPA)
```

Both target groups point at the same task. The diagram shows two paths into one network
namespace, not two services.

- **Rejected: everything through nginx** (ALB:80 → nginx → `localhost:8000`). This was
  the plan until the guide existed, and it has three problems:
  - It needs `backend:8000` in `frontend/nginx.conf` changed to `localhost:8000`, which
    patches the system under test.
  - nginx proxies only `/api/`, `/admin/` and `/media/`, so `/mcp` and the OAuth routes
    under `/o/` would be unreachable.
  - It puts an nginx hop in front of the API that the reference deployment does not have.
    The harness would be meeting a different system from the one users run, which is the
    scan-fidelity error D5 exists to avoid.
- **Why this serves goal 1 as well:** listener rules, priorities, and two target groups
  behind one service are the "routing between services" the goal names. The nginx path
  would have hidden all of it inside a container's config file.

**What it costs.**

- A second port in the security-group mesh: `alb → target :8000`, egress and ingress.
  The header of `security_group.tf` says no rule carries the :8000 hop. That stops being
  true and has to be rewritten.
- A second target group, a second health check, and two `load_balancer` blocks on the
  ECS service.
- Six paths do not fit in one rule. ALB conditions allow three values per condition,
  five match evaluations per rule, and five wildcards per rule
  ([condition types](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/rule-condition-types.html),
  read 2026-10-13). So this is at least two rules.

nginx's own `/api/` proxy blocks stay in the image, unchanged and never reached.

### D7 — TLS on the internal ALB

**Superseded 2026-10-13 by D9.** The redirect problem it solved belongs to the guide's
deployment too, where Caddy terminates TLS and `workshop.py` trusts its header. How
Caddy gets a certificate inside the lab is open (Open questions).

**Chosen:** the internal ALB has a single HTTPS listener on 443. It serves a public ACM
certificate for a hostname under a domain we control. A Route 53 private hosted zone,
associated with the VPC, resolves that hostname to the ALB. The ALB-to-task hop stays
plain HTTP inside the VPC. There is no :80 listener.

**The forcing problem:** Precogly's `production.py` sets `SECURE_SSL_REDIRECT`,
`SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`. On a plain-HTTP listener, every request
from the harness gets a 301 to https, and a cookie jar holds the session cookie back on
the next request because it is marked secure. The harness cannot authenticate, so it
cannot test cross-tenant access.

- **Rejected: a lab settings module that turns those three off.** It is cheaper: no
  domain, no certificate, no DNS. The cost is that the target runs a configuration no
  real deployment runs. The application-layer results would carry over to the public
  deployment, but only after an argument that the switched-off settings never mattered.
  The tier split is supposed to make that argument unnecessary.
- **Rejected: publishing the ALB's name in public DNS.** An internal ALB's DNS name
  resolves publicly to its private addresses, so a public CNAME would work without a
  private zone. But it publishes the VPC's internal addresses, and it skips split-horizon
  DNS, which is the AWS part of this decision.

**TLS alone does not end the redirect loop.** The ALB sends `X-Forwarded-Proto: https`,
but `production.py` has no `SECURE_PROXY_SSL_HEADER`, so Django ignores that header and
still sees plain HTTP from the ALB. The fix is the one-line `workshop.py` from Precogly's
AWS guide, which subclasses production and trusts that header. The target runs
`config.settings.workshop`, a configuration Precogly itself tells people to use, not one
invented here. The guide creates the file on the host, so the image this lab builds has
to carry it.

**What this costs or defers.**

- It needs a domain whose public DNS we control. ACM validates by a CNAME in public DNS,
  which a private hosted zone cannot serve. The CNAME stays in place, or renewal fails.
- The private hosted zone is $0.50/mo (Route 53 pricing, to be checked when it is
  built). The certificate is free.
- `scanner → alb` moves from :80 to :443 in the mesh.
- The backend target group's health check reaches gunicorn directly. It has no
  `X-Forwarded-Proto` and its Host is the task's IP, so `ALLOWED_HOSTS` or
  `SECURE_SSL_REDIRECT` rejects it before it reaches `/api/health/`. This is not
  resolved here; see `SESSION.md` in the lab repo.

### D8 — A base and instances, not a target

**Chosen:** the lab is a long-lived base plus Precogly instances created and destroyed
by name. An instance is one call of a Terraform module, with its own state, and its
differences from other instances are a small config: git ref, auth mode, seed data,
extras.

- **Rejected: one shared deployment that the team and the scanners take turns on.**
  A pentest agent's damage lands in a teammate's test. Testing Entra ID SSO and testing
  cross-tenant authz need different configurations at the same time, and one
  deployment holds one configuration.
- **Rejected: a Terraform root per purpose** (`sso/`, `pentest/`). This is the
  combinations problem written out by hand. Every new purpose copies a stack, and the
  copies drift.
- **Rejected: Terraform workspaces over a single root.** Workspaces give per-instance
  state, but which instance a command acts on is set by `terraform workspace select`,
  which is easy to get wrong when destroying. Per-instance state by name keeps the
  instance in the command.
- **Why this shape:** it is what every lab and preview-environment system read for this
  decision converged on (Architecture). Combinations become config values, not designs.

**What it costs.** Explicit resources gave way to a module for the instance stack;
the base stays literal. Instances need a reaper or they accumulate (R5). How the
module is invoked, and where per-instance state is keyed, is not designed yet.

### D9 — An instance is Precogly's own AWS deployment

**Chosen:** an instance follows
[`docs/guides/self-hosting-aws.md`](https://github.com/precogly/precogly/blob/ac22b875c5542a9be1db73f53373f0fa5eac22cc/docs/guides/self-hosting-aws.md)
(Vikram, PR #558): one EC2 running compose, with Caddy, Django/gunicorn, nginx serving
the SPA, and Postgres. The lab departs from the guide only where R1 forces it, and
each departure is listed in the instance module.

- **Rejected: Precogly on Fargate + RDS behind an ALB**, the design until 2026-10-13.
  It taught more AWS and was a deployment nobody runs. Each part of it broke a
  Precogly assumption: a compose service name in `nginx.conf`, the production
  settings' HTTPS redirect, seeding only in the dev image. Fixing those produced
  D5–D7.
- **What the guide brings that the old design did not:** Caddy's routing, the
  `workshop.py` settings for running behind a TLS proxy, the env vars a deployment
  needs, and seeding as a one-off command.

**Known departures:**

- **Ingress.** The guide's security group opens 22, 80 and 443 to the world. The lab's
  has no inbound rules; people and scanners arrive over the tailnet (D10). The seeded
  `admin@precogly.dev` / `admin123` account stays: everyone who can reach the instance
  is meant to, and authenticated scans need a known login.
- **Certificates.** The guide's Caddy uses Let's Encrypt's HTTP-01 challenge, which
  needs port 80 reachable from the internet. The lab's Caddyfile names the instance's
  `ts.net` name instead, and Caddy gets that certificate from the local `tailscaled`
  (D11). The compose file gains one volume, the host's `/var/run/tailscale`, so Caddy
  can reach the socket, and loses the guide's `dns: 8.8.8.8` lines, which served only
  ACME lookups and would fail against the security group's egress.
- **Bind address.** Caddy's ports are bound to the box's Tailscale address rather than
  every interface, so a mistaken inbound rule on the public address still reaches
  nothing.
- **Hostname.** `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL` and the two MCP
  URLs carry the `ts.net` name.
- **Shell.** SSM Session Manager rather than SSH with a key pair, so there is no key to
  hand out and no port 22.

### D10 — Access: Tailscale on each box, the tailnet policy as the gate

**Chosen:** every box a person or a scanner has to reach runs `tailscaled` and joins
the tailnet under a tag: the instance as `tag:precogly`, the scanner box as
`tag:scanner` (D12). The tailnet policy is the whole access control. It replaces the
default allow-all rule and grants exactly this:

```text
  source            destination      ports
  named people  ──► tag:precogly     tcp:443
  named people  ──► tag:scanner      tcp:22, plus an `ssh` accept rule (Tailscale SSH)
  tag:scanner   ──► tag:precogly     tcp:443
  tag:precogly  ──► (nothing)
```

People are listed by login rather than through `group:`, so the policy does not
depend on the plan's group support. Each box joins with a one-off, pre-approved,
tagged auth key that expires in a day. Terraform creates an empty Secrets Manager
secret per box, the key is put in by hand, and the box reads it at first boot, so the
key never enters Terraform state or user data.

- **Why:** nothing to run between people and the instance. No gateway, no subnet
  routes to approve, no split DNS, no private zone. A box's name and certificate come
  with its tailnet membership (D11).
- **Overturns the rejection of an agent inside each instance**, which this decision
  made on 2026-10-13. Its argument: an instance being pentested is where a credential
  is most likely to be stolen, and a Tailscale credential joins its holder to the
  lab's network. The answer is what each credential is worth once stolen. The auth key
  is spent at first boot, so reading it later yields nothing. What stays on the box is
  its node key, which lets a thief act as that node: receive the connections people
  make to the instance, whose contents a thief with root on the box already has, and
  open connections as `tag:precogly`, which the policy grants to nothing. That holds
  only while the policy does; see the costs.
- **Rejected: a Tailscale subnet router in the base**, the choice from 2026-10-13 to
  2026-10-17. It kept agents off instances. It cost a gateway EC2, route approval,
  split DNS through the VPC resolver, a private zone, and, because the names were
  private, a private CA nobody else would vouch for (D11). Each piece was setup per
  teammate or per gateway replacement.
- **Rejected: Cloudflare Tunnel with Access.** No client software, only a browser and
  an email code. Everything else was work: the tunnel and the Access application,
  edge certificates that cover only first-level names, proxied names clashing with
  challenge CNAMEs, a Cloudflare API token, and scanners kept off the tunnel because
  Cloudflare's edge rewrites TLS and headers.
- **Rejected: a security-group allow list of people's addresses.** No client, but
  home addresses change, and an address is not an identity: anyone sharing a
  teammate's network passes.
- **Rejected: AWS Verified Access.** The AWS-native identity-aware proxy, at $0.27 per
  application-hour (launch pricing, not re-checked), about $197/mo per application.
- **Rejected: SSM port-forwarding.** No ingress and IAM for identity, but every person
  runs a CLI session, maps a hostname to localhost, and needs an IAM identity.

**What it costs.**

- The policy is the only gate. Leave the default allow-all rule in, or add
  `tag:precogly` as a source, and a compromised target reaches every laptop on the
  tailnet. The policy is set by hand in the admin console, with the steps in the lab
  repo, and can move to Tailscale's Terraform provider once it settles.
- Both boxes sit in a public subnet with public addresses, so they reach Tailscale,
  packages and images without a NAT gateway (~$32/mo saved). The security group is
  then the one thing between a box and the internet; a private subnet would add the
  route table as a second. Chosen without it, because neither box has an inbound rule
  to get wrong and every later service that needs a private subnet brings the NAT
  back with it.
- Each person installs the Tailscale client and joins the tailnet. Someone on a
  locked-down work machine may not be able to.
- The free Personal plan was reported to allow six users from April 2026, by
  third-party guides; Tailscale's own pricing page was not read.
- Every new box needs a fresh auth key, minted by hand. Fine for two boxes. Fargate
  jobs need something else (Open questions).

### D11 — Certificates: Tailscale's `ts.net` certificates, served by the guide's Caddy

**Chosen:** MagicDNS and HTTPS certificates are turned on for the tailnet. The
instance's Caddyfile site address is `<name>.<tailnet>.ts.net`. Caddy recognises the
suffix and gets the certificate from the local `tailscaled` instead of running ACME
itself (`isTailscaleDomain` in `modules/caddyhttp/autohttps.go`, Caddy v2.11.4),
through the socket at `/var/run/tailscale/tailscaled.sock` (`internal/paths` in
`tailscale/tscert`, both read 2026-10-17). Caddy still terminates TLS, so
`X-Forwarded-Proto` and `workshop.py` behave as they do in the guide.

- **Why:** a certificate every browser and scanner already trusts, with no root to
  install, no domain to buy, no CA to run, and the stock `caddy:alpine` image.
- **Rejected: a private lab CA** served over ACME by Caddy in the base, the choice from
  2026-10-13 to 2026-10-17. It needed a root installed on every machine and baked into
  every scanner image, a CA key to guard whose name constraint was never checked
  against browsers, a gateway to host it, and it issued 12-hour certificates, so half a
  day of gateway outage broke every instance's TLS.
- **Rejected: a bought domain with DNS-01** from each instance. Publicly trusted too,
  but it needs a custom Caddy build with `caddy-dns/route53`, a public zone delegated
  from the domain, and per-record IAM on every instance. The probe for it is parked in
  `precogly-security-lab/tmp/acme-probe/`.
- **Rejected: `tailscale serve` in front of Caddy.** It would terminate TLS outside
  Caddy, so TLS findings would measure Tailscale's settings rather than the guide's
  (Architecture), and Caddy, seeing plain HTTP from the Docker bridge, would set
  `X-Forwarded-Proto: http` unless told to trust that address.
- **Rejected: plain HTTP.** Caddy overwrites `X-Forwarded-Proto`, and `workshop.py`
  starts the redirect loop again.

**What it costs.**

- Machine names and the tailnet's DNS name are published in Certificate Transparency
  logs ([Tailscale: enabling HTTPS](https://tailscale.com/kb/1153/enabling-https),
  read 2026-10-17). A box's name must not carry anything sensitive.
- Every URL is tied to this tailnet. Moving tailnets changes each one, including
  anything outside the lab that recorded it, such as an Entra ID redirect URI.
- The Caddy container gets the `tailscaled` socket. Caddy runs as root in that image,
  and the local API answers root with far more than certificates, so a compromised
  Caddy can drive the node. That is the same reach as a stolen node key, which D10
  already bounds by policy.

### D12 — Where scanners and agents run: a scanner box on the tailnet

**Chosen:** a second EC2 in the same public subnet, tagged `tag:scanner`, with no
inbound rules. Scanners, the cross-tenant harness and AI pentest agents run there and
write their output to its disk. People get a shell over Tailscale SSH, so a teammate
needs no IAM identity to run a scan.

- **Rejected: team laptops.** The fewest boxes, and fine for a person running one tool
  by hand. An autonomous agent issues requests and runs commands its model chooses, and
  on a laptop it does so with that person's files, credentials and home network.
- **Rejected: Fargate jobs in Phase A.** The eventual answer (Phase B), but before the
  first finding it adds task definitions, a tailnet key per task, and the S3 handoff.
- **Rejected: scanners on the instance itself.** They would measure from localhost
  rather than over the path people use, and a scanner's or agent's damage would mix
  with the target's state.

**What it costs.**

- R6 is not met. The box has internet egress, which an agent needs to reach its model
  API, and nothing stops it reaching any other internet host. On the tailnet it reaches
  only `tag:precogly` on 443.
- `lab` uploads each run's reports to SecObserve from this box (D14), so it holds
  an upload token beside untrusted code. Phase B moves the upload to a collector.
- One more machine to patch and pay for. Neither box's size has been checked against
  what the scanners need; stop both when idle.

### D13 — The cross-tenant harness: Schemathesis against a Precogly of its own

**Chosen:** the harness is one job, `schemathesis`. It fuzzes the whole API of a
throwaway Precogly, built for that job at the commit the instance deploys, and a check
of the lab's own replays every read of one tenant's object as the other tenant.

```text
  terraform plan: precogly_branch ("main") ──► GitHub API ──► commit SHA
        │
        ├──► instance user data: deploy that commit (replaced when it changes)
        └──► SSM parameter, written by Terraform only
                  │
  scanner box, the schemathesis job:
     1. read the SHA; build Precogly's backend image at it (cached per SHA)
     2. docker compose -p lab-<run>-schemathesis up, on a network with no way out:
          db       postgres:16, empty
          seed     the backend image: migrate, seed; exits
          backend  the backend image, the instance's settings
     3. schemathesis ──► http://backend:8000, logged in as admin@ (Demo Organization)
          fuzzes every operation the schema lists, writes included
          CrossTenant: each of admin@'s successful reads, lists and writes,
                       re-sent as contoso@ (Contoso Financial), must not
                       reach a Demo object
     4. failures, and object reads never probed ──► SARIF ──► SecObserve
     5. docker compose down -v, whatever happened
```

- **Why Schemathesis and not a route walk of our own.** The first design walked
  Django's URL resolver for completeness, because routes from the schema might miss
  some. Measured at `94dd831` (2026-10-18): of 112 `api/` routes that take an object
  identifier, the schema served at `/api/schema/` lists 111. The one it lacks is
  `/api/auth/registration/account-confirm-email/{key}/`, a confirmation key and no
  tenant's object. Schemathesis also fuzzes, which a replayer would not. The walk
  (`harness/route_walk.py`) is retired.
- **The check is the lab's, on Schemathesis's public API.** `CrossTenant` is a check
  class that re-sends `admin@`'s successful requests with `contoso@`'s token, through
  `case.call(headers=...)`, in three ways, one for each shape of the milestone's bugs:

  | probe | re-sent as `contoso@` | fails when | milestone bug it is for |
  |---|---|---|---|
  | read | each 2xx `GET` of one object | anything but 403 or 404 | #227's leak |
  | list | each 2xx `GET` of a collection | a Demo-owned ID is in it | #405 |
  | write | each 2xx write that names a Demo-owned ID, in the path or the body | a 2xx | #226, #227's writes |

  An ID is Demo-owned when `admin@` created it in this run, or when `contoso@`'s read
  of it was refused. A shipped framework every tenant may see is never Demo-owned, so
  it raises nothing; a component `admin@` created with no organization is, so #227's
  leak is caught. Writes are replayed because the stack is thrown away; against the
  instance they would not be.
- **Rejected: Schemathesis's own `object_level_authorization`.** It replays reads
  only, never writes, so #226 is out of its reach. It passes a peer that receives
  masked fields, or that can list the object, which between tenants is still a leak.
  It first shipped in 4.31.0 (2026-10-12) and was being fixed the week after, and
  extending it would mean its internal modules.
- **A read never probed is a finding, not a pass.** At the end of the run the check
  lists each object `GET` in the schema that never answered `admin@` with a 2xx, so was
  never replayed, and each becomes a low-severity finding named by its route. It
  resolves in SecObserve once a run probes it.
- **Full fuzzing writes, so the job gets a Precogly no one else uses.** Jobs do not
  share a database. Fuzzing the instance would scramble the data every other job and
  every person sees. The stack is new for each job and deleted after it, so nothing one
  run does reaches the next, and no running backend is pointed at a new database: each
  job starts its own.
- **The stack copies the instance's settings**, so the two do not drift: the
  `postgres:16-alpine` image, the backend image at the SHA, and the instance's
  `workshop.py` settings, which trust Caddy's `X-Forwarded-Proto`; Schemathesis sends
  that header as Caddy does, or production settings redirect every request to HTTPS.
  `ALLOWED_HOSTS` is the service name, `backend`.
- **The network has no way out.** The scanner box's job containers can reach tailnet
  peers as `tag:scanner`. A fuzzed backend with a request-forgery bug could use that to
  reach SecObserve or the instance, so the stack's network is `internal` and the backend
  reaches only its database. Precogly's AI features fail there, which a fuzz run does not
  need.
- **`/api/auth/` is not fuzzed.** The run's own logins are there: fuzzing logout,
  password changes and token refresh as `admin@` can lock the run out of the account
  it tests with. Login is how the run authenticates, so it is exercised, if not fuzzed.
  Access tokens last 60 minutes (`SIMPLE_JWT`), so the run logs in again when one
  expires.
- **Shaped for Phase B.** Each Compose service is one container of a future Fargate
  task: containers in one task reach each other on `localhost`, ECS's `dependsOn`
  has `HEALTHY` and `SUCCESS` for Compose's `service_healthy` and
  `service_completed_successfully`, and when the essential container, the scanner,
  exits, ECS stops the rest. Addresses are configuration, never written into a
  container, since Compose names services and Fargate uses `localhost`.
- **Why the SHA comes from Terraform and not from the instance:** the instance is the
  target. If it published its own commit, a compromised target could choose what the
  harness builds and tests. Terraform writes the SHA, and no role on either box has
  `ssm:PutParameter`. Both boxes can read it, because `AmazonSSMManagedInstanceCore`
  grants `ssm:GetParameter` on every parameter; a public commit SHA loses nothing by
  that.
- **The branch is resolved to a SHA at plan time**, by Terraform's `http` data source
  against `GET /repos/precogly/precogly/commits/<branch>` with `Accept:
  application/vnd.github.sha`, which returns the bare SHA (checked 2026-10-17;
  unauthenticated, 60 requests an hour). Both boxes then use that SHA, never the branch
  name. A branch name passed through would deploy whatever the branch held at boot
  while the harness built whatever it held at run time. Resolving on every plan keeps
  the lab on `main` with no bump step to forget.
- **Rejected: a pinned SHA in `terraform.tfvars`, bumped by hand.** No surprise
  rebuilds, but the instance lags `main` until someone bumps it, and the bump is one
  more step that can be forgotten.
- **Rejected: fuzzing the instance.** Its database is shared by every job and by the
  people using it.
- **Rejected: a second instance on the instance's box, reset before each fuzz job** by
  an SSM document the scanner may send. It would fuzz through Caddy, TLS and Tailscale,
  but it gives a box that runs untrusted code a lever on the target, as safe as one IAM
  policy, and the reset races anyone using the box. The research behind this and the
  next two is in the 2026-10-18 log entry.
- **Rejected: preview-environment tools** (Argo CD's pull-request generator, Signadot,
  Okteto). They assume Kubernetes, and they share an expensive baseline across many
  developers' branches, which this lab does not have.
- **Rejected for now: a seeded template database cloned per job** (`CREATE DATABASE
  ... TEMPLATE`). Faster than seeding each time, but with one fuzz job a fresh Postgres
  container is isolation enough. Revisit if seeding proves slow or writing jobs
  multiply.

**What it costs.**

- It tests the code and its settings, not the deployment. Caddy, TLS, Tailscale and
  the frontend are not in the stack, so an authorization bug that exists only through
  them is missed. Nothing reads the instance cross-tenant; add a read-only replay
  against it if that becomes the gap that matters.
- A route the schema leaves out is not tested, and with the walk retired nothing
  re-measures that gap. One in 112 at `94dd831`; rerunning the walk, kept in git
  history, measures it again.
- The settings are a copy. A change to the instance's settings has to be made to the
  stack's too.
- Each job pays a migrate and a seed, and runs a second backend on the box that holds
  the SecObserve upload token, mitigated by the network with no way out.
- The scanner box builds Precogly's backend image: minutes on the first run of each
  SHA, cached after that.
- Any apply after a push to `main` replaces the instance and loses its database, even
  an apply made only to change something else. The plan shows the replacement, but in
  an unrelated change it is easy to approve without noticing. Read the plan for
  `aws_instance.precogly` before every apply.
- Plans need GitHub's API to answer. Offline, or over the unauthenticated limit, a
  plan fails rather than deploying a guess.
- A finding cannot be reproduced on an old commit without a pin. Add an optional
  override when that is first needed.

### D14 — One run path: a job contract, a `lab` CLI, and SecObserve as the record

**Chosen:** every scanner, the cross-tenant harness included, is a job with one
contract. One command, `lab`, runs any job on the scanner box, and its last step
uploads the job's report to [SecObserve](https://github.com/SecObserve/SecObserve).
SecObserve is the record of findings and of how they change over time; the lab stores
no findings of its own. Until 2026-10-17 the record was DefectDojo; why it changed is
under the rejected alternatives.

```text
  person ── ssh ubuntu@scanner ──► lab run <job> [--all]
                                     │
       1. resolve: SHA from SSM (D13), target URL, credentials
       2. run the job's container:  inputs in env, report out to a directory
            runs/<run-id>/<job>/report.<ext>   in a format SecObserve parses
            runs/<run-id>/<job>/meta.json      job, tool version, SHA, times, exit
       3. upload the report to SecObserve, as the job's vulnerability check
                                     │
                                     ▼
  SecObserve (tag:secobserve):  Product "Precogly", branch "main"
                                ├─ service "semgrep"         ◄── uploaded every run
                                ├─ service "trivy-backend"   ◄── uploaded every run
                                └─ service "zap-baseline"    ◄── uploaded every run
```

The contract a job implements:

- **Inputs**, as environment variables: `TARGET_URL`, `PRECOGLY_SHA`, `RUN_ID`,
  `OUT_DIR`, and a path to a credentials file holding the seed's logins.
- **Outputs**: one report, and nothing else. `lab` writes `meta.json`; the job does not.
- **Its definition**, one small file per job. Adding a tool is adding one definition.
  Tools and targets are combined by `lab`, so N tools and M targets are N + M
  definitions, never N × M scripts.
- **The report's format** is one SecObserve parses, chosen by what the finding is
  about. SecObserve detects the parser from the file, so a job names no parser.
  - Code (Semgrep, the harness): SARIF.
  - Images (Trivy): CycloneDX. SARIF cannot say which package in an image a finding
    is in: every result points at the image itself, and SecObserve merges results
    with the same rule and location. Uploaded as SARIF, Trivy's 787 findings for the
    backend image became 157 observations; as CycloneDX, 786 (spike, 2026-10-17).
  - ZAP: its traditional JSON report.

The model, and why it is shaped this way:

- **One vulnerability check per job.** SecObserve groups an upload by product, branch,
  service and file name, and calls that a vulnerability check. `lab` uploads each job
  as its own service on branch `main`, so each job is one check, uploaded every run.
  An upload compares the report with what the check holds: findings no longer reported
  become Resolved, new ones are created, and matching ones are updated. On the spike,
  a second upload of the same reports gave 0 new, every finding updated, 0 resolved.
- **The time series is SecObserve's.** Each observation carries when it was created
  and last seen, and SecObserve keeps daily product metrics: its dashboard charts
  severities over the last seven days, and `api/metrics/product_metrics_timeline/`
  serves the history behind longer charts.
- **`lab` labels each upload with the run:** the image name and tag for image scans
  (`precogly-backend:<sha>`, through `docker_image_name_tag`), so an image finding
  names the commit it was built from. The scanner's name and version come from the
  report itself.
- **A finding must have the same identity in every run.** An upload matches findings
  between runs, so a job whose titles or locations vary between runs (a timestamp, an
  object ID from the seed) reports every finding as resolved and new again on every
  run. `lab` rewrites container paths (`/in/precogly-source/...`) to repository paths
  before upload, so a path never depends on where the source was mounted. The harness
  keys its findings by route and method, never by object ID, since the seed's IDs
  change on every rebuild of the instance.
- **What a count means is fixed here.** "Findings at run R" for a job is its check's
  Open observations after R's upload, excluding those assessed as false positive, not
  affected or risk accepted. A chart that moves for any other reason is misleading.
- **One run path.** Jobs run only through `lab`, only on the scanner box. People reach
  it over Tailscale SSH. A scan run any other way does not reach SecObserve, so a
  laptop run is a test of the job, not a run.

- **Rejected: DefectDojo**, the record from the start of Phase A until 2026-10-17. It
  worked, with backups and a tested restore, but most of it went unused (product
  types, engagements, SLAs, JIRA, benchmarks, surveys), and it took a `t3.large`,
  Celery, Valkey and five containers. SecObserve did what the lab used DefectDojo for,
  on the same data, in four containers using about 600 MB with a thousand findings
  loaded (spike, 2026-10-17), and added a time-series chart and licence tracking.
- **Rejected: GitHub code scanning** (D15): the upload token would reach Precogly's
  real repository.
- **Rejected: a custom app to run scans and track findings.** A findings store, dedup
  and a triage UI are solved upstream, and the first anti-goal names building them as
  the failure.
- **Rejected: secureCodeBox**, OWASP's scan orchestrator. It runs on Kubernetes only
  ([installation docs](https://www.securecodebox.io/docs/getting-started/installation),
  read 2026-10-17), a larger system than the boxes it would run scans between.
- **Rejected: the lab's own time-series store.** SecObserve keeps the history; a
  second copy would disagree with it the first time a finding is assessed there.

**What it costs.**

- **A small project.** SecObserve had 323 stars and has been maintained mostly by one
  person since December 2025 (checked 2026-10-17). If it stalls, the lab migrates
  again. Reports in standard formats (SARIF, CycloneDX) keep that move cheap.
- A third box, joined to the tailnet as `tag:secobserve`, fronted by `tailscale serve`.
  It is not a target, so `tailscale serve` changes nothing anyone measures (D11
  rejected it only for the target). The policy grants people 443 on it, and the
  scanner box 443 for uploads.
- `lab` runs beside untrusted jobs and holds a product API token with SecObserve's
  Upload role, which may import observations and nothing else: not view, edit, assess
  or delete (`docs/usage/users_permissions.md`, v1.61.0). A compromised scanner box
  can upload a misleading report, which resolves findings the report omits, but cannot
  read or edit the record. The SecObserve box creates the product and the token at
  first boot and writes the token to a secret only the scanner box can read.
- Counts move for reasons other than the code: a new tool version, a changed rule
  pack, a new vulnerability database. The scanner version is on every observation so
  a chart can mark those, but nothing stops them.
- Run artifacts live on the scanner box's disk and go when it is replaced. SecObserve
  keeps the findings and the history. Raw reports move to S3 in Phase B.
- **lab talks to SecObserve with httpx, as effects like any command.** Every side
  effect in lab goes through one runner, tagged as a read or a write, so `--dry-run`
  prints every change and tests script every effect in one place. An `HttpRequest`
  sits beside `Command` for that: the live runner sends it with httpx, the dry-run
  runner sends reads and prints writes, and the token is a secret header, redacted
  wherever a request is printed. Rejected: curl, which the first uploads used. It kept
  lab dependency-free and the token out of argv, but paging JSON through a
  subprocess's stdout is clumsy and its failures are exit codes. Rejected: an HTTP
  client injected beside the runner, which would need its own dry-run and fake
  variants, so "a dry run prints every change" would hold only if both were wired
  right.

**Getting findings out: `lab findings`.** The core team reads SecObserve, and triage is
increasingly done with an AI agent, which needs the findings as a file rather than a UI.

```text
lab findings -o findings.json            # active findings, every job
lab findings --job semgrep -o sast.json  # one job
lab findings --status all                # every status but Resolved
lab findings --status false-positive --status risk-accepted
```

- **It reads SecObserve, not raw reports**, so the export is the deduplicated record
  with the team's assessments applied, using the count definition above.
- **It runs on any machine on the tailnet**, with the person's own SecObserve API token
  from `lab auth login`. It needs no AWS access, no Docker and no scanners; those stay
  on the scanner box.
- **The agent never holds a credential.** It reads a file. Pointing it at the API
  instead would hand it a token that can also change assessments.
- **By default it exports the active statuses**: Open, Affected and In review, the
  ones nobody has decided. That is SecObserve's own `STATUS_ACTIVE` and the default
  filter on its Observations page, so the file holds what the team sees there, and
  it follows `gh issue list --state`, which defaults to open. `--status all` adds the
  triaged statuses, so an agent can second-guess a past decision; it leaves out
  Resolved, which means the scanner stopped reporting the finding and is not a
  finding to triage. `--status` also takes exact statuses, repeated, spelt as slugs
  (`false-positive`) and checked against SecObserve's set before any request.
  Rejected as the default: everything but Resolved. The file and the page the team
  reads would disagree, and an agent would spend its time on decided findings.
- **Flags, no prompt.** The consumer is a script or an agent, neither on a terminal.
  clig.dev allows a prompt only when stdin is a TTY and never in place of a flag, so
  a picker could be added later on top of `--status`, not instead of it.
- **`--job` matches exactly.** SecObserve's `origin_service_name` filter matches a
  substring, so `--job trivy` would export both Trivy jobs. `lab findings` looks up
  the job's service by name, checks the name is equal, and filters on its ID.
- **A small, versioned schema**: id, a link to the observation, job, scanner, status,
  severity, title, CWE, CVEs, component and version, path and line, endpoint (for
  DAST), image, the commit scanned, first seen, description. Paths are repository
  paths, so an agent can open the code at the commit given.
- **Nothing uploaded yet is an empty export, not an error.** Before a job's first
  upload SecObserve has no service for it, and before any upload no `main` branch.
  For an agent that is the same answer as nothing to triage, so the export is empty,
  with a note on stderr naming what has never been uploaded. A misspelt job never
  gets that far: `--job` is checked against the job definitions first. A missing
  product is an error, since the SecObserve box creates it at first boot.
- **The commit is known for image findings only.** SecObserve keeps an image's tag,
  which lab sets to the commit, but has no field for the commit of a code or DAST
  scan, and putting it in the branch or file name would make every run a new
  vulnerability check, so nothing would ever resolve. Those findings export with no
  commit; they are as of the latest run, which scanned the commit in the `precogly_sha`
  SSM parameter.
- DefectDojo ignored query filters it did not know, silently, so a misspelt filter
  exported everything. django-filter, which SecObserve uses, also ignores unknown
  query parameters; every filter `lab findings` relies on is verified by flipping it
  before it is relied on.
- Not built: writing assessments back. The agent proposes, a person records the
  decision in SecObserve. Applying a decisions file would need write access, so it is
  a separate decision.

**Logging in: `lab auth`.** A person's token comes from lab, not from a page in
SecObserve's settings, following `gh auth`.

```text
lab auth login     check the tailnet and SecObserve, then mint and store a token
lab auth status    where tailscale is, whether SecObserve answers, the token's source and expiry
lab auth logout    revoke the token in SecObserve, then forget it
```

- **`login` checks before it asks.** It finds tailscale, reads the tailnet, and checks
  that SecObserve answers, so a network problem is reported as one rather than as a
  failed login. Then it prompts for the SecObserve username and the password, without
  echo, or reads the password from stdin with `--password-stdin`, as `docker login`
  does. It ends `✓ Logged in to secobserve.<tailnet> as <user>; token expires <date>`.
- **The token is minted from the password**, with SecObserve's
  `/api/authentication/create_user_api_token/`, the endpoint its own settings page
  calls. It is named `lab-<hostname>`; names are unique per user, so logging in again
  revokes that machine's previous token first.
- **It lives in the system keyring**, through `keyring`: the macOS Keychain, the
  Secret Service on Linux, the Credential Locker on Windows. Where there is none, as
  on a headless box, `login` fails and says to set `SECOBSERVE_TOKEN`, which overrides
  the keyring anywhere, as `GH_TOKEN` does for gh. Rejected: gh's fallback to a
  plain-text file. A file any process running as the person can read is the thing
  the keyring exists to avoid, and the environment variable already covers machines
  without one.
- **Tokens expire after 90 days.** Logging in again is one prompt, and a copied token
  stops working within a quarter; `logout` revokes at once. Tailscale's keys default
  to 90 days for the same trade. Others differ: gh's OAuth tokens never expire, its
  fine-grained tokens default to 30 days. A rejected token reports `SecObserve
  rejected the token (expired or revoked). Run: lab auth login`.
- **`logout` revokes**, unlike gh's, which only forgets the local copy and leaves the
  token valid. It asks for the password again: SecObserve's
  `/api/authentication/revoke_user_api_token/` takes the username and password and
  not the token, so a stolen token cannot revoke one and mint another, and its own
  settings page asks for the password to revoke too.
- **The keyring holds what `status` shows**: the token, the user, the server and the
  expiry, recorded when the token is minted, so `status` needs no SecObserve call to
  say when it lapses.
- **tailscale is found on PATH, then in the app.** Tailscale's own instructions for
  its Mac App Store app add a shell alias, which a subprocess never sees, so following
  them leaves `tailscale` off PATH. lab tries PATH, then the app's documented binary
  at `/Applications/Tailscale.app/Contents/MacOS/Tailscale`, and only then fails,
  linking Tailscale's install page.

**Opening the boxes: `lab open`.** The URLs are derived, not remembered: the target
file gives Precogly's, `secobserve` gives SecObserve's, and the local tailscale gives
the tailnet, so `lab open` needs neither AWS nor Terraform, as `terraform output`
would. It follows `heroku open`, `fly open` and `gh browse`, whose `-n` prints the
URL instead.

```text
lab open pentest | precogly     open Precogly
lab open secobserve             open SecObserve
lab open secobserve -n          print the URL, for a script or a machine with no browser
lab open                        list both
```

- **`precogly` is an alias of `pentest`**, the name a person reaches for; the URL
  and the tailnet keep the machine's name. Rejected: renaming the machine. The name
  is set into the box at first boot: Caddy's site and certificate, Django's allowed
  hosts and origins, and the check that the box joined under the name expected, so a
  rename in Tailscale's console takes Precogly down. Renaming through
  `instance_name` replaces the box, and every ZAP finding, keyed by its endpoint
  URL, would resolve and return as new.
- It opens through Python's `webbrowser`, which honours `$BROWSER`, and prints the
  URL when there is no browser to open.

**Running from a laptop: `lab run --remote`.** Scanning and exporting are one step
for whoever is triaging: scan the current commit, then read what changed.

```text
lab run --all --remote -o findings.json   # run on the scanner box, then export
lab run --remote --attach                 # follow the run in progress
```

It cannot be one command on the scanner box: the box's token may upload and not
read, so a compromised box cannot read the record. The laptop runs the jobs over
Tailscale SSH and exports with the person's own token, as `lab findings` does.

- **The box decides what runs.** It runs its own lab, at the commit it was
  installed at, with that commit's job definitions; the laptop sends job names only.
  HCP Terraform does the same with a workspace's Terraform version. A job list that
  differs between the two is a warning, since committing locally before reinstalling
  on the box is the normal order.
  Rejected: the laptop installing its own lab on the box for each run, as Ansible
  ships its modules. It removes skew entirely, but the box would run whatever is on
  the laptop, unpushed code included, beside untrusted jobs.
- **The run is detached and its progress is a file.** The laptop starts `lab run
  --events FILE` on the box as the transient systemd unit `lab-run`, so a dropped
  SSH connection does not stop it, and the run appends one JSON line per change of
  state to that file. The laptop follows the file over SSH and draws it, so
  attaching again replays the run from its start. Ctrl-C stops the drawing, not the
  run. Rejected: polling `meta.json`, which needs no format between the two but
  shows a job only once it ends.
- **The laptop names the file**, `/var/lib/lab/events/<nonce>.jsonl`, and puts the
  nonce in the unit's description, which is how `--attach` finds the file of the run
  in progress. The run ID cannot name it: the box makes that from the commit it
  reads, after the laptop has had to start following. `tail -F --pid` with the
  unit's main PID ends the stream when lab exits, so a run that dies without a last
  event is reported, with its journal (`journalctl -u lab-run`), rather than waited
  on.
- **A system unit, run as `ubuntu`** (`sudo systemd-run --uid ubuntu`), so it needs
  no lingering user session; it gets `ubuntu`'s home and the docker group, checked
  on the box. Errors before the first job, such as an unknown job name, are an
  event too, so the laptop shows them rather than a run that never starts.
- **The login is checked before the run starts**, since the export needs it: a
  missing token is found before twenty minutes of scanning, not after.
- **The event stream has its own version.** The first event is
  `{"type": "version", "lab": "<commit>", "events": 1}`, following Terraform's
  machine-readable UI. The laptop refuses an `events` version it does not know and
  names the commit to install; it ignores fields it does not know. The integer, not
  the commit, is what must match: most commits change neither side's events.
- **One run at a time.** The unit name is the lock: systemd refuses a second unit of
  the same name, and `--collect` stops a failed run holding it. A second
  `lab run --remote` reports the run in progress, who started it, when and at which
  commit, and the command that attaches to it.
- **Progress is per job, never a percentage.** None of the scanners reports progress
  without a terminal, checked in their source at the pinned versions: Semgrep and
  Grype turn their bars off, Trivy's only bar is its database download, and ZAP
  baseline buffers its output until it exits. The laptop shows an overall bar of
  jobs finished, and for each job a spinner, its elapsed time, and its result.
  Rejected: an estimate from the job's last duration. It would be a guess drawn as
  a measurement, and a job's time moves with the database download and the target.
- **The export follows the run** when `-o` names a file, for the jobs that ran, with
  the active statuses; the export's `jobs` lists them. It happens even when a job
  failed, and the exit code is non-zero if any did.
  SecObserve is updated by each job's upload as before; the export only reads.
- **The CLI is Typer.** Options are typed parameters, so mypy checks them, and an
  enum parameter is its own set of choices; rich, which draws the progress, comes
  with it. Typer is still 0.x, so any minor release may change its API; `uv.lock`
  pins it, and an upgrade is deliberate. Rejected: Click, stable at 8.x, whose decorators
  are matched to parameters by name, unchecked. Typer 0.27 vendors its own Click,
  so Click's plugins do not apply either way.

**Keeping the record across a replacement.** SecObserve's database is the whole
record, and it lives on the box's root volume, so replacing the box would delete every
finding and the history with it. Chosen: a nightly `pg_dump` to S3, and a restore at
first boot.

- **Backup:** a systemd timer dumps the database, gzipped, to
  `s3://<bucket>/pg/<UTC timestamp>.sql.gz`. The bucket is versioned, private and
  encrypted, and expires dumps after 30 days (arbitrary).
- **Restore:** at first boot, if the bucket holds a dump, the box starts Postgres
  alone, loads the newest dump, then starts the rest.
- **The keys travel with the data.** SecObserve encrypts some stored fields with
  `FIELD_ENCRYPTION_KEY`, and a restored database is unreadable under a new one. The
  first box saves that key and the Django secret key to Secrets Manager; every later
  box restores them. API tokens are stored as hashes and survive regardless.
- **The box's role** may put and get objects under `pg/` and list the bucket, and
  nothing else. Without `s3:DeleteObject`, and with versioning on, a compromised box
  can add bad dumps but cannot remove good ones.
- **Rejected: `prevent_destroy` on the instance**, which stops an accidental
  replacement but not a deliberate one; and **a separate EBS volume**, which an
  accidental `terraform destroy` takes with the box.
- Costs: up to a day of findings lost on a replacement, the time since the last dump
  (`sudo systemctl start secobserve-backup` first closes the gap); and the restore is
  code that runs rarely, so it is tested by a deliberate replacement once findings
  exist.

**Job definitions and the CLI.**

A job is a TOML file in `lab/src/lab/jobs/`, inside the package so that
`uv tool install` ships it, read with the standard library's `tomllib` into a frozen
dataclass that rejects unknown keys. Data, not code: a job that needs logic ships it
in its image or its assets, so `lab` stays the one place that runs things.

```toml
# lab/src/lab/jobs/trivy-backend.toml
name      = "trivy-backend"
image     = "aquasec/trivy:0.76.0"               # a tag, never `latest`
inputs    = ["precogly-images"]                  # mounted read-only under /in
command   = ["image", "--input", "/in/precogly-images/backend.tar",
             "--scanners", "vuln", "--format", "cyclonedx",
             "--output", "/out/report.cdx.json"]
report    = "report.cdx.json"                    # relative to /out
timeout   = "30m"
```

```toml
# lab/src/lab/jobs/harness.toml
name      = "harness"
image     = "@precogly-backend"    # "@": from this run's inputs, not a registry
inputs    = ["precogly-images"]
command   = ["python", "/job/run.py"]
assets    = "harness"              # lab/src/lab/harness, mounted read-only at /job
report    = "findings.sarif"
```

What `lab` gives every job container:

| | |
|---|---|
| `/out` | the job's run directory, writable; the report goes here. A job can move it with `out_mount`: in Docker, `zap-baseline.py` writes reports only under `/zap/wrk` and exits 3 if that is not mounted (lines 302–309 at v2.17.0) |
| `/run/lab/target.json` | the target's URL and logins, read-only |
| `/in/<input>` | each input the job declares, read-only |
| env | `TARGET_URL`, `PRECOGLY_SHA`, `RUN_ID`, `OUT_DIR=/out` |
| secrets | each name in `secrets`, as an env var: `anthropic-api-key` becomes `ANTHROPIC_API_KEY` |
| command placeholders | `{target_url}`, `{precogly_sha}`, `{run_id}`; any other `{name}` is an error at load |
| network | Docker's bridge network, with the target's host pinned to its tailnet address |

- **`secrets`** names entries under `precogly-seclab/jobs/` in Secrets Manager, for
  jobs that cannot work without one: the AI agent's model key, promptfoo's grader.
  `docker run` gets `--env NAME` with no value and reads the value from `lab`'s
  environment, so no secret reaches the command line, `ps`, `--dry-run` output, the
  run directory or `meta.json`. Handing a key to untrusted code is inherent to running
  an agent; the key should be one scoped to the lab, with a spending limit.
- **`timeout`**, `"45m"` style, default `1h`, at most `12h` (both arbitrary). On
  timeout `lab` kills the container by name and the run fails, so nothing is uploaded.
- **Bridge network, never host.** Checked on the scanner box on 2026-10-17: a bridge
  container reached the target over the tailnet with `--add-host` and could not get a
  metadata token. With host networking it could, and the box's role reads `lab`'s
  upload token.
- **One function builds every container**, `lab.container.run_args`, rather than an
  abstract job class. A subclass per tool could override how it runs, which is the
  per-tool scripting this decision removes. Every planned tool was checked against
  image + command + report: all fit, two of them once `secrets` existed. What
  will need an interface is the runner, local Docker now and Fargate in Phase B: a
  `Runner` protocol is added with its second implementation, not before.
- **Inputs are what a job needs built from Precogly at the run's commit**, prepared by
  `lab` once per run and cached by SHA, so several jobs needing the images cause one
  build:
  - `precogly-source`: the checkout, for SAST (Semgrep).
  - `precogly-images`: the backend and frontend images, saved as `backend.tar` and
    `frontend.tar`, for image scanning (`trivy image --input`, checked at v0.76.0).

  - `precogly-stack`: a throwaway Precogly of the job's own, at the run's commit, on a
    network with no way out (D13). `{target_url}` is then that stack, not the
    instance, and the stack is deleted when the job ends.
- **A target is a TOML file too**, `lab/src/lab/targets/pentest.toml`: URL and the
  seed's logins. The logins are the seed's published constants, so they are not
  secrets. Jobs and targets combine at run time, which is what makes it N + M files.
- **Success is "the report exists and is not empty", not the exit code.** Many
  scanners exit non-zero when they find something: `zap-baseline.py` at v2.17.0 exits
  1 for at least one FAIL, 2 for warnings only, and 3 for any other failure. The exit
  code is recorded in `meta.json`.
- **A failed job is never uploaded.** An upload resolves every finding missing from the
  report, so uploading an empty or truncated report from a crashed run would resolve a
  job's whole history. No report, no upload, and the run is marked failed.
- **Run ID** is `<UTC timestamp>-<first 7 of the SHA>`, for example
  `20261017T163000Z-94dd831`, to the second so two runs in one minute do not collide.
  Run directories live at `/var/lib/lab/runs/<run-id>/<job>/` on the scanner box.

The CLI, kept small on purpose:

```text
lab jobs                       list job definitions, and fail on any that do not load
lab run <job>... [--all]       run jobs against the target, then upload each report
lab run <job> --check          run the job twice, parse both reports offline, upload nothing
lab run <job> --dry-run        read the real tailnet, address and commit; print every
                               change a run would make; make none
lab run ... --remote [-o FILE] run on the scanner box from a laptop, then export
lab run --remote --attach      follow the run in progress on the scanner box
lab findings [-o FILE] [--job JOB] [--status STATUS]...
                               export active findings from SecObserve as JSON
lab auth login|status|logout   mint, show, or revoke this machine's SecObserve token
lab open [BOX] [-n]            open Precogly or SecObserve in the browser, or print its URL
```

- **`--check` is how a job is developed:** run the job as a real run would, parse each
  report with SecObserve's own parser at the deployed release, offline, and fail if any
  finding's identity differs between two runs, which is the "same identity in every
  run" rule made into a test. Not yet checked: whether SecObserve's parsers run without
  a database. A scratch product that development runs upload to was rejected: its
  results would pile up, and a run that does not count is a tempting way round the one
  that does.
- **No `--no-import` flag.** A run that skips SecObserve but counts as a run is the
  second run path this decision exists to prevent; `--check` does not count as a run.
- **One target for now**, `pentest`, so no `--target` flag until a second exists.
- **Install:** the scanner box installs `lab` from
  `github.com/precogly/precogly-security-lab` at a commit, with `uv tool install`.

### D15 — GitHub code scanning as the record: tried, and rejected

**Rejected** (2026-10-17), after a trial. SecObserve, tried next, became the record
(D14).

The idea was to upload each job's report as SARIF to code scanning on
`precogly/precogly`, where Precogly already uploads OpenSSF Scorecard results, and
drop the DefectDojo box. The trial, on a copy of PyGoat: Semgrep and two Trivy scans
uploaded against two commits kept 2,968 alerts with no duplicates, and recorded one
analysis per job per commit with its `results_count`. So the lifecycle works.

- **What disqualified it:** uploading needs a token with code scanning write access
  to Precogly's real repository, held on the scanner box beside untrusted agents.
  That access can also dismiss alerts there. A self-hosted store's token reaches only
  the lab's own box.
- **Also against it:** no built-in charts on the free plan (the `precogly` org has no
  "Security and quality" tab), and code scanning on a private repository needs a paid
  licence.
- **Carried forward:** GitHub opens a new alert whenever a result's path differs
  between uploads, so `lab` rewrites container paths (`/in/precogly-source/...`) to
  repository paths before sending a report anywhere; and two runs of one tool need
  distinct categories, or the second replaces the first's alerts.

## The AI layer

Two additions and one stage, all additive to the spine — no rearchitecting. The order
reflects value, not the diagram.

### An AI pentest agent as a sandboxed job

An autonomous LLM agent that plans and calls tools runs as one more Fargate job. It is
**not built here** — an existing agent is dropped into the container. The deliverable is
not the agent; it is the **sandbox around it**, and that sandbox is the AWS security
lesson:

- an ephemeral task with a **scoped IAM role** — reach its target instance, write its S3
  prefix, nothing else
- **egress-restricted** so it cannot reach the instance metadata service, other
  instances, the base, or anything off its target (R6)
- no standing credentials, destroyed at the end of the run

"Isolation layer to run agents safely" is a posting phrase (ButterflyMX, recorded in the
AppSec plan). Building it is the point; the agent is the pretext.

### LLM triage over aggregated findings

Phase 6b of the AppSec plan. After SecObserve dedups, an LLM reads the findings against a
threat model of Precogly and rates severity *in context*, flags likely false positives,
and clusters related findings. Runs as a small job after the collector. Reuses Precogly's
existing BYOM stack, so it is provider-agnostic. This is the high-signal, low-hype use of
an LLM in this platform.

### AI red-team of Precogly's own AI

Phase 5b, run as a job: garak or promptfoo against the suggest path. Tests the AI feature
rather than using AI to test. Fits the fan-out with no special handling.

### The recursion worth naming

Once the platform makes its own LLM calls (the agent and the triage stage), the
platform's own outbound traffic wants the same bounding designed for Precogly's BYOM path
— a call leaving the VPC to reach a model is the same trust and egress question. The
Fargate sandbox and the egress SG answer both with one control. The property that falls
out — built the isolation, then showed it holds against the adversarial cases — is worth
stating on its own.

## Build phases

Sequenced so the platform earns its existence with a real finding before it grows. The
guard is explicit: **do not add a second job type until the first one finds a real
defect end to end.**

**Phase A — the MVP thread.** Two boxes, one finding.

1. By hand, once: the tailnet policy, MagicDNS and HTTPS (D10, D11). Steps in the lab
   repo's `docs/setup.md`.
2. Terraform: a VPC with one public subnet and an internet gateway; the instance,
   following Precogly's AWS guide with D9's departures, seeded with at least two
   tenants; the scanner box (D12). Each box has its own empty auth-key secret, IMDSv2
   only, and SSM.
3. SecObserve on its own EC2 via compose, joined to the tailnet as `tag:secobserve`,
   with one product, branch `main`, and one service per job (D14).
4. `lab`, the one run path (D14): the job contract, a job definition per tool, and
   the upload to SecObserve as each run's last step.
5. The cross-tenant harness (D13): Schemathesis fuzzing a throwaway Precogly at the
   instance's commit, with the lab's `CrossTenant` check, and `main` resolved to a
   SHA at plan time and published to an SSM parameter only Terraform writes.

Done when the harness finds [#226](https://github.com/precogly/precogly/issues/226),
[#227](https://github.com/precogly/precogly/issues/227), or
[#405](https://github.com/precogly/precogly/issues/405) through `lab`, as a finding in
SecObserve. These are open, so the thread proves itself against real positives, not a
predicted clean pass.

**Phase B — the platform.** Private subnets and a NAT; jobs as Fargate tasks under the
same contract (D14), writing to S3; a small collector that does the upload, taking
the upload token off the scanner box; the instance becomes a module created by
name (D8). Then replace the manual trigger with Step Functions + EventBridge and add
fan-out with a second scanner (Trivy is cheapest — container CVEs on the images). Now
the Map state, retries, and parallel collection are exercised. A second instance for
feature testing (such as #585) needing only another module call is the test of D8.

**Phase C — more coverage.** Semgrep (SAST), ZAP (authenticated DAST), Schemathesis (API
fuzz). Each is one job in a format SecObserve parses; Schemathesis needs its output
converted to SARIF first, since SecObserve has no parser for it.

**Phase D — SecObserve goes native.** Migrate from EC2-compose to ECS + RDS + internal
ALB. The migration is the lesson (D1).

**Phase E — the AI layer.** The sandboxed agent job and its isolation, then the LLM triage
stage, then the AI red-team job.

## Trade-offs

- **Cost is real and ongoing.** Phase A is two boxes and two public IPv4 addresses
  (~$3.60/mo each), and nothing else stands: both boxes can be stopped. The instance is
  a `t3.medium` in the guide; the scanner box's size is not chosen. From Phase B the
  NAT and SecObserve stand all the time, and a forgotten instance is the likeliest
  surprise on the bill. The reaper (R5) is the mitigation. Native SecObserve (Phase D)
  is a standing cost that does not tear down. The ~$75–150/mo figure predates the
  base/instance split and has not been redone.
- **Phase A teaches little AWS.** One public subnet, two EC2s, security groups with no
  inbound rules, Secrets Manager and SSM. Routing between services, private DNS and
  the security-group mesh were the gateway design's lessons and went with it (D10).
  The target has no ALB, ECS service or RDS (D9). Those lessons move to Phases B and D.
- **This is weeks, and the largest thing on either plan.** The phasing is the defense:
  Phase A is a complete, useful system on its own, and every later phase is optional.
- **The core team uses it, and it is not Precogly's code.** It lives in its own
  repository and is not a hosting offering. Anyone reading this expecting a merge should
  read "Where this sits" again.
- **The AI layer is the riskiest square.** Kept last, kept scoped to a job type, and
  guarded by the anti-goal. If it slips, the platform is complete without it.

## Resume evidence tracker

The headline bullet, defensible cold: *built a security orchestration platform on AWS
(Fargate, Step Functions, SQS, S3, per-job IAM) that fans out SAST/DAST/SCA and custom
authz/OAuth/SSRF pentest jobs against a self-hosted target and lands normalized findings in
SecObserve.*

Sub-claims each phase unlocks:

- **A** — zero-ingress access through a tailnet with tag-based policy, a target
  deployed unattended from Precogly's own guide, an isolated scanner and agent box, the
  first real finding.
- **B** — VPC design with private subnets, ECS/Fargate jobs, SecObserve integration,
  Terraform modules with per-instance state, Step Functions orchestration, EventBridge,
  parallel fan-out with retry.
- **C** — SAST/DAST/SCA operated as automated jobs; SecObserve integration.
- **D** — ALB, RDS, ElastiCache, a live migration, service-to-service IAM and SGs.
- **E** — "isolation layer to run agents safely," AI security, LLM-assisted triage.

No bullet may claim a phase not built, and none may imply the scanners surfaced findings
they did not — the same discipline the AppSec plan holds itself to.

## Open questions

- **How does a Fargate scan job get a tailnet key?** A reusable key in Secrets Manager
  works, but a job runs untrusted code, and a leaked reusable key lets anyone add
  `tag:scanner` nodes until it expires. Minting an ephemeral key per job from a
  Tailscale OAuth client avoids that, at the cost of a client secret the trigger holds.
  Decide in Phase B.
- **What is an instance's config?** The R3 fields are a first guess. Per-instance state needs a key scheme, and creating instances needs to be
  something 2–3 people can do, not only one person's laptop.
- **Read before building the instance tooling:** GOAD's Instances and Provisioning
  docs (not readable on 2026-10-13) and Preevy, which runs compose previews on cheap
  VMs and is close to the guide's shape.
- Does a scan target run continuously or spin up per scan run? Under D8 this is
  "create an instance at the start of a run". Decide when Phase B lands.
- One AWS account or a separate one for the blast radius of the agent jobs? The sandbox
  argues for isolation; a second account is the strongest boundary and the most setup.
  Revisit at Phase E.
- Which off-the-shelf AI agent goes in the sandbox? Deferred to Phase E on purpose — the
  sandbox is designed first, the agent chosen second.

## Log

- **2026-10-18 (Schemathesis implementation review)** — The D13 per-job Compose
  stack, Schemathesis run, SARIF conversion and SecObserve upload ran end to end
  on the scanner box. The backend log showed no fuzzing below `/api/auth/` beyond
  login, and teardown left no job containers, volumes or networks. The run did
  not reach the milestone: the ownership oracle does not yet learn integer IDs
  or foreign-key IDs, conflates resource types, and treats an unknown peer 2xx
  as a violation. The next iteration keeps Schemathesis for broad exploration
  but adds deterministic fixtures and probes for #226, #227 and #405, typed
  ownership, delayed list evaluation and unit tests. A second identical run and
  `lab run --all` remain acceptance work; no stability or regression claim is
  made yet.

- **2026-10-18 (Schemathesis)** — D13 rewritten: the harness is Schemathesis fuzzing a
  throwaway Precogly, with a check of the lab's, instead of a route walk and a
  replayer. The schema the first D13 rejected turned out served at `/api/schema/`,
  and against the walk it lacks one object route of 112, a confirmation key. Fuzzing
  writes, so the job gets a stack of its own; research on how others isolate per-job
  environments found the same answer used in CI (a Compose stack per job, as
  Schemathesis's and StackHawk's CI guides do), preview-environment tools built for
  Kubernetes and for sharing baselines, and a Fargate task as the same stack in AWS.
  Resetting the shared instance was rejected by it too. Reading the milestone's bugs
  against the first draft of the check showed a read-only replay would catch at most
  one of #226, #227 and #405, so the check replays lists and writes as well.

- **2026-10-17 (SecObserve)** — D14 rewritten: SecObserve replaces DefectDojo as the
  record. DefectDojo worked but was mostly unused weight. GitHub code scanning was
  tried and rejected (D15) for putting a write token to Precogly's repository on the
  scanner box. A spike ran SecObserve on the same reports: the lifecycle matched
  (second upload: 0 new, all updated, 0 resolved), it charts severities over time,
  and its Upload role can only import. It showed that image scans must be CycloneDX:
  as SARIF, 787 per-package findings merged into 157.

- **2026-10-17 (DefectDojo backups)** — D14 gains "Keeping the record across a
  replacement". Writing the DefectDojo box showed its database, and so the whole time
  series, lived on a root volume any replacement would delete. A nightly dump to S3
  with a restore at first boot was chosen over a destroy guard, which still loses
  everything on a deliberate replacement, and a separate volume, which an accidental
  destroy takes too.

- **2026-10-17 (last)** — D14 added, and DefectDojo moved into Phase A. With the
  harness, ZAP, Trivy and more planned, each run as its own script and its own set of
  commands would multiply with every tool and target, and findings would pile up as
  files. One job contract, one command, and DefectDojo as the record fix both. Reading
  DefectDojo's reimport docs settled the time-series question: one Test per job,
  reimported each run, already keeps per-run counts against a commit, so the lab builds
  no store of its own.

- **2026-10-17 (later)** — D13 added. The AppSec plan's harness walks the DRF router
  from inside Django; the lab's runs from the scanner box over HTTPS. Choosing one meant
  giving up either completeness or the deployment path, so it is both, joined by a
  route list. A stored list could go stale without anyone noticing, so it is
  regenerated every run from the commit the instance runs, which Terraform resolves from
  `main` at plan time, publishes, and the instance cannot write. A hand-bumped pin was
  rejected for lagging `main`. Lab boxes up and checked the same day: the seed already
  creates the second organization the harness needs.

- **2026-10-17** — D10–D12 rewritten in place, and Phase A cut to two boxes. The
  question was the simplest route to two requirements: only named people reach the
  instance, and scanners and agents can be pointed at it. The gateway design met them
  with five moving parts (subnet router, split DNS, private zone, private CA, a root
  on every machine). Tailscale on each box meets them with a policy file. The cost is
  that D10's old objection to an agent on the target is now answered by policy rather
  than by keeping the credential off the box, and that Phase A teaches little AWS. The
  platform (DefectDojo, Fargate jobs, the base/instance split) moves to Phase B
  unchanged. Caddy's support for `ts.net` certificates was read in its source before
  D11 relied on it.

- **2026-10-13 (final)** — D11 switched to a private lab CA under `lab.internal`. The
  DNS-01 design needed a domain, and every free one failed: deSEC's `dedyn.io` forbids
  delegating subdomains, eu.org approval takes a month or more, and is-a.dev refuses
  NS records for self-hosting. A domain costs about $3/yr, but a private CA removes the
  domain, the public zone and the custom Caddy build entirely. The people who must
  trust it are three teammates and the lab's own scanners. The domain path stays in
  D11, and the Terraform is to keep switching to it cheap.

- **2026-10-13 (last)** — D10 switched from Cloudflare Tunnel to a Tailscale subnet
  router, and D11 was proposed. Choosing certificates for Cloudflare-fronted instances
  ran into one Cloudflare-specific problem after another: edge certificate coverage,
  proxied names clashing with challenge CNAMEs, zone-wide API tokens, and a tunnel that
  scanners had to avoid. Tailscale removes Cloudflare's edge from the path, so all of
  those go. The cost is a client on each of 2–3 machines. D11 waits on a probe.

- **2026-10-13 (later)** — Rebuilt around a base and instances: D8–D10, a new
  Requirements section, Goal 3, and D5–D7 marked superseded. D5 → D6 → D7, and a
  proposed D8 for tunnel routing, were each fixing a problem the last one created. The
  root was that nobody had written down who uses the lab. Answering that gave two users
  (scanners and agents, and the core team testing features such as #585) and many
  configurations. Security labs and preview-environment systems all handle many
  configurations the same way: a base, and instances described by config. The target
  stopped being a bespoke Fargate deployment and became Precogly's own guide, which
  costs Phase A its ALB and RDS lessons.

- **2026-10-13** — D6 and D7 added after reading Vikram's
  [AWS self-hosting guide](https://github.com/precogly/precogly/blob/ac22b875c5542a9be1db73f53373f0fa5eac22cc/docs/guides/self-hosting-aws.md),
  which landed upstream on 2026-09-20 and gives Precogly a reference deployment for the
  first time. Its Caddyfile settled routing: the API never goes through nginx. Its
  `workshop.py` exposed the HTTPS redirect, which would have stopped the Phase A harness
  at its first request. The guide also confirmed seeding as a one-off command, which
  becomes a one-off ECS task. It did not settle anything about access: its
  security group opens 22, 80 and 443 to the world, which this design does not copy.

- **2026-09-18** — D5 added while writing the security groups. Fixing the ALB's ingress
  rule forced the question of which deployment Phase A actually is; the scan-tier split
  already answered it, and the table's ALB row had been describing the eventual state as
  though it were the current one. DefectDojo's UI access was never decided anywhere —
  the row implied a host route, and it is a tunnel.

- **2026-09-04** — Doc written. No infrastructure yet. Converged in chat from a question
  about learning AWS well: the platform is the AWS learning, DefectDojo is bought not
  built, the harness is a plugin, and the AI layer is an isolation-first job type. The two
  anti-goals were the sharpest part of the conversation and are stated first because both
  are cheap to walk into.
