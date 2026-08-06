#!/usr/bin/env python3
"""Interactively chat with the local hosted agent Responses endpoint."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

EXIT_SUCCESS = 0
EXIT_FAILURE = 1


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Interactively chat with a local or deployed hosted agent."
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Invoke a deployed agent through azd instead of the local endpoint.",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8088/responses",
        help="Local Responses endpoint URL (default: %(default)s).",
    )
    parser.add_argument(
        "--service",
        help="azd agent service name. Use when the project has multiple agents.",
    )
    parser.add_argument(
        "--agent-endpoint",
        help="Full deployed agent protocol endpoint for use outside its azd project.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Request timeout in seconds (default: %(default)s).",
    )
    return parser


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be an absolute http or https URL.")
    return url


def _extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_parts: list[str] = []
    output = response.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)

    if not text_parts:
        raise ValueError("Agent response did not contain any output text.")
    return "\n".join(text_parts).strip()


def _send_message(
    url: str,
    conversation: list[dict[str, str]],
    timeout: float,
) -> str:
    body = json.dumps({"input": conversation, "stream": False}).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Agent returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the agent at {url}: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Agent returned an unexpected response payload.")
    return _extract_output_text(payload)


def _invoke_remote(
    message: str,
    service: str | None,
    agent_endpoint: str | None,
    timeout: float,
    *,
    new_conversation: bool,
) -> str:
    command = ["azd", "ai", "agent", "invoke"]
    if service:
        command.append(service)
    if agent_endpoint:
        command.extend(["--agent-endpoint", agent_endpoint])
    if new_conversation:
        command.append("--new-conversation")
    command.append(message)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("azd was not found. Install Azure Developer CLI first.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Agent invocation timed out after {timeout:g} seconds.") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "Unknown azd error").strip()
        raise RuntimeError(f"azd agent invocation failed: {details}") from exc

    output = result.stdout.strip()
    if not output:
        raise RuntimeError("azd agent invocation returned no output.")
    return output


def run(url: str, timeout: float) -> int:
    """Run the interactive chat loop."""
    conversation: list[dict[str, str]] = []
    print(f"Chatting with {url}. Type /exit to quit.")

    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError:
            print()
            return EXIT_SUCCESS

        if user_input.lower() in {"/exit", "/quit"}:
            return EXIT_SUCCESS
        if not user_input:
            continue

        pending_conversation = [
            *conversation,
            {"role": "user", "content": user_input},
        ]
        assistant_text = _send_message(url, pending_conversation, timeout)
        print(f"Agent: {assistant_text}\n")
        conversation = [
            *pending_conversation,
            {"role": "assistant", "content": assistant_text},
        ]


def run_remote(
    service: str | None,
    agent_endpoint: str | None,
    timeout: float,
) -> int:
    """Run a remote chat loop using azd-managed conversation state."""
    target = agent_endpoint or service or "the deployed project agent"
    print(f"Chatting with {target}. Type /exit to quit.")
    new_conversation = True

    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError:
            print()
            return EXIT_SUCCESS

        if user_input.lower() in {"/exit", "/quit"}:
            return EXIT_SUCCESS
        if not user_input:
            continue

        assistant_text = _invoke_remote(
            user_input,
            service,
            agent_endpoint,
            timeout,
            new_conversation=new_conversation,
        )
        print(f"Agent: {assistant_text}\n")
        new_conversation = False


def main() -> int:
    """Parse arguments and run the chat client."""
    args = create_parser().parse_args()
    try:
        if args.timeout <= 0:
            raise ValueError("Timeout must be greater than zero.")
        if args.service and args.agent_endpoint:
            raise ValueError("Use either --service or --agent-endpoint, not both.")
        if args.remote:
            return run_remote(args.service, args.agent_endpoint, args.timeout)
        if args.service or args.agent_endpoint:
            raise ValueError("--service and --agent-endpoint require --remote.")
        return run(_validate_url(args.url), args.timeout)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except BrokenPipeError:
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())