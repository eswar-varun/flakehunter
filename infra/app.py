"""CDK entry point. `npx aws-cdk@2 deploy` runs this (see cdk.json).

    -c allowedOrigins=https://you.github.io   restrict CORS to the dashboard's origin
"""

from __future__ import annotations

import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_lambda import build  # noqa: E402
from stack import FlakeHunterStack  # noqa: E402

app = cdk.App()
origins = app.node.try_get_context("allowedOrigins")
FlakeHunterStack(
    app, "FlakeHunter",
    code=lambda_.Code.from_asset(str(build())),
    allowed_origins=origins.split(",") if origins else ("*",),
)
app.synth()
