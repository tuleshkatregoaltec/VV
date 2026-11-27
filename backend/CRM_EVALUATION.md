# CRM Assistant evaluation

30 selected cases in `scripts/evaluations/crm_assistant/crm_benchmark.json` (schema version 2),
written against one synthetic agency and checked in four separate layers. This is a smaller,
representative evaluation set, not exhaustive coverage of every CRM action. Market AI has its own
benchmark and runner ([EVALUATION.md](EVALUATION.md)); neither scores the other's questions.

| Layer | What it proves | Needs | Command | Status |
| --- | --- | --- | --- | --- |
| 1. Offline fixture checks | The cases are valid and grounded: real tools, resources, action kinds and statuses; no Market AI tool reachable; every write needs confirmation; the input guard refuses exactly the guarded questions; scoring and reporting are correct; live runs refuse without opt-in. | Nothing (dummy settings) | `just crm-eval-offline` | Executable, in `just test-backend` and CI |
| 2. CRM database integration | Each case's expected outcome is what the CRM actually does, as that role: visibility, counts, refusals, nothing written before confirmation, persisted state after confirmation or cancellation, stale proposals. | Local PostgreSQL | `TEST_POSTGRES_URL=… just crm-eval-db` | Executable; not in CI |
| 3. Live-model evaluation (optional) | A real model, through the production chat turn, picks the right workflow and CRM tools, proposes only allowed writes and never claims them done. | Local PostgreSQL, paid model calls, two opt-ins | `just crm-eval-live --cases … --live` | Built and plumbing-tested with scripted models; **never run** |
| 4. Answer quality review | Whether the wording is helpful, accurate and well-attributed. | People (or a versioned judge) | Review `answers_for_review.json` from a live run | Process only; nothing automated |

Layers 1–3 are deterministic about permissions, tools and writes. Layer 3 also runs simple
text checks (expected facts present, forbidden claims absent, a question asked when clarifying);
they are reported separately and never override a deterministic result. A judge model must
never be the only check on permissions or writes.

## The synthetic fixture

`crm_fixture.py` defines everything a case refers to. All of it is invented: names, phones
(`+97150000…`), addresses (`@example.test`). No real CRM record is read, copied or exported.

- **Palm Crescent Realty** (the actors): Olivia Grant (owner); Nadia Rahman manages *Marina
  Sales* (agents Omar Siddiqui, Sara Khan); Karim Haddad manages *JVC Sales* (agents Lina Costa,
  Sara Malik); Hugo Brandt (agent in no team); empty teams *Downtown* and *Marina Luxury*.
  25 leads across every CRM stage, shared pools, unpooled and teamless leads, a shared
  "recently sold" signal, two leads named Bilal Hameed, five deals (open/won/lost), calendar
  events, reminders, a viewing, a listing draft, notes (one holding a prompt injection),
  activities and a two-message email thread.
- **Harbour Point Properties**: a second tenant with its own *Marina Sales* team and a lead
  sharing a contact name with one of Palm Crescent's, to prove nothing crosses organizations.

"Today" is fixed at 2026-12-01 (`reference_date`). Every seed creates fresh organizations and
user IDs, so cases never share state.

## What a case defines

```jsonc
{
  "id": "crm095", "category": "action", "role": "manager", "actor": "nadia",
  "question": "Assign Aaliyah Brooks to Sara.",
  "expect": {                     // checked against a model run (layer 3)
    "outcome": "answer",          // answer | clarify | refuse | unsupported
    "workflows": ["action"],      // allowed coordinator workflows
    "tools": ["query_my_crm_records", "find_assignment_colleagues", "propose_crm_action"],
    "write": "proposal",          // none | proposal | refused
    "action_kind": "assign_lead",
    "confirmation_required": true,
    "answer_facts": ["Sara Khan"],
    "forbidden_claims": ["has been assigned", "successfully"]
  },
  "probe": {                      // run against the real CRM (layer 2)
    "type": "action",
    "lookups": [{"tool": "find_assignment_colleagues", "search": "Sara"}],
    "kind": "assign_lead",
    "payload": {"lead_id": "@lead:L01", "assignee_id": "@person:sara"},
    "proposal": "created", "decision": "confirm", "final_status": "succeeded",
    "state": [{"subject": "lead:L01", "field": "assigned_to", "before": "omar", "after": "sara"}]
  }
}
```

Probe types: `read` (query_my_crm_records: totals, counts by status/team/handler, the exact
rows, paging, records that must stay out), `calendar`, `lead_emails`, `lookup` (the four
colleague/team lookups), `action` (lookups, proposal, optional changes by someone else,
confirm or cancel, state before/after), `pending` (a request held between turns is rechecked),
`input_guard` (refused before any model call) and `none` (nothing in the CRM to probe, with
the reason). A state check's `before` must hold before the proposal and still after it;
leaving out `after` means "unchanged".

## How the 30 selected cases map to the CRM

| Category | Cases | Covers |
| --- | --- | --- |
| lead_read | 5 | Owner, manager and agent reads, including status/counts, pagination and contact details |
| deal_read | 2 | Owner and agent deal reads |
| team_read | 3 | Team roster, manager workload and an agent's team membership |
| followup | 2 | Agent follow-up planning and manager follow-up lookup |
| calendar | 3 | Calendar read, meeting booking and event cancellation |
| action | 6 | Lead assignment/status/note, reminder, viewing and lead creation proposals |
| team_action | 2 | Team creation and agent transfer |
| permission | 2 | Agent and manager permission boundaries |
| tenant_isolation | 1 | Cross-organization lead lookup |
| clarification | 1 | Ambiguous assignment lookup |
| stale_context | 1 | Lead state changes before confirmation |
| unsupported | 1 | Market research refused by the CRM Assistant |
| security | 1 | Prompt/schema disclosure refusal |

