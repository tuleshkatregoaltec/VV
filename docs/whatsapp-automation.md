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

Superseded on 6 November 2026 (see “Multi-agent Embedded Signup” below): inbound text
is no longer written anywhere before classification, and every connected agent number
is served, not only the env-configured one. Meta does not pre-filter the account to
property messages. Property history remains in PostgreSQL.

### API

Every endpoint under `/api/v1/whatsapp` requires an authenticated active subscription
and exact connection owner/user plus organization scope. Credentials are never exposed.

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /connections` | List/create the configured connection |
| `PATCH /connections/{id}` | Enable/disable or rename |
| `PUT /connections/{id}/knowledge` | Replace approved facts (20 unique facts, max 1,000 chars each) |
| `PUT /connections/{id}/voice` | Set or reset (`{"voice": null}`) the agent's reply voice; see “Reply style” |
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

## Multi-agent Embedded Signup (backend) — 6 November 2026

Any Vitevue agent can connect their own WhatsApp Business number with Meta Embedded
Signup in coexistence mode (they keep using the WhatsApp Business app on their phone).
Flow: connect → contacts sync arrives → agent blocks contacts → agent turns automation
on → property enquiries are answered from the agent's own number.

### Privacy model

- **Blocked contacts**: dropped in the webhook handler by phone number or business-scoped
  user ID before the message text is read. No thread, message or log row is written
  and nothing is queued. Blocking later also cancels unsent replies on that thread.
- **Unclassified text is never persisted.** The webhook writes a content-free receipt
  (`status = classifying`, `content = NULL`) for deduplication and the daily cap, commits,
  answers Meta, then classifies in an in-process task that holds the text in memory only.
  Text is written to `whatsapp_customer_messages.content` only once the classifier admits
  it as a property enquiry and a reply is drafted. Personal/uncertain text ends as
  `ignored` with no content. Nothing goes through Redis (the server's Redis uses AOF).
- If the API process dies mid-classification the text is lost by design; the worker marks
  the receipt `failed (worker_lost)` after ten minutes.
- Agent replies typed in the phone app (`smb_message_echoes`) only pause a thread that
  already has a property enquiry and cancel its unsent draft. Echo text is never read or
  stored and no thread is created for personal chats. Message history sync is never
  requested. Group messages are ignored.

### Routing and sending

Each webhook change is routed to the connection whose `account_id` (WABA ID, the entry
`id`) **and** `phone_number_id` both match and whose `status = connected`. Spoofed or
unknown pairs are dropped. Each agent's business token is stored Fernet-encrypted in
`whatsapp_connections.access_token_encrypted` and decrypted only to send. The worker
(`scripts.whatsapp_worker`) now only delivers due replies for every agent and recovers
lost receipts; classification runs in the API process
(`WHATSAPP_CLASSIFIER_CONCURRENCY`, default 4 per process).

`account_update` `PARTNER_REMOVED` / `ACCOUNT_OFFBOARDED` disconnects the agent: automation
off, unsent replies cancelled, token and synced contacts deleted.

### Environment

| Variable | Purpose |
| --- | --- |
| `WHATSAPP_TOKEN_ENCRYPTION_KEY` | Fernet key(s), comma-separated; first encrypts, all decrypt. **Required outside `ENVIRONMENT=local`**; without it tokens cannot be stored or read and sending fails closed. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `WHATSAPP_APP_ID` | Meta app ID (public; returned to the browser for `FB.init`). |
| `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` | Facebook Login for Business configuration ID (public). Absent → signup reports `not_configured`. |
| `WHATSAPP_CLASSIFIER_CONCURRENCY` | In-process classifier concurrency (default 4). |
| `WHATSAPP_HUMAN_TIMING_ENABLED` | Read receipt, typing indicator, human-paced delays and two-text splitting for automatic replies (default `true`). |

Existing: `WHATSAPP_APP_SECRET` (signature checks and code exchange),
`WHATSAPP_GRAPH_API_VERSION`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_CUSTOMER_AUTOMATION_ENABLED`
(global kill switch). `WHATSAPP_CUSTOMER_PHONE_NUMBER_ID/ACCOUNT_ID/ACCESS_TOKEN` and
`WHATSAPP_PILOT_USER_ID/ORGANIZATION_ID` are now only used to migrate the env pilot.

### Env pilot migration (Kian's number)

