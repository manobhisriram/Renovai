# ---- PostgreSQL (private, encrypted, backed up) ----------------------------------------------------------
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "renovai-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier                 = "renovai-${var.environment}"
  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = var.db_instance_class
  allocated_storage          = var.db_allocated_storage
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = "renovai"
  username                   = "renovai"
  password                   = random_password.db.result
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.db.id]
  publicly_accessible        = false
  multi_az                   = true
  backup_retention_period    = 7
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "renovai-${var.environment}-final"
  auto_minor_version_upgrade = true
  performance_insights_enabled = true
}

# ---- Redis (rate-limit counters) ---------------------------------------------------------------------------
resource "aws_elasticache_subnet_group" "main" {
  name       = "renovai-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "renovai-${var.environment}"
  description                = "RenovAI rate limiting"
  engine                     = "redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 1
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# ---- Object storage for uploaded photos --------------------------------------------------------------------
resource "random_id" "bucket" {
  byte_length = 4
}

resource "aws_s3_bucket" "uploads" {
  bucket = "renovai-${var.environment}-uploads-${random_id.bucket.hex}"
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "uploads_tls_only" {
  bucket = aws_s3_bucket.uploads.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.uploads.arn, "${aws_s3_bucket.uploads.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---- Secrets ------------------------------------------------------------------------------------------------
resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "metrics_token" {
  length  = 32
  special = false
}

resource "random_password" "admin" {
  length  = 24
  special = true
}

locals {
  # Static names (not derived from sensitive values) so they can be used as for_each keys.
  generated_secret_names = ["SECRET_KEY", "METRICS_TOKEN", "SEED_ADMIN_PASSWORD", "DATABASE_URL", "REDIS_URL"]
  secrets = {
    SECRET_KEY          = random_password.secret_key.result
    METRICS_TOKEN       = random_password.metrics_token.result
    SEED_ADMIN_PASSWORD = random_password.admin.result
    DATABASE_URL        = "postgresql://renovai:${random_password.db.result}@${aws_db_instance.main.address}:5432/renovai"
    REDIS_URL           = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
  }
}

resource "aws_secretsmanager_secret" "generated" {
  for_each                = toset(local.generated_secret_names)
  name                    = "renovai/${var.environment}/${each.key}"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "generated" {
  for_each      = toset(local.generated_secret_names)
  secret_id     = aws_secretsmanager_secret.generated[each.key].id
  secret_string = local.secrets[each.key]
}

# Secrets YOU provide. Terraform creates the empty container; set the value before the first deploy:
#   aws secretsmanager put-secret-value --secret-id renovai/prod/ANTHROPIC_API_KEY --secret-string "sk-ant-..."
resource "aws_secretsmanager_secret" "provided" {
  for_each                = toset(["ANTHROPIC_API_KEY", "QDRANT_API_KEY"])
  name                    = "renovai/${var.environment}/${each.key}"
  recovery_window_in_days = 7
}
