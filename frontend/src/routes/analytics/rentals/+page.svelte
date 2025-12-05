<script lang="ts">
    import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
    <PageHeader 
        title="Rental Analytics" 
        subtitle="Market insights and trends for property rentals"
    />

    <div class="mt-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div class="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 class="text-sm font-medium text-gray-500 uppercase tracking-wider">Avg. Rent/sq.ft</h3>
            <p class="mt-2 text-3xl font-bold text-gray-900">--</p>
            <p class="mt-1 text-sm text-gray-500">Coming soon</p>
        </div>

        <div class="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 class="text-sm font-medium text-gray-500 uppercase tracking-wider">Active Contracts</h3>
            <p class="mt-2 text-3xl font-bold text-gray-900">--</p>
            <p class="mt-1 text-sm text-gray-500">Coming soon</p>
        </div>

        <div class="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 class="text-sm font-medium text-gray-500 uppercase tracking-wider">Avg. Contract Duration</h3>
            <p class="mt-2 text-3xl font-bold text-gray-900">--</p>
            <p class="mt-1 text-sm text-gray-500">Coming soon</p>
        </div>
    </div>

    <div class="mt-8 bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">Rental Price Trends</h3>
        <div class="h-64 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
            <div class="text-center">
                <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <p class="mt-2 text-sm text-gray-500">Rental analytics charts coming soon</p>
            </div>
        </div>
    </div>

    <div class="mt-8 bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">Occupancy Rates by Area</h3>
        <div class="h-48 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
            <div class="text-center">
                <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
                <p class="mt-2 text-sm text-gray-500">Occupancy analysis coming soon</p>
            </div>
        </div>
    </div>
</div>
