terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source = "hashicorp/aws",
      version = "~> 6.0" }
  }
}

provider "aws" {
  region = var.region }

variable "region" {
  default = "eu-west-2" }

variable "name" {
  default = "nexus" }

variable "vpc_id" {
  type = string }

variable "private_subnet_ids" {
  type = list(string) }

variable "domain" {
  type = string }

variable "certificate_arn" {
  type = string }

variable "hosted_zone_id" {
  type = string }

variable "image_uri" {
  type = string }

variable "auth_secret_arn" {
  type = string }

variable "database_app_secret_arn" {
  type = string }

variable "google_secret_arn" {
  type = string }

variable "google_client_id" {
  type = string }

variable "ses_from_email" {
  type = string }

variable "ses_identity_arn" {
  type = string }

variable "bedrock_chat_model_id" {
  type = string }

variable "bedrock_model_arns" {
  type = list(string) }

# Start at zero, run migration, then set to two; see docs/AWS.md.

variable "api_count" {
  default = 0 }

variable "worker_count" {
  default = 0 }

data "aws_caller_identity" "current" {}

resource "aws_security_group" "link" {
  name_prefix = "${var.name}-link-"
  vpc_id = var.vpc_id
  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  vpc_id = var.vpc_id
  ingress {
    from_port = 80
    to_port = 80
    protocol = "tcp"
    security_groups = [aws_security_group.link.id] }
  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_security_group" "app" {
  name_prefix = "${var.name}-app-"
  vpc_id = var.vpc_id
  ingress {
    from_port = 8000
    to_port = 8000
    protocol = "tcp"
    security_groups = [aws_security_group.alb.id] }
  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_security_group" "db" {
  name_prefix = "${var.name}-db-"
  vpc_id = var.vpc_id
  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id] }
}

resource "aws_db_subnet_group" "db" {
  name = "${var.name}-db"
  subnet_ids = var.private_subnet_ids
}

resource "aws_db_instance" "db" {
  identifier = var.name
  engine = "postgres"
  engine_version = "17"
  instance_class = "db.t4g.medium"
  allocated_storage = 30
  max_allocated_storage = 200
  storage_encrypted = true
  db_name = "nexus"
  username = "nexus_admin"
  manage_master_user_password = true
  db_subnet_group_name = aws_db_subnet_group.db.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible = false
  multi_az = true
  backup_retention_period = 14
  deletion_protection = true
  skip_final_snapshot = false
  final_snapshot_identifier = "${var.name}-final"
  auto_minor_version_upgrade = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
}

resource "aws_lb" "app" {
  name = "${var.name}-private"
  internal = true
  load_balancer_type = "application"
  security_groups = [aws_security_group.alb.id]
  subnets = var.private_subnet_ids
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_target_group" "api" {
  name = "${var.name}-api"
  port = 8000
  protocol = "HTTP"
  target_type = "ip"
  vpc_id = var.vpc_id
  deregistration_delay = 30
  health_check {
    path = "/ready"
    interval = 30
    timeout = 5
    healthy_threshold = 2
    unhealthy_threshold = 3 }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port = 80
  protocol = "HTTP"
  default_action {
    type = "forward"
    target_group_arn = aws_lb_target_group.api.arn }
}

resource "aws_apigatewayv2_api" "api" {
  name = var.name
  protocol_type = "HTTP"
  disable_execute_api_endpoint = true
}

resource "aws_apigatewayv2_vpc_link" "link" {
  name = var.name
  security_group_ids = [aws_security_group.link.id]
  subnet_ids = var.private_subnet_ids
}

resource "aws_apigatewayv2_integration" "app" {
  api_id = aws_apigatewayv2_api.api.id
  integration_type = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri = aws_lb_listener.http.arn
  connection_type = "VPC_LINK"
  connection_id = aws_apigatewayv2_vpc_link.link.id
  payload_format_version = "1.0"
  timeout_milliseconds = 30000
  request_parameters = {
    "overwrite:path" = "$request.path"
    "overwrite:header.x-nexus-client-ip" = "$context.identity.sourceIp"
  }
}

resource "aws_apigatewayv2_route" "all" {
  api_id = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target = "integrations/${aws_apigatewayv2_integration.app.id}"
}

resource "aws_cloudwatch_log_group" "gateway" {
  name = "/nexus/${var.name}/gateway"
  retention_in_days = 30 }

resource "aws_apigatewayv2_stage" "live" {
  api_id = aws_apigatewayv2_api.api.id
  name = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit = 50 }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.gateway.arn
    format = jsonencode({
      requestId = "$context.requestId",
      status = "$context.status",
      route = "$context.routeKey",
      latency = "$context.responseLatency" })
  }
}

resource "aws_apigatewayv2_domain_name" "app" {
  domain_name = var.domain
  domain_name_configuration {
    certificate_arn = var.certificate_arn
    endpoint_type = "REGIONAL"
    security_policy = "TLS_1_2" }
}

resource "aws_apigatewayv2_api_mapping" "app" {
  api_id = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.app.id
  stage = aws_apigatewayv2_stage.live.id
}

resource "aws_route53_record" "app" {
  zone_id = var.hosted_zone_id
  name = var.domain
  type = "A"
  alias {
    name = aws_apigatewayv2_domain_name.app.domain_name_configuration[0].target_domain_name
    zone_id = aws_apigatewayv2_domain_name.app.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_ecs_cluster" "app" {
  name = var.name
  setting {
    name = "containerInsights"
    value = "enabled" }
}

resource "aws_cloudwatch_log_group" "app" {
  name = "/nexus/${var.name}/app"
  retention_in_days = 30 }

resource "aws_iam_role" "execution" {
  name_prefix = "${var.name}-exec-"
  assume_role_policy = jsonencode({Version="2012-10-17",
    Statement=[{Effect="Allow",Principal={Service="ecs-tasks.amazonaws.com"},Action="sts:AssumeRole"}]})
}

resource "aws_iam_role_policy_attachment" "execution" {
  role = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Action=["secretsmanager:GetSecretValue"],Resource=[var.auth_secret_arn,var.jwt_signing_keys_secret_arn,var.google_secret_arn,var.database_app_secret_arn,var.database_index_secret_arn,var.database_mail_secret_arn,aws_db_instance.db.master_user_secret[0].secret_arn]}]})
}

resource "aws_iam_role" "task" {
  for_each = toset(["api","mail","index"])
  name_prefix = "${var.name}-${each.key}-"
  assume_role_policy = aws_iam_role.execution.assume_role_policy
}

resource "aws_iam_role_policy" "bedrock" {
  for_each = toset(["api","index"])
  role = aws_iam_role.task[each.key].id
  policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Action=["bedrock:InvokeModel"],Resource=var.bedrock_model_arns}]})
}

resource "aws_iam_role_policy" "ses" {
  role = aws_iam_role.task["mail"].id
  policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Action=["ses:SendEmail"],Resource=[var.ses_identity_arn],Condition={StringEquals={"ses:FromAddress"=var.ses_from_email}}}]})
}

locals {
  environment = {
    ENVIRONMENT = "production",
    APP_ORIGIN = "https://${var.domain}",
    AWS_REGION = var.region,
    TRUST_GATEWAY = "true",
    MAIL_MODE = "ses",
    SES_FROM_EMAIL = var.ses_from_email,
    GOOGLE_CLIENT_ID = var.google_client_id,
    BEDROCK_CHAT_MODEL_ID = var.bedrock_chat_model_id,
    BEDROCK_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0",
    DB_HOST = aws_db_instance.db.address,
    DB_NAME = "nexus"
  }
  database_secrets = { api = var.database_app_secret_arn, index = var.database_index_secret_arn, mail = var.database_mail_secret_arn }
  common_secrets = [{ name="AUTH_SECRET", valueFrom=var.auth_secret_arn }]
  commands = {
    api = ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-proxy-headers","--no-access-log"],
    mail = ["python","-m","app.worker"],
    index = ["python","-m","app.indexer"]
  }
}

