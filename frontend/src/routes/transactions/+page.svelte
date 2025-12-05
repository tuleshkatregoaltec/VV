<script lang="ts">
  import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte';
  import PriceRangeDropdown from '$lib/components/dropdowns/PriceRangeDropdown.svelte';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import { setContext } from 'svelte';
  import { writable } from 'svelte/store';

  // Create context for dropdown coordination
  const openDropdownId = writable<string | null>(null);
  setContext('openDropdownId', openDropdownId);

  // Filter configuration
  const projectOptions = ['All Projects', 'Marina Gate', 'Palm Jumeirah', 'Business Bay Tower', 'Dubai Marina', 'Downtown Dubai'];
  const bedroomOptions = ['All', '1 BR', '2 BR', '3 BR', '4 BR'];

  // Table column configuration
  const columns = [
    { id: 'date', label: 'Date', align: 'left' as const },
    { id: 'project', label: 'Project', align: 'left' as const },
    { id: 'building', label: 'Building', align: 'left' as const },
    { id: 'bedrooms', label: 'Bedrooms', align: 'left' as const, badge: true },
    { 
      id: 'area', 
      label: 'Area (sq.ft)', 
      align: 'right' as const,
      format: (val: number) => val.toLocaleString()
    },
    { 
      id: 'price', 
      label: 'Price (AED)', 
      align: 'right' as const,
      format: (val: number) => val.toLocaleString()
    },
    { 
      id: 'pricePerSqFt', 
      label: 'Price/sq.ft', 
      align: 'right' as const,
      highlighted: true,
      format: (val: number) => val.toLocaleString()
    }
  ];

  // Sample data
  let allData = [
    {
      date: '2024-01-15',
      project: 'Marina Gate',
      building: 'Tower A',
      bedrooms: '2 BR',
      area: 1160,
      price: 1450000,
      pricePerSqFt: 1250
    },
    {
      date: '2024-01-14',
      project: 'Palm Jumeirah',
      building: 'Golden Mile',
      bedrooms: '3 BR',
      area: 2254,
      price: 3200000,
      pricePerSqFt: 1420
    },
    {
      date: '2024-01-14',
      project: 'Business Bay Tower',
      building: 'Executive Heights',
      bedrooms: '1 BR',
      area: 780,
      price: 920000,
      pricePerSqFt: 1180
    },
    {
      date: '2024-01-13',
      project: 'Dubai Marina',
      building: 'Princess Tower',
      bedrooms: '2 BR',
      area: 1244,
      price: 1680000,
      pricePerSqFt: 1350
    },
    {
      date: '2024-01-12',
      project: 'Downtown Dubai',
      building: 'Burj Vista',
      bedrooms: '4 BR',
      area: 3671,
      price: 5800000,
      pricePerSqFt: 1580
    }
  ];

  let filteredData = $state(allData);
  
  // Filter values
  let selectedProject = $state('All Projects');
  let selectedBedrooms = $state('All');
  let priceRange = $state({ min: '', max: '' });

  // Apply filters whenever any filter changes
  $effect(() => {
    filteredData = allData.filter(row => {
      if (selectedProject !== 'All Projects' && row.project !== selectedProject) return false;
      if (selectedBedrooms !== 'All' && row.bedrooms !== selectedBedrooms) return false;
      if (priceRange.min && row.price < parseFloat(priceRange.min)) return false;
      if (priceRange.max && row.price > parseFloat(priceRange.max)) return false;
      return true;
    });
  });

  // Handle row click
  function handleRowClick(event: CustomEvent) {
    console.log('Row clicked:', event.detail);
    // You can add navigation or modal opening here
  }
</script>

<div class="min-h-screen bg-background">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

    <!-- Filters -->
    <div class="bg-white rounded-xl shadow-md border border-gray-200 p-6 mb-6">
      <h2 class="text-xl font-bold text-gray-900 mb-6">Filters</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <StandardDropdown 
          id="project"
          ariaLabel="Project"
          options={projectOptions}
          bind:value={selectedProject}
        />
        <StandardDropdown 
          id="bedrooms"
          ariaLabel="Bedrooms"
          options={bedroomOptions}
          bind:value={selectedBedrooms}
        />
        <PriceRangeDropdown 
          id="price"
          ariaLabel="Price (AED)"
          bind:value={priceRange}
          placeholderMin="0"
          placeholderMax="10,000,000"
        />
      </div>
    </div>

    <!-- Results Summary -->
    <div class="mb-4">
      <p class="text-sm text-gray-600">
        Showing <span class="font-semibold text-gray-900">{filteredData.length}</span> of <span class="font-semibold text-gray-900">{allData.length}</span> transactions
      </p>
    </div>

    <!-- Data Table -->
    <DataPanel columns={columns} data={filteredData} onrowclick={handleRowClick} />
  </div>
</div>
