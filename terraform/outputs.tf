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
  description = "Secrets to fill with a fresh Tailscale auth key after apply (docs/setup.md, Auth keys)."
  value = {
    precogly   = aws_secretsmanager_secret.precogly_authkey.name
    scanner    = aws_secretsmanager_secret.scanner_authkey.name
    defectdojo = aws_secretsmanager_secret.defectdojo_authkey.name
    secobserve = aws_secretsmanager_secret.secobserve_authkey.name
  }
}

output "defectdojo_url" {
  description = "DefectDojo's UI and API, over the tailnet. Log in as admin with the password in the defectdojo-admin secret."
  value       = "https://defectdojo.${var.tailnet_domain}"
}

output "defectdojo_instance_id" {
  description = "For `aws ssm start-session --target`: a shell on the DefectDojo box."
  value       = aws_instance.defectdojo.id
}

output "secobserve_url" {
  description = "SecObserve's UI and API, over the tailnet. Log in as admin with the password in the secobserve-admin secret."
  value       = "https://secobserve.${var.tailnet_domain}"
}

output "secobserve_instance_id" {
  description = "For `aws ssm start-session --target`: a shell on the SecObserve box."
  value       = aws_instance.secobserve.id
}
