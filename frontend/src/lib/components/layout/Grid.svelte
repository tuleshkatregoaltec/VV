<script lang="ts">
	export let cols: number = 1;
	export let mdCols: number = cols;
	export let lgCols: number = mdCols;
	export let gap: number = 4;
	export let className: string = '';

	const colsMap: Record<number, string> = {
		1: 'grid-cols-1',
		2: 'grid-cols-2',
		3: 'grid-cols-3',
		4: 'grid-cols-4',
		5: 'grid-cols-5',
		6: 'grid-cols-6'
	};

	const mdColsMap: Record<number, string> = {
		1: 'md:grid-cols-1',
		2: 'md:grid-cols-2',
		3: 'md:grid-cols-3',
		4: 'md:grid-cols-4',
		5: 'md:grid-cols-5',
		6: 'md:grid-cols-6'
	};

	const lgColsMap: Record<number, string> = {
		1: 'lg:grid-cols-1',
		2: 'lg:grid-cols-2',
		3: 'lg:grid-cols-3',
		4: 'lg:grid-cols-4',
		5: 'lg:grid-cols-5',
		6: 'lg:grid-cols-6'
	};

	const gapMap: Record<number, string> = {
		0: 'gap-0',
		1: 'gap-1',
		2: 'gap-2',
		3: 'gap-3',
		4: 'gap-4',
		5: 'gap-5',
		6: 'gap-6',
		8: 'gap-8'
	};
</script>

<div class="grid justify-items-center sm:justify-items-stretch {colsMap[cols]} {mdColsMap[mdCols]} {lgColsMap[lgCols]} {gapMap[gap]} {className}">
	<slot />
</div>
