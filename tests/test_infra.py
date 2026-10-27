"""The CDK stack, checked on the CloudFormation template it synthesizes (no AWS account needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

cdk = pytest.importorskip("aws_cdk")

from aws_cdk import aws_lambda as lambda_  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from flakehunter.api import ROUTE_KEYS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra"))
from stack import FlakeHunterStack  # noqa: E402


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = FlakeHunterStack(app, "Test", code=lambda_.Code.from_inline("def handler(e, c): pass"),
                             allowed_origins=["https://dashboard.example.com"])
    return Template.from_stack(stack)


def test_table_keys_match_the_store_and_history_survives_stack_deletion(template):
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.has_resource("AWS::DynamoDB::Table", {
        "DeletionPolicy": "Retain",
        "Properties": {
            "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"},
                          {"AttributeName": "sk", "KeyType": "RANGE"}],
            "BillingMode": "PAY_PER_REQUEST",
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
        },
    })


def test_function_runs_the_api_handler_within_the_gateway_timeout(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "flakehunter.api.handler",
        "Runtime": "python3.12",
        "Architectures": ["arm64"],
        "Timeout": 29,
        "Environment": {"Variables": {"TABLE_NAME": Match.any_value(),
                                      "TOKEN_SECRET_ARN": Match.any_value()}},
    })


def test_function_gets_item_access_and_the_secret_but_cannot_drop_the_table(template):
    policies = template.find_resources("AWS::IAM::Policy")
    actions = set()
    for policy in policies.values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            granted = statement["Action"]
            actions.update([granted] if isinstance(granted, str) else granted)

    assert {"dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query",
            "secretsmanager:GetSecretValue"} <= actions
    assert not {a for a in actions if a.endswith("*") and a.split(":")[1] == "*"}
    assert not {"dynamodb:DeleteTable", "dynamodb:CreateTable", "dynamodb:UpdateTable"} & actions


def test_api_exposes_exactly_the_routes_the_handler_serves(template):
    routes = template.find_resources("AWS::ApiGatewayV2::Route")

    assert sorted(r["Properties"]["RouteKey"] for r in routes.values()) == sorted(ROUTE_KEYS)


def test_api_is_throttled(template):
    template.has_resource_properties("AWS::ApiGatewayV2::Stage", {
        "DefaultRouteSettings": {"ThrottlingBurstLimit": 20, "ThrottlingRateLimit": 10},
    })


def test_cors_allows_only_the_configured_dashboard(template):
    template.has_resource_properties("AWS::ApiGatewayV2::Api", {
        "CorsConfiguration": Match.object_like({
            "AllowOrigins": ["https://dashboard.example.com"],
            "AllowHeaders": ["authorization", "content-type"],
        }),
    })


def test_outputs_tell_ci_where_to_upload(template):
    outputs = template.find_outputs("*")

    assert {"ApiUrl", "TableName", "UploadTokenSecretArn"} <= set(outputs)
