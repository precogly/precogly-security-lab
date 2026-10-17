# The scanner box: where scanners, the cross-tenant harness and AI pentest
# agents run against the Precogly instance (design doc D12). Joined to the
# tailnet as tag:scanner, whose only grant is tag:precogly on 443. People get a
# shell over Tailscale SSH.
#
# The same shape as precogly.tf, written out again rather than shared: the two
# differ in tag, size, disk, user data and what the role may read, and a module
# for two boxes would hide those differences behind arguments.

# Empty until filled by hand, as in precogly.tf, and for the same reasons.
resource "aws_secretsmanager_secret" "scanner_authkey" {
  name                    = "${var.project}/scanner-authkey"
  description             = "One-off, pre-approved Tailscale auth key tagged tag:scanner. Read at the scanner box's first boot only."
  recovery_window_in_days = 0
}

# Read its own auth key and nothing else, plus SSM. In particular, no access to
# the instance's secret: an agent that takes over this box should learn nothing
# it could use to join the tailnet as tag:precogly.
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

resource "aws_iam_role_policy" "scanner_read_authkey" {
  name = "read-authkey"
  role = aws_iam_role.scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.scanner_authkey.arn
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
    region             = var.region
    authkey_secret_arn = aws_secretsmanager_secret.scanner_authkey.arn
    tailscale_hostname = "scanner"
    tailscale_tag      = "tag:scanner"
    tailnet_domain     = var.tailnet_domain
  })

  user_data_replace_on_change = true

  lifecycle {
    # As in precogly.tf: image updates are a deliberate -replace.
    ignore_changes = [ami]
  }

  tags = { Name = "${var.project}-scanner" }
}
