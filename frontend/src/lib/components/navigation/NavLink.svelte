<script lang="ts">
import { page } from '$app/state'

let { href, label }: { href: string; label: string } = $props()

const isActive = $derived(page.url.pathname === href || page.url.pathname.startsWith(`${href}/`))
</script>

<a
	{href}
	class="rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150 {isActive
		? 'bg-slate-100 text-[var(--color-fg-1)] font-semibold'
		: 'text-[var(--color-fg-3)] hover:bg-slate-100 hover:text-[var(--color-fg-1)]'}"
	aria-current={isActive ? 'page' : undefined}
>
	{label}
</a>
