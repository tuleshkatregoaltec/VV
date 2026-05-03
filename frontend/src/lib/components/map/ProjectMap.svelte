<script lang="ts">
import maplibregl from 'maplibre-gl'
import { onMount } from 'svelte'
import type { DdaPlotFeature, GeoPin, GeoPolygon } from '$lib/api/projects'
import { colorTheme } from '$lib/stores/preferences.svelte'

const LIGHT_MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json'
const DARK_MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

interface ProjectPin {
	projectId: number
	projectName: string
	latitude: number
	longitude: number
	marker?: maplibregl.Marker
}

type ProjectMarkerInput = Omit<ProjectPin, 'marker'>

let {
	onProjectSelect,
	onBuildingPinClick
}: {
	onProjectSelect?: (projectId: number) => void
	onBuildingPinClick?: (pin: GeoPin) => void
} = $props()

let mapContainer = $state<HTMLDivElement>()
let map = $state<maplibregl.Map>()
let projectMarkers = $state<Map<number, ProjectPin>>(new Map())
let currentMarker = $state<maplibregl.Marker | null>(null)
let buildingMarkers = $state<maplibregl.Marker[]>([])
let buildingPopups = $state<maplibregl.Popup[]>([])
let areaPolygonLayer = $state<string | null>(null)
let currentMapStyle = $state<string | null>(null)
let currentProjectMarkerInput = $state<ProjectMarkerInput | null>(null)
let currentAreaPolygon = $state<GeoPolygon | null>(null)
let currentBuildingPins = $state<GeoPin[]>([])
let currentDDAPlots = $state<DdaPlotFeature[]>([])
let currentFitBoundsPins = $state<GeoPin[]>([])
const resolvedTheme = $derived(colorTheme.resolved)

function getMapStyle(theme: 'light' | 'dark') {
	return theme === 'dark' ? DARK_MAP_STYLE : LIGHT_MAP_STYLE
}

onMount(() => {
	if (!mapContainer) {
		console.error('Map container not found')
		return
	}

	// Initialize MapLibre
	currentMapStyle = getMapStyle(resolvedTheme)
	map = new maplibregl.Map({
		container: mapContainer,
		style: currentMapStyle, // Carto basemaps accept font CORS warnings.
		center: [55.2708, 25.2048], // Dubai [lng, lat]
		zoom: 11
	})

	// Add navigation controls
	map.addControl(new maplibregl.NavigationControl(), 'top-right')

	map.on('error', (e) => {
		console.error('Map error:', e)
	})

	return () => {
		map?.remove()
	}
})

$effect(() => {
	const currentMap = map
	const nextStyle = getMapStyle(resolvedTheme)
	if (!currentMap || currentMapStyle === nextStyle) return

	currentMapStyle = nextStyle
	_unbindDDAHandlers()
	areaPolygonLayer = null
	currentMap.setStyle(nextStyle)
	currentMap.once('style.load', () => {
		if (currentMapStyle !== nextStyle) return
		replayCurrentOverlays()
	})
})

function _removeAreaPolygon() {
	if (!map) return
	try {
		if (areaPolygonLayer && map.getLayer(areaPolygonLayer)) map.removeLayer(areaPolygonLayer)
		if (areaPolygonLayer && map.getLayer(`${areaPolygonLayer}-outline`)) {
			map.removeLayer(`${areaPolygonLayer}-outline`)
		}
		if (map.getSource('area-polygon')) map.removeSource('area-polygon')
	} catch (_e) {
		// Layer or source might not exist during a style reload.
	}
	areaPolygonLayer = null
}

function _clearProjectMarkers() {
	if (currentMarker) {
		currentMarker.remove()
		currentMarker = null
	}
	projectMarkers.forEach((pin) => {
		pin.marker?.remove()
	})
	projectMarkers.clear()
}

