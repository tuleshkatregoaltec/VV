<script lang="ts">
	import type { NewsArticle } from '$lib/api/news';

	let { article }: { article: NewsArticle } = $props();

	const imageSrc = $derived(
		article.thumbnail_base64
			? `data:image/jpeg;base64,${article.thumbnail_base64}`
			: article.thumbnail_url
	);
</script>

<a
	href={article.url}
	target="_blank"
	rel="noopener noreferrer"
	class="flex gap-4 p-4 border border-gray-200 rounded-lg no-underline text-inherit hover:bg-gray-50 transition-colors"
>
	<img src={imageSrc} alt={article.headline} class="w-32 h-20 object-cover rounded flex-shrink-0" />
	<div class="flex flex-col gap-1">
		<h3 class="font-semibold text-gray-900 line-clamp-2">{article.headline}</h3>
		{#if article.publish_date}
			<time class="text-sm text-gray-500">
				{new Date(article.publish_date).toLocaleDateString()}
			</time>
		{/if}
	</div>
</a>
