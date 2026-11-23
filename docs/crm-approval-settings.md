# CRM approval settings

Source: team call, 19 Nov 2026 (Kian, Pankaj, Ashwin).

## Problem

Agencies disagree on what an agent may do without a manager's say-so. We should not hard-code it.
The manager (or administrator) decides, in Settings, which agent actions need approval. Those
actions then go to the manager's approval inbox instead of happening straight away.

## Requirements

1. **Settings › Approvals** has one switch for each gateable action, grouped by area:
   - **Leads:** stage moves, written as from → to pairs (for example Viewing → Offer). A manager
     can add several pairs. "Any stage" is allowed as the from side.
   - **Deals:** entering a chosen step. This includes opening the deal, which is the step "Offer
     accepted" ("offer received → offer accepted", Kian) and closing as Won.
   - **Owner imports:** whether an agent's owner file waits for approval. Today it always waits,
     so the default stays on.
2. A manager sets the rules for the teams they supervise. An administrator sets the organization
   default and can set any team's rules. A team with no rules of its own uses the organization
   default.
3. When a rule applies, the agent's action is not carried out. The agent can send it for
   approval, with an optional note. It then waits in the approval inbox of whoever may decide.
4. The decider approves or denies it, with an optional note. Approving carries out the original
   action. If the lead or deal changed in the meantime, the request becomes stale and nothing
   happens.
5. Managers and administrators acting on leads or deals they supervise never need approval.
6. The agent sees that a request is pending on the lead or deal, and can withdraw it.

## Later, not in this build

- **Listings** (publish, create, edit, price change). Listings are read-only today, since they
  sync from the portal source, so there is no agent action to gate yet.
- **Per-agent exceptions:** trusted agents skip a rule.
- **Required document:** a move is blocked until a given document is uploaded.
- **Lead response reminders and auto-reassign** after N unanswered reminders. This is a separate
  routing feature with its own plan.
- **Email or push notification** of new requests. This build has the inbox and the sidebar
  count only.
