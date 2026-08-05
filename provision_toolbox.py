#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Foundry toolbox containing configured tools and skills."
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""),
        help="Foundry project endpoint. Defaults to FOUNDRY_PROJECT_ENDPOINT.",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("TOOLBOX_TO_CREATE", "customer-service-toolbox"),
        help="New Foundry toolbox name.",
    )
    parser.add_argument(
        "--tool-names",
        default=os.getenv("TOOL_NAMES", ""),
        help="Comma-separated existing Foundry project connection names.",
    )
    parser.add_argument(
        "--skill-names",
        default=os.getenv("SKILL_NAMES", "support-style,escalation-policy"),
        help="Comma-separated existing Foundry skill names.",
    )
    parser.add_argument(
        "--return-postage-api-url",
        default=os.getenv("RETURN_POSTAGE_API_URL", ""),
        help="Base URL of the deployed return-postage API.",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write the created toolbox name to TOOLBOX_NAMES in .env.",
    )
    return parser


def _validate_https_url(raw_value: str, label: str) -> str:
    value = raw_value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be a valid HTTPS URL.")
    return value


def _return_postage_tool(api_url: str) -> dict[str, object]:
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Return Postage Calculator",
            "version": "1.0.0",
        },
        "servers": [{"url": api_url}],
        "paths": {
            "/calculate": {
                "get": {
                    "operationId": "calculateReturnPostage",
                    "summary": "Calculate estimated return postage in USD.",
                    "parameters": [
                        {
                            "name": "weight_kg",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "number", "exclusiveMinimum": 0},
                        },
                        {
                            "name": "distance_km",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "number", "minimum": 0},
                        },
                        {
                            "name": "expedited",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean", "default": False},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Postage estimate.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "currency": {"type": "string"},
                                            "price": {"type": "number"},
                                            "service": {"type": "string"},
                                            "expedited": {"type": "boolean"},
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"description": "Invalid calculation input."},
                    },
                }
            }
        },
    }
    return {
        "type": "openapi",
        "name": "return_postage",
        "description": "Calculate return shipping postage from weight and distance.",
        "openapi": {
            "name": "return_postage",
            "description": "Calculate return shipping postage from weight and distance.",
            "spec": spec,
            "auth": {"type": "anonymous"},
        },
    }


def _build_manifest(
    tool_names: list[str],
    skill_names: list[str],
    return_postage_api_url: str,
) -> dict[str, object]:
    tools: list[dict[str, object]] = []
    if return_postage_api_url:
        tools.append(_return_postage_tool(return_postage_api_url))
    if not tool_names and not tools:
        raise ValueError(
            "Configure TOOL_NAMES or RETURN_POSTAGE_API_URL; a toolbox needs at least one tool."
        )

    return {
        "description": "Customer-service tools and progressively disclosed support skills.",
        "connections": [{"name": name} for name in tool_names],
        "skills": [{"name": name} for name in skill_names],
        "tools": tools,
    }


def _upsert_env(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_toolbox(endpoint: str, name: str, manifest: dict[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        manifest_path = Path(temp_dir) / "toolbox.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        command = [
            "azd",
            "ai",
            "toolbox",
            "create",
            name,
            "--from-file",
            str(manifest_path),
            "--project-endpoint",
            endpoint,
            "--no-prompt",
            "--output",
            "json",
        ]
        result = subprocess.run(command, capture_output=True, check=True, text=True)
    return json.loads(result.stdout)


def main() -> int:
    load_dotenv(override=True)
    args = create_parser().parse_args()
    try:
        endpoint = _validate_https_url(args.endpoint, "FOUNDRY_PROJECT_ENDPOINT")
        api_url = ""
        if args.return_postage_api_url.strip():
            api_url = _validate_https_url(
                args.return_postage_api_url,
                "RETURN_POSTAGE_API_URL",
            )
        manifest = _build_manifest(
            _csv(args.tool_names),
            _csv(args.skill_names),
            api_url,
        )
        result = _create_toolbox(endpoint, args.name, manifest)
        if args.write_env:
            _upsert_env(Path(__file__).parent / ".env", "TOOLBOX_NAMES", args.name)
        consumer_endpoint = (
            f"{endpoint}/toolboxes/{args.name}/mcp?api-version=v1"
        )
        print(f"Created toolbox '{args.name}'.")
        print(f"Version: {result.get('version', '<unknown>')}")
        print(f"Consumer endpoint: {consumer_endpoint}")
        print(f"Set TOOLBOX_NAMES={args.name} for the hosted agent.")
        return EXIT_SUCCESS
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        print(f"Toolbox provisioning failed: {stderr.strip() or exc}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())