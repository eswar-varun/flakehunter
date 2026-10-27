"""Run the real API handler locally, against an in-memory DynamoDB (moto), for dashboard work.

    python dev/local_api.py --seed 10          # 10 runs of the zoo, 2 per commit
    cd dashboard && npm run dev                 # VITE_API_URL defaults to this server

Requests go through the same handler code Lambda runs, wrapped in the same event shape API
Gateway sends, so what works here works deployed. Uploads use the token printed at start-up.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import boto3
from moto import mock_aws

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

from evaluate_zoo import run_zoo  # noqa: E402

from flakehunter.api import ROUTE_KEYS, make_handler  # noqa: E402
from flakehunter.dynamo import DynamoStore, create_table  # noqa: E402
from flakehunter.junit import parse_file  # noqa: E402
from flakehunter.model import Run  # noqa: E402

TABLE = "flakehunter-local"


def _route(method: str, path: str) -> tuple[str | None, dict[str, str]]:
    """Match a request against the API's route keys, as API Gateway does."""
    for key in ROUTE_KEYS:
        route_method, template = key.split(" ", 1)
        pattern = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template) + "$"
        match = re.match(pattern, path)
        if route_method == method and match:
            return key, match.groupdict()
    return None, {}


def serve(port: int, handler, token: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-headers", "authorization, content-type")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_OPTIONS(self) -> None:  # noqa: N802 - http.server's naming
            self._send(204, "")

        def _dispatch(self) -> None:
            url = urlsplit(self.path)
            route, params = _route(self.command, url.path)
            length = int(self.headers.get("content-length") or 0)
            event = {
                "version": "2.0",
                "routeKey": route or f"{self.command} {url.path}",
                "pathParameters": params,
                "queryStringParameters": dict(parse_qsl(url.query)) or None,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": self.rfile.read(length).decode() if length else None,
                "isBase64Encoded": False,
                "requestContext": {"requestId": secrets.token_hex(8)},
            }
            response = handler(event, None)
            self._send(response["statusCode"], response["body"])

        do_GET = do_POST = _dispatch  # noqa: N815

    print(f"FlakeHunter API on http://localhost:{port}  (upload token: {token})")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def seed(store: DynamoStore, project: str, runs: int) -> None:
    start = datetime.now(UTC) - timedelta(hours=runs)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(1, runs + 1):
            report = Path(tmp) / f"run-{i}.xml"
            run_zoo(report, seed=i)
            store.add_run(project, Run(f"run-{i}", f"commit-{(i - 1) // 2:03d}",
                                       start + timedelta(hours=i)), parse_file(report))
            print(f"seeded run {i}/{runs}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--project", default="zoo")
    parser.add_argument("--seed", type=int, default=0, metavar="RUNS",
                        help="pre-load this many runs of the zoo")
    args = parser.parse_args()

    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_table(client, TABLE)
        store = DynamoStore(TABLE, client=client)
        if args.seed:
            seed(store, args.project, args.seed)
        token = secrets.token_urlsafe(24)
        serve(args.port, make_handler(store, token=lambda: token), token)


if __name__ == "__main__":
    main()
