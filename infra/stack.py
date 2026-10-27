"""The serverless backend: API Gateway (HTTP API) -> one Lambda function -> one DynamoDB table.

Sized for a team's CI traffic, and cheap at rest: on-demand DynamoDB and Lambda cost nothing
without requests, and the API is throttled so a misbehaving client can't run up a bill.
"""

from __future__ import annotations

from collections.abc import Sequence

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

ROUTES = (
    (apigw.HttpMethod.POST, "/projects/{project}/runs"),
    (apigw.HttpMethod.GET, "/projects/{project}/verdicts"),
    (apigw.HttpMethod.GET, "/projects/{project}/history"),
)


class FlakeHunterStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, code: lambda_.Code,
                 allowed_origins: Sequence[str] = ("*",), **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Keys match flakehunter.dynamo: one partition per project, sort key in analysis order.
        table = dynamodb.Table(
            self, "History",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True),
            # History is the product; deleting the stack must not delete it.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # CI uploads with this token; the dashboard only reads, which needs none.
        token = secretsmanager.Secret(
            self, "UploadToken",
            description="Bearer token for FlakeHunter uploads",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True, password_length=40),
        )

        function = lambda_.Function(
            self, "Api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="flakehunter.api.handler",
            code=code,
            memory_size=512,
            # Just under API Gateway's 30-second integration limit.
            timeout=Duration.seconds(29),
            environment={"TABLE_NAME": table.table_name,
                         "TOKEN_SECRET_ARN": token.secret_arn},
            log_group=logs.LogGroup(self, "ApiLogs", retention=logs.RetentionDays.TWO_WEEKS,
                                    removal_policy=RemovalPolicy.DESTROY),
        )
        # Least privilege: item reads and writes on this table and reading this one secret.
        table.grant_read_write_data(function)
        token.grant_read(function)

        api = apigw.HttpApi(
            self, "HttpApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=list(allowed_origins),
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.hours(1),
            ),
        )
        integration = integrations.HttpLambdaIntegration("ApiIntegration", function)
        for method, path in ROUTES:
            api.add_routes(path=path, methods=[method], integration=integration)

        stage = api.default_stage.node.default_child
        stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=20, throttling_rate_limit=10)

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "UploadTokenSecretArn", value=token.secret_arn)
