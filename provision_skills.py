import asyncio
import io
import os
from urllib.parse import urlparse
import zipfile
from pathlib import Path

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import CreateSkillVersionFromFilesBody
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

SKILLS_DIR = Path(__file__).parent / "skills"


def _validate_foundry_endpoint(raw_value: str) -> str:
    endpoint = raw_value.strip()
    if not endpoint:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT is empty. Set it in .env or shell environment."
        )

    if "<" in endpoint or ">" in endpoint:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT still contains placeholders. "
            "Replace <account> and <project> with real values."
        )

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT must be a valid https URL like "
            "https://<account>.services.ai.azure.com/api/projects/<project>."
        )

    expected_host_suffix = ".services.ai.azure.com"
    if not parsed.netloc.endswith(expected_host_suffix):
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT host must end with .services.ai.azure.com."
        )

    expected_path_prefix = "/api/projects/"
    if not parsed.path.startswith(expected_path_prefix) or len(parsed.path) <= len(expected_path_prefix):
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT path must look like /api/projects/<project>."
        )

    return endpoint


def _zip_skill_dir(skill_dir: Path) -> bytes:
    """Package an entire skill directory as a ZIP with SKILL.md and any references/ files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(skill_dir).as_posix()
                zf.write(f, arcname)
    return buffer.getvalue()


async def _delete_skill_if_exists(project: AIProjectClient, name: str) -> None:
    try:
        await project.beta.skills.delete(name)
    except (ResourceNotFoundError, Exception) as exc:
        if "not found" in str(exc).lower() or isinstance(exc, ResourceNotFoundError):
            return
        raise
    print(f"Deleted existing skill '{name}'.")


async def _create_skill(project: AIProjectClient, name: str, zip_bytes: bytes) -> object:
    # create_from_files accepts a multipart body; a single-entry list with a ZIP
    # is the canonical way to upload a packaged skill archive.
    body = CreateSkillVersionFromFilesBody(
        files=[("skill.zip", zip_bytes, "application/zip")],
    )
    return await project.beta.skills.create_from_files(name, body)


async def main() -> None:
    load_dotenv(override=True)
    endpoint = _validate_foundry_endpoint(os.environ["FOUNDRY_PROJECT_ENDPOINT"])

    skill_dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    if not skill_dirs:
        raise RuntimeError(f"No skill directories with SKILL.md found under {SKILLS_DIR}.")

    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True) as project,
    ):
        for skill_dir in skill_dirs:
            name = skill_dir.name
            print(f"Provisioning skill '{name}' from {skill_dir.relative_to(SKILLS_DIR.parent)}/...")
            await _delete_skill_if_exists(project, name)
            imported = await _create_skill(project, name, _zip_skill_dir(skill_dir))
            print(
                f"Imported '{imported.name}' "
                f"(id={imported.skill_id}, version={imported.version})."
            )

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
