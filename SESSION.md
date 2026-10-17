# Deferred

- Not yet checked: whether `manage.py seed` creates the two tenants with data
  that the cross-tenant harness needs. If not, the pentest instance needs its own
  seed profile (R3).

- Precogly's guide has each deployer write `workshop.py` and the Caddyfile on the
  host. An instance's user data will have to write them too, so the lab carries
  copies that can drift from the guide. Upstreaming `workshop.py` (or
  `SECURE_PROXY_SSL_HEADER` as an env var in `production.py`) would remove one
  copy and a manual step from Vikram's guide.

- The guide seeds `admin@precogly.dev` / `admin123` on a host it opens to the
  world on 22, 80 and 443. That is a finding about the guide, not the lab, and
  could be raised upstream.

- The guide's compose file has no `restart:` policy, so after a reboot or a
  stop/start the Precogly stack stays down until someone runs `compose up` over
  SSM. The lab copies the guide, so it inherits this. Adding
  `restart: unless-stopped` would also need Caddy to wait for tailscaled, since
  its ports are bound to the Tailscale address.


- For Phase B: Fargate scanner egress will need `0.0.0.0/0:443` because a task
  pulls its image and ships logs over its own ENI. Closing it needs ecr.api,
  ecr.dkr and logs interface endpoints — ~$22/mo in one AZ, ~$44/mo across both
  (PrivateLink pricing, checked 2026-09-18). Until then the design doc's
  "egress-restricted" sandbox is not implemented.
