variable "region" {
  description = "AWS region for every resource in this configuration. The subnet's AZ is derived from it."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for all resources, and the value of the Project tag."
  type        = string
  default     = "precogly-seclab"
}

variable "vpc_cidr" {
  description = "IPv4 range for the VPC. /16 leaves room for Phase B's private /20s."
  type        = string
  default     = "10.0.0.0/16"
}

variable "tailnet_domain" {
  description = "The tailnet's MagicDNS suffix, as shown on the admin console's DNS page, e.g. \"tail1234.ts.net\". Every URL is https://<machine>.<tailnet_domain>."
  type        = string

  validation {
    condition     = endswith(var.tailnet_domain, ".ts.net") && !startswith(var.tailnet_domain, ".")
    error_message = "tailnet_domain is the suffix alone, ending in .ts.net, with no leading dot: e.g. \"tail1234.ts.net\"."
  }
}

variable "instance_name" {
  description = "The Precogly instance's tailnet machine name, and so its URL's first label. It is published in Certificate Transparency logs, so it must not carry anything sensitive."
  type        = string
  default     = "pentest"
}

variable "precogly_ref" {
  description = "Git ref of precogly/precogly the instance deploys. A branch moves under a rebuild; a commit SHA does not."
  type        = string
  default     = "main"
}
