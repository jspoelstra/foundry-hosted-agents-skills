#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import io
import os
import shlex
import sys
import zipfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointProtocol,
    AgentKind,
    CodeConfiguration,
    CodeDependencyResolution,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 2


def create_parser() -> argparse.ArgumentParser:
    """Create command line arguments."""
    parser = argparse.ArgumentParser(
        description="Deploy a hosted Foundry agent version by uploading a source ZIP."
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""),
        help="Foundry project endpoint. Defaults to FOUNDRY_PROJECT_ENDPOINT.",
    )
    parser.add_argument(
        "--agent-name",
        required=True,
        help="Foundry hosted agent name (new or existing).",
    )
    parser.add_argument(
        "--model-deployment",
        default=os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", ""),
        help="Model deployment name for the agent definition.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).parent,
        help="Source directory to package. Defaults to repository root.",
    )
    parser.add_argument(
        "--entry-point",
        default="main.py",
        help="Code entry point file path relative to --source.",
    )
    parser.add_argument(
        "--runtime",
        default="python_3_13",
        help="Hosted runtime name (for example python_3_13).",
    )
    parser.add_argument(
        "--cpu",
        default="0.5",
        help="Hosted CPU setting.",
    )
    parser.add_argument(
        "--memory",
        default="1Gi",
        help="Hosted memory setting.",
    )
    parser.add_argument(
        "--dependency-resolution",
        choices=("remote_build", "bundled"),
        default="remote_build",
        help="Dependency resolution mode for code deployments.",
    )
    parser.add_argument(
        "--skill-names",
        default=os.getenv("SKILL_NAMES", "support-style,escalation-policy"),
        help="Comma-separated skill names passed as SKILL_NAMES env var.",
    )
    parser.add_argument(
        "--toolbox-names",
        default=os.getenv("TOOLBOX_NAMES", ""),
        help="Comma-separated Foundry toolbox names passed as TOOLBOX_NAMES.",
    )
    parser.add_argument(
        "--toolbox-endpoints",
        default=os.getenv("TOOLBOX_ENDPOINTS", ""),
        help="Comma-separated toolbox MCP endpoints passed as TOOLBOX_ENDPOINTS.",
    )
    parser.add_argument(
        "--description",
        default="Code deploy via deploy_hosted_agent.py",
        help="Version description shown in Foundry.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build ZIP and print metadata without uploading a new version.",
    )
    return parser


def _validate_endpoint(raw_value: str) -> str:
    endpoint = raw_value.strip()
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT is empty. Set --endpoint or .env.")
    if "<" in endpoint or ">" in endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT still contains placeholders.")

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Endpoint must be a valid https URL.")
    if not parsed.netloc.endswith(".services.ai.azure.com"):
        raise ValueError("Endpoint host must end with .services.ai.azure.com.")
    if not parsed.path.startswith("/api/projects/"):
        raise ValueError("Endpoint path must look like /api/projects/<project>.")
    return endpoint


def _read_ignore_patterns(source_dir: Path) -> list[str]:
    ignore_file = source_dir / ".agentignore"
    defaults = [".git/", ".venv/", "__pycache__/", "*.pyc", "*.pyo"]
    if not ignore_file.is_file():
        return defaults

    patterns: list[str] = defaults.copy()
    for raw_line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _matches_ignore(rel_path: str, patterns: Iterable[str]) -> bool:
    normalized = rel_path.replace("\\", "/")
    for pattern in patterns:
        p = pattern.strip().replace("\\", "/")
        if not p:
            continue

        # Directory-like patterns from .agentignore (for example "skills/").
        if p.endswith("/"):
            prefix = p.rstrip("/") + "/"
            if normalized.startswith(prefix):
                return True
            continue

        if fnmatch.fnmatch(normalized, p):
            return True
    return False


