<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import type { GeoPolygon, GeoPin } from '$lib/api/projects';

	interface ProjectPin {
		projectId: number;
		projectName: string;
		latitude: number;
		longitude: number;
		marker?: maplibregl.Marker;
	}

	let {
		onProjectSelect,
		onBuildingPinClick
	}: {
		onProjectSelect?: (projectId: number) => void;
		onBuildingPinClick?: (pin: GeoPin) => void;
	} = $props();

	let mapContainer = $state<HTMLDivElement>();
	let map = $state<maplibregl.Map>();
	let projectMarkers = $state<Map<number, ProjectPin>>(new Map());
	let currentMarker = $state<maplibregl.Marker | null>(null);
	let buildingMarkers = $state<maplibregl.Marker[]>([]);
	let buildingPopups = $state<maplibregl.Popup[]>([]);
	let areaPolygonLayer = $state<string | null>(null);

	onMount(() => {
		if (!mapContainer) {
			console.error('Map container not found');
			return;
		}

		// Initialize MapLibre
		map = new maplibregl.Map({
			container: mapContainer,
			style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json', // Carto Voyager (accept font CORS warnings)
			center: [55.2708, 25.2048], // Dubai [lng, lat]
			zoom: 11
		});

		// Add navigation controls
		map.addControl(new maplibregl.NavigationControl(), 'top-right');

		map.on('error', (e) => {
			console.error('Map error:', e);
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
				if (areaPolygonLayer) {
					try {
						map!.removeLayer(areaPolygonLayer);
						map!.removeLayer(`${areaPolygonLayer}-outline`);
						map!.removeSource('area-polygon');
					} catch (e) {
						// layers may not exist yet
					}
				}

				const sourceId = 'area-polygon';
				const layerId = 'area-polygon-layer';

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
			} catch (error) {
				console.error('Error drawing polygon:', error);
			}
		};

		if (map.isStyleLoaded()) {
			drawPolygon();
		} else {
			map.once('styledata', drawPolygon);
		}
	}

	// Add building pin markers to map
	function addBuildingMarkers(pins: GeoPin[]) {
		buildingPopups.forEach((p) => p.remove());
		buildingPopups = [];
		buildingMarkers.forEach((marker) => marker.remove());
		buildingMarkers = [];

		pins.forEach((pin) => {
			const markerEl = document.createElement('div');
			markerEl.style.cssText =
				'cursor: pointer; display: flex; flex-direction: column; align-items: center;';
			markerEl.innerHTML = `
				<svg width="28" height="36" viewBox="0 0 28 36" fill="none" xmlns="http://www.w3.org/2000/svg">
					<path d="M14 0C6.268 0 0 6.268 0 14C0 24.5 14 36 14 36C14 36 28 24.5 28 14C28 6.268 21.732 0 14 0Z" fill="#0d9488"/>
					<circle cx="14" cy="14" r="6" fill="white"/>
				</svg>
			`;

			const label = pin.building_name || pin.project_name;
			const popup = new maplibregl.Popup({
				offset: [0, -38],
				closeButton: false,
				closeOnClick: false,
				className: 'building-popup'
			}).setHTML(
				`<div style="font-size:13px;font-weight:600;color:#0f172a;white-space:nowrap;padding:2px 0;">${label}</div>`
			);

			const marker = new maplibregl.Marker({ element: markerEl })
				.setLngLat([pin.longitude, pin.latitude])
				.addTo(map!);

			markerEl.addEventListener('mouseenter', () =>
				popup.addTo(map!).setLngLat([pin.longitude, pin.latitude])
			);
			markerEl.addEventListener('mouseleave', () => popup.remove());
			markerEl.addEventListener('click', () => onBuildingPinClick?.(pin));

			buildingMarkers.push(marker);
			buildingPopups.push(popup);
		});
	}

	// Add or update a marker on the map
	export function addProjectMarker(
		projectId: number,
		projectName: string,
		latitude: number,
		longitude: number
	) {
		// Remove previous marker if exists
		if (currentMarker) {
			currentMarker.remove();
		}

		// Create marker element
		const markerEl = document.createElement('div');
		markerEl.className =
			'w-10 h-10 bg-teal-600 rounded-full flex items-center justify-center shadow-lg border-2 border-white cursor-pointer hover:bg-teal-700 transition-colors';
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
		const popup = new maplibregl.Popup({ offset: 25 }).setHTML(
			`<div class="font-semibold text-sm">${projectName}</div>`
		);

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

		// Clear building markers and popups
		buildingPopups.forEach((p) => p.remove());
		buildingPopups = [];
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
		geoPins: GeoPin[] = [],
		zoom: number = 14
	) {
		if (!map) {
			console.error('Map not initialized');
			return;
		}

		// Clear previous markers
		clearMarkers();

		// Fly to location
		map.flyTo({ center: [longitude, latitude], zoom, duration: 2000 });

		// Add main project marker
		addProjectMarker(projectId, projectName, latitude, longitude);

		if (areaPolygon && areaPolygon.coordinates && areaPolygon.coordinates.length > 0) {
			drawAreaPolygon(areaPolygon);
		}

		// Add building pin markers if available
		if (geoPins && geoPins.length > 0) {
			addBuildingMarkers(geoPins);
		}
	}

	export function flyToLocation(lng: number, lat: number, zoom: number = 14) {
		map?.flyTo({ center: [lng, lat], zoom });
	}

	// Show all building pins for a master project and fit map to their bounds
	export function fitBounds(pins: GeoPin[]) {
		if (!map || pins.length === 0) return;
		clearMarkers();
		addBuildingMarkers(pins);
		const lats = pins.map((p) => p.latitude);
		const lngs = pins.map((p) => p.longitude);
		map.fitBounds(
			[
				[Math.min(...lngs), Math.min(...lats)],
				[Math.max(...lngs), Math.max(...lats)]
			],
			{ padding: 60 }
		);
	}
</script>

<div class="w-full h-full relative" style="min-height: 400px;">
	<div bind:this={mapContainer} class="absolute inset-0" style="width: 100%; height: 100%;"></div>
</div>
