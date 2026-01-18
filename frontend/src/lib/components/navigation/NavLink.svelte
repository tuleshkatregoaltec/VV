<script lang="ts">
    import { page } from '$app/state';

    let { href, label }: { href: string; label: string } = $props();
    
    const isActive = $derived(page.url.pathname === href || page.url.pathname.startsWith(href + '/'));
</script>

<a
    {href}
    class="px-3 py-2 text-base font-medium rounded-xl transition-all {isActive
        ? 'bg-gradient-to-r from-teal-600/80 to-cyan-600/80 text-white shadow-sm'
        : 'text-gray-700 hover:text-slate-900 hover:bg-slate-50'}"
    aria-current={isActive ? 'page' : undefined}
>
    {label}
</a>
