# WhatsApp automation

## Property enquiries on Kian’s number

This customer channel is separate from the private test-number assistant below.
It accepts unknown numbers: no saved contact, prior CRM record or manual lead
approval is required. An incoming message must clearly concern property brokerage.

The selected policy supersedes the earlier 30-second review timer:

```text
Signed inbound message → scoped durable receipt → classify topic and risk
  personal / mixed / ambiguous → no reply; message body removed
  routine property enquiry → fixed question or approved fact → send when ready
  sensitive enquiry / missing verified inventory → pause conversation + owner inbox
```

Routine replies have no review countdown. They still take model, worker and network
time. A sender’s accepted property conversation provides up to three recent exchanges
within 24 hours for short answers such as “Rent” or “AED 120,000 per year”. An ignored
or failed message breaks that context. A bare greeting or budget without relevant
context does not become permission to automate a personal conversation.

### Try this conversation

Send **looking for a two bedroom apartment in Marina** to **+971 50 127 9179**.
The expected flow is:

1. “Are you looking to buy or rent?” — reply **Rent**.
2. “What budget do you have in mind, and in which currency?” — reply **AED 120,000 per year**.
3. “When are you looking to move?” — reply **Next month**.
4. With no approved available listings, the conversation pauses and Kian gets a
   pending item in the Vitevue WhatsApp inbox. No unsupported property is offered.

The actual configured model passed this sequence in a synthetic dry-run on
3 November 2026. “Hi Kian” and “Dinner tonight?” returned no reply; a discount request
required approval. That is model-path evidence, not confirmation of phone delivery.

### Kian’s controls

Open **/dashboard/whatsapp** in the pilot site with the configured connection owner’s
existing account. The sidebar has a WhatsApp link. The page shows property conversations,
an approval inbox, drafts and API acceptance status. Personal-only contacts are not
shown as property leads. Access is exact connection-user plus organization scope;
being a colleague in the same organization does not grant access.

- **Automatic replies on/off** controls the entire connected number.
- **Take over conversation** pauses that conversation and cancels unsent replies.
- **Approve reply** sends that exact revision once; automation stays paused.
- **Save draft** edits a pending response and requires another explicit approval.
- **Resume automation** explicitly returns the conversation to routine automation.
- **Cancel draft** prevents that unsent response from being sent.

Sensitive questions, negotiations, bookings, payments and commitments pause the
conversation automatically. Ordinary follow-ups while paused do not erase the pending
review or restart automation. Read them and respond in WhatsApp. Customer `STOP`
opts out; `HUMAN` pauses; `START` clears opt-out but does not undo human takeover.
A human approval never bypasses opt-out, disabled connection, expired service window,
or revoked user/subscription access.

The page polls while open. This is **not a mobile push notification**. Automatic
detection of Kian’s replies from the WhatsApp Business phone app is not implemented;
use **Take over conversation before replying manually**. Continued phone-app use
also depends on the number’s actual Meta coexistence setup, which has not been
verified by this change.

### What the customer agent can access

The customer agent has no tools and cannot access the private chat agent or private
CRM. It reads only owner-approved property facts/FAQs stored on the connection in
PostgreSQL. It selects fact IDs; the server copies those facts verbatim or renders a
fixed qualification question. It never invents a property, availability, price or
appointment. Without approved inventory, this version qualifies and hands off leads;
it does not search live listings or run arbitrary database queries for customers.

Customer replies use ordinary business language without an unsolicited AI introduction.
They do not claim Kian personally took an action or completed a viewing/booking.
Classification remains probabilistic: tests and the live dry-run do not guarantee
perfect interpretation of every language or personal conversation.

### Runtime and safety

`WHATSAPP_CUSTOMER_AUTOMATION_ENABLED` and the persisted connection must both be enabled.
Number/account/token and owner binding stay server-side in private `.env.dev`.
`WHATSAPP_CUSTOMER_TEST_RECIPIENT` is an optional test-only sender restriction. Remove
it to admit unknown senders; the topic/risk policy still gates every reply. Private
self-assistant sender restrictions remain unchanged.

The worker persists receipts before acknowledging Meta, deduplicates webhook retries,
checks the 24-hour service window and rechecks access before sending. Routine drafts
use `auto_pending` with a due time of now. Approval-only drafts never time out into a
send. Existing `grace_pending` records remain readable for rolling compatibility.
Connection → thread → message locks serialize send/approve/cancel decisions. Once
`sending` commits, a cancellation cannot retract a network request. Ambiguous send
outcomes are never automatically retried. `accepted` means Meta accepted the request,
not that the recipient received or read it.