Migration `7a1d3c5e9b20` marks existing connections `onboarding_type = env`. On API and
worker start-up, `bootstrap_env_connection` encrypts `WHATSAPP_CUSTOMER_ACCESS_TOKEN` into
the row matching `WHATSAPP_CUSTOMER_PHONE_NUMBER_ID` (same user, organization and WABA),
keeping its `enabled` state, or creates the row with automation off. It re-encrypts if the
env token changes, never revives a disconnected row and never takes a number owned by
someone else. On the server: set `WHATSAPP_TOKEN_ENCRYPTION_KEY`, run
`alembic upgrade head`, restart API and worker. `WHATSAPP_CUSTOMER_TEST_RECIPIENT`, if set,
still restricts only the env pilot number.

### Agent API (`/api/v1/whatsapp`, active subscription; identity from the session)

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /signup/config` | — | `{configured, missing[], app_id, config_id, graph_api_version, extras, state}`; `state` is null when not configured |
| `POST /signup/complete` | `{state, code, phone_number_id, waba_id, business_id?, event}`; `event` is `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`, `FINISH` or `FINISH_ONLY_WABA` (rejected 422) | `AgentConnectionStatus` |
| `GET /connection` | — | `AgentConnectionStatus` |
| `PATCH /connection/automation` | `{enabled}` | `AgentConnectionStatus` |
| `POST /connection/disconnect` | — | `AgentConnectionStatus` (`state = disconnected`) |
| `GET /connection/contacts` | `search?` (name or digits), `blocked?`, `limit` 1–500 (50), `offset` | `{items[{id, wa_id, name, in_address_book, blocked, blocked_at, updated_at}], total, limit, offset}` |
| `PUT /connection/contacts/blocked` | `{contact_ids[], phone_numbers[], blocked}` (at least one list, ≤1000 each) | `{updated, blocked_total}` |
| `POST /connection/contacts/sync` | — | `AgentConnectionStatus`; retries the one-time contacts sync within 24 h if the automatic request failed |

`AgentConnectionStatus`: `state` (`not_configured`, `not_connected`, `connected`,
`disconnected`), `signup_configured`, `connection_id`, `phone_number_id`, `waba_id`,
`business_id`, `display_phone_number`, `display_name`, `onboarding_type`
(`coexistence`, `cloud_api`, `env`), `automation_enabled`, `connected_at`,
`disconnected_at`, `last_account_event`, `quality_rating`, `can_send_message`
(Meta health: `AVAILABLE`, `LIMITED`, `BLOCKED`), `health_errors[]`,
`payment_method_status` (always `unknown`: billing is on the agent's own WABA),
`contacts {total, blocked, sync_requested_at, synced_at}`.

Signup completion (code expires in ~30 s, so call it immediately from the SDK callback):
exchanges the code (`GET /oauth/access_token` with app ID/secret), checks that
`phone_number_id` is in `GET /{waba_id}/phone_numbers`, subscribes the app
(`POST /{waba_id}/subscribed_apps`), registers the number only for `FINISH` (Cloud API),
stores the encrypted token, then requests the contacts sync once
(`POST /{phone_number_id}/smb_app_data`, `sync_type = smb_app_state_sync`) and reads
`health_status`. Errors: 400 expired state, 403 number not in the shared WABA, 409 number
linked to another account or agent already connected, 502 Meta rejection, 503 not
configured. Automation starts **off** so the agent can block contacts first.

Errors elsewhere: 404 when the agent has no connected number; 409 when enabling without
a decryptable token.

### Admin

`GET /api/v1/admin/whatsapp/connections` (system admin): `{total, connected, automation_on,
items[{connection_id, user_id, user_email, organization_id, organization_name,
phone_number_id, display_phone_number, display_name, status, onboarding_type,
automation_enabled, contacts_total, contacts_blocked, contacts_synced_at, last_message_at,
connected_at, disconnected_at, can_send_message}]}`.

### Meta app settings needed

- App Dashboard → WhatsApp → Configuration → Webhooks: callback
  `https://api-pilot.vitevue.com/api/v1/webhooks/whatsapp`, verify token
  `WHATSAPP_VERIFY_TOKEN`; subscribe `messages`, `smb_app_state_sync`,
  `smb_message_echoes`, `account_update` (Meta lists `history` for coexistence too; we
  never request history, so subscribing to it is optional and its events are ignored).
