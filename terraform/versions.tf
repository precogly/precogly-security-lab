terraform {
  # Pinned rather than floating: a provider minor bump can change default
  # arguments on resources this project reads as teaching material, and a
  # silent diff in `plan` is the one thing that makes the diff untrustworthy.
  required_version = "~> 1.15"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State is local for Phase A. An S3 + DynamoDB backend is itself one of the
  # AWS lessons on the list, but bootstrapping it needs a bucket that Terraform
  # would have to create first, so it lands after the MVP thread closes rather
  # than as a chicken-and-egg detour ahead of the VPC.
  # TODO(phase-b): move state to S3 with DynamoDB locking.
}

provider "aws" {
  region = var.region

  # Every resource carries these, so cost can be attributed per project when
  # the bill arrives and `terraform destroy` misses something.
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}
