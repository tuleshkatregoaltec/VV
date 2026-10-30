# CRM Assistant: adding a CRM section

The CRM Assistant (`/crm/assistant`) is a pydantic-ai agent in `backend/app/crm/assistant/`. Version 1 covers **Leads**. Each CRM section is one group of tools in a registry. Adding a section therefore means adding tools; the agent, the chat, the stream and the frontend stay as they are.

## How it is built

| Piece | File | Role |
|---|---|---|
| Scope | `deps.py` | `AssistantDeps.from_auth(AuthContext, db)` is the only constructor. Tools read `ctx.deps.organization_id` and `ctx.deps.user_id`. |
| Org checks | `scope.py` | `load_lead()` returns a lead only if it is in the caller's organisation (otherwise the same 404 as a missing id). `org_member()` does the same for members. |
| Tools | `tools/<section>.py` | Read tools return compact dicts. Write tools are `propose_*` and only store a pending action. |
| Registry | `tools/__init__.py` | `SECTION_TOOLS = {"leads": [...]}`. The agent registers every tool listed here. |
| Actions | `actions.py` | `create_pending_action()` (expires after 10 min). `confirm_action()` re-checks the user, the org, expiry and the record, then calls the section's **existing** service. |
| Agent | `agent.py` | System prompt and `SUPPORTED_SECTIONS`. |
| Chat | `service.py`, `router.py`, `models.py` | Own tables (`crm_assistant_*`), SSE events `text-delta`, `tool-status`, `action-proposed`, `done`, `error`. |

## Adding a section (e.g. Deals)

1. **Tools.** Create `tools/deals.py`.
   - Every tool takes `ctx: RunContext[AssistantDeps]` first and reads the scope from `ctx.deps`.
   - **Never add an `organization_id`, `user_id`, `organization` or `user` parameter.** A test fails if you do.
   - Add a `load_deal(db, organization_id, deal_id)` to `scope.py` that 404s for other organisations, exactly like `load_lead`.
   - Wrap outside text (emails, notes) in `<lead_data>…</lead_data>`, or in a new tag that the prompt names.
   - Do not return phone numbers or emails to the model.
2. **Registry.** Add `"deals": [...]` to `SECTION_TOOLS`.
3. **Changes.** Each change is a `propose_*` tool that calls `create_pending_action(action_type="deal_stage", ...)`. In `confirm_action`, add a branch that loads the deal with the org check and calls the **existing** Deals service function. That way validation, history entries and side effects match the normal UI.
4. **Prompt.** Add the section to `SUPPORTED_SECTIONS` in `agent.py` and take it out of the "coming soon" list.
5. **Tests.** Copy the patterns in `tests/unit/crm_assistant/`:
   - another org's id gives the same result as a missing id;
   - propose doesn't change anything;
   - confirm by another user or org gets 404;
   - an expired action gets 410;
   - a second confirm gets 409.

   `tests/agents/test_crm_assistant_agent.py` already covers new tools for scope parameters and registration.
6. **Frontend.** No change is needed unless the section wants new labels on the card (`LABELS` in `frontend/src/lib/crm/assistant/components/ActionCard.svelte`). Confirm calls `refreshCrm()`, which refreshes every CRM query.
