#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy the return-postage calculator to Azure Container Apps."
    )
    parser.add_argument(
        "--name",
        default=os.getenv("RETURN_POSTAGE_APP_NAME", "return-postage-tool"),
        help="Container App name.",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP", ""),
        help="Azure resource group. Defaults to AZURE_RESOURCE_GROUP.",
    )
    parser.add_argument(
        "--location",
        default=os.getenv("AZURE_LOCATION", "eastus2"),
        help="Azure region used when associated resources must be created.",
    )
    parser.add_argument(
        "--environment",
        default=os.getenv("AZURE_CONTAINER_APPS_ENVIRONMENT", ""),
        help="Optional existing Container Apps environment name or resource ID.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).parent / "return_postage_tool",
        help="Tool source directory containing its Dockerfile.",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write RETURN_POSTAGE_API_URL to the repository .env file.",
    )
    return parser


def _upsert_env(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    updated = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            updated = True
            break
    if not updated:
        lines.append(f"{prefix}{value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _deploy(args: argparse.Namespace) -> str:
    if not args.resource_group.strip():
        raise ValueError("Set --resource-group or AZURE_RESOURCE_GROUP.")
    if not (args.source / "Dockerfile").is_file():
        raise ValueError(f"Dockerfile not found under {args.source}.")

    command = [
        "az",
        "containerapp",
        "up",
        "--name",
        args.name,
        "--resource-group",
        args.resource_group,
        "--location",
        args.location,
        "--source",
        str(args.source.resolve()),
        "--ingress",
        "external",
        "--target-port",
        "8080",
        "--query",
        "properties.configuration.ingress.fqdn",
        "--output",
        "tsv",
        "--only-show-errors",
    ]
    if args.environment.strip():
        command.extend(["--environment", args.environment])

    result = subprocess.run(command, capture_output=True, check=True, text=True)
    fqdn = result.stdout.strip()
    if not fqdn:
        raise RuntimeError("Azure did not return a Container App FQDN.")
    return f"https://{fqdn}"


def main() -> int:
    load_dotenv(override=True)
    args = create_parser().parse_args()
    try:
        api_url = _deploy(args)
        if args.write_env:
            _upsert_env(Path(__file__).parent / ".env", "RETURN_POSTAGE_API_URL", api_url)
        print(f"Return-postage API: {api_url}")
        print(f"Health check: {api_url}/health")
        return EXIT_SUCCESS
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Deployment failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())