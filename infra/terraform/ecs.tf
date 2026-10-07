data "aws_caller_identity" "current" {}

resource "aws_ecs_cluster" "main" {
  name = "renovai-${var.environment}"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/renovai/${var.environment}/backend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/renovai/${var.environment}/frontend"
  retention_in_days = var.log_retention_days
}

# ---- IAM -----------------------------------------------------------------------------------------------------
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "renovai-${var.environment}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = concat([for s in aws_secretsmanager_secret.generated : s.arn], [for s in aws_secretsmanager_secret.provided : s.arn])
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-app-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

# The task role is what application code runs as: it may touch ONLY the uploads bucket.
resource "aws_iam_role" "backend_task" {
  name               = "renovai-${var.environment}-backend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "backend_s3" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.uploads.arn]
  }
}

resource "aws_iam_role_policy" "backend_s3" {
  name   = "uploads-bucket"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_s3.json
}

# ---- Task definitions ----------------------------------------------------------------------------------------
locals {
  backend_env = [
    { name = "APP_ENV", value = "production" },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "CORS_ORIGINS", value = var.cors_origins },
    { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "LLM_MODEL_SIMPLE", value = var.llm_model_simple },
    { name = "LLM_MODEL_MEDIUM", value = var.llm_model_medium },
    { name = "LLM_MODEL_COMPLEX", value = var.llm_model_complex },
    { name = "EMBEDDING_PROVIDER", value = var.embedding_provider },
    { name = "QDRANT_URL", value = var.qdrant_url },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = aws_s3_bucket.uploads.bucket },
    { name = "S3_REGION", value = var.region },
    { name = "CRM_PROVIDER", value = var.crm_provider },
    { name = "FORWARDED_ALLOW_IPS", value = var.vpc_cidr },
    { name = "RUN_MIGRATIONS", value = "false" },
  ]
  backend_secret_names = ["SECRET_KEY", "METRICS_TOKEN", "DATABASE_URL", "REDIS_URL"]
  backend_secrets = concat(
    [for n in local.backend_secret_names : { name = n, valueFrom = aws_secretsmanager_secret.generated[n].arn }],
    [for n in ["ANTHROPIC_API_KEY", "QDRANT_API_KEY"] : { name = n, valueFrom = aws_secretsmanager_secret.provided[n].arn }],
  )
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "renovai-${var.environment}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn
  container_definitions = jsonencode([{
    name                   = "backend"
    image                  = var.backend_image
    essential              = true
    readonlyRootFilesystem = false
    portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
    environment            = local.backend_env
    secrets                = local.backend_secrets
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)\""]
      interval    = 15
      timeout     = 3
      retries     = 5
      startPeriod = 40
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])
}

# One-off task: run migrations (and optionally the seed script) before deploying a new version:
#   aws ecs run-task --cluster renovai-prod --task-definition renovai-prod-migrate --launch-type FARGATE \
#     --network-configuration "awsvpcConfiguration={subnets=[<private-subnet>],securityGroups=[<backend-sg>]}"
resource "aws_ecs_task_definition" "migrate" {
  family                   = "renovai-${var.environment}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn
  container_definitions = jsonencode([{
    name        = "migrate"
    image       = var.backend_image
    essential   = true
    command     = ["alembic", "upgrade", "head"]
    environment = local.backend_env
    secrets     = local.backend_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "renovai-${var.environment}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name                   = "frontend"
    image                  = var.frontend_image
    essential              = true
    readonlyRootFilesystem = false
    portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
    # ALB routes /api/* straight to the backend; this upstream only has to be a syntactically valid address.
    environment = [{ name = "BACKEND_UPSTREAM", value = "http://127.0.0.1:8000" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "frontend"
      }
    }
  }])
}

resource "aws_ecs_service" "backend" {
  name            = "backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_appautoscaling_target" "backend" {
  max_capacity       = 8
  min_capacity       = var.backend_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.backend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  name               = "backend-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
