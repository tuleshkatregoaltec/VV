<script lang="ts">
	interface Props {
		title: string;
		description: string;
		icon: string;
	}

	let { title, description, icon }: Props = $props();
</script>

<div class="group bg-white/80 backdrop-blur-sm rounded-2xl p-6 shadow-lg border border-gray-200 hover:border-teal-600 hover:shadow-xl transition-all duration-300 h-full hover:-translate-y-2">
	<div class="text-5xl mb-5 group-hover:scale-110 transition-transform duration-300 inline-block">
		{icon}
	</div>
	<h3 class="text-xl font-black text-gray-900 mb-3 leading-tight">{title}</h3>
	<p class="text-gray-600 leading-relaxed text-sm">{description}</p>

	<!-- Hover accent -->
	<div class="mt-4 pt-4 border-t border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
		<span class="text-teal-600 font-bold text-sm flex items-center gap-1">
			Learn more
			<svg class="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
			</svg>
		</span>
	</div>
</div>