- Facebook Login for Business → Configurations: create one with the **WhatsApp Embedded
  Signup** login variation (or the “WhatsApp Embedded Signup Configuration With 60
  Expiration Token” template), selecting only the WhatsApp assets/permissions needed;
  put its ID in `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`.
- Facebook Login for Business → Settings → Client OAuth settings: Client OAuth login,
  Web OAuth login, Enforce HTTPS, Embedded Browser OAuth Login, Strict Mode for redirect
  URIs and Login with the JavaScript SDK all on; add `vv-pilot.pages.dev` (and any other
  frontend domain) to Allowed domains and Valid OAuth redirect URIs.

### Not done

Delivery-status reconciliation, retention/purge of property history, senders identified
only by business-scoped user ID (no phone number) are not automated, and per-thread
ordering is guaranteed only within one API process.

## Reply style: sounding like the agent (backend) — 6 November 2026

Goal: an automatic reply reads as if the agent wrote it, without ever pretending to be a
person. Rules agreed with the product owner:

1. **Voice.** The drafter writes the message itself, short, in the buyer's language and
   register (English, Arabic, Hindi/Hinglish, Russian and others), with varied phrasing.
   No bot introduction, no "As an AI", no assistant boilerplate ("Thank you for reaching
   out", "How can I assist you today"), no lists, headings, bold, em dashes or emoji (one
   emoji at most if the agent's voice allows it).
2. **Never claim to be human, never deny being automated.** If a buyer sincerely asks
   whether they are talking to a bot, AI, machine or real person, in any language,
   the automation sends **no reply**. The thread is paused, the message is stored as an
   `approval_required` notification with `reply = null`, `reason = "identity_question"`
   and a `handoff_summary`, and the agent answers personally. Detection is a deliberately
   broad multilingual pattern set (`customer_voice.asks_if_automated`, applied before any
   model call) plus the classifier's `asks_if_automated` flag. It only fires inside a
   property conversation or alongside a property enquiry; otherwise the message is
   ignored and nothing is stored, like any other non-property text. A false positive
   costs a paused thread, never a reply.
3. **Sensitive topics are handed off with a summary.** Negotiation, offers, legal or
   financial questions, payments, viewings/scheduling, reservations, promises and
   requests for a person produce an `approval_required` draft: a brief true holding line
   ("let me check with the owner and come back to you") and `handoff_summary`, a one or two
   sentence note for the agent (what the buyer wants, any numbers they gave, why it was
   handed over). Nothing is sent until the agent approves or edits it. The same applies
   when the approved facts do not cover the question. Auto-sending holding lines is a
   possible later product decision; it is not enabled.
4. **Grounded.** The model may phrase facts naturally ("AED 2,450,000" as "2.45M") but
   every reply is screened by `customer_voice.reply_violations` before it is stored and again
   at the send boundary: references to being an AI/bot, claims of being human, assistant
   boilerplate, commitments ("booked", "confirmed", "I promise", "in 10 minutes"), numbers
   (including written numbers such as "three") that appear in neither the selected facts nor
   the buyer's own messages, URLs/emails not in the facts, and availability or sold
   claims the facts do not make. A reply that fails is never sent. A failed routine
   answer becomes a handoff draft; a failed qualification question or holding line is
   replaced by short fixed wording chosen from a few variants. Injection protection,
   the conservative property/personal classification and the 0.95 confidence floor are
   unchanged. The assistant stays on real-estate topics for this agent.

### Qualification questions

The drafter now words the buy/rent, budget and timeframe questions itself. The question
a reply asked is stored in `whatsapp_customer_messages.asked_detail` and passed back in
history as `asked`, so a bare "Rent" or "120k" is still recognised as the answer.

### Human timing

For an automatic reply, in order: wait a reading delay (4 to 20 s, longer for longer
messages, jittered), call Graph to mark the buyer's message read and show the typing
indicator, wait a typing delay (3 to 18 s, scaled to the reply length, jittered), then send.
A long reply the drafter wrote as two paragraphs goes out as at most two texts, the second
after a 1.5 to 5 s pause with a fresh indicator.

Typing indicator request (verified against Meta's Cloud API docs, 6 November 2026):

```
POST /{version}/{phone_number_id}/messages
{"messaging_product": "whatsapp", "status": "read",
 "message_id": "<inbound wamid>", "typing_indicator": {"type": "text"}}
```

Meta clears the indicator when we reply or after 25 seconds, so every delay is below 25 s.
The call is cosmetic: a failure is logged by class only and the reply is still sent.

Implementation: the waits are `send_after` timestamps, not sleeps. `draft` sets
`send_after` to the reading delay; the worker's first pass at that time sends the read and
typing indicator and sets `typing_started_at` and a new `send_after` (typing delay); a
second pass sends. The worker lane is free in between, so one agent's wait never delays
another agent's reply. Eligibility (agent still enabled, thread not paused or opted out,
24-hour window open, evidence still valid) is rechecked at the send pass, so an agent
who answers from the phone during the wait cancels the automatic reply. Delays are
skipped entirely when the 24-hour window would close within about four minutes.
Agent-approved and agent-edited replies are sent promptly and exactly as written.
`WHATSAPP_HUMAN_TIMING_ENABLED=false` disables all of this.

### Per-agent voice: `PUT /api/v1/whatsapp/connections/{id}/voice`

Request: `{"voice": VoiceProfile | null}`; `null` restores the default voice. Response:
`ConnectionResponse`, now with `reply_voice` (`VoiceProfile | null`).

| Field | Type | Meaning |
| --- | --- | --- |
| `agent_name` | string ≤ 80, optional | Name the agent goes by (defaults to the connection `display_name`) |
| `tone` | string ≤ 200, optional | Style description, e.g. "warm, brief, a bit playful" |
| `sign_off` | string ≤ 80, optional | Used now and then, never on every message |
| `languages` | ≤ 8 strings ≤ 30 | Languages the agent works in. Replies still mirror the buyer's language |
| `sample_messages` | ≤ 3 strings ≤ 300 | Messages the agent might send; the drafter imitates, never copies |
| `emoji` | `"none"` (default) or `"light"` | `light` allows at most one emoji |

Unknown fields are rejected (422), and fields that look like instructions ("ignore
previous instructions", and the like) are rejected so a voice cannot weaken the policy.
With nothing stored, the default is a friendly, brief, relaxed tone with no samples.
Stored as JSON in `whatsapp_connections.reply_voice`. Changing the voice affects new drafts only.

New nullable columns (migration `8b2e4f6a1c93`): `whatsapp_connections.reply_voice`,
`whatsapp_customer_messages.handoff_summary`, `asked_detail`, `typing_started_at`.
`CustomerMessageResponse` gains `handoff_summary` (redacted for ignored messages).
A notification may now have `reply = null` (identity question); `approve` returns 409
for it, and the agent can `PATCH` their own text or `cancel`.

### Webhook text and observability audit

Inbound message text exists only in the in-process classification job, and in PostgreSQL
once a message is admitted as a property enquiry. Where it could have leaked, and what
holds now:

| Path | Status |
| --- | --- |
| Application logs | Every WhatsApp log line carries only the exception class or counts. No `exc_info` or `logger.exception`. Tests assert a sentinel buyer message never appears in captured logs when the classifier, drafter or background task fails. |
| SQL logs and exception messages | `hide_parameters=True` on the engine (existing), so statement values never reach `logs/sql.log` or `DBAPIError` text. |
| Uvicorn access log | Query string of the webhook path is stripped (existing `CallbackQueryFilter`). |
| Unhandled webhook exception → server error log and Honeybadger middleware | **Fixed.** Previously an unexpected error in `receive_customer` propagated, so the traceback with its exception message (which can echo SQL values or text) went to the log and to Honeybadger with the request's query string (`hub.verify_token`) and headers. The route now catches it, logs the class only, notifies Honeybadger with the class and a fixed message, and returns 500 (Meta retries; duplicates are ignored). |
| Honeybadger context for any webhook request | **Fixed.** `before_notify=scrub_notice` keeps only method and URL and replaces the exception with its class and a fixed message, dropping causes, headers, query string and body. |
| Logfire / OpenTelemetry | `logfire.configure(send_to_logfire=False)` with the allowlist exporter (existing). Both WhatsApp agents are created with `instrument=False`; a test pins it. |
| LLM provider | OpenRouter `zdr=true`, `data_collection=deny`, no fallbacks (existing). |

Not covered: provider-side retention outside ZDR, and the CRM/web-chat paths, which are
outside WhatsApp.

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
