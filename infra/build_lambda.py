"""Assemble the Lambda deployment package: the flakehunter package plus its dependencies.

Dependencies come from pyproject.toml, installed as wheels for Lambda's platform (Linux,
ARM64, Python 3.12) so nothing needs Docker or a Linux machine to build. boto3 is left out:
the Lambda runtime provides it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path = ROOT / "build" / "lambda") -> Path:
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"]["dependencies"]
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if dependencies:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "--target", str(out), "--platform", "manylinux2014_aarch64",
             "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:",
             *dependencies],
            check=True,
        )
    shutil.copytree(ROOT / "src" / "flakehunter", out / "flakehunter",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return out


if __name__ == "__main__":
    print(build())