function _clearBuildingMarkers() {
	buildingPopups.forEach((p) => {
		p.remove()
	})
	buildingPopups = []
	buildingMarkers.forEach((marker) => {
		marker.remove()
	})
	buildingMarkers = []
}

function _clearRenderedOverlays() {
	_clearProjectMarkers()
	_clearBuildingMarkers()
	_removeAreaPolygon()
	_removeDDALayers()
}

function fitMapToPins(pins: GeoPin[], duration?: number) {
	if (!map || pins.length === 0) return
	const lats = pins.map((p) => p.latitude)
	const lngs = pins.map((p) => p.longitude)
	const options = duration === undefined ? { padding: 60 } : { padding: 60, duration }
	map.fitBounds(
		[
			[Math.min(...lngs), Math.min(...lats)],
			[Math.max(...lngs), Math.max(...lats)]
		],
		options
	)
}

function replayCurrentOverlays() {
	if (!map) return
	if (!map.isStyleLoaded()) {
		map.once('style.load', replayCurrentOverlays)
		return
	}

	const projectMarker = currentProjectMarkerInput
	const areaPolygon = currentAreaPolygon
	const buildingPins = [...currentBuildingPins]
	const ddaPlots = [...currentDDAPlots]
	const fitBoundsPins = [...currentFitBoundsPins]

	_clearRenderedOverlays()

	if (projectMarker) {
		addProjectMarker(
			projectMarker.projectId,
			projectMarker.projectName,
			projectMarker.latitude,
			projectMarker.longitude
		)
	}
	if ((areaPolygon?.coordinates?.length ?? 0) > 0 && areaPolygon) {
		drawAreaPolygon(areaPolygon)
	}
	if (buildingPins.length > 0) {
		addBuildingMarkers(buildingPins)
	}
	if (ddaPlots.length > 0) {
		showDDAPlots(ddaPlots)
	}
	if (fitBoundsPins.length > 0) {
		fitMapToPins(fitBoundsPins, 0)
	}
}

// Draw area polygon on map
function drawAreaPolygon(polygon: GeoPolygon) {
	if (!map) {
		console.error('Map not initialized')
		return
	}
	currentAreaPolygon = polygon

	const drawPolygon = () => {
		if (!map) return
		if (currentAreaPolygon !== polygon) return
		try {
			_removeAreaPolygon()

			const sourceId = 'area-polygon'
			const layerId = 'area-polygon-layer'

			// Add source with polygon data
			map.addSource(sourceId, {
				type: 'geojson',
				data: {
					type: 'Feature',
					geometry: {
						type: 'Polygon',
						coordinates: [polygon.coordinates]
					},
					properties: {}
				}
			})

			// Add fill layer
			map.addLayer({
				id: layerId,
				type: 'fill',
				source: sourceId,
				paint: {
					'fill-color': '#0d9488',
					'fill-opacity': 0.2
				}
			})

			// Add outline layer
			map.addLayer({
				id: `${layerId}-outline`,
				type: 'line',
				source: sourceId,
				paint: {
					'line-color': '#0d9488',
					'line-width': 3,
					'line-opacity': 1
				}
			})

			areaPolygonLayer = layerId
		} catch (error) {
			console.error('Error drawing polygon:', error)
		}
	}

	if (map.isStyleLoaded()) {
		drawPolygon()
	} else {
		map.once('styledata', drawPolygon)
	}
}

// Add building pin markers to map
function addBuildingMarkers(pins: GeoPin[]) {
	if (!map) return

	currentBuildingPins = [...pins]
	_clearBuildingMarkers()

	pins.forEach((pin) => {
		const currentMap = map
		if (!currentMap) return
		const markerEl = document.createElement('div')
		markerEl.style.cssText =
			'cursor: pointer; display: flex; flex-direction: column; align-items: center;'
		markerEl.innerHTML = `
				<svg width="28" height="36" viewBox="0 0 28 36" fill="none" xmlns="http://www.w3.org/2000/svg">
					<path d="M14 0C6.268 0 0 6.268 0 14C0 24.5 14 36 14 36C14 36 28 24.5 28 14C28 6.268 21.732 0 14 0Z" fill="#0d9488"/>
					<circle cx="14" cy="14" r="6" fill="white"/>
				</svg>
			`

		const label = pin.building_name || pin.project_name
		const popup = new maplibregl.Popup({
			offset: [0, -38],
			closeButton: false,
			closeOnClick: false,
			className: 'building-popup'
		}).setHTML(
			`<div style="font-size:13px;font-weight:600;color:var(--color-map-popup-fg);white-space:nowrap;padding:2px 0;">${label}</div>`
		)

		const marker = new maplibregl.Marker({ element: markerEl })
			.setLngLat([pin.longitude, pin.latitude])
			.addTo(currentMap)

		markerEl.addEventListener('mouseenter', () =>
			popup.addTo(currentMap).setLngLat([pin.longitude, pin.latitude])
		)
		markerEl.addEventListener('mouseleave', () => popup.remove())
		markerEl.addEventListener('click', () => onBuildingPinClick?.(pin))

		buildingMarkers.push(marker)
		buildingPopups.push(popup)
	})
}

// Add or update a marker on the map
export function addProjectMarker(
	projectId: number,
	projectName: string,
	latitude: number,
	longitude: number
) {
	if (!map) return
	currentProjectMarkerInput = { projectId, projectName, latitude, longitude }

	// Remove previous marker if exists
	if (currentMarker) {
		currentMarker.remove()
	}

	// Create marker element
	const markerEl = document.createElement('div')
	markerEl.className =
		'w-10 h-10 bg-[#1c344a] rounded-full flex items-center justify-center shadow-lg border-2 border-white cursor-pointer hover:bg-[#0b1b2b] transition-colors'
	markerEl.innerHTML = `
			<svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
				<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16z" clip-rule="evenodd" />
			</svg>
		`

	// Create and add marker to map
	const marker = new maplibregl.Marker({ element: markerEl })
		.setLngLat([longitude, latitude])
		.addTo(map)

	// Create popup
	const popup = new maplibregl.Popup({ offset: 25, className: 'building-popup' }).setHTML(
		`<div style="font-size:13px;font-weight:600;color:var(--color-map-popup-fg);">${projectName}</div>`
	)

	marker.setPopup(popup)

	// Store current marker
	currentMarker = marker

	// Store in project markers map
	projectMarkers.set(projectId, {
		projectId,
		projectName,
		latitude,
		longitude,
		marker
	})
}

// Clear all markers and polygon
export function clearMarkers() {
	currentProjectMarkerInput = null
	currentAreaPolygon = null
	currentBuildingPins = []
	currentFitBoundsPins = []
	_clearProjectMarkers()
	_clearBuildingMarkers()
	_removeAreaPolygon()
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
		console.error('Map not initialized')
		return
	}

	// Clear previous markers
	clearMarkers()

	// Fly to location
	map.flyTo({ center: [longitude, latitude], zoom, duration: 2000 })

	// Add main project marker
	addProjectMarker(projectId, projectName, latitude, longitude)

	if ((areaPolygon?.coordinates?.length ?? 0) > 0 && areaPolygon) {
		drawAreaPolygon(areaPolygon)
	}

	// Add building pin markers if available
	if (geoPins && geoPins.length > 0) {
		addBuildingMarkers(geoPins)
	}
}

export function flyToLocation(lng: number, lat: number, zoom: number = 14) {
	map?.flyTo({ center: [lng, lat], zoom })
}

function handleDDAPlotClick(e: maplibregl.MapLayerMouseEvent) {
	const props = e.features?.[0]?.properties
	if (!props || !map) return
	const areaSqm = Number(props.plot_area_sqm)
	const areaLabel =
		areaSqm >= 1000 ? `${(areaSqm / 1000).toFixed(1)}k sqm` : `${Math.round(areaSqm)} sqm`
	new maplibregl.Popup({ className: 'building-popup' })
		.setLngLat(e.lngLat)
		.setHTML(
			`<div style="font-size:12px;line-height:1.6;">` +
				`<div style="font-weight:700;color:var(--color-map-popup-fg);">Plot ${props.plot_number}</div>` +
				`<div style="color:var(--color-map-popup-muted);margin-top:2px;">${areaLabel} · ${props.community_name}</div>` +
				`</div>`
		)
		.addTo(map)
}

function handleDDAPlotMouseEnter() {
	if (map) map.getCanvas().style.cursor = 'pointer'
}

function handleDDAPlotMouseLeave() {
	if (map) map.getCanvas().style.cursor = ''
}

function _unbindDDAHandlers() {
	if (!map) return
	try {
		map.off('click', 'dda-plots-fill', handleDDAPlotClick)
		map.off('mouseenter', 'dda-plots-fill', handleDDAPlotMouseEnter)
		map.off('mouseleave', 'dda-plots-fill', handleDDAPlotMouseLeave)
	} catch (_e) {
		// Handlers may not be bound yet.
	}
}

function _bindDDAHandlers() {
	if (!map) return
	_unbindDDAHandlers()
	map.on('click', 'dda-plots-fill', handleDDAPlotClick)
	map.on('mouseenter', 'dda-plots-fill', handleDDAPlotMouseEnter)
	map.on('mouseleave', 'dda-plots-fill', handleDDAPlotMouseLeave)
}

function _removeDDALayers() {
	if (!map) return
	try {
		_unbindDDAHandlers()
		if (map.getLayer('dda-plots-fill')) map.removeLayer('dda-plots-fill')
		if (map.getLayer('dda-plots-outline')) map.removeLayer('dda-plots-outline')
		if (map.getSource('dda-plots')) map.removeSource('dda-plots')
	} catch (_e) {}
}

export function showDDAPlots(plots: DdaPlotFeature[]) {
	if (!map) return
	const requestedPlots = [...plots]
	currentDDAPlots = requestedPlots

	const render = () => {
		if (!map) return
		if (currentDDAPlots !== requestedPlots) return
		_removeDDALayers()
		if (requestedPlots.length === 0) return

		const geojson: GeoJSON.FeatureCollection = {
			type: 'FeatureCollection',
			features: requestedPlots.map((plot) => ({
				type: 'Feature',
				geometry: { type: 'Polygon', coordinates: [plot.coordinates] },
				properties: {
					plot_number: plot.plot_number,
					plot_area_sqm: plot.plot_area_sqm,
					community_name: plot.community_name
				}
			}))
		}

		map.addSource('dda-plots', { type: 'geojson', data: geojson })

		const beforeId = map.getLayer('area-polygon-layer') ? 'area-polygon-layer' : undefined
		map.addLayer(
			{
				id: 'dda-plots-fill',
				type: 'fill',
				source: 'dda-plots',
				paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.12 }
			},
			beforeId
		)
		map.addLayer(
			{
				id: 'dda-plots-outline',
				type: 'line',
				source: 'dda-plots',
				paint: { 'line-color': '#d97706', 'line-width': 1.5, 'line-opacity': 0.8 }
			},
			beforeId
		)

		_bindDDAHandlers()
	}

	if (map.isStyleLoaded()) {
		render()
	} else {
		map.once('styledata', render)
	}
}

export function hideDDAPlots() {
	currentDDAPlots = []
	_removeDDALayers()
}

// Show all building pins for a master project and fit map to their bounds
export function fitBounds(pins: GeoPin[]) {
	if (!map || pins.length === 0) return
	clearMarkers()
	currentFitBoundsPins = [...pins]
	addBuildingMarkers(pins)
	fitMapToPins(pins)
}
</script>

<div class="w-full h-full relative" style="min-height: 400px;">
	<div bind:this={mapContainer} class="absolute inset-0" style="width: 100%; height: 100%;"></div>
</div>
