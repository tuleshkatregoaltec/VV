<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import type { GeoPolygon, BuildingInfo } from '$lib/api/projects';

	interface ProjectPin {
		projectId: number;
		projectName: string;
		latitude: number;
		longitude: number;
		marker?: maplibregl.Marker;
	}

	let {
		onProjectSelect
	}: {
		onProjectSelect?: (projectId: number) => void;
	} = $props();

	let mapContainer = $state<HTMLDivElement>();
	let map = $state<maplibregl.Map>();
	let projectMarkers = $state<Map<number, ProjectPin>>(new Map());
	let currentMarker = $state<maplibregl.Marker | null>(null);
	let buildingMarkers = $state<maplibregl.Marker[]>([]);
	let areaPolygonLayer = $state<string | null>(null);

	onMount(() => {
		if (!mapContainer) {
			console.error('Map container not found');
			return;
		}

		// Initialize MapLibre
		map = new maplibregl.Map({
			container: mapContainer,
			style: 'https://tiles.openstreetmap.fr/hot/style.json', // Better detailed OSM style
			center: [55.2708, 25.2048], // Dubai [lng, lat]
			zoom: 11,
			preserveDrawingBuffer: true
		});

		// Add navigation controls
		map.addControl(new maplibregl.NavigationControl(), 'top-right');

		map.on('error', (e) => {
			console.error('Map error:', e);
		});

		// Wait for map to be fully loaded
		map.on('load', () => {
			console.log('Map fully loaded and ready');
		});

		return () => {
			map?.remove();
		};
	});

	// Draw area polygon on map
	function drawAreaPolygon(polygon: GeoPolygon) {
		if (!map) {
			console.error('Map not initialized');
			return;
		}

		const drawPolygon = () => {
			try {
				// Remove existing polygon layer if present
				if (areaPolygonLayer) {
					try {
						map!.removeLayer(areaPolygonLayer);
						map!.removeLayer(`${areaPolygonLayer}-outline`);
						map!.removeSource('area-polygon');
					} catch (e) {
						console.log('Polygon layers not found, skipping removal');
					}
				}

				const sourceId = 'area-polygon';
				const layerId = 'area-polygon-layer';

				console.log('Drawing polygon with coordinates:', polygon.coordinates.length, 'points');

				// Add source with polygon data
				map!.addSource(sourceId, {
					type: 'geojson',
					data: {
						type: 'Feature',
						geometry: {
							type: 'Polygon',
							coordinates: [polygon.coordinates]
						},
						properties: {}
					}
				});

				// Add fill layer
				map!.addLayer({
					id: layerId,
					type: 'fill',
					source: sourceId,
					paint: {
						'fill-color': '#0d9488',
						'fill-opacity': 0.2
					}
				});

				// Add outline layer
				map!.addLayer({
					id: `${layerId}-outline`,
					type: 'line',
					source: sourceId,
					paint: {
						'line-color': '#0d9488',
						'line-width': 3,
						'line-opacity': 1
					}
				});

				areaPolygonLayer = layerId;
				console.log('Polygon drawn successfully');
			} catch (error) {
				console.error('Error drawing polygon:', error);
			}
		};

		if (map.isStyleLoaded()) {
			drawPolygon();
		} else {
			console.log('Map style not loaded yet, waiting...');
			map.once('styledata', drawPolygon);
		}
	}

	// Add building markers to map
	function addBuildingMarkers(buildings: BuildingInfo[]) {
		// Clear existing building markers
		buildingMarkers.forEach((marker) => marker.remove());
		buildingMarkers = [];

		buildings.forEach((building) => {
			const markerEl = document.createElement('div');
			markerEl.className = 'w-8 h-8 bg-amber-500 rounded-lg flex items-center justify-center shadow-md border border-amber-600 cursor-pointer hover:bg-amber-600 transition-colors text-xs font-bold text-white';
			markerEl.textContent = (buildings.indexOf(building) + 1).toString();

			const marker = new maplibregl.Marker({ element: markerEl })
				.setLngLat([building.longitude, building.latitude])
				.addTo(map!);

			// Create popup with building info
			const popup = new maplibregl.Popup({ offset: 15 })
				.setHTML(`
					<div class="text-sm">
						<div class="font-semibold">${building.building_name || 'Building'}</div>
						${building.floors ? `<div class="text-xs text-slate-600">${building.floors} Floors</div>` : ''}
					</div>
				`);

			marker.setPopup(popup);
			buildingMarkers.push(marker);
		});
	}

	// Add or update a marker on the map
	export function addProjectMarker(projectId: number, projectName: string, latitude: number, longitude: number) {
		// Remove previous marker if exists
		if (currentMarker) {
			currentMarker.remove();
		}

		// Create marker element
		const markerEl = document.createElement('div');
		markerEl.className = 'w-10 h-10 bg-teal-600 rounded-full flex items-center justify-center shadow-lg border-2 border-white cursor-pointer hover:bg-teal-700 transition-colors';
		markerEl.innerHTML = `
			<svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
				<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16z" clip-rule="evenodd" />
			</svg>
		`;

		// Create and add marker to map
		const marker = new maplibregl.Marker({ element: markerEl })
			.setLngLat([longitude, latitude])
			.addTo(map!);

		// Create popup
		const popup = new maplibregl.Popup({ offset: 25 })
			.setHTML(`<div class="font-semibold text-sm">${projectName}</div>`);

		marker.setPopup(popup);

		// Store current marker
		currentMarker = marker;

		// Store in project markers map
		projectMarkers.set(projectId, {
			projectId,
			projectName,
			latitude,
			longitude,
			marker
		});
	}

	// Clear all markers and polygon
	export function clearMarkers() {
		if (currentMarker) {
			currentMarker.remove();
			currentMarker = null;
		}
		projectMarkers.forEach((pin) => {
			pin.marker?.remove();
		});
		projectMarkers.clear();

		// Clear building markers
		buildingMarkers.forEach((marker) => marker.remove());
		buildingMarkers = [];

		// Clear area polygon
		if (areaPolygonLayer && map) {
			try {
				map.removeLayer(areaPolygonLayer);
				map.removeLayer(`${areaPolygonLayer}-outline`);
				map.removeSource('area-polygon');
			} catch (e) {
				// Layer or source might not exist
			}
			areaPolygonLayer = null;
		}
	}

	// Fly to project and display area + buildings
	export function flyToProject(
		projectId: number,
		projectName: string,
		latitude: number,
		longitude: number,
		areaPolygon: GeoPolygon | null = null,
		buildings: BuildingInfo[] = [],
		zoom: number = 14
	) {
		if (!map) {
			console.error('Map not initialized');
			return;
		}

		console.log('Flying to project:', projectName, 'at', latitude, longitude);
		console.log('Area polygon:', areaPolygon ? 'present' : 'missing');
		console.log('Buildings:', buildings.length);

		// Clear previous markers
		clearMarkers();

		// Fly to location
		map.flyTo({ center: [longitude, latitude], zoom, duration: 2000 });

		// Add main project marker
		addProjectMarker(projectId, projectName, latitude, longitude);

		// Draw area polygon if available
		if (areaPolygon && areaPolygon.coordinates && areaPolygon.coordinates.length > 0) {
			console.log('Drawing area polygon');
			drawAreaPolygon(areaPolygon);
		} else {
			console.log('No valid area polygon data');
		}

		// Add building markers if available
		if (buildings && buildings.length > 0) {
			console.log('Adding', buildings.length, 'building markers');
			addBuildingMarkers(buildings);
		} else {
			console.log('No buildings to display');
		}
	}

	// Expose method to fly to location (legacy)
	export function flyToLocation(lng: number, lat: number, zoom: number = 14) {
		map?.flyTo({ center: [lng, lat], zoom });
	}
</script>

<div class="w-full h-full relative" style="min-height: 400px;">
	<div bind:this={mapContainer} class="absolute inset-0" style="width: 100%; height: 100%;"></div>
</div>
