<script lang="ts">
import type { Snippet } from 'svelte'

let {
	title,
	description,
	updated = '10 November 2026',
	current,
	children
}: {
	title: string
	description: string
	updated?: string
	current: '/privacy' | '/terms' | '/data-deletion'
	children: Snippet
} = $props()

const links = [
	{ href: '/privacy', label: 'Privacy Policy' },
	{ href: '/terms', label: 'Terms of Service' },
	{ href: '/data-deletion', label: 'Data deletion' }
] as const
</script>

<svelte:head>
	<title>{title} | Vitevue</title>
	<meta name="description" content={description} />
</svelte:head>

<div class="legal theme-app">
	<header class="legal-header">
		<a href="/" class="legal-brand" aria-label="Vitevue home">
			<img src="/logos/vitevue-navbar-800@2x.png" alt="Vitevue" class="brand-logo-light" />
			<img src="/logos/vitevue-navbar-bone.png" alt="Vitevue" class="brand-logo-dark" />
		</a>
	</header>

	<main class="legal-main">
		<h1>{title}</h1>
		<p class="legal-updated">Last updated: {updated}</p>
		<div class="legal-body">
			{@render children()}
		</div>
	</main>

	<footer class="legal-footer">
		<nav aria-label="Legal">
			{#each links as link (link.href)}
				<a href={link.href} aria-current={link.href === current ? 'page' : undefined}>{link.label}</a>
			{/each}
		</nav>
		<p>Vitevue, Dubai, United Arab Emirates</p>
	</footer>
</div>

<style>
	.legal {
		min-height: 100vh;
		background: var(--color-bg-app);
		color: var(--color-fg-2);
		font-family: var(--font-sans);
		padding-inline: 16px;
	}
	.legal-header,
	.legal-main,
	.legal-footer {
		max-width: 44rem;
		margin-inline: auto;
	}
	.legal-header {
		padding-block: 24px 8px;
	}
	.legal-brand img {
		height: 24px;
		width: auto;
	}
	.legal-main {
		padding-block: 32px 48px;
	}
	h1 {
		margin: 0;
		font-size: 1.875rem;
		line-height: 1.2;
		font-weight: 700;
		color: var(--color-fg-1);
		letter-spacing: -0.01em;
	}
	.legal-updated {
		margin: 8px 0 0;
		font-size: 0.875rem;
		color: var(--color-fg-4);
	}
	.legal-body {
		margin-top: 32px;
		font-size: 1rem;
		line-height: 1.7;
		overflow-wrap: anywhere;
	}
	.legal-body :global(h2) {
		margin: 36px 0 8px;
		font-size: 1.125rem;
		line-height: 1.35;
		font-weight: 600;
		color: var(--color-fg-1);
	}
	.legal-body :global(p),
	.legal-body :global(ul),
	.legal-body :global(ol) {
		margin: 0 0 12px;
	}
	.legal-body :global(ul),
	.legal-body :global(ol) {
		padding-left: 1.25rem;
	}
	.legal-body :global(ul) {
		list-style: disc;
	}
	.legal-body :global(ol) {
		list-style: decimal;
	}
	.legal-body :global(li) {
		margin-bottom: 6px;
	}
	.legal-body :global(a) {
		color: var(--color-accent-text);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.legal-body :global(strong) {
		color: var(--color-fg-1);
		font-weight: 600;
	}
	.legal-footer {
		border-top: 1px solid var(--color-border);
		padding-block: 24px 40px;
		font-size: 0.875rem;
		color: var(--color-fg-4);
	}
	.legal-footer nav {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 20px;
	}
	.legal-footer a {
		color: var(--color-fg-3);
		text-decoration: none;
	}
	.legal-footer a:hover,
	.legal-footer a[aria-current='page'] {
		color: var(--color-fg-1);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.legal-footer p {
		margin: 12px 0 0;
	}
</style>
