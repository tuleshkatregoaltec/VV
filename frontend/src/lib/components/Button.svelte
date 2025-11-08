<script lang="ts">
	export let variant: 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'ghost' =
		'primary';
	export let size: 'sm' | 'md' | 'lg' = 'md';
	export let disabled: boolean = false;
	export let fullWidth: boolean = false;
	export let type: 'button' | 'submit' | 'reset' = 'button';
	export let href: string | null = null;
	export let ariaLabel: string = '';

	const variantClasses = {
		primary: 'bg-primary text-white hover:bg-primary-dark shadow-md hover:shadow-lg',
		secondary: 'bg-primary-pale text-primary hover:bg-primary-pale/60 border-2 border-primary',
		success: 'bg-success text-white hover:bg-success-dark shadow-md hover:shadow-lg',
		warning: 'bg-warning text-white hover:bg-warning-dark shadow-md hover:shadow-lg',
		error: 'bg-error text-white hover:bg-error-dark shadow-md hover:shadow-lg',
		ghost: 'bg-transparent text-primary hover:bg-primary-pale/30 border border-primary'
	};

	const sizeClasses = {
		sm: 'px-4 py-2 text-sm',
		md: 'px-6 py-3 text-base',
		lg: 'px-8 py-4 text-lg'
	};

	$: buttonClasses = `
    ${variantClasses[variant]}
    ${sizeClasses[size]}
    ${fullWidth ? 'w-full' : ''}
    inline-flex items-center justify-center
    rounded-lg font-semibold
    transition-all duration-200
    disabled:opacity-50 disabled:cursor-not-allowed
    focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
  `;
</script>

{#if href}
	<a {href} class={buttonClasses} aria-label={ariaLabel} role="button" tabindex={disabled ? -1 : 0}>
		<slot />
	</a> use:link
{:else}
	<button {type} {disabled} class={buttonClasses} aria-label={ariaLabel} on:click>
		<slot />
	</button>
{/if}
