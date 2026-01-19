<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';

	let {
		onProjectSelect
	}: {
		onProjectSelect?: (projectId: number) => void;
	} = $props();

	let mapContainer = $state<HTMLDivElement>();
	let map = $state<maplibregl.Map>();

	onMount(() => {
		if (!mapContainer) {
			console.error('Map container not found');
			return;
		}

		console.log('Initializing MapLibre GL map...');
		console.log('Container dimensions:', mapContainer.offsetWidth, 'x', mapContainer.offsetHeight);

		// Initialize MapLibre
		map = new maplibregl.Map({
			container: mapContainer,
			style: 'https://demotiles.maplibre.org/style.json', // Free OSM style
			center: [55.2708, 25.2048], // Dubai [lng, lat]
			zoom: 11
		});

		// Add navigation controls
		map.addControl(new maplibregl.NavigationControl(), 'top-right');

		// Log when map is loaded
		map.on('load', () => {
			console.log('Map loaded successfully');
		});

		map.on('error', (e) => {
			console.error('Map error:', e);
		});

		// TODO: Add area markers when project data loaded

		return () => {
			map?.remove();
		};
	});

	// Expose method to fly to location
	export function flyToLocation(lng: number, lat: number, zoom: number = 14) {
		map?.flyTo({ center: [lng, lat], zoom });
	}
</script>

<div class="w-full h-full relative" style="min-height: 400px;">
	<div bind:this={mapContainer} class="absolute inset-0" style="width: 100%; height: 100%;"></div>
</div>
