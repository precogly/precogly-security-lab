# Setup

Installing the lab, in order. The reasoning is in [`design.md`](design.md),
D10–D14.

```text
  1. Tailscale (admin console)   MagicDNS + HTTPS, the policy        once
  2. Terraform                   terraform.tfvars, init, apply       once, then on change
  3. Auth keys                   one per box, into its secret        each time a box is created
  4. Check                       reachability and isolation          after every change
```

## Prerequisites

- An AWS account, with the AWS CLI v2 signed in to it and its default region set to
  `us-east-1` (`aws configure get region`), which is Terraform's default `region`.
  The commands below pass no `--region`.
- Terraform 1.15 (`versions.tf` pins `~> 1.15`).
- The Session Manager plugin, for a shell on a box over SSM:
  `brew install --cask session-manager-plugin`.
- A Tailscale account that is an admin of the tailnet, and the Tailscale client on
  your machine, signed in.

## 1. Tailscale

### MagicDNS and HTTPS

In the [admin console](https://login.tailscale.com/admin/dns), on the **DNS** page:

1. Enable **MagicDNS** if it is off.
2. Under **HTTPS Certificates**, enable HTTPS. This publishes the tailnet's DNS name
   and every machine's name in Certificate Transparency logs
   ([Tailscale docs](https://tailscale.com/kb/1153/enabling-https)), so no machine
   name may carry anything sensitive.
3. Copy the **Tailnet DNS name**, such as `tail1234.ts.net`. Terraform needs it.

### The policy

On the [**Access controls**](https://login.tailscale.com/admin/acls/file) page, in
the JSON editor, replace the file with the policy below, with your login in place
of the example, and save.

The default allow-all rule must go: while it exists, a compromised target reaches
every laptop. Keep any rules of your own unrelated to the lab.

```jsonc
{
  "tagOwners": {
    "tag:precogly":   ["autogroup:admin"],
    "tag:scanner":    ["autogroup:admin"],
    "tag:defectdojo": ["autogroup:admin"],
  },

  "grants": [
    // People reach Precogly.
    {"src": ["teammate-one@example.com"], "dst": ["tag:precogly"],   "ip": ["tcp:443"]},
    // People reach the scanner box over Tailscale SSH (the ssh rule below too).
    {"src": ["teammate-one@example.com"], "dst": ["tag:scanner"],    "ip": ["tcp:22"]},
    // People reach DefectDojo's UI.
    {"src": ["teammate-one@example.com"], "dst": ["tag:defectdojo"], "ip": ["tcp:443"]},
    // Scanners reach Precogly, and `lab` reaches DefectDojo's API. Nothing else.
    {"src": ["tag:scanner"], "dst": ["tag:precogly", "tag:defectdojo"], "ip": ["tcp:443"]},
    // tag:precogly and tag:defectdojo are never a source: neither reaches anything.
  ],

  "ssh": [
    {"action": "accept", "src": ["teammate-one@example.com"], "dst": ["tag:scanner"], "users": ["ubuntu"]},
  ],
}
```

People are listed by login rather than through `group:`, so the policy does not
depend on the plan's group support. The tags have to exist here before step 3 can
mint keys for them.

## 2. Terraform

```sh
cd terraform
echo 'tailnet_domain = "tail1234.ts.net"' > terraform.tfvars   # yours, from step 1
terraform init
terraform plan -out=lab.tfplan
terraform apply lab.tfplan
```

The apply creates the network, the three boxes, an empty auth-key secret per box
and DefectDojo's backup bucket. Each box boots and waits for its key.

Check every plan for `aws_instance.*` replacements. Two things cause one with no
change of your own:

- **A push to Precogly's `main`.** The branch is resolved to a commit on every plan,
  so the next apply after a push rebuilds the instance and its database.
- **An edit to a `*-user-data.sh.tftpl` file, comments included.** The rendered
  script is the box's user data.

Replacing the DefectDojo box restores its newest nightly dump. Take a fresh one
first: `sudo systemctl start defectdojo-backup` on the box.

## 3. Auth keys

For each box, in the admin console under **Settings → Keys → Generate auth key**:

| Setting | Value |
|---|---|
| Reusable | off |
| Ephemeral | off |
| Pre-approved | on |
| Tags | the box's tag, below |
| Expiration | 1 day |

Put each key in its box's secret. A key in the wrong secret joins the wrong box
under the wrong tag.

| Box | Tag | Secret |
|---|---|---|
| Precogly | `tag:precogly` | `precogly-seclab/precogly-authkey` |
| Scanner | `tag:scanner` | `precogly-seclab/scanner-authkey` |
| DefectDojo | `tag:defectdojo` | `precogly-seclab/defectdojo-authkey` |

```sh
aws secretsmanager put-secret-value --secret-id precogly-seclab/precogly-authkey --secret-string 'tskey-auth-...'
```

Each box waits up to an hour for a value starting `tskey-auth-`, joins, and
overwrites its secret with `spent`. Precogly and DefectDojo then take several
minutes more to build and start. To watch a boot:

```sh
aws ssm start-session --target "$(terraform -chdir=terraform output -raw precogly_instance_id)"
sudo tail -f /var/log/cloud-init-output.log
```

A box that finishes prints `Precogly is up at …`, `scanner box is up at …` or
`DefectDojo is up at …` as its last line.

**Replacing a box:** remove its old node on the **Machines** page first. Otherwise
the new one joins as `<name>-1`, and its boot stops itself rather than run under
the wrong URL. A replaced scanner box has a new SSH host key, so `ssh` refuses it
until the old one is forgotten: `ssh-keygen -R scanner`.

## 4. Check

From your machine:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://pentest.<tailnet>.ts.net/            # 200
curl -sS -o /dev/null -w '%{http_code}\n' https://defectdojo.<tailnet>.ts.net/login    # 200
ssh ubuntu@scanner true && echo ok                                                     # no key needed
```

From the scanner box (`ssh ubuntu@scanner`), Precogly answers:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://pentest.<tailnet>.ts.net/            # 200
tailscale ip -4                                                                        # note it
```

From the instance and from DefectDojo, over SSM, the scanner's port 22 must not
answer: proof the default policy is gone. Use the scanner's address, since neither
box resolves tailnet names; `tailscale ping` tests the path, not the policy.

```sh
nc -z -w 5 <scanner tailnet IP> 22 && echo "OPEN: fix the policy" || echo closed
```

From outside the tailnet, every box's public address is closed on every port.

## 5. Install `lab` on the scanner box

`lab` is installed at an exact commit of this repository, so the box runs code
you can name. The box's first boot already installed uv, at the version
`lab/pyproject.toml` requires, and created `/var/lib/lab`. Over
`ssh ubuntu@scanner`, to install or move to a commit:

```sh
uv tool install --force \
  "git+https://github.com/precogly/precogly-security-lab@<commit>#subdirectory=lab"
lab jobs                          # every job loads
lab run zap-baseline --dry-run    # reads real values, changes nothing
```

uv installs `lab` in `~/.local/bin`, which only a login shell puts on `PATH`. An
interactive `ssh ubuntu@scanner` is one; a one-shot command is not, so run it
through one: `ssh ubuntu@scanner 'bash -lc "lab run zap-baseline"'`.

## Using it

| | |
|---|---|
| Precogly | `https://pentest.<tailnet>.ts.net`, as `admin@precogly.dev` / `admin123` (or `analyst@`, `contoso@`) |
| DefectDojo | `https://defectdojo.<tailnet>.ts.net`, as `admin`, password below |
| Scanner box | `ssh ubuntu@scanner` |
| Any box | `aws ssm start-session --target <instance id>` (`terraform output` lists them) |

```sh
aws secretsmanager get-secret-value --secret-id precogly-seclab/defectdojo-admin \
  --query SecretString --output text
```

The boxes bill while running. Stop them when idle:

```sh
aws ec2 stop-instances --instance-ids $(terraform -chdir=terraform output -json \
  | jq -r '[.precogly_instance_id, .scanner_instance_id, .defectdojo_instance_id] | map(.value) | join(" ")')
```

Neither Precogly nor DefectDojo starts again by itself after a stop: their compose
files, copied from upstream, have no restart policy. After starting the boxes, over
SSM:

```sh
# Precogly
cd /home/ubuntu/precogly && sudo -u ubuntu docker compose -f docker-compose.workshop.yml up -d
# DefectDojo
cd /opt/defectdojo && sudo docker compose up -d
```
