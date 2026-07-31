# Foundry Hosted Agent + Foundry-Shared Skills (Teaching Demo)

This sample demonstrates a **hosted agent** that uses **skills shared in Azure AI Foundry** (not skills packaged with the agent image).

The learning loop is:

1. Author `SKILL.md` files locally.
2. Upload skills into the Foundry project (`provision_skills.py`).
3. Start/deploy agent.
4. Agent downloads skills from Foundry at startup and uses them via `load_skill` on demand.

## What this demo proves

- The agent runs even when no local `skills/` folder is mounted into runtime context.
- Skill behavior updates without code changes: edit `SKILL.md`, re-upload, restart/redeploy.
- Skills are progressively disclosed (name/description first, full instructions loaded only when relevant).

## Prerequisites

- Python 3.13+
- `az login` completed (you already have this)
- `azd` installed
- `azd` extensions:
  - `azure.ai.agents`
  - `azure.ai.skills`

Install extensions if needed:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd extension install azure.ai.agents
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd extension install azure.ai.skills
```

## Project files

- `main.py` – hosted agent entry point
- `provision_skills.py` – uploads skills to Foundry
- `skills/*/SKILL.md` – local source of skills to publish
- `azure.yaml` – azd project + agent service definition
- `.agentignore` – excludes `skills/` from deploy package so runtime only uses Foundry-downloaded skills

## Quick start

1. Create and activate env:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Configure environment:

```bash
cp .env.example .env
```

Set:
- `FOUNDRY_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `SKILL_NAMES` (default in `.env.example` is fine)

3. Upload / refresh skills in Foundry:

```bash
python provision_skills.py
```

4. Run locally:

```bash
python main.py
```

In another terminal:

```bash
curl -sS -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"input":"I want a $900 refund for a damaged tent and I am threatening legal action.","stream":false}'
```

## Deploy with azd

On first provision, run **without** `--no-prompt` so azd can interactively ask for your subscription and location:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision
```

azd writes `AZURE_SUBSCRIPTION_ID` and `AZURE_LOCATION` into the environment after you confirm. Subsequent runs can use `--no-prompt`:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd provision --no-prompt
```

Then set the required env vars (only needed once per azd environment — `azd provision` does not set these automatically):

```bash
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "gpt-5.4-mini"
azd env set SKILL_NAMES "support-style,escalation-policy"
```

Then deploy and invoke:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy --no-prompt
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke "Can I return hiking boots after 35 days?"
```

## Teach these concepts live

1. Ask a normal support question (loads `support-style` only).
2. Ask a legal/refund-escalation question (loads `escalation-policy` + `support-style`).
3. Change a canary token in `skills/escalation-policy/SKILL.md`.
4. Re-run `python provision_skills.py`.
5. Restart agent and ask the same escalation prompt; show updated canary in output.

## Troubleshooting

- `403 Forbidden` during `azd deploy` (`agents/read`) or when provisioning/downloading skills:
  - Your identity needs **Foundry Owner** (or **Foundry User**) on both the Foundry *account* and *project* scopes — not just `Azure AI Developer`:
    ```bash
    ACCOUNT_SCOPE="/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>"
    PROJECT_SCOPE="${ACCOUNT_SCOPE}/projects/<project>"
    az role assignment create --assignee <your-object-id> --role "Foundry Owner" --scope "$ACCOUNT_SCOPE"
    az role assignment create --assignee <your-object-id> --role "Foundry Owner" --scope "$PROJECT_SCOPE"
    ```
  - After assigning the roles, wait ~60 seconds for RBAC propagation then retry `azd deploy`.
- `session_not_ready` with logs showing `Skill '<name>' not found`:
  - The deployed agent is using a different Foundry project than where skills were uploaded.
  - Ensure `.env` and azd env both point to the same `FOUNDRY_PROJECT_ENDPOINT`, then re-run:
    ```bash
    python provision_skills.py
    ```
- `session_not_ready` with logs showing a timeout inside skill download (`_bootstrap_skills`):
  - The app starts by downloading skills; if this is slow/failing in your environment, `SKILLS_REQUIRED=false` lets the agent start without skills instead of failing readiness.
  - If you want fail-fast behavior (never run without skills), set `SKILLS_REQUIRED=true`.
- `SKILL.md not found`:
  - each skill package must contain `SKILL.md` at archive root (handled by `provision_skills.py`).
- Agent starts but does not apply a skill:
  - improve `description` in skill front matter to make routing intent clearer.
