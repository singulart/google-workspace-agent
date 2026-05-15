provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project = "vincent"
      Repository = "google-workspace-agent"
    }
  }
}
