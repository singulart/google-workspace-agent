# GCP Workload Identity Federation ADC JSON (set value out-of-band; Terraform keeps the parameter shell).

resource "aws_ssm_parameter" "gcp_wif" {
  name        = "/${var.name_prefix}/gcp-wif-credential-config"
  description = "WIF external_account JSON for GCP APIs (Chat, Gmail, etc.)."
  type        = "SecureString"
  value       = "dummy"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.name_prefix}-gcp-wif-credential-config"
  }
}