def _zip_source(source_dir: Path, patterns: Iterable[str]) -> bytes:
    if not source_dir.is_dir():
        raise ValueError(f"Source directory not found: {source_dir}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_dir).as_posix()
            if _matches_ignore(rel, patterns):
                continue
            zf.write(path, arcname=rel)
    return buf.getvalue()


def _dependency_resolution(value: str) -> CodeDependencyResolution:
    if value == "bundled":
        return CodeDependencyResolution.BUNDLED
    return CodeDependencyResolution.REMOTE_BUILD


def _entry_point_args(runtime: str, entry_point: str) -> list[str]:
    """Build a command-style entry point list for hosted runtime execution."""
    parts = shlex.split(entry_point)
    if not parts:
        raise ValueError("Entry point must not be empty.")

    # For Python runtimes, run script/module through interpreter unless already explicit.
    if runtime.startswith("python_") and parts[0] not in {"python", "python3", "uv"}:
        return ["python", *parts]
    return parts


async def _deploy(args: argparse.Namespace) -> None:
    endpoint = _validate_endpoint(args.endpoint)
    source_dir = args.source.resolve()
    entry_point = args.entry_point.strip()
    entry_parts = _entry_point_args(args.runtime, entry_point)
    entry_path = source_dir / entry_parts[-1]
    if not entry_path.is_file():
        raise ValueError(f"Entry point file does not exist: {entry_path}")

    patterns = _read_ignore_patterns(source_dir)
    zip_bytes = _zip_source(source_dir, patterns)
    sha256 = hashlib.sha256(zip_bytes).hexdigest()

    print(f"Source directory: {source_dir}")
    print(f"Entry point: {' '.join(entry_parts)}")
    print(f"ZIP size: {len(zip_bytes)} bytes")
    print(f"ZIP sha256: {sha256}")
    print(f"Ignore patterns: {patterns}")

    if args.dry_run:
        print("Dry run complete. Skipping upload.")
        return

    environment_variables = {
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": args.model_deployment,
        "FOUNDRY_PROJECT_ENDPOINT": endpoint,
        "SKILL_NAMES": args.skill_names,
        "TOOLBOX_NAMES": args.toolbox_names,
        "TOOLBOX_ENDPOINTS": args.toolbox_endpoints,
    }

    definition = HostedAgentDefinition(
        kind=AgentKind.HOSTED,
        cpu=args.cpu,
        memory=args.memory,
        environment_variables=environment_variables,
        protocol_versions=[
            ProtocolVersionRecord(
                protocol=AgentEndpointProtocol.RESPONSES,
                version="2.0.0",
            )
        ],
        code_configuration=CodeConfiguration(
            runtime=args.runtime,
            entry_point=entry_parts,
            dependency_resolution=_dependency_resolution(args.dependency_resolution),
        ),
    )

    if not args.model_deployment.strip():
        raise ValueError(
            "Model deployment is empty. Set --model-deployment or AZURE_AI_MODEL_DEPLOYMENT_NAME."
        )

    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True) as project,
    ):
        code_stream = io.BytesIO(zip_bytes)
        code_stream.name = "agent_code.zip"
        version = await project.agents.create_version_from_code(
            args.agent_name,
            definition=definition,
            code=code_stream,
            code_zip_sha256=sha256,
            description=args.description,
            metadata={"deployedBy": "deploy_hosted_agent.py"},
        )

        print("Created/updated hosted agent version:")
        print(f"  agent: {args.agent_name}")
        print(f"  version: {getattr(version, 'version', '<unknown>')}")
        print(f"  id: {getattr(version, 'id', '<unknown>')}")

        details = await project.agents.get(args.agent_name)
        print("Agent details:")
        print(f"  name: {getattr(details, 'name', args.agent_name)}")
        print(f"  enabled: {getattr(details, 'enabled', '<unknown>')}")


async def run_async() -> int:
    load_dotenv(override=True)
    parser = create_parser()
    args = parser.parse_args()

    try:
        await _deploy(args)
        return EXIT_SUCCESS
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        print(f"Deployment failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILURE


def main() -> int:
    return asyncio.run(run_async())


if __name__ == "__main__":
    sys.exit(main())
