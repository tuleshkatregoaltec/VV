<script lang="ts">
import LegalPage from '$lib/components/legal/LegalPage.svelte'
</script>

<LegalPage
	title="Privacy Policy"
	description="How Vitevue collects, uses, stores and deletes personal data, including data from WhatsApp connections."
	current="/privacy"
>
	<p>
		Vitevue is a CRM for property agents in Dubai. This policy explains what personal data we
		handle, why, where it is stored and how you can control it. In this policy, "Vitevue", "we" and
		"us" mean Vitevue, Dubai, United Arab Emirates. For any question about it, write to
		<a href="mailto:privacy@vitevue.com">privacy@vitevue.com</a>.
	</p>

	<h2>Who this applies to</h2>
	<ul>
		<li><strong>Agents</strong> who create a Vitevue account and use the product.</li>
		<li>
			<strong>Contacts</strong> of those agents: people who message an agent's connected WhatsApp
			number, or whose details an agent saves in Vitevue.
		</li>
	</ul>
	<p>
		For contact data, the agent decides what to put into Vitevue and we process it on the agent's
		behalf to provide the service.
	</p>

	<h2>What we collect</h2>
	<p><strong>Account data.</strong> Your name, email address and password, your organisation and
		your subscription status. Passwords are handled by our authentication provider and are not
		readable by us.</p>
	<p><strong>CRM data.</strong> The leads, contacts, notes and property information that you or your
		team enter or import.</p>
	<p><strong>WhatsApp data</strong>, only if you connect WhatsApp (see the next section).</p>
	<p><strong>Usage and technical data.</strong> Basic product analytics and technical logs, such as
		pages used, browser type and error reports, so we can keep the service working and improve it.</p>

	<h2>WhatsApp</h2>
	<p>
		An agent can connect their own WhatsApp Business number to Vitevue through Meta's Embedded
		Signup. The connection uses coexistence, so the agent keeps using the WhatsApp Business app on
		their phone as before. When a connection is active:
	</p>
	<ul>
		<li>
			We store an access token for that connection, encrypted. We use it only to send and receive
			messages for that agent's number.
		</li>
		<li>
			We sync the agent's contact list (names and phone numbers) so that Vitevue can recognise who
			is writing. The agent can block any contact in Vitevue.
		</li>
		<li>
			Messages from blocked contacts are never read or stored. Personal messages that are not
			property enquiries are not stored.
		</li>
		<li>
			Property enquiries are classified and answered by an AI model on behalf of the agent, in the
			agent's voice. The assistant does not claim to be human. Sensitive or risky topics are handed
			to the agent instead of being answered automatically.
		</li>
		<li>Existing message history is not imported. Only messages received after the connection.</li>
	</ul>
	<p>
		To classify and draft replies, the text of an enquiry is sent through OpenRouter to a large
		language model provider. We send only what is needed for that reply. We do not use agent or
		contact messages to train our own models.
	</p>
	<p>
		The agent can disconnect WhatsApp at any time from the WhatsApp page in Vitevue. Disconnecting
		stops all processing, removes the stored access token and removes the synced contact list.
	</p>
	<p>
		WhatsApp itself is operated by Meta. Meta's own terms and privacy policy apply to the messages
		you send and receive on WhatsApp. Messaging fees are billed by Meta to the agent's own WhatsApp
		Business account, not by Vitevue.
	</p>

	<h2>Why we use data</h2>
	<ul>
		<li>To provide the CRM and the WhatsApp assistant that the agent asked for.</li>
		<li>To secure accounts, prevent abuse and fix problems.</li>
		<li>To understand how the product is used and improve it.</li>
		<li>To meet legal obligations.</li>
	</ul>
	<p>We do not sell personal data and we do not use it for third-party advertising.</p>

	<h2>Who we share data with</h2>
	<p>We use a small number of service providers to run Vitevue:</p>
	<ul>
		<li>Supabase, for sign-in (authentication), hosted in the EU (Frankfurt, Germany).</li>
		<li>Hetzner, for the servers that run the application and store its data, in Germany.</li>
		<li>Cloudflare, for hosting the website.</li>
		<li>Meta, for the WhatsApp Business Platform.</li>
		<li>OpenRouter and the language model provider it routes to, for AI replies.</li>
		<li>PostHog, for product analytics.</li>
	</ul>
	<p>
		We may also disclose data where the law requires it. Your data may be processed outside the UAE
		and the EU by the providers listed above, under their own data protection terms.
	</p>

	<h2>How long we keep data</h2>
	<p>
		We keep account and CRM data while the account is active. WhatsApp access tokens and synced
		contacts are removed when the agent disconnects. When an account is deleted we delete its data
		within 30 days, except for what we must keep by law. Backups are overwritten on their normal
		cycle.
	</p>

	<h2>Security</h2>
	<p>
		Data is encrypted in transit. WhatsApp access tokens are stored encrypted. Access to production
		systems is limited to the people who need it. No system is perfectly secure, so we cannot
		guarantee absolute security.
	</p>

	<h2>Your rights and choices</h2>
	<p>
		You can ask us to access, correct, export or delete your personal data, or to stop processing
		it. Agents can also disconnect WhatsApp, block contacts and edit their data inside Vitevue. If
		you are a contact who messaged an agent, you can ask us directly or ask the agent. To delete
		data, follow the steps on our <a href="/data-deletion">data deletion page</a>. We respond within
		30 days.
	</p>

	<h2>Children</h2>
	<p>Vitevue is for business use by adults. It is not directed at children.</p>

	<h2>Changes to this policy</h2>
	<p>
		We will update this page when our practices change and change the date at the top. If a change
		is significant, we will tell account holders.
	</p>

	<h2>Contact</h2>
	<p>
		Vitevue, Dubai, United Arab Emirates.
		<a href="mailto:privacy@vitevue.com">privacy@vitevue.com</a>
	</p>
</LegalPage>
