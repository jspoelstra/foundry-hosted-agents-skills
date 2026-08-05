---
title: Foundry Hosted Agent with Shared Skills and Tools
description: Teaching sample for a hosted agent that consumes Foundry skills, tools, and toolboxes
---

This sample demonstrates a hosted agent that uses skills and toolboxes shared in
Microsoft Foundry rather than packaging those resources in the agent image.

The learning loop is:

1. Author `SKILL.md` files locally.
2. Upload the skills with `provision_skills.py`.
3. Connect existing project tools or create the sample return-postage tool.
4. Create a toolbox containing tools and skill references with
  `provision_toolbox.py`.
5. Start or deploy the agent. It downloads skills and connects to the configured
  toolbox MCP endpoints.

## What this demo proves

* The agent runs without mounting the local `skills/` folder into runtime context
* Skill behavior updates without code changes after upload and agent restart
* Skills are progressively disclosed by the Agent Framework skills provider
* Existing Foundry toolboxes can be attached by name or explicit MCP endpoint
* Existing connection-backed project tools can be composed into a new toolbox
* One toolbox can contain both tools and Foundry skill references

## Prerequisites

* Python 3.13+
* Azure CLI with `az login` completed
* Azure Developer CLI with `azd auth login` completed
* The unified Microsoft Foundry extension