Ordinary receipts are limited to 20 per sender per connection per UTC day, so one
contact does not consume every other lead’s allowance. STOP/HUMAN controls bypass
that cap. Model turns additionally use the existing shared durable user/tenant quotas.
An empty technical chat conversation scopes budgets, without copying customer text
into the private web chat.

Personal/uncertain messages can reach the webhook, be temporarily stored and be
classified before their bodies are erased. Meta does not pre-filter the account to
property messages. Property history remains in PostgreSQL. This is a one-number pilot,
not customer-wide Embedded Signup onboarding. Keep the WSL computer, Docker and
internet running; always-on production hosting and retention remain separate work.

### API

Every endpoint under `/api/v1/whatsapp` requires an authenticated active subscription
and exact connection owner/user plus organization scope. Credentials are never exposed.

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /connections` | List/create the configured connection |
| `PATCH /connections/{id}` | Enable/disable or rename |
| `PUT /connections/{id}/knowledge` | Replace approved facts (20 unique facts, max 1,000 chars each) |
| `GET /connections/{id}/threads` | Property conversations only |
| `GET /threads/{id}/messages` | Conversation history, with ignored bodies redacted |
| `GET /notifications` | Actionable review/failure notifications |
| `POST /notifications/{message_id}/seen` | Record seen; never approves |
| `POST /messages/{message_id}/approve` | Approve one expected revision |
| `POST /messages/{message_id}/cancel` | Cancel one unsent expected revision |
| `PATCH /messages/{message_id}` | Edit and require review |
| `POST /threads/{id}/takeover` | Pause and cancel unsent replies |
| `POST /threads/{id}/resume` | Resume unless opted out |

Decisions require `expected_revision`; edits also require `reply`. Stale revisions
return 409. Browser helpers follow paginated lists. No schema migration is needed
for the selective policy; existing migration `31c7e90b42ad` provides its tables.

## Verification and current pilot state — 3 November 2026

- Customer automation and the persisted connection are enabled; the customer-only
  test-recipient restriction was removed. The private self-assistant stays restricted.
- Published to `https://vv-pilot.pages.dev/dashboard/whatsapp`, release
  `https://aa02cafc.vv-pilot.pages.dev`.
- Real authenticated browser smoke: page and approval inbox visible, automation on,
  no WhatsApp API errors. Public webhook verification and signed empty receipt both
  return 200; unauthenticated owner API returns 401.
- Backend full suite: 1,883 passed. Customer PostgreSQL integration: 42 passed.
  Frontend suite: 391 passed. Mocked browser review/handoff flow: 3 passed.
  Backend/frontend lint, Svelte diagnostics and pilot production build passed.
- Crew: GPT-6-Luna scout; GPT-6.1-Sol policy and UI builders; fresh GPT-6.1-Sol
  read-only verifier. Final independent verdict passed. No model fallback was used;
  the UI builder resumed after a transient capacity error.
- The actual configured model passed seven synthetic checks (qualification sequence,
  greeting/personal silence, negotiation handoff) without sending any WhatsApp message.
  Real phone receipt/reply for this customer flow remains the user’s next test.

## Private self-assistant demo (separate Meta test number)


1. On the already configured phone ending **8092**, open the conversation with
   Meta's test number **+1 (555) 210-1068**.
2. Send: **What dates does your Dubai sales data cover? Query the database.**
3. Vitevue receives the signed message, saves it, runs the existing chat agent and
   its authorized database tools, and replies on WhatsApp.
4. Sign into https://vv-pilot.pages.dev/dashboard/chat with the existing pilot
   account. Select **WhatsApp pilot** to see the same question and full answer.
   WhatsApp answers longer than 4,000 characters are shortened; the complete chat
   answer remains available in Vitevue.

This exact flow passed on 3 November 2026: receipt persisted, existing chat agent
called ClickHouse, Graph API accepted the reply, and the user confirmed phone
delivery. Meta app **Vitevue** is subscribed to the supplied messaging account;
callback verification alone had not established that account subscription.

The CRM presentation assistant remains its separate fictional demonstration. This
integration reuses the real web chat service, not those fictional CRM fixtures.

## Scope and permissions

Only the configured recipient is bound to the existing pilot user and organization.
This is an agent asking their own assistant questions. It must not be opened to
arbitrary buyers using that user's private CRM permissions. Unknown senders,
other business-number IDs, unsupported message types, echo events and expired
messages cannot start chat turns. The existing input refusal rules also apply.

