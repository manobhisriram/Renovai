variable "region" {
  type = string
  description = "AWS region"
}

variable "environment" {
  type = string
  default = "prod"
}

variable "domain_name" {
  type = string
  description = "Public hostname, e.g. app.example.com. Must be covered by the ACM certificate."
}

variable "acm_certificate_arn" {
  type = string
  description = "ARN of an ISSUED ACM certificate in this region (create and validate it first)."
}

variable "cors_origins" {
  type = string
  description = "Comma-separated allowed browser origins, e.g. https://app.example.com"
}

variable "backend_image" {
  type = string
  description = "Backend image URI including tag (push to the ECR repository first)."
}

variable "frontend_image" {
  type = string
  description = "Frontend image URI including tag."
}

variable "vpc_cidr" {
  type = string
  default = "10.40.0.0/16"
}

variable "db_instance_class" {
  type = string
  default = "db.t4g.small"
}

variable "db_allocated_storage" {
  type = number
  default = 50
}

variable "backend_cpu" {
  type = number
  default = 1024
}

variable "backend_memory" {
  type = number
  default = 2048
}

variable "backend_desired_count" {
  type = number
  default = 2
}

variable "llm_provider" {
  type = string
  default = "anthropic"
}

variable "llm_model_simple" {
  type = string
  default = "claude-haiku-4-5-20251001"
}

variable "llm_model_medium" {
  type = string
  default = "claude-sonnet-5-5"
}

variable "llm_model_complex" {
  type = string
  default = "claude-opus-5-5"
}

variable "embedding_provider" {
  type = string
  description = "hash (lexical, light image) or sentence_transformers (build the image with INSTALL_ML=true)."
  default = "hash"
}

variable "qdrant_url" {
  type = string
  description = "Qdrant Cloud URL (recommended) or a Qdrant reachable from the private subnets."
}

variable "crm_provider" {
  type = string
  default = "internal"
}

variable "log_retention_days" {
  type = number
  default = 90
}

