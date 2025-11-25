<script lang="ts">
  export let title: string;
  export let value: string | number;
  export let trend: { value: string; direction: 'up' | 'down' } | null = null;
  export let colSpan: string = '';
</script>

<div
			class="bg-white/80 backdrop-blur-xl rounded-xl shadow-lg shadow-primary-pale/20 border border-primary-pale hover:shadow-xl hover:border-primary-pale/50 transition-all duration-300 p-5 flex flex-col items-center justify-center text-center group w-full sm:w-auto {colSpan}"
>
	<div class="flex flex-col items-center w-full">
		<div class="flex items-start justify-between mb-4 w-full">
			<h2 class="text-base font-semibold text-gray-700 text-center w-full">{title}</h2>
						<div
							class="h-6 w-6 text-primary opacity-80 group-hover:opacity-100 transition-opacity duration-300 ml-auto"
						>
							<slot name="icon" />
						</div>
		</div>
		<p class="text-3xl sm:text-4xl font-bold text-gray-900">{value}</p>
	</div>
	{#if trend}
		<div
			class="mt-4 text-sm font-medium flex items-center justify-center w-full {trend.direction ===
			'up'
				? 'text-green-600'
				: 'text-red-600'}"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-4 w-4 mr-2"
				viewBox="0 0 20 20"
				fill="currentColor"
			>
				{#if trend.direction === 'up'}
					<path
						fill-rule="evenodd"
						d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 0l-3 3a1 1 0 001.414 1.414L9 9.414V13a1 1 0 102 0V9.414l1.293 1.293a1 1 0 001.414-1.414z"
						clip-rule="evenodd"
					/>
				{:else}
					<path
						fill-rule="evenodd"
						d="M10 18a8 8 0 100-16 8 8 0 000 16zm.707-10.293l3-3a1 1 0 00-1.414-1.414L10 8.586 7.707 6.293a1 1 0 00-1.414 1.414l3 3a1 1 0 001.414 0z"
						clip-rule="evenodd"
					/>
				{/if}
			</svg>
			<span>{trend.value}</span>
		</div>
	{/if}
	<slot />
</div>
