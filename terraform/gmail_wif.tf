# Gmail domain-wide delegation: WIF ADC JSON (set value out-of-band; Terraform keeps the parameter shell).

resource "aws_ssm_parameter" "gmail_wif" {
  name        = "/${var.name_prefix}/gmail-wif-config"
  description = "Settings for user impersonation."
  type        = "SecureString"
  value       = "dummy"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "${var.name_prefix}-gmail-wif-config"
  }
}