Roles: 11 owner, 5 manager, 14 agent cases. The selected cases exercise 10 action kinds; the
offline registry checks still verify all supported action kinds and block Market AI tools from
the CRM Assistant. One unsupported market question has no CRM probe and is reported as not
applicable in layer 2, never as passed.

## Running it

From the repository root.

**Layer 1** — no services:

```sh
just crm-ai-benchmark        # validate and print coverage counts and the dataset SHA-256
just crm-eval-offline        # 27 tests
```

**Layer 2** — needs a PostgreSQL on localhost that you may create databases on. The test
creates `vv_migration_test_<random>`, applies every migration, seeds a fresh fixture per case
and drops the database at the end; it never reads existing databases. If port 5432 is free,
`docker compose -f docker-compose.dev.yml up -d postgres` works; otherwise run the same service
on another loopback port:

```sh
docker compose -f docker-compose.dev.yml run -d --rm --name crm-eval-postgres \
  -p 127.0.0.1:55433:5432 postgres
TEST_POSTGRES_URL=postgresql+asyncpg://vitevue:vitevue_dev@127.0.0.1:55433/vitevue \
  just crm-eval-db
docker stop crm-eval-postgres
```

It runs the 29 CRM probes, checks that the market question is listed as not applicable, runs
focused deliberately-wrong-expectation checks for the probe types represented in this sample,
and exercises the live runner with scripted models. Failures name the case and its failing
checks.

**Layer 3** — optional, paid. Preview first (no calls):

```sh
just crm-eval-live --cases crm001,crm095,crm185
```

Then, only when you intend to pay for model calls:

```sh
CRM_EVAL_ALLOW_MODEL_CALLS=1 \
CRM_EVAL_POSTGRES_URL=postgresql+asyncpg://vitevue:vitevue_dev@127.0.0.1:55433/vitevue \
  just crm-eval-live --cases crm001,crm095,crm185 --live [--save-answers]
```

`--all` runs all 30 selected cases (30 turns). Evidence goes to `.evaluation/crm_assistant/<UTC time>/`
(git-ignored, owner-only files): `summary.json` and `results.json` hold case IDs, check names,
tool names, proposal kinds and statuses; `answers_for_review.json` (only with
`--save-answers`) holds the answers for layer 4.

## Safety boundaries

- **Synthetic data only.** Cases and fixture are invented. The lead mailbox is replaced by the
  fixture's in-memory thread; the evaluation never reads `app/crm/crm_email_store.json`.
- **Local disposable databases only.** Layer 2 requires an explicit loopback `TEST_POSTGRES_URL`
  and runs with the dummy `tests/evaluation/offline.env`; it fails if the application's own
  `POSTGRES_URL` is not loopback either, so no unpatched code path can reach a shared database.
  Layer 3 refuses to start unless both its database and the application's are loopback.
  `Settings` reads `../.env.dev` for any unset variable, which is why these recipes set the
  database URLs explicitly; `.env.dev`'s `POSTGRES_URL` is a shared LAN host and is never used.
- **No external side effects.** Brevo and Google Calendar report themselves unconfigured, member
  names come from the fixture, and every outbound HTTP request fails unless its host is allowed:
  none in layers 1–2; only `openrouter.ai` in an opted-in layer 3 run. Emails, WhatsApp
  messages, publications and Google bookings end as `not_connected` outbox rows; CRM calendar
  writes stay in the disposable database. Nobody is invited.
- **Paid calls need two opt-ins** (`--live` and `CRM_EVAL_ALLOW_MODEL_CALLS=1`).
- **Writes only after confirmation**, and the evaluation proves it: state is read before the
  proposal, after it, and after the decision. Layer 3 never confirms; that is the user's act.
- **Safe evidence.** Results carry case IDs, check names, counts, statuses and exception types,
  never record contents, prompts or tool results. Answer text is stored only on request.

## Limitations

- Layer 3 has not been run; there is no model-quality result yet. Its runner is tested end to
  end only with scripted models.
- With typed routing enabled (`ASSISTANT_TYPED_ROUTING_ENABLED`), the turn reports no workflow
  tool names, so the `workflows` check can only fail on specialist tools outside the case's
  workflows.
- Text checks are substring heuristics: fine for spotting a missing name or a forbidden claim,
  not for judging quality. Layer 4 has no tooling beyond the saved answers.
- Single-turn cases. Multi-turn behaviour is covered by held-request (`pending`) probes and by
  the existing chat-turn tests in `tests/integration/postgres/test_assistant_*.py`.
- Layer 2 is not in CI (no PostgreSQL service there yet). `just test-backend-postgres` sources
  `.env.dev`, so this module fails there by design with a pointer to `just crm-eval-db`.
- Renewals, owner properties, workspaces and saved leads (imports and Vitevue lease data) have
  no fixture data and no cases yet.

## Changing the cases

Edit `crm_benchmark.json`, then run layers 1 and 2. `crm_dataset.py` lists the CRM tools,
Market AI tools, resources and action kinds the cases may use; layer 1 fails if those drift
from the code, so update them together with the assistant. A changed expectation must be
confirmed by layer 2 against the real CRM, not edited until it passes: if layer 2 disagrees,
first decide whether the CRM or the case is wrong.
