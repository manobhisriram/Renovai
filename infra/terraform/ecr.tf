# Create these first (terraform apply -target=aws_ecr_repository.backend -target=aws_ecr_repository.frontend),
# push images, then apply everything. See docs/deployment.md.
resource "aws_ecr_repository" "backend" {
  name                 = "renovai/backend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "renovai/frontend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}