Install or update the extension if needed:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd extension install microsoft.foundry
```

## Project files

* `main.py`: hosted agent entry point
* `provision_skills.py`: uploads skills to Foundry
* `provision_toolbox.py`: creates a toolbox from existing tools, skills, and the
  sample OpenAPI tool
* `deploy_return_postage_tool.py`: deploys the sample API to Azure Container Apps
* `return_postage_tool/`: source and Dockerfile for the sample API
* `skills/*/SKILL.md`: local source of skills to publish
* `azure.yaml`: azd project and agent service definition
* `.agentignore`: excludes local skill and provisioning sources from the agent
  deployment

## Environment configuration

Copy the template and set the project and model values:

```bash
cp .env.example .env
```

The tool-related settings are:

* `TOOL_NAMES`: comma-separated names of existing Foundry project connections
  that represent connection-backed tools, such as MCP or Azure AI Search
  connections. `provision_toolbox.py` includes them in the new toolbox.
* `TOOLBOX_NAMES`: comma-separated names of existing toolboxes in the same
  project. The agent constructs each consumer MCP endpoint from the project
  endpoint and toolbox name.
* `TOOLBOX_ENDPOINTS`: comma-separated explicit toolbox MCP endpoints. Use this
  for toolboxes in another project or to test a version-specific endpoint.
* `TOOLBOX_TO_CREATE`: name created by `provision_toolbox.py`.
* `RETURN_POSTAGE_API_URL`: HTTPS base URL produced by the sample tool deployment.

Foundry tools are tool definitions or project connections, not independently
callable runtime endpoints. The agent therefore consumes toolboxes directly.
`TOOL_NAMES` is used when creating a toolbox, while `TOOLBOX_NAMES` and
`TOOLBOX_ENDPOINTS` are used by the running agent.

## Quick start

1. Create and activate env:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

1. Configure `.env` as described above.

1. Upload or refresh skills in Foundry:

```bash
python provision_skills.py
```

1. Run locally. Toolbox configuration is optional:

```bash
python main.py
```

In another terminal:

```bash
curl -sS -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"input":"I want a $900 refund for a damaged tent and I am threatening legal action.","stream":false}'
```

## Create the sample tool and toolbox

The return-postage API is intentionally simple and anonymous for teaching. Do
not use its pricing formula or anonymous ingress as a production shipping service.

1. Deploy the tool. The command creates or updates a Container App and writes its
  HTTPS URL to `.env`:

```bash
python deploy_return_postage_tool.py \
  --resource-group <resource-group> \
  --location <location> \
  --write-env
```

1. Upload the local skills if they are not already in the project:

```bash
python provision_skills.py
```

1. Create a toolbox containing the return-postage OpenAPI tool, every connection
  in `TOOL_NAMES`, and every skill in `SKILL_NAMES`:

```bash
python provision_toolbox.py --write-env
```

The first toolbox version becomes the default. The script writes its name to
`TOOLBOX_NAMES`, so the next local run or deployment connects to the consumer
endpoint automatically.

To use only existing resources, leave `RETURN_POSTAGE_API_URL` empty, set
`TOOL_NAMES` to existing project connection names, and run the same toolbox
provisioning command. To consume existing toolboxes without creating one, set
`TOOLBOX_NAMES` or `TOOLBOX_ENDPOINTS` and skip both provisioning scripts.

## Deploy with azd

On first provision, run **without** `--no-prompt` so azd can interactively ask for your subscription and location:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision
```

azd writes `AZURE_SUBSCRIPTION_ID` and `AZURE_LOCATION` into the environment after you confirm. Subsequent runs can use `--no-prompt`:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision --no-prompt
```

Then set the required environment values. These are needed once per azd
environment because `azd provision` does not set them automatically:

```bash
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "gpt-5.4-mini"
azd env set SKILL_NAMES "support-style,escalation-policy"
azd env set TOOLBOX_NAMES "customer-service-toolbox"
azd env set TOOLBOX_ENDPOINTS ""
```

Then deploy and invoke:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy --no-prompt
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke "Can I return hiking boots after 35 days?"
```

## Deploy without azd provision (direct Python SDK)

If `azd provision` or `azd deploy` is blocked in your environment, you can deploy a hosted agent version directly to an existing Foundry project.

1. Ensure `.env` has:

```bash
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<existing-model-deployment-name>
SKILL_NAMES=support-style,escalation-policy
```

1. Upload skills first (optional but recommended for this sample):

```bash
python provision_skills.py
```

1. Deploy code as a hosted agent version:

```bash
python deploy_hosted_agent.py --agent-name customer-service-agent --description "manual zip deploy"
```

The deploy script packages the repository into a ZIP, respects `.agentignore`,
and calls Foundry directly through `azure.ai.projects`. It reads
`TOOLBOX_NAMES` and `TOOLBOX_ENDPOINTS` from `.env` and passes them to the hosted
agent version.

1. Verify by listing versions (example):

```bash
python -c "import asyncio; from azure.ai.projects.aio import AIProjectClient; from azure.identity.aio import DefaultAzureCredential; endpoint='https://<account>.services.ai.azure.com/api/projects/<project>'; async def main():
  async with DefaultAzureCredential() as cred, AIProjectClient(endpoint=endpoint, credential=cred, allow_preview=True) as p:
    async for v in p.agents.list_versions('customer-service-agent', limit=5): print(v.version)
asyncio.run(main())"
```

## Teach these concepts live

1. Ask a normal support question to load `support-style` only.
2. Ask a legal or refund-escalation question to load both skills.
3. Ask for return postage for a 2 kg package traveling 750 km to invoke the
  toolbox OpenAPI tool.
4. Change a canary token in `skills/escalation-policy/SKILL.md`.
5. Re-run `python provision_skills.py`.
6. Restart the agent and show the updated behavior without a code change.

## Troubleshooting

* `azd` reports an expired login while creating a toolbox:
  * Run `azd auth login`, then retry `python provision_toolbox.py`.
* `403 Forbidden` during deployment or project resource provisioning:
  * Your identity needs **Foundry Owner** or **Foundry User** on both the Foundry
    account and project scopes, not only `Azure AI Developer`:

    ```bash
    ACCOUNT_SCOPE="/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>"
    PROJECT_SCOPE="${ACCOUNT_SCOPE}/projects/<project>"
    az role assignment create --assignee <your-object-id> --role "Foundry Owner" --scope "$ACCOUNT_SCOPE"
    az role assignment create --assignee <your-object-id> --role "Foundry Owner" --scope "$PROJECT_SCOPE"
    ```

  * Wait about 60 seconds for RBAC propagation before retrying.
* `session_not_ready` with `Skill '<name>' not found`:
  * Ensure `.env` and the azd environment point to the project where the skills
    were uploaded, then re-run:

    ```bash
    python provision_skills.py
    ```

* Skill bootstrap times out:
  * `SKILLS_REQUIRED=false` lets the agent start without skills. Set it to `true`
    for fail-fast behavior.
* `SKILL.md not found`:
  * Each skill package must contain `SKILL.md` at its archive root.
* Toolbox creation reports that a connection or skill is missing:
  * `TOOL_NAMES` and `SKILL_NAMES` must reference resources in the same Foundry
    project as `FOUNDRY_PROJECT_ENDPOINT`.
* Toolbox creation reports that the toolbox already exists:
  * Choose a new `TOOLBOX_TO_CREATE`, or delete the teaching toolbox before recreating
    it. Toolbox versions are immutable.
* The agent starts but does not apply a skill or tool:
  * Improve the skill front matter description or the tool description so the
    model can route the request correctly.
