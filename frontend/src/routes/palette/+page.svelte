<script lang="ts">
	import PageContainer from '$lib/components/layout/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Button from '$lib/components/Button.svelte';
	import DashboardCard from '$lib/components/DashboardCard.svelte';
	import Grid from '$lib/components/layout/Grid.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import ChatBox from '$lib/components/ChatBox.svelte';

	function handleChatSubmit(value: string) {
		console.log('Chat submitted:', value);
	}

	function handleButtonClick() {
		console.log('Button clicked!');
	}
</script>

<PageContainer maxWidth="7xl">
	<PageHeader title="Component Showcase" subtitle="All reusable components in one place" />

	<!-- Buttons Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Buttons</h2>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">Button Variants</h3>
			<div class="flex flex-wrap gap-4">
				<Button variant="primary" on:click={handleButtonClick}>Primary Button</Button>
				<Button variant="secondary" on:click={handleButtonClick}>Secondary Button</Button>
				<Button variant="success" on:click={handleButtonClick}>Success Button</Button>
				<Button variant="warning" on:click={handleButtonClick}>Warning Button</Button>
				<Button variant="error" on:click={handleButtonClick}>Error Button</Button>
				<Button variant="ghost" on:click={handleButtonClick}>Ghost Button</Button>
			</div>
		</div>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">Button Sizes</h3>
			<div class="flex flex-wrap items-center gap-4">
				<Button variant="primary" size="sm">Small</Button>
				<Button variant="primary" size="md">Medium</Button>
				<Button variant="primary" size="lg">Large</Button>
			</div>
		</div>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">Button States</h3>
			<div class="flex flex-wrap gap-4">
				<Button variant="primary">Enabled</Button>
				<Button variant="primary" disabled>Disabled</Button>
				<Button variant="primary" fullWidth>Full Width Button</Button>
			</div>
		</div>
	</section>

	<!-- Dashboard Cards Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Dashboard Cards</h2>

		<Grid cols={1} mdCols={2} lgCols={3} gap={4}>
			<DashboardCard
				title="Total Users"
				value={1234}
				icon={`<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>`}
				trend={{ value: '15% increase', direction: 'up' }}
			/>

			<DashboardCard
				title="Revenue"
				value="$45,231"
				icon={`<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v.01" />
        </svg>`}
				trend={{ value: '8% decrease', direction: 'down' }}
			/>

			<DashboardCard
				title="Active Sessions"
				value={892}
				icon={`<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>`}
			/>
		</Grid>
	</section>

	<!-- Icons Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Icons</h2>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">Icon Sizes</h3>
			<div class="flex flex-wrap items-end gap-6">
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="xs" className="text-primary" />
					<span class="text-xs text-gray-500">xs</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="sm" className="text-primary" />
					<span class="text-xs text-gray-500">sm</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="md" className="text-primary" />
					<span class="text-xs text-gray-500">md</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">lg</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="xl" className="text-primary" />
					<span class="text-xs text-gray-500">xl</span>
				</div>
			</div>
		</div>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">Available Icons</h3>
			<div class="flex flex-wrap gap-8">
				<div class="flex flex-col items-center gap-2">
					<Icon name="arrow-up" size="lg" className="text-success" />
					<span class="text-xs text-gray-500">arrow-up</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="arrow-down" size="lg" className="text-error" />
					<span class="text-xs text-gray-500">arrow-down</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="chart" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">chart</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="transactions" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">transactions</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="currency" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">currency</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="plus" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">plus</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="send" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">send</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="home" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">home</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="menu" size="lg" className="text-primary" />
					<span class="text-xs text-gray-500">menu</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Icon name="close" size="lg" className="text-error" />
					<span class="text-xs text-gray-500">close</span>
				</div>
			</div>
		</div>
	</section>

	<!-- Grid Layout Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Grid Layouts</h2>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">2 Columns</h3>
			<Grid cols={1} mdCols={2} gap={4}>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 1
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 2
				</div>
			</Grid>
		</div>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">3 Columns</h3>
			<Grid cols={1} mdCols={2} lgCols={3} gap={4}>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 1
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 2
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 3
				</div>
			</Grid>
		</div>

		<div class="mb-8">
			<h3 class="text-lg font-semibold text-gray-700 mb-4">4 Columns</h3>
			<Grid cols={2} mdCols={3} lgCols={4} gap={4}>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 1
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 2
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 3
				</div>
				<div class="bg-primary-pale rounded-lg p-6 text-center text-primary font-semibold">
					Item 4
				</div>
			</Grid>
		</div>
	</section>

	<!-- ChatBox Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Chat Box</h2>

		<div class="flex justify-center">
			<ChatBox
				placeholder="Type your message here..."
				onSubmit={handleChatSubmit}
				options={['Option 1', 'Option 2', 'Option 3']}
			/>
		</div>
	</section>

	<!-- Page Headers Section -->
	<section class="mb-16">
		<h2 class="text-2xl font-bold text-gray-900 mb-6">Page Headers</h2>

		<div class="space-y-8">
			<div class="bg-white rounded-lg p-6">
				<PageHeader
					title="Gradient Header"
					subtitle="With a colorful gradient effect"
					gradient={true}
				/>
			</div>

			<div class="bg-white rounded-lg p-6">
				<PageHeader title="Simple Header" subtitle="Without gradient effect" gradient={false} />
			</div>

			<div class="bg-white rounded-lg p-6">
				<PageHeader title="Header Only" gradient={true} />
			</div>
		</div>
	</section>
</PageContainer>
