# WhatsApp Meta setup checklist

Everything on the Vitevue side is live. The Connect WhatsApp page shows a calm
"being set up" message until the Embedded Signup configuration ID exists. This list
is what is left on the Meta side, in order. Nothing here needs a secret pasted into
chat except the one non-secret configuration ID in step 9.

Facts used below
- Meta app ID: `1723271579129715`
- Business: Vitevue, ID `1425178709197050`
- Meta developer account: "Maan Meta"
- Webhook callback URL: `https://api-pilot.vitevue.com/api/v1/webhooks/whatsapp`
- Website domain for the pilot: `vv-pilot.pages.dev`

Steps

1. Complete the "Confirm Account" identity check on developers.facebook.com for the
   account "Maan Meta". Until this is done the developer dashboard stays limited.

2. Get added as an admin of the business Vitevue (1425178709197050). Kian does this in
   Business Settings, People, Add. Give Maan full control (admin) and assign both the
   app (1723271579129715) and the WhatsApp account with full control.

3. Check Business Verification and Tech Provider status. Business Settings, Security
   Center shows whether Vitevue is verified. If it is not, start Business Verification
   now, because it takes days. Also check whether Vitevue needs to be registered as a
   Tech Provider for Embedded Signup (App Dashboard, WhatsApp, Embedded Signup or
   Onboarding shows what the dashboard asks for).

4. Webhook. App Dashboard, WhatsApp, Configuration.
   - Callback URL: `https://api-pilot.vitevue.com/api/v1/webhooks/whatsapp`
   - Verify token: the existing one already stored on the server (it is the value Meta
     was given earlier; do not make a new one. If you no longer have it, tell Claude
     and a new token can be set on the server and entered here together).
   - Click Verify and save. The server answers the check.
   - Subscribe to these fields: `messages`, `smb_app_state_sync`,
     `smb_message_echoes`, `account_update`.

5. Create the Embedded Signup configuration. App Dashboard, Facebook Login for
   Business, Configurations, Create configuration. Choose the "WhatsApp Embedded
   Signup" variation (or the template "WhatsApp Embedded Signup Configuration With 60
   Expiration Token"). Save it and write down the Configuration ID (a long number).

6. Login settings. App Dashboard, Facebook Login for Business, Settings. Turn ON:
   - Client OAuth login
   - Web OAuth login
   - Enforce HTTPS
   - Embedded Browser OAuth Login
   - Strict Mode for redirect URIs
   - Login with the JavaScript SDK
   Then add `vv-pilot.pages.dev` to Allowed domains for the JavaScript SDK, and add
   `https://vv-pilot.pages.dev/` to Valid OAuth redirect URIs.

7. Permissions. App Dashboard, App Review, Permissions and features. Request Advanced
   Access (App Review) for `whatsapp_business_management` and
   `whatsapp_business_messaging`. Confirm the exact names in the dashboard. Meta will
   ask for a screencast of the Connect WhatsApp flow and an explanation that messages
   from personal contacts are never stored.

8. Payment method. Kian adds a payment method to his WhatsApp Business account in
   WhatsApp Manager, Settings, Payment methods. Without it, business-initiated
   conversations can fail.

9. Tell Claude the Configuration ID from step 5. Claude then sets
   `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` on the server and restarts the API. After
   that the Connect page shows the real Connect button instead of "being set up".

10. First live test. Open https://vv-pilot.pages.dev/crm/whatsapp, sign in as a tester
    and connect a tester number. App admins and testers can do this before App Review
    finishes. Confirm that the contact sync arrives (the number of synced contacts
    appears on the page), that a blocked contact is never read, and that a property
    question to the tester number gets a reply in the agent's voice.

Capacity
- Until Business Verification, App Review and Access Verification are complete, the app
  can onboard 10 new businesses per rolling 7 days.
- After all three are complete the limit rises to 200 per 7 days.

Safe fallback
- Kian's own automated number (+971 50 127 9179) keeps working throughout. It does not
  depend on any of the steps above.
