<script lang="ts">
	interface Props {
		icon: string;
		title: string;
		description: string;
		gradient?: string;
		accentColor?: string;
	}

	let { icon, title, description, gradient = 'from-gray-50 to-gray-100', accentColor = 'text-teal-600' }: Props = $props();
</script>

<div class="group relative bg-white rounded-2xl p-8 shadow-lg border border-gray-200 hover:shadow-2xl hover:border-teal-600/30 transition-all duration-300 h-full">
	<div class="absolute inset-0 bg-gradient-to-br {gradient} rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>

	<div class="relative z-10">
		<div class="text-6xl mb-6 group-hover:scale-110 group-hover:rotate-6 transition-all duration-300 inline-block">
			{icon}
		</div>
		<h3 class="text-2xl font-black text-gray-900 mb-4 leading-tight">
			{title}
		</h3>
		<p class="text-gray-600 text-lg leading-relaxed">
			{description}
		</p>
	</div>
</div>
