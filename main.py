import asyncio
import io
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Final

from agent_framework import Agent, SkillsProvider, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

load_dotenv(override=True)

LOGGER = logging.getLogger(__name__)
# Use /tmp in hosted containers (app dir is read-only); fall back to next to main.py locally.
_DEFAULT_SKILLS_DIR = (
    Path("/tmp/downloaded_skills")
    if os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT") or os.getenv("WEBSITE_SITE_NAME")
    else Path(__file__).parent / "downloaded_skills"
)
DOWNLOADED_SKILLS_DIR: Final = Path(os.getenv("DOWNLOADED_SKILLS_DIR", str(_DEFAULT_SKILLS_DIR)))
SKILL_BOOTSTRAP_TIMEOUT_SECONDS: Final = 60.0

ORDER_STATUS = {
    "A-1042": "delivered 9 days ago",
    "A-2235": "in transit, arriving tomorrow",
    "A-9011": "delivered 41 days ago",
}


def _resolved_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if (value.startswith("${") and value.endswith("}")) or (
        value.startswith("{{") and value.endswith("}}")
    ):
        return ""
    return value


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    for member in zf.infolist():
        member_path = (dest_root / member.filename).resolve()
        if dest_root != member_path and dest_root not in member_path.parents:
            raise RuntimeError(
                f"Refusing to extract unsafe path '{member.filename}' outside of '{dest_root}'."
            )
    zf.extractall(dest_dir)


async def _bootstrap_skills(endpoint: str, skill_names: list[str], target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True) as project,
    ):
        for name in skill_names:
            LOGGER.info("Downloading skill '%s' from Foundry...", name)
            stream = await project.beta.skills.download(name)
            zip_bytes = b"".join([chunk async for chunk in stream])

            skill_dir = target_dir / name
            skill_dir.mkdir()

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                _safe_extract_zip(zf, skill_dir)

            if not (skill_dir / "SKILL.md").is_file():
                raise RuntimeError(
                    f"Downloaded archive for '{name}' did not contain SKILL.md at archive root."
                )


@tool(approval_mode="never_require")
def get_order_status(
    order_id: Annotated[str, Field(description="Order ID such as A-1042.")],
) -> str:
    key = order_id.strip().upper()
    return ORDER_STATUS.get(key, "Order not found. Ask for email + postal code for manual lookup.")


async def main() -> None:
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model_name = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
    skill_names = [name.strip() for name in _resolved_env("SKILL_NAMES").split(",") if name.strip()]

    context_providers = []
    if skill_names:
        await asyncio.wait_for(
            _bootstrap_skills(project_endpoint, skill_names, DOWNLOADED_SKILLS_DIR),
            timeout=SKILL_BOOTSTRAP_TIMEOUT_SECONDS,
        )
        context_providers.append(
            SkillsProvider.from_paths(
                skill_paths=str(DOWNLOADED_SKILLS_DIR),
                disable_load_skill_approval=True,
                disable_read_skill_resource_approval=True,
            )
        )
    else:
        LOGGER.warning("SKILL_NAMES is empty. Running without Foundry-shared skills.")

    async with DefaultAzureCredential() as credential:
        client = FoundryChatClient(
            project_endpoint=project_endpoint,
            model=model_name,
            credential=credential,
        )

        agent = Agent(
            client=client,
            instructions=(
                "You are the Contoso Outdoors support agent. "
                "Use get_order_status when users ask about an order. "
                "Use available skills when user intent matches them."
            ),
            tools=[get_order_status],
            context_providers=context_providers,
            default_options={"store": False},
        )

        server = ResponsesHostServer(agent)
        await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