Organization membership and subscription are rechecked before generation and
before sending, with the same chat authorization, evidence checks, tool limits,
daily token reservations and quota settlement as browser chat. A default maximum
of 20 incoming turns per UTC day additionally bounds this pilot. Excess turns are
ignored. Proposals can appear in the answer but must be confirmed in Vitevue;
WhatsApp does not confirm mutations. A deleted/reassigned account must have its
binding removed; offboarding/rebinding beyond this one-number pilot is future work.

## Running and pausing

Keep this computer awake with Docker Desktop, WSL and internet running. The existing
recovery script starts the API, tunnel and worker when automation is enabled:

```sh
bash /home/maan3/vv/VV-git/handoff/deploy/local/start-pilot.sh
just whatsapp-demo status
```

Private `.env.dev` configuration adds:

```dotenv
WHATSAPP_AUTOMATION_ENABLED=true
WHATSAPP_PILOT_USER_ID=<already bound locally>
WHATSAPP_PILOT_ORGANIZATION_ID=<already bound locally>
WHATSAPP_MAX_DAILY_TURNS=20
```

Keep all Meta credentials server-side. The exposed temporary token and App Secret
should be rotated, entered locally and loaded by restarting both API and worker.
Do not paste replacements into chat. These host processes load settings at startup.

To pause immediately, stop the identified `scripts.whatsapp_worker` process.
Set `WHATSAPP_AUTOMATION_ENABLED=false`, restart the API and keep the worker stopped
to stop new queueing as well. Do not run `just down`: it removes local volumes.
The queued backlog is durable; restarting with automation enabled can resume it.

## Persistence and failure behavior

`whatsapp_turns` stores the allowed sender's inbound ID, bound identity, message,
reply, conversation reference and processing state. Receipt commits before the
webhook responds. The worker runs outside the HTTP request. Database uniqueness
deduplicates Meta retries; transactional claims prevent parallel processing of the
same pilot queue. The additive migration is `0a9c3d7e1f62`.

Incoming message time gates ordinary replies to the 24-hour service window. The
worker checks the window again immediately before sending. It never retries a send
automatically: a lost response might mean Meta already accepted the reply. Worker
loss/ambiguous sends become `unknown`, requiring operator review. Chat failures
become `failed`; revoked access becomes `revoked`. `accepted` records API acceptance,
not confirmed delivery/read status. Delivery-event reconciliation is not implemented.

Logs are private and contain execution/status metadata rather than message bodies:

```text
handoff/deploy/local/backend.log
handoff/deploy/local/whatsapp-worker.log
```

Messages, answers and existing chat history now contain business data in the local
database. No automatic purge is implemented for this pilot ledger. Agree retention,
deletion, backups and approved AI subprocessors before customer rollout; deleting a
web conversation does not delete the independent WhatsApp ledger. Production needs
an always-on deployment, monitored worker recovery and the customer-onboarding and
visibility controls, not an assumption that a laptop tunnel provides availability.

## Checks

Targeted API/unit, existing chat streaming and architecture tests cover signatures,
sender isolation, chat context, access revocation, service-window expiry and incomplete
answers. Real PostgreSQL tests cover migration replay, deduplication, daily caps,
worker claims and uncertain-send handling. Schema contract checks register the new
table. Third-party callbacks do not change the browser OpenAPI contract.

## Qualification-reference fix — 3 November 2026

The first customer phone test reached the webhook in approximately two seconds but
was discarded after generation. A synthetic reproduction with the configured generic
brokerage fact showed the drafter choosing a valid fixed qualification question while
including an unnecessary fact ID. The old renderer rejected that combination. Fixed
clarifications/handoffs now discard unused evidence IDs; factual responses still
require unique approved evidence. Added payload-free failure diagnostics and six
regression cases. Focused policy/agent/runtime tests: 131 passed; backend lint passed.
The synthetic live regression produced the expected question in 3.25 seconds, without
retransmitting the customer’s message. Worker restarted; a fresh phone message is
required because the original ignored body was erased.

## Live sending blocker — 3 November 2026

The fresh phone test reached the backend in 2.39 seconds and generated the correct
qualification reply. Meta rejected the outbound request with HTTP400/code10. A
controlled diagnostic of that definite rejection returned: “You do not have WhatsApp
granular permission for sending messages on behalf of this WhatsApp Business Account.”
The token checked at that time was valid and listed whatsapp_business_messaging and
management scopes. Empty granular target IDs do not establish missing asset access.
The account review is APPROVED and business verification is verified. Generating the
reply is fixed; Meta's sending rejection remains unresolved. Do not claim phone
delivery passed. No unknown/ambiguous send is automatically retried.

