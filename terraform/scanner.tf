# The scanner box: where scanners, the cross-tenant harness and AI pentest
# agents run against the Precogly instance. A box of its own, rather than
# teammates' laptops, because an autonomous agent runs commands its model
# chooses, and on a laptop it would run them beside that person's files and
# credentials. Joined to the tailnet as tag:scanner, whose only grant is
# tag:precogly on 443. People get a shell over Tailscale SSH.
#
# The same shape as precogly.tf, written out again rather than shared: the two
# differ in tag, size, disk, user data and what the role may read, and a module
# for two boxes would hide those differences behind arguments.

# uv for installing lab, at the version lab's pyproject.toml requires, so the box
# and every developer run the same uv. regex() fails the plan if the line is
# missing or not in the exact `required-version = "==X.Y.Z"` form.
locals {
  uv_version = regex(
    "required-version = \"==([0-9]+\\.[0-9]+\\.[0-9]+)\"",
    file("${path.module}/../lab/pyproject.toml"),
  )[0]
}

# Empty until filled by hand, as in precogly.tf, and for the same reasons.
resource "aws_secretsmanager_secret" "scanner_authkey" {
  name                    = "${var.project}/scanner-authkey"
  description             = "One-off, pre-approved Tailscale auth key tagged tag:scanner. Read at the scanner box's first boot only."
  recovery_window_in_days = 0
}

# The box's SSH host keys, saved by the first box and restored by every later
# one, so a replacement keeps the host key people's ssh already trusts. Anyone
# who can read this through the box's role already has root on the box, and so
# its keys.
resource "aws_secretsmanager_secret" "scanner_ssh_host_keys" {
  name                    = "${var.project}/scanner-ssh-host-keys"
  description             = "The scanner box's SSH host keys, as JSON {rsa, ecdsa, ed25519}. Written by the first box, restored by every replacement."
  recovery_window_in_days = 0
}

# Read its own auth key (and overwrite it once spent) and the commit the
# instance runs, plus SSM. In particular, no access to the instance's secret: an
# agent that takes over this box should learn nothing it could use to join the
# tailnet as tag:precogly.
resource "aws_iam_role" "scanner" {
  name = "${var.project}-scanner"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# As in precogly.tf: PutSecretValue on this one secret, for overwriting the key
# after joining.
resource "aws_iam_role_policy" "scanner_authkey" {
  name = "own-authkey"
  role = aws_iam_role.scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
      ]
      Resource = [
        aws_secretsmanager_secret.scanner_authkey.arn,
        aws_secretsmanager_secret.scanner_ssh_host_keys.arn,
      ]
    }]
  })
}

# lab's DefectDojo token, for the reimport at the end of each run.
resource "aws_iam_role_policy" "scanner_read_lab_token" {
  name = "read-lab-token"
  role = aws_iam_role.scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.defectdojo_lab_token.arn
    }]
  })
}

# The harness reads the commit to check out, so it walks the routes of the code
# the instance actually runs. Public information, but written by Terraform
# alone, which is what makes it trusted.
#
# AmazonSSMManagedInstanceCore below already grants ssm:GetParameter on every
# parameter, so this adds no access today. It is written out so the harness's
# one AWS dependency is visible here, and survives AWS narrowing that policy.
resource "aws_iam_role_policy" "scanner_read_precogly_sha" {
  name = "read-precogly-sha"
  role = aws_iam_role.scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = aws_ssm_parameter.precogly_sha.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "scanner_ssm" {
  role       = aws_iam_role.scanner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "scanner" {
  name = "${var.project}-scanner"
  role = aws_iam_role.scanner.name
}

resource "aws_instance" "scanner" {
  ami = data.aws_ssm_parameter.ubuntu_2604_amd64.insecure_value

  # Arbitrary, not measured. 4 GiB is a floor for ZAP, which is Java. Move up if
  # several scanners or an agent run at once; down costs nothing to try.
  instance_type = "t3.medium"

  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.scanner.id]
  iam_instance_profile   = aws_iam_instance_profile.scanner.name

  # Dials out with no NAT, accepts nothing; see precogly.tf.
  associate_public_ip_address = true

  # IMDSv2 only, and hop limit 1 keeps the role's credentials away from
  # containers. That matters more here than on the instance: this box runs
  # untrusted code on purpose, much of it in containers.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Arbitrary: room for a handful of scanner images and their output.
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  user_data = templatefile("${path.module}/scanner-user-data.sh.tftpl", {
    region               = var.region
    authkey_secret_arn   = aws_secretsmanager_secret.scanner_authkey.arn
    tailscale_hostname   = "scanner"
    tailscale_tag        = "tag:scanner"
    tailnet_domain       = var.tailnet_domain
    uv_version           = local.uv_version
    host_keys_secret_arn = aws_secretsmanager_secret.scanner_ssh_host_keys.arn
  })

  user_data_replace_on_change = true

  lifecycle {
    # As in precogly.tf: image updates are a deliberate -replace.
    ignore_changes = [ami]
  }

  tags = { Name = "${var.project}-scanner" }
}

# lab's SecObserve upload token, for the upload at the end of each run.
resource "aws_iam_role_policy" "scanner_read_upload_token" {
  name = "read-secobserve-upload-token"
  role = aws_iam_role.scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.secobserve_upload_token.arn
    }]
  })
}
