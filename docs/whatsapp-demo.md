# WhatsApp connectivity demo

This covers one Meta test number and the connectivity command. The pilot now also
supports automatic replies through the existing guarded Vitevue chat service; see
[WhatsApp automation](whatsapp-automation.md). Embedded Signup and general customer
onboarding are not implemented. The existing frontend needs no redeployment.

## Kian's dashboard setup

1. Open the existing app at https://developers.facebook.com/apps/ and its WhatsApp
   API setup/testing screen. Start with Meta's supplied test number. Add a consenting
   recipient and complete the recipient verification offered by Meta.
2. Copy the **Phone number ID**, not the visible phone number or WABA ID. Generate
   a token with `whatsapp_business_messaging` access to this asset. A temporary
   token is adequate for this demo; track its expiry.
3. Copy the App Secret from the same app's basic settings. This validates inbound
   webhook signatures; it is different from the access token and verify token.
4. Enter the callback URL below and the locally generated verify token in Meta's
   WhatsApp webhook configuration. Select **Verify and save**.
5. Subscribe to the `messages` webhook field. Ensure this app is subscribed to the
   test account; verifying the callback alone does not subscribe its messages.
   Use Meta's account-subscription operation if the dashboard has not done this.

Callback (no trailing slash):

```text
https://api-pilot.vitevue.com/api/v1/webhooks/whatsapp
```

The tunnel already routes this domain to WSL's backend. Keep Docker Desktop, WSL,
the backend, tunnel, computer and internet connection running throughout the demo.

## Private local configuration

Edit `.env.dev` on this machine. Do not paste secrets in chat, commit this file,
put credentials in Cloudflare Pages variables, or put them in frontend code.
The setup generates `WHATSAPP_VERIFY_TOKEN` locally; copy it from the file into
Meta's verification field. Do not replace it with the App Secret/access token.

```dotenv
WHATSAPP_DEMO_ENABLED=true
WHATSAPP_VERIFY_TOKEN=<already generated locally>
WHATSAPP_APP_SECRET=<same Meta app's secret>
WHATSAPP_ACCESS_TOKEN=<token with access to the test number>
WHATSAPP_PHONE_NUMBER_ID=<Meta phone-number ID>
WHATSAPP_TEST_RECIPIENT=<verified consenting recipient, country code and digits only>
WHATSAPP_GRAPH_API_VERSION=<supported version shown in Meta's API example, such as v26.0>
WHATSAPP_TEST_TEMPLATE=hello_world
```

The recipient is a single configured destination; the command cannot accept an
arbitrary destination or message. Never use an unconsenting customer's number.
App ID, WABA ID and Embedded Signup Configuration ID are not required by this
connectivity command. Record them separately for later onboarding work.

Restart only the pilot backend after editing configuration. Obtain its PID with
`ss -ltnp 'sport = :8000'`, confirm it is this checkout's Uvicorn process, stop that
process with SIGTERM, then run the retained recovery script:

```sh
bash /home/maan3/vv/VV-git/handoff/deploy/local/start-pilot.sh
just whatsapp-demo status
```

`status` prints readiness booleans only. It does not validate token permissions,
Meta approvals, webhook subscription or delivery. Sending requires the enabled
flag, access token, sending-number ID, recipient and Graph version. Receiving also
requires the App Secret. Incoming POST requests return 503 until the App Secret and number ID are
configured, and 403 when the signature is missing or invalid.

## Demonstration

1. Verify/save the callback in Meta.
2. Run `just whatsapp-demo send-test` once. It sends the configured English sample
   template to the configured recipient using the official Graph API. The supported
   choices are `hello_world` and `jaspers_market_order_confirmation_v1`. The latter
   uses fictional sample order details (John Doe, 123456 and today's date), not CRM
   data. Select the template available in the dashboard. A successful
   API response means acceptance; check the recipient's phone to prove delivery.
3. Reply from that phone to the Meta test number. In a second terminal run:

   ```sh
   tail -f handoff/deploy/local/backend.log
   ```

4. Look for `WhatsApp demo signed event: messages=1 statuses=0`. Delivery updates
   can arrive separately with a nonzero `statuses` count. Counts may vary with
   batches and retries; these logs are not a unique-message or delivery ledger.

The endpoint verifies the raw-body HMAC before interpreting the event. With
`WHATSAPP_AUTOMATION_ENABLED=false`, it counts matching events and discards content.
With automation enabled, allowlisted text messages are persisted and answered by
the worker as described in the automation guide.
Access-log filtering removes the verification query string; do not enable raw
request capture or external telemetry for this demo.

The CLI never prints access tokens or upstream error bodies. On failure check
expiry, permissions, the verified recipient and template availability in Meta.
On timeout, check the recipient's phone before resending: a timed-out request may
already have reached Meta. This command deliberately does not retry sends.
For a newly registered real business number, these sample templates may be unavailable:
use an appropriately approved template in a later sending implementation rather
than assuming the test-number demonstration proves real-number onboarding.

## Customer onboarding after the pilot

Embedded Signup needs the Meta App ID, a suitable Facebook Login for Business
configuration, allowed origins, server-side code exchange, verified asset mapping,
and the applicable permissions/review. Do not advertise an onboarding button until
that flow is implemented and tested. The current automation is an explicitly bound
agent-assistant pilot, not an external-customer assistant. Broad per-agent onboarding
still needs encrypted customer credential storage, account lifecycle, opt-outs,
takeover and delivery reconciliation.

Official references:

- [Meta Cloud API examples](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Meta send-message reference](https://www.postman.com/meta/whatsapp-business-platform/folder/o48mro7/messages)
- [Subscribe app to account](https://www.postman.com/meta/whatsapp-business-platform/request/26gui66/subscribe-to-a-waba)
- [Embedded Signup](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview)
