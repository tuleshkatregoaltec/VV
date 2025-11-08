<script lang="ts">
	export const name = 'Icon';
	export let size: 'xs' | 'sm' | 'md' | 'lg' | 'xl' = 'md';
	export let className: string = '';

	const sizeClasses = {
		xs: 'w-3 h-3',
		sm: 'w-4 h-4',
		md: 'w-5 h-5',
		lg: 'w-6 h-6',
		xl: 'w-8 h-8'
	};

	const icons: Record<string, string> = {
		'arrow-up':
			'<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 0l-3 3a1 1 0 001.414 1.414L9 9.414V13a1 1 0 102 0V9.414l1.293 1.293a1 1 0 001.414-1.414z" clip-rule="evenodd" />',
		'arrow-down':
			'<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.707-10.293l3-3a1 1 0 00-1.414-1.414L10 8.586 7.707 6.293a1 1 0 00-1.414 1.414l3 3a1 1 0 001.414 0z" clip-rule="evenodd" />',
		chart:
			'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />',
		transactions:
			'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5l-3 3-3-3" />',
		currency:
			'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v.01" />',
		plus: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />',
		send: '<path d="M16.6915026,12.4744748 L3.50612381,13.2599618 C3.19218622,13.2599618 3.03521743,13.4170592 3.03521743,13.5741566 L1.15159189,20.0151496 C0.8376543,20.8006365 0.99,21.89 1.77946707,22.52 C2.41,22.99 3.50612381,23.1 4.13399899,22.8429026 L21.714504,14.0454487 C22.6563168,13.5741566 23.1272231,12.6315722 22.9702544,11.6889879 C22.9702544,11.6889879 22.9702544,11.5318905 22.9702544,11.4748031 L22.9702544,11.3177057 C22.9702544,10.3751214 22.6563168,9.43253706 21.714504,8.96126502 L4.13399899,0.163821323 C3.34915502,0.0567539539 2.40734225,0.163821323 1.77946707,0.637394323 C0.994623095,1.27108255 0.837654326,2.36036823 1.15159189,3.14585511 L3.03521743,9.58684815 C3.03521743,9.74394555 3.19218622,9.90104294 3.50612381,9.90104294 L16.6915026,10.6865299 C16.6915026,10.6865299 17.1624089,10.6865299 17.1624089,10.3751214 L17.1624089,12.6315722 C17.1624089,12.6315722 17.1624089,12.4744748 16.6915026,12.4744748 Z" />',
		home: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />',
		menu: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />',
		close:
			'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />'
	};
</script>

<svg
	class="{sizeClasses[size]} {className}"
	fill="none"
	viewBox="0 0 24 24"
	stroke="currentColor"
	aria-hidden="true"
>
	<slot />
</svg>
