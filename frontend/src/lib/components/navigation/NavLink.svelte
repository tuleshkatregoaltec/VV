<script lang="ts">
    import { page } from '$app/state';

    let { href, label }: { href: string; label: string } = $props();
</script>

<a
    {href}
    class="px-3 py-2 text-base font-medium text-gray-700 hover:text-primary rounded-lg hover:bg-gray-50 transition-colors"
    aria-current={page.url.pathname === href ? 'page' : undefined}
>
    {label}
</a>
