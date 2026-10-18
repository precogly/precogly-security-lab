# SecObserve, the findings record, on the tailnet as tag:secobserve.

# Pinned: an upgrade can change how a report is parsed, moving every count with
# no change in the scanned code. Latest release on 2026-10-17.
locals {
  secobserve_version = "1.61.0"
}

# Filled by hand, overwritten by the box once spent; see precogly.tf.
resource "aws_secretsmanager_secret" "secobserve_authkey" {
  name                    = "${var.project}/secobserve-authkey"
  description             = "One-off, pre-approved Tailscale auth key tagged tag:secobserve. Read at the SecObserve box's first boot only."
  recovery_window_in_days = 0
}

# Written by the box on a fresh database; a restore keeps the old one valid.
resource "aws_secretsmanager_secret" "secobserve_admin" {
  name                    = "${var.project}/secobserve-admin"
  description             = "SecObserve admin password, written by the SecObserve box on a fresh database."
  recovery_window_in_days = 0
}

# lab's product API token, Upload role: may import observations and nothing
# else. Written by the box, read by the scanner box.
resource "aws_secretsmanager_secret" "secobserve_upload_token" {
  name                    = "${var.project}/secobserve-upload-token"
  description             = "SecObserve product API token with the Upload role, for lab on the scanner box."
  recovery_window_in_days = 0
}

# The Django and field-encryption keys, saved by the first box and restored by
# later ones: a restored database is unreadable under a new encryption key.
resource "aws_secretsmanager_secret" "secobserve_keys" {
  name                    = "${var.project}/secobserve-keys"
  description             = "SecObserve's DJANGO_SECRET_KEY and FIELD_ENCRYPTION_KEY, as JSON. Kept across replacements."
  recovery_window_in_days = 0
}

# Nightly database dumps, restored at first boot. Bucket names are global,
# hence the account ID.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "secobserve_backups" {
  bucket = "${var.project}-secobserve-backups-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "secobserve_backups" {
  bucket                  = aws_s3_bucket.secobserve_backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# With versioning and no s3:DeleteObject on the role, a compromised box can add
# bad dumps but not remove good ones.
resource "aws_s3_bucket_versioning" "secobserve_backups" {
  bucket = aws_s3_bucket.secobserve_backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 30 days is arbitrary.
resource "aws_s3_bucket_lifecycle_configuration" "secobserve_backups" {
  bucket = aws_s3_bucket.secobserve_backups.id

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

resource "aws_iam_role" "secobserve" {
  name = "${var.project}-secobserve"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Its auth key and keys, read and write; the admin password and upload token,
# write only.
resource "aws_iam_role_policy" "secobserve_secrets" {
  name = "own-secrets"
  role = aws_iam_role.secobserve.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = [
          aws_secretsmanager_secret.secobserve_authkey.arn,
          aws_secretsmanager_secret.secobserve_keys.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = "secretsmanager:PutSecretValue"
        Resource = [
          aws_secretsmanager_secret.secobserve_admin.arn,
          aws_secretsmanager_secret.secobserve_upload_token.arn,
        ]
      },
    ]
  })
}

# Write dumps and read them back for a restore; no delete.
resource "aws_iam_role_policy" "secobserve_backups" {
  name = "backups"
  role = aws_iam_role.secobserve.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.secobserve_backups.arn}/pg/*"
      },
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.secobserve_backups.arn
        Condition = { StringLike = { "s3:prefix" = ["pg/*"] } }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "secobserve_ssm" {
  role       = aws_iam_role.secobserve.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "secobserve" {
  name = "${var.project}-secobserve"
  role = aws_iam_role.secobserve.name
}

resource "aws_instance" "secobserve" {
  ami = data.aws_ssm_parameter.ubuntu_2604_amd64.insecure_value

  # Measured on the spike: about 600 MB for all of SecObserve with a thousand
  # findings loaded, so 2 GiB leaves room for imports.
  instance_type = "t3.small"

  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.secobserve.id]
  iam_instance_profile        = aws_iam_instance_profile.secobserve.name
  associate_public_ip_address = true

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Arbitrary: room for the images and Postgres.
  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = templatefile("${path.module}/secobserve-user-data.sh.tftpl", {
    region                  = var.region
    authkey_secret_arn      = aws_secretsmanager_secret.secobserve_authkey.arn
    admin_secret_arn        = aws_secretsmanager_secret.secobserve_admin.arn
    upload_token_secret_arn = aws_secretsmanager_secret.secobserve_upload_token.arn
    keys_secret_arn         = aws_secretsmanager_secret.secobserve_keys.arn
    backup_bucket           = aws_s3_bucket.secobserve_backups.id
    tailscale_hostname      = "secobserve"
    tailscale_tag           = "tag:secobserve"
    tailnet_domain          = var.tailnet_domain
    secobserve_version      = local.secobserve_version
  })

  user_data_replace_on_change = true

  lifecycle {
    # A replacement restores from the newest dump and loses what came after it.
    # Before a planned one: sudo systemctl start secobserve-backup
    ignore_changes = [ami]
  }

  tags = { Name = "${var.project}-secobserve" }
}