resource "aws_ecs_task_definition" "app" {
  for_each = local.commands
  family = "${var.name}-${each.key}"
  network_mode = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu = 512
  memory = 1024
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn = aws_iam_role.task[each.key].arn
  container_definitions = jsonencode([{
      name = "app",
      image = var.image_uri,
      essential = true,
      readonlyRootFilesystem = true,
      command = each.value,
      portMappings = each.key=="api" ? [{containerPort=8000,
          protocol="tcp"}] : [],
      environment = [for key,value in merge(local.environment,{ APP_ROLE=each.key, JWT_ACTIVE_KID=var.jwt_active_kid }) : {name=key,value=value}],
      secrets = concat(local.common_secrets,[
        {name="DB_USER",valueFrom="${local.database_secrets[each.key]}:username::"},
        {name="DB_PASSWORD",valueFrom="${local.database_secrets[each.key]}:password::"}
      ], each.key=="api" ? [
        {name="JWT_SIGNING_KEYS",valueFrom=var.jwt_signing_keys_secret_arn},
        {name="GOOGLE_CLIENT_SECRET",valueFrom=var.google_secret_arn}
      ] : []),
      logConfiguration = {logDriver="awslogs",options={awslogs-group=aws_cloudwatch_log_group.app.name,awslogs-region=var.region,awslogs-stream-prefix=each.key}}
  }])
}

resource "aws_ecs_service" "api" {
  name = "api"
  cluster = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app["api"].arn
  desired_count = var.api_count
  launch_type = "FARGATE"
  platform_version = "1.4.0"
  deployment_circuit_breaker {
    enable = true
    rollback = true }
  health_check_grace_period_seconds = 60
  network_configuration {
    subnets=var.private_subnet_ids
    security_groups=[aws_security_group.app.id]
    assign_public_ip=false }
  load_balancer {
    target_group_arn=aws_lb_target_group.api.arn
    container_name="app"
    container_port=8000 }
  depends_on = [aws_lb_listener.http,aws_iam_role_policy.secrets]
}

resource "aws_ecs_service" "worker" {
  for_each = toset(["mail","index"])
  name = each.key
  cluster = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app[each.key].arn
  desired_count = var.worker_count
  launch_type = "FARGATE"
  platform_version = "1.4.0"
  deployment_circuit_breaker {
    enable = true
    rollback = true }
  network_configuration {
    subnets=var.private_subnet_ids
    security_groups=[aws_security_group.app.id]
    assign_public_ip=false }
  depends_on = [aws_iam_role_policy.secrets]
}

resource "aws_appautoscaling_target" "api" {
  count = var.api_count>0 ? 1 : 0
  max_capacity = 6
  min_capacity = 2
  resource_id = "service/${aws_ecs_cluster.app.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace = "ecs"
}

resource "aws_appautoscaling_policy" "api" {
  count = var.api_count>0 ? 1 : 0
  name = "${var.name}-cpu"
  policy_type = "TargetTrackingScaling"
  resource_id = aws_appautoscaling_target.api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension
  service_namespace = "ecs"
  target_tracking_scaling_policy_configuration {
    target_value=60
    scale_in_cooldown=300
    scale_out_cooldown=60
    predefined_metric_specification {
      predefined_metric_type="ECSServiceAverageCPUUtilization" }
  }
}

resource "aws_cloudwatch_metric_alarm" "unhealthy" {
  alarm_name = "${var.name}-unhealthy-api"
  namespace = "AWS/ApplicationELB"
  metric_name = "UnHealthyHostCount"
  dimensions = {LoadBalancer=aws_lb.app.arn_suffix,TargetGroup=aws_lb_target_group.api.arn_suffix}
  statistic = "Maximum"
  period = 60
  evaluation_periods = 3
  threshold = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_description = "API targets unhealthy; connect an SNS incident topic in your account."
}

