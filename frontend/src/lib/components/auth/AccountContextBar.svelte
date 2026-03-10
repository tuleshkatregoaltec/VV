<script lang="ts">
import { logout } from '$lib/api/auth'

export let email: string | null | undefined = null
export let label = 'Signed in as'
export let compact = false
export let redirectTo = '/auth'
let loading = false

async function handleLogout() {
	loading = true
	await logout(redirectTo)
}
</script>

{#if email}
	<div
		class:rounded-xl={compact}
		class:px-3={compact}
		class:py-2.5={compact}
		class="flex items-center justify-between gap-3 rounded-2xl border border-slate-200/80 bg-white/85 px-4 py-3 shadow-sm backdrop-blur"
	>
		<div class="min-w-0">
			<p class="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">{label}</p>
			<p class="truncate text-sm font-medium text-slate-900">{email}</p>
		</div>
		<button
			type="button"
			onclick={handleLogout}
			disabled={loading}
			class:text-xs={compact}
			class:px-2.5={compact}
			class:py-1={compact}
			class="shrink-0 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-60"
		>
			{loading ? 'Signing out...' : 'Use a different account'}
		</button>
	</div>
{/if}
