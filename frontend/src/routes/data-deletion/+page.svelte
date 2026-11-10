<script lang="ts">
import LegalPage from '$lib/components/legal/LegalPage.svelte'
</script>

<LegalPage
	title="User Data Deletion"
	description="How to disconnect WhatsApp, request deletion of your data, or delete your Vitevue account."
	current="/data-deletion"
>
	<p>
		This page explains how to remove your data from Vitevue. You do not need an account to ask for
		deletion.
	</p>

	<h2>Disconnect WhatsApp yourself</h2>
	<p>If you are an agent with a connected WhatsApp number:</p>
	<ol>
		<li>Sign in to Vitevue and open the WhatsApp page.</li>
		<li>Choose Disconnect.</li>
	</ol>
	<p>
		This stops all processing of your WhatsApp messages straight away and removes the stored access
		token and the synced contact list. You can also remove Vitevue from your WhatsApp Business
		settings at any time, which has the same effect.
	</p>

	<h2>Request deletion by email</h2>
	<p>
		Whether you are an agent or a contact who messaged an agent, email
		<a href="mailto:privacy@vitevue.com?subject=Data%20deletion%20request">privacy@vitevue.com</a>
		with the subject "Data deletion request" and tell us:
	</p>
	<ul>
		<li>
			Who you are: the email address of your Vitevue account, or, if you are a contact, the phone
			number you wrote from and, if you know it, the agent you messaged.
		</li>
		<li>What you want deleted: everything, or only your WhatsApp conversations.</li>
	</ul>
	<p>
		We may ask you to confirm your identity before we act, so that we never delete or hand over
		data to the wrong person. We will confirm by email once it is done and will respond within
		<strong>30 days</strong>.
	</p>

	<h2>Delete your Vitevue account</h2>
	<p>
		Agents can ask us to delete their account, and the data stored under it, by emailing the
		address above from the email address on the account. We delete the account's profile and CRM
		data within 30 days. If your organisation has other users, the organisation owner decides what
		happens to shared company data. We keep only what the law requires us to keep, and backups are
		overwritten on their normal cycle.
	</p>

	<h2>What is deleted</h2>
	<ul>
		<li>Your account details and sign-in.</li>
		<li>The WhatsApp access token and the synced contact list.</li>
		<li>The enquiry conversations stored for your connection.</li>
		<li>The CRM records you created.</li>
	</ul>
	<p>
		Messages that exist in WhatsApp itself stay in WhatsApp and are governed by Meta. Delete those
		in the WhatsApp app.
	</p>

	<p>
		More detail on how we handle data is in the <a href="/privacy">Privacy Policy</a>.
	</p>
</LegalPage>
