# DefectDojo, the findings record, on the tailnet as tag:defectdojo.

# Pinned: an upgrade can change how a report is parsed, moving every count with
# no change in the scanned code. Latest release on 2026-10-17.
locals {
  defectdojo_version = "3.4.101"
}

# Filled by hand, overwritten by the box once spent; see precogly.tf.
resource "aws_secretsmanager_secret" "defectdojo_authkey" {
  name                    = "${var.project}/defectdojo-authkey"
  description             = "One-off, pre-approved Tailscale auth key tagged tag:defectdojo. Read at the DefectDojo box's first boot only."
  recovery_window_in_days = 0
}

# The initializer prints a generated admin password once; the box stores it
# here, keeping it out of Terraform state.
resource "aws_secretsmanager_secret" "defectdojo_admin" {
  name                    = "${var.project}/defectdojo-admin"
  description             = "DefectDojo admin password, generated at the DefectDojo box's first boot and written by the box."
  recovery_window_in_days = 0
}

# API token for `lab`, the plain Product member the scanner box reimports as.
# Written by this box at first boot; read only by the scanner box.
resource "aws_secretsmanager_secret" "defectdojo_lab_token" {
  name                    = "${var.project}/defectdojo-lab-token"
  description             = "DefectDojo API token for the lab user. Written by the DefectDojo box, read by lab on the scanner box."
  recovery_window_in_days = 0
}

# Nightly database dumps, restored at first boot so a replacement keeps the
# history. Bucket names are global, hence the account ID.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "defectdojo_backups" {
  bucket = "${var.project}-defectdojo-backups-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "defectdojo_backups" {
  bucket                  = aws_s3_bucket.defectdojo_backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# With versioning and no s3:DeleteObject on the role, a compromised box can add
# bad dumps but not remove good ones.
resource "aws_s3_bucket_versioning" "defectdojo_backups" {
  bucket = aws_s3_bucket.defectdojo_backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 30 days is arbitrary.
resource "aws_s3_bucket_lifecycle_configuration" "defectdojo_backups" {
  bucket = aws_s3_bucket.defectdojo_backups.id

  rule {
    id     = "expire-dumps"
    status = "Enabled"
    filter {
      prefix = "pg/"
    }
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_iam_role" "defectdojo" {
  name = "${var.project}-defectdojo"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Its own auth key, read and overwrite; the admin password and lab's token,
# write only.
resource "aws_iam_role_policy" "defectdojo_secrets" {
  name = "own-secrets"
  role = aws_iam_role.defectdojo.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
        ]
        Resource = aws_secretsmanager_secret.defectdojo_authkey.arn
      },
      {
        Effect = "Allow"
        Action = "secretsmanager:PutSecretValue"
        Resource = [
          aws_secretsmanager_secret.defectdojo_admin.arn,
          aws_secretsmanager_secret.defectdojo_lab_token.arn,
        ]
      },
    ]
  })
}

# Write dumps and read them back for a restore; no delete.
resource "aws_iam_role_policy" "defectdojo_backups" {
  name = "backups"
  role = aws_iam_role.defectdojo.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.defectdojo_backups.arn}/pg/*"
      },
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.defectdojo_backups.arn
        Condition = { StringLike = { "s3:prefix" = ["pg/*"] } }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "defectdojo_ssm" {
  role       = aws_iam_role.defectdojo.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "defectdojo" {
  name = "${var.project}-defectdojo"
  role = aws_iam_role.defectdojo.name
}

resource "aws_instance" "defectdojo" {
  ami = data.aws_ssm_parameter.ubuntu_2604_amd64.insecure_value

  # Unmeasured guess. DefectDojo's smallest sizing tier (16-32 GB) is for
  # ~1000x this lab's findings; 4 GiB looked too tight for uWSGI, Celery,
  # Postgres and Valkey together.
  instance_type = "t3.large"

  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.defectdojo.id]
  iam_instance_profile        = aws_iam_instance_profile.defectdojo.name
  associate_public_ip_address = true

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Arbitrary: room for the images, Postgres and uploaded reports.
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  user_data = templatefile("${path.module}/defectdojo-user-data.sh.tftpl", {
    region             = var.region
    authkey_secret_arn = aws_secretsmanager_secret.defectdojo_authkey.arn
    admin_secret_arn   = aws_secretsmanager_secret.defectdojo_admin.arn
    backup_bucket      = aws_s3_bucket.defectdojo_backups.id
    lab_token_secret   = aws_secretsmanager_secret.defectdojo_lab_token.arn
    tailscale_hostname = "defectdojo"
    tailscale_tag      = "tag:defectdojo"
    tailnet_domain     = var.tailnet_domain
    defectdojo_version = local.defectdojo_version
  })

  user_data_replace_on_change = true

  lifecycle {
    # A replacement restores from the newest dump and loses what came after it.
    # Before a planned one: sudo systemctl start defectdojo-backup
    ignore_changes = [ami]
  }

  tags = { Name = "${var.project}-defectdojo" }
}