The worker now records numeric Meta codes without upstream payloads, distinguishes
definite4xx rejection from unknown delivery, and preserves admitted property drafts
for human handling. Personal classification failures remain redacted. Latest targeted
unit tests89 and PostgreSQL customer tests43 passed, plus backend lint.

## Routine reply latency — 4 November 2026 (Asia/Calcutta)

Routine search qualification now selects a fixed next question during the existing
topic/risk classification, avoiding a second model request. Factual answers still
use the approved-fact drafter. Topic confidence, short-answer context, sensitive-text,
human request and quota checks precede the shortcut. Customer idle polling changed
from2s to0.5s; private-assistant polling and infrastructure-error backoff remain2s.

Three sequential synthetic nameless enquiries with the generic brokerage fact
measured2.774s median before and1.545s after (44% lower). This measures the guarded
model path only, not webhook transit or Meta delivery; it is a small sample, not a
latency SLA. The synthetic buy/rent→budget→timeframe→human flow and greeting/personal
silence also passed. Tests:143 focused unit tests and43 PostgreSQL customer tests;
backend lint passed. Idle worker restarted. No customer message retransmitted and
no WhatsApp message sent during these benchmarks. The previously confirmed Meta
account-specific sending permission blocker remains unresolved.

## Token replacement and permission correction — 4 November 2026 (Asia/Calcutta)

The owner's Meta screenshot confirms that the system user has Messages (send and
respond) enabled on Kian's actual WhatsApp number. WhatsApp accounts and Messaging
accounts appear separately in that UI. The earlier interpretation of template-only
tasks on the Messaging account as proof of missing phone messaging access was wrong.

The configured customer token was subsequently invalid. With explicit owner approval,
the valid replacement was saved privately and the API and worker restarted. Both
running processes were verified to load that replacement; local and public API health
checks returned HTTP 200. One authorized retry of the existing, definitely rejected
test draft returned Meta code 10 again in 1.01 seconds, with no outbound message ID.
The replacement fixes the stale local credential but does not resolve Meta's sending
denial. Do not infer that broader asset permissions or token regeneration will fix it
without further evidence. No successful customer reply delivery is established.

A subsequent freshly generated system-user token was validated for the Vitevue app,
both WhatsApp scopes, and the correct phone number, then installed at the owner's
explicit request. Both restarted processes loaded it and both health checks passed.
One controlled retry still returned HTTP 400 / code 10 in 1.07 seconds, with the same
granular sending-permission message, no subcode or additional details, and no outbound
message ID. Meta trace ID: `AQemjtdBV73HfP0U7bm0OVw`. Fresh token generation did not
resolve the rejection; further identical retries are not useful without new evidence.

## Assistant models and customer evidence — 4 November 2026

In-app chat, the internal WhatsApp pilot, and customer classification/drafting now use
assistant-specific model settings. They never fall back to `DEFAULT_CHAT_MODEL`.
Gemini and Qwen3.8 Max model IDs are rejected. `ASSISTANT_ENABLED` defaults to false
until model qualification; `ASSISTANT_TYPED_ROUTING_ENABLED` separately controls the
new in-app routing path. These settings do not change feasibility or import models.
See `backend/.env.example` and `backend/EVALUATION.md` for role settings and the
cumulative USD 10 local model-selection campaign.

The WhatsApp page now contains **Customer information** controls for each owned
connection. The broker can explicitly permit customer market summaries and publish
customer-facing listings. This permission defaults off and must be consistent with
the broker's dataset-sharing rights. It does not grant access to private CRM data.

Listing publication requires a title, location, property type, sale/rent transaction,
asking price (annual rent for rentals), availability, explicit approval and an expiry
within 30 days. Bedrooms and square-foot size are optional. These are manually
approved customer snapshots, not pointers into private contacts or owner records.
Editing/renewing and revoking require the reviewed revision; concurrent changes return
409 rather than silently overwriting approval. Revoked/expired snapshots are excluded
from retrieval and selected evidence is rechecked immediately before sending. A price
or availability change requires another approved publication update.

Customer market retrieval exposes only count and median sale price/annual rent for a
city/community and the previous month or quarter. Groups below ten records are
suppressed. Replies retain source, coverage and freshness limitations; release IDs
remain internal. Market evidence expires after 15 minutes and is rejected if the
connection's permission is revoked before sending. The model selects a typed lookup;
the application controls query scope and renders the exact returned facts.

Publications and permitted market results do not override opt-out, human takeover,
subscription/access checks, sensitive-request approval, the messaging window, or
uncertain-send protection. Existing broker-approved knowledge remains supported.
No new WhatsApp message was sent to validate this implementation; the previously
documented Meta delivery-permission issue requires separate verification.
