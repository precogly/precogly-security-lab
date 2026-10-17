output "precogly_url" {
  description = "Where people and the scanner box reach Precogly, over the tailnet."
  value       = "https://${var.instance_name}.${var.tailnet_domain}"
}

output "precogly_instance_id" {
  description = "For `aws ssm start-session --target`: a shell on the instance with no SSH key and no inbound rule."
  value       = aws_instance.precogly.id
}

output "scanner_instance_id" {
  description = "For SSM, when Tailscale SSH is not up yet. Otherwise `ssh ubuntu@scanner` over the tailnet."
  value       = aws_instance.scanner.id
}

output "authkey_secret_ids" {
  description = "Secrets to fill with a fresh Tailscale auth key after apply (docs/tailnet-setup.md, step 3)."
  value = {
    precogly = aws_secretsmanager_secret.precogly_authkey.name
    scanner  = aws_secretsmanager_secret.scanner_authkey.name
  }
}