output "url" {
  value = "https://${var.domain}" }

output "cluster" {
  value = aws_ecs_cluster.app.name }

output "migration_task_definition" {
  value = aws_ecs_task_definition.migration.arn }

output "task_security_group" {
  value = aws_security_group.app.id }

output "database_secret_arn" {
  value = aws_db_instance.db.master_user_secret[0].secret_arn }

resource "aws_ecs_task_definition" "migration" {
  family = "${var.name}-migration"
  network_mode = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu = 512
  memory = 1024
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn = aws_iam_role.task["api"].arn
  container_definitions = jsonencode([{
      name="app",
      image=var.image_uri,
      essential=true,
      readonlyRootFilesystem=true,
      command=["python","-m","app.migrate"],
      environment=[for key,value in merge(local.environment,{APP_ROLE="migration"}) : {name=key,value=value}],
      secrets=[
        {name="AUTH_SECRET",valueFrom=var.auth_secret_arn},
        {name="DB_USER",valueFrom="${aws_db_instance.db.master_user_secret[0].secret_arn}:username::"},
        {name="DB_PASSWORD",valueFrom="${aws_db_instance.db.master_user_secret[0].secret_arn}:password::"},
        {name="APP_DB_USER",valueFrom="${var.database_app_secret_arn}:username::"},
        {name="APP_DB_PASSWORD",valueFrom="${var.database_app_secret_arn}:password::"},
        {name="INDEX_DB_USER",valueFrom="${var.database_index_secret_arn}:username::"},
        {name="INDEX_DB_PASSWORD",valueFrom="${var.database_index_secret_arn}:password::"},
        {name="MAIL_DB_USER",valueFrom="${var.database_mail_secret_arn}:username::"},
        {name="MAIL_DB_PASSWORD",valueFrom="${var.database_mail_secret_arn}:password::"}
      ],
      logConfiguration={logDriver="awslogs",options={awslogs-group=aws_cloudwatch_log_group.app.name,awslogs-region=var.region,awslogs-stream-prefix="migration"}}
  }])
}

variable "jwt_signing_keys_secret_arn" { type = string }
variable "jwt_active_kid" { default = "primary" }
variable "database_index_secret_arn" { type = string }
variable "database_mail_secret_arn" { type = string }

# WAF is attached to the private ALB; only the VPC-link SG may reach it.
resource "aws_wafv2_web_acl" "edge" {
  name = "${var.name}-edge"
  scope = "REGIONAL"
  default_action { allow {} }
  rule {
    name = "source-ip-budget"
    priority = 1
    action { block {} }
    statement {
      rate_based_statement {
        limit = 1000
        aggregate_key_type = "FORWARDED_IP"
        forwarded_ip_config {
          header_name = "x-nexus-client-ip"
          fallback_behavior = "NO_MATCH"
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name = "${var.name}-ip-budget"
      sampled_requests_enabled = false
    }
  }
  rule {
    name = "managed-auth-protection"
    priority = 2
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        name = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
        scope_down_statement {
          byte_match_statement {
            search_string = "/api/auth/"
            positional_constraint = "STARTS_WITH"
            field_to_match { uri_path {} }
            text_transformation { priority = 0
              type = "NONE" }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name = "${var.name}-auth-protection"
      sampled_requests_enabled = false
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name = "${var.name}-waf"
    sampled_requests_enabled = false
  }
}
resource "aws_wafv2_web_acl_association" "edge" {
  resource_arn = aws_lb.app.arn
  web_acl_arn = aws_wafv2_web_acl.edge.arn
}
resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name = "${var.name}-database-storage"
  namespace = "AWS/RDS"
  metric_name = "FreeStorageSpace"
  dimensions = { DBInstanceIdentifier = aws_db_instance.db.identifier }
  statistic = "Minimum"
  period = 300
  evaluation_periods = 2
  threshold = 5368709120
  comparison_operator = "LessThanThreshold"
  alarm_description = "Less than 5 GiB free database storage. Connect an incident SNS topic."
}
