# WhatsApp (Meta WhatsApp Cloud API): setup and activation

CRM › Connectors › WhatsApp. Each agent chats from their own registered number, so a customer sees
a separate chat per agent. Organization owners send promotions from one campaign number
(Connectors › WhatsApp › Campaigns) and answer replies in the Campaign inbox.

Code: `backend/app/crm/whatsapp/` (models, `meta.py` Graph client, `service.py` agent chats,
`campaigns.py`, router) and the frontend wrappers in `frontend/src/lib/crm/api/backend.ts`.

## Status

**Not live.** Everything below that needs Meta credentials, real numbers or a public URL has not
been tested against Meta. It is tested only against mocked Meta responses.

## Configuration

Set these in `.env.dev` locally and in the production secret store. Never put them in frontend code
or commit them.

| Variable | Secret | Where it comes from |
| --- | --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | yes | Meta Business Settings › Users › System users › create an admin system user, assign it the app and the WhatsApp account, generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`. Not the 24-hour token on API Setup. |
| `WHATSAPP_APP_SECRET` | yes | Meta for Developers › the app › App settings › Basic › App secret |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | yes | A long random string we choose (e.g. `openssl rand -hex 32`), entered again in the Meta webhook settings |
| `WHATSAPP_WABA_ID` | no | WhatsApp Manager, or the app's WhatsApp › API Setup page |
| `WHATSAPP_GRAPH_API_VERSION` | no | A Graph API version Meta currently supports, e.g. `v23.0` |

WhatsApp stays off (status `configured: false`, nothing sent) until the token, WABA ID and version
are set. The webhook rejects every request until the app secret is set.

Which agent uses which number lives in the database (`crm_whatsapp_numbers`), not in env vars, so a
number can be added without a redeploy. The Meta App ID is not needed by the backend.

## Activation steps (once access is granted)

1. Set the five variables above and restart the backend.
2. Apply the migrations: `just migrate` (revisions `b7d2e9f4a1c3` and `c4e1a8b7d2f9`: numbers,
   messages, opt-outs, campaigns, campaign recipients).
3. As an organization owner, list Meta's numbers to get their Phone Number IDs:
   `GET /api/v1/crm/whatsapp/meta/numbers`
4. Register each number:
   `PUT /api/v1/crm/whatsapp/numbers/{phone_number_id}`
   - agent: `{"display_number": "+971 50 000 0001", "label": "Vitevue · Sara", "purpose": "agent", "user_id": "<Sara's user id>"}`
   - campaign: `{"display_number": "+971 50 000 0003", "label": "Vitevue Properties", "purpose": "campaign"}`
5. In Meta for Developers › the app › WhatsApp › Configuration, set the callback URL to
   `https://{API_HOST}/api/v1/crm/whatsapp/webhook` with the verify token, and subscribe to the
   `messages` field. Meta needs a public HTTPS URL; localhost does not work.
6. Subscribe the app to the business account: `POST /api/v1/crm/whatsapp/meta/subscribe`
7. Create and get approval for templates in WhatsApp Manager. The CRM lists them from Meta and
   only offers approved ones.
8. Live test (see checklist) before calling the integration operational.

## Rules the CRM enforces

- An agent sends and reads only on their own active number; an agent without one cannot send.
- Free-form replies only within 24 hours of the customer's last message; otherwise an approved
  template is required.
- Marketing-category templates need the contact's consent recorded (`consent_status = provided`).
- STOP, UNSUBSCRIBE or a "Stop promotions" button records an opt-out for the organization (every
  number); START lifts it. Contacts marked do-not-contact are never messaged.
- Webhooks are accepted only with a valid `X-Hub-Signature-256`; repeated messages (same Meta
  message id) are stored once; delivery statuses only move forward.

## Campaigns

- Owners only. Sender is always the active campaign number (register one with `"purpose": "campaign"`).
- Audience: leads with `consent_status = provided`, not do-not-contact, not opted out, with a
  WhatsApp number; one message per number. Opt-outs are checked again just before each send.
- `{first_name}` as a value becomes each recipient's first name; other values are the same for all.
- Sending runs in the background after the campaign is saved. Each recipient is a row claimed
  with `FOR UPDATE SKIP LOCKED`, so several API tasks never send to the same person. If the
  server stops mid-campaign, the rest stay pending: press **Resume sending**. A recipient caught
  mid-send is marked "Check chat" (unknown) and is not sent again.
- Results (sent, delivered, read, failed, replies) come from Meta's status webhooks.

## Live test checklist

- [ ] `GET /webhook` verification succeeds from Meta's configuration page.
- [ ] A message from a test phone to an agent number appears in that agent's chats, not others'.
- [ ] Replying within 24 hours delivers, and sent → delivered → read appears.
- [ ] A template starts a chat with a lead and fills its values.
- [ ] STOP blocks further sends; START re-allows them.
- [ ] A refused send shows Meta's reason on the thread.
- [ ] A campaign to two opted-in test phones arrives once each from the campaign number; a lead
      without consent is not offered; results move to delivered/read.
- [ ] "Stop promotions" on a campaign message records the opt-out; the next campaign skips them.
- [ ] A reply to a campaign shows in the Campaign inbox and can be answered.

## Not built yet

- Assigning a campaign reply to an agent from the inbox (open the lead instead), and scheduling a
  campaign for later: it sends as soon as it is saved.
- A dedicated worker for campaign sending: it runs in the API process after the response, so a
  deploy or restart mid-campaign needs a Resume (nobody is sent to twice).
- Submitting templates to Meta from the CRM (`POST /{WABA_ID}/message_templates`): create them in
  WhatsApp Manager for now.
- A screen for owners to register numbers (the API above exists).
- Media (images, documents) in and out: incoming media shows as "[image]" etc.
