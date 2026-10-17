# The Precogly instance: one EC2 running Precogly as its AWS guide deploys it,
# so behaviour seen here is behaviour users of the guide would see. Joined to
# the tailnet as tag:precogly. People and the scanner box reach it at
# https://<instance_name>.<tailnet_domain>; nothing reaches it from the
# internet.
#
# Phase A has one instance, written out literally. When there is a second,
# this file becomes a module called once per instance, each with its own state.
#
# Setup that Terraform does not do (the tailnet policy, MagicDNS and HTTPS, the
# auth key) is in docs/setup.md.

# The commit the instance deploys, resolved from the branch on every plan, so
# the lab follows the branch with no bump step to forget. Both boxes use this
# SHA and never the branch name: the
# instance deploys it, and the scanner box's harness checks it out to walk the
# routes. A branch name handed to each separately could name two different
# commits, and the harness would test routes the instance does not have.
#
# The vnd.github.sha media type makes GitHub return the bare SHA as the body.
# Unauthenticated, 60 requests an hour, ample for plans.
data "http" "precogly_commit" {
  url = "https://api.github.com/repos/precogly/precogly/commits/${var.precogly_branch}"

  request_headers = {
    Accept = "application/vnd.github.sha"
  }

  lifecycle {
    # A rate-limit or not-found reply is JSON, not a SHA. Fail the plan rather
    # than deploy a body that is not a commit.
    postcondition {
      condition     = self.status_code == 200 && can(regex("^[0-9a-f]{40}$", trimspace(self.response_body)))
      error_message = "Could not resolve branch \"${var.precogly_branch}\" of precogly/precogly to a commit (HTTP ${self.status_code}). Check the branch exists, or wait out GitHub's unauthenticated rate limit."
    }
  }
}

locals {
  precogly_sha = trimspace(data.http.precogly_commit.response_body)
}

# The harness's source of truth for which commit the instance runs. Only
# Terraform writes it. The instance is the target, and a target that could
# change this could hide routes from the harness, so no role on either box has
# ssm:PutParameter. Both can read it: AmazonSSMManagedInstanceCore grants
# ssm:GetParameter on every parameter (checked 2026-10-17), which is harmless
# for a public commit SHA.
resource "aws_ssm_parameter" "precogly_sha" {
  name        = "/${var.project}/precogly-sha"
  description = "Commit of precogly/precogly the instance deploys. Read by the harness on the scanner box."
  type        = "String"
  value       = local.precogly_sha
}

# Terraform creates the secret empty and never writes a value, so the auth key
# never passes through Terraform state. It is filled by hand after apply; the
# instance reads it at first boot.
#
# recovery_window_in_days = 0 deletes at once on destroy. The key is spent at
# first boot and a new one is minted for every new box, so there is nothing to
# recover, and a recovery window would block re-creating a secret of the same
# name for a week after every destroy.
resource "aws_secretsmanager_secret" "precogly_authkey" {
  name                    = "${var.project}/precogly-authkey"
  description             = "One-off, pre-approved Tailscale auth key tagged tag:precogly. Read at the instance's first boot only."
  recovery_window_in_days = 0
}

# The instance's role: read its own auth key and overwrite it once spent, and
# be reachable by SSM Session Manager so a shell needs no SSH key and no inbound
# rule.
resource "aws_iam_role" "precogly" {
  name = "${var.project}-precogly"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# PutSecretValue lets the box overwrite its key with a placeholder after
# joining (see the user data). Scoped to this one secret, the most a
# compromised instance can do with it is write junk into its own spent key.
resource "aws_iam_role_policy" "precogly_authkey" {
  name = "own-authkey"
  role = aws_iam_role.precogly.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
      ]
      Resource = aws_secretsmanager_secret.precogly_authkey.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "precogly_ssm" {
  role       = aws_iam_role.precogly.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "precogly" {
  name = "${var.project}-precogly"
  role = aws_iam_role.precogly.name
}

# Ubuntu 26.04 for amd64, the guide's image and architecture, looked up from
# Canonical's public parameter (path checked with get-parameters-by-path on
# 2026-10-17). The value moves whenever Canonical publishes a new image; see
# `lifecycle` below for why that does not replace the instance. scanner.tf uses
# it too.
data "aws_ssm_parameter" "ubuntu_2604_amd64" {
  name = "/aws/service/canonical/ubuntu/server/26.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_instance" "precogly" {
  # insecure_value: the provider marks `value` sensitive for every parameter,
  # which would hide a public AMI id in every plan.
  ami = data.aws_ssm_parameter.ubuntu_2604_amd64.insecure_value

  # The guide's size: 2 vCPU and 4 GiB, enough for Postgres, gunicorn, nginx
  # and Caddy, and for the first `compose build`.
  instance_type = "t3.medium"

  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.precogly.id]
  iam_instance_profile   = aws_iam_instance_profile.precogly.name

  # A public address so the box can dial out through the internet gateway with
  # no NAT. It accepts nothing on it: the security group has no inbound rules,
  # and Caddy is bound to the Tailscale address only.
  associate_public_ip_address = true

  # IMDSv2 only. A request forged through the app (an SSRF, which is exactly
  # what a pentest of this box looks for) cannot read the role's credentials
  # without first obtaining a session token by PUT.
  #
  # Hop limit 1, the default, also keeps the token out of reach of containers
  # on Docker's bridge network, one hop further away. Nothing in a container
  # needs the role: the AWS CLI runs on the host.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # The guide's 20 GiB. Images, build cache and Postgres share it.
  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = templatefile("${path.module}/precogly-user-data.sh.tftpl", {
    region             = var.region
    authkey_secret_arn = aws_secretsmanager_secret.precogly_authkey.arn
    tailscale_hostname = var.instance_name
    tailscale_tag      = "tag:precogly"
    tailnet_domain     = var.tailnet_domain
    precogly_ref       = local.precogly_sha
  })

  # User data runs only at first boot, so an edit that did not replace the
  # instance would change nothing while looking applied.
  user_data_replace_on_change = true

  # Because the SHA is in the user data above, a push to the branch followed by
  # any apply replaces this instance and loses its database. Read the plan for
  # this resource before every apply.

  lifecycle {
    # A new AMI would replace the instance, and with it the database, on the
    # next apply after Canonical publishes one. Replacement also needs a fresh
    # auth key and the old node removed from the tailnet by hand. So image
    # updates are deliberate: `terraform apply -replace=aws_instance.precogly`.
    ignore_changes = [ami]
  }

  tags = { Name = "${var.project}-${var.instance_name}" }
}
