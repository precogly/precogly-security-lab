# Tailnet setup

The steps Terraform does not do: the tailnet's DNS and certificates, its policy,
and an auth key for each box. Steps 1 and 2 are done once, step 3 each time a box
is created, step 4 once per teammate's machine. The reasoning is in the design
doc, D10–D12.

`terraform apply` creates each box's auth-key secret empty and boots the box. Its
first-boot script waits up to an hour for step 3 to fill the secret, and fails the
boot if it is not. Follow it in `/var/log/cloud-init-output.log` over SSM:

```sh
aws ssm start-session --target "$(terraform -chdir=terraform output -raw precogly_instance_id)"
```

## 1. MagicDNS and HTTPS (once)

In the admin console, DNS page: enable MagicDNS if it is off, then under HTTPS
Certificates, enable HTTPS. Enabling it publishes the tailnet's DNS name and every
machine's name in Certificate Transparency logs, so no machine name may carry
anything sensitive.

Note the tailnet DNS name (`<tailnet>.ts.net`). Every URL is
`https://<machine>.<tailnet>.ts.net`, and Terraform takes it as `tailnet_domain`.

## 2. The policy (once)

Replace the default allow-all rule. A new tailnet's policy has one entry with `*` as
both source and destination, under `grants` or `acls`; while it is there, everything
below is decoration, and a compromised target reaches every laptop.

People are listed by login rather than through `group:`, so the policy does not
depend on the plan's group support.

```jsonc
{
  "tagOwners": {
    "tag:precogly": ["autogroup:admin"],
    "tag:scanner":  ["autogroup:admin"],
  },

  "grants": [
    // People reach the instance's Caddy.
    {
      "src": ["teammate-one@example.com", "teammate-two@example.com"],
      "dst": ["tag:precogly"],
      "ip":  ["tcp:443"],
    },
    // People reach the scanner box over Tailscale SSH. The ssh rule below is
    // needed as well: Tailscale SSH requires both.
    {
      "src": ["teammate-one@example.com", "teammate-two@example.com"],
      "dst": ["tag:scanner"],
      "ip":  ["tcp:22"],
    },
    // Scanners and agents reach the instance, and nothing else on the tailnet.
    {
      "src": ["tag:scanner"],
      "dst": ["tag:precogly"],
      "ip":  ["tcp:443"],
    },
    // tag:precogly appears as a source nowhere. Keep it that way: it is what
    // stops a compromised target reaching anything.
  ],

  "ssh": [
    {
      "action": "accept",
      "src":    ["teammate-one@example.com", "teammate-two@example.com"],
      "dst":    ["tag:scanner"],
      "users":  ["ubuntu"],
    },
  ],
}
```

## 3. An auth key per box (each time a box is created)

Settings → Keys → Generate auth key:

- Reusable: off. One key, one node.
- Ephemeral: off. The box should stay on the tailnet across reboots.
- Pre-approved: on.
- Tags: `tag:precogly` for the instance, `tag:scanner` for the scanner box.
- Expiration: 1 day. It is used once, at first boot.

```sh
aws secretsmanager put-secret-value --secret-id precogly-seclab/precogly-authkey \
  --secret-string 'tskey-auth-...'
aws secretsmanager put-secret-value --secret-id precogly-seclab/scanner-authkey \
  --secret-string 'tskey-auth-...'
```

When replacing a box, remove the old node from the Machines page first, or the new
one joins as `<name>-1` and every URL changes.

## 4. Each teammate (once per machine)

Install Tailscale and sign in to the tailnet. Nothing else: the certificates are
publicly trusted, and MagicDNS resolves the names.

## Checking it worked

From a teammate's machine:

```sh
curl -sI https://pentest.<tailnet>.ts.net | head -1    # HTTP/2 200, no -k
ssh ubuntu@scanner                                       # Tailscale SSH, no key
```

From the scanner box, the instance answers on 443:

```sh
curl -sI https://pentest.<tailnet>.ts.net | head -1
```

From the instance, over SSM, the scanner box's port 22 must not answer, although
Tailscale SSH is listening there. This is the check that the allow-all rule is gone
and `tag:precogly` reaches nothing. It uses a real port rather than `tailscale ping`,
which tests the path between nodes and is not a reliable test of the policy.

```sh
nc -z -w 5 scanner.<tailnet>.ts.net 22 && echo "OPEN: fix the policy" || echo closed
```
