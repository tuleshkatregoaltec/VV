<script lang="ts">
import { messageParts } from '../../email'

/** A message as the email shows it: paragraphs, links and buttons (rendered safely, no HTML). */
let { text }: { text: string } = $props()

const paragraphs = $derived(messageParts(text))
</script>

<div class="eb">
	{#each paragraphs as parts, i (i)}
		<p>
			{#each parts as part, j (j)}
				{#if part.kind === 'text'}{part.text}{:else if part.kind === 'link'}<a
						href={part.url}
						target="_blank"
						rel="noreferrer">{part.text}</a
					>{:else}<a class="eb-btn" href={part.url} target="_blank" rel="noreferrer">{part.text}</a>{/if}
			{/each}
		</p>
	{/each}
</div>

<style>
	.eb p {
		margin: 0 0 10px;
		white-space: pre-wrap;
	}
	.eb p:last-child {
		margin-bottom: 0;
	}
	.eb a {
		color: var(--blue);
		overflow-wrap: anywhere;
	}
	/* Same look as the email (brevo.BUTTON_STYLE). */
	.eb .eb-btn {
		display: inline-block;
		padding: 10px 20px;
		background: #2563eb;
		color: #ffffff;
		text-decoration: none;
		border-radius: 6px;
		font-weight: 600;
	}
</style>
