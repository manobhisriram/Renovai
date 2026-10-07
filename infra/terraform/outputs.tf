output "alb_dns_name" {
  description = "Create a CNAME/ALIAS from var.domain_name to this."
  value       = aws_lb.main.dns_name
}

output "ecr_backend_repository" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository" {
  value = aws_ecr_repository.frontend.repository_url
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "backend_security_group_id" {
  value = aws_security_group.backend.id
}

output "admin_password_secret_arn" {
  description = "Read the initial admin password: aws secretsmanager get-secret-value --secret-id <arn>"
  value       = aws_secretsmanager_secret.generated["SEED_ADMIN_PASSWORD"].arn
}

output "anthropic_key_secret_arn" {
  description = "Set its value before the first deploy: aws secretsmanager put-secret-value ..."
  value       = aws_secretsmanager_secret.provided["ANTHROPIC_API_KEY"].arn
}
