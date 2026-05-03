<script lang="ts">
import type { NewsArticleResponse } from '$lib/api/news'

let { article }: { article: NewsArticleResponse } = $props()

const imageSrc = $derived(article.thumbnail_url)

function formatRelativeTime(dateString: string | null): string {
	if (!dateString) return ''

	const now = new Date()
	const date = new Date(dateString)
	const diffInMs = now.getTime() - date.getTime()
	const diffInMinutes = Math.floor(diffInMs / (1000 * 60))
	const diffInHours = Math.floor(diffInMs / (1000 * 60 * 60))
	const diffInDays = Math.floor(diffInMs / (1000 * 60 * 60 * 24))

	if (diffInMinutes < 60) {
		return diffInMinutes === 1 ? '1 minute ago' : `${diffInMinutes} minutes ago`
	} else if (diffInHours < 24) {
		return diffInHours === 1 ? '1 hour ago' : `${diffInHours} hours ago`
	} else {
		return diffInDays === 1 ? '1 day ago' : `${diffInDays} days ago`
	}
}

const relativeTime = $derived(formatRelativeTime(article.publish_date))
const sourceLabel = $derived.by(() => {
	try {
		return new URL(article.url).hostname.replace(/^www\./, '')
	} catch {
		return null
	}
})
</script>

<a
	href={article.url}
	target="_blank"
	rel="noopener noreferrer"
	class="group flex gap-4 p-5 bg-white border border-border rounded-lg no-underline text-inherit hover:border-slate-300 transition-colors duration-200"
>
	<img
		src={imageSrc}
		alt={article.headline}
		class="w-36 h-24 object-cover rounded border border-slate-100 flex-shrink-0"
	/>
	<div class="flex flex-col gap-2 flex-1">
		<div class="flex items-center gap-2 text-xs text-slate-500">
			{#if sourceLabel}
				<span class="font-semibold text-slate-600">{sourceLabel}</span>
				<span class="text-slate-400">•</span>
			{/if}
			<time>{relativeTime}</time>
		</div>
		<h3
			class="text-base font-semibold text-fg-1 group-hover:text-primary-light line-clamp-2 transition-colors duration-200"
		>
			{article.headline}
		</h3>
	</div>
	<div class="flex items-center opacity-0 group-hover:opacity-100 transition-opacity duration-200">
		<svg class="w-5 h-5 text-fg-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
		</svg>
	</div>
</a>
