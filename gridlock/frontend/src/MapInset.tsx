import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { Map as MLMap } from 'maplibre-gl'
// MapLibre derives its worker via `new URL('./maplibre-gl-worker.mjs', import.meta.url)`.
// Vite's dep prebundle rewrites import.meta.url to /node_modules/.vite/deps/maplibre-gl.js,
// where the worker file doesn't exist → 404 → worker dead → map can never paint.
// Pin the real file (dev serves it, build emits it as an asset).
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { FeatureCollection } from 'geojson'
import { useStore } from './store'
import { EXCLUDED_OPACITY, TIER_HALO, TIER_LABEL, UTILITY } from './palette'

maplibregl.setWorkerUrl(workerUrl)

// OpenFreeMap Liberty — free, no API key (START-GATE 04-1, user-supplied).
const STYLE = 'https://tiles.openfreemap.org/styles/liberty'

// No-tile fallback: plain background so data layers still render when the
// remote style is unreachable (offline / blocked).
const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [
    { id: 'bg', type: 'background' as const, paint: { 'background-color': '#e3e9ef' } },
  ],
} as maplibregl.StyleSpecification

const haloColor = [
  'match', ['get', 'tier'],
  'crossing', TIER_HALO.crossing,
  '<1.6 km', TIER_HALO['<1.6 km'],
  '<8 km', TIER_HALO['<8 km'],
  '<40 km', TIER_HALO['<40 km'],
  TIER_HALO.excluded,
] as const

const utilityColor = ['match', ['get', 'util'], 'GPC', UTILITY.GPC, UTILITY.DESC] as const

export default function MapInset() {
  const hostRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const rows = useStore((s) => s.rows)
  const projects = useStore((s) => s.projects)
  const hoverId = useStore((s) => s.hoverId)
  const selectedId = useStore((s) => s.selectedId)
  const expanded = useStore((s) => s.mapExpanded)
  const select = useStore((s) => s.select)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const [showProjects, setShowProjects] = useState(true)
  const [webgl2, setWebgl2] = useState(true)
  const applyRef = useRef<() => void>(() => {})

  // init once
  useEffect(() => {
    if (!hostRef.current) return
    // MapLibre v6 hard-requires WebGL2 — guard instead of a silent blank pane.
    if (!document.createElement('canvas').getContext('webgl2')) {
      setWebgl2(false)
      return
    }
    const map = new maplibregl.Map({
      container: hostRef.current,
      style: STYLE,
      center: [-81.35, 33.75],
      zoom: 6.3,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left')
    mapRef.current = map

    // Effect-closure locals (not refs — StrictMode remounts must re-arm).
    let styleLoaded = false
    let fellBack = false
    map.on('error', (e) => {
      if (styleLoaded) {
        console.warn('[map]', e.error)
        return
      }
      // First style unreachable → swap once to the no-tile fallback.
      if (fellBack) return
      fellBack = true
      console.warn('[map] style failed, falling back to plain background:', e.error)
      map.setStyle(FALLBACK_STYLE)
    })
    // Fires on initial style load AND after any setStyle swap.
    map.on('style.load', () => {
      styleLoaded = true
      applyRef.current()
    })

    // Delegated listeners live on the Map and survive setStyle — register
    // exactly once here (registering inside apply() would duplicate them).
    map.on('mouseenter', 'halos', () => (map.getCanvas().style.cursor = 'pointer'))
    map.on('mouseleave', 'halos', () => (map.getCanvas().style.cursor = ''))
    map.on('click', 'halos', (e) => {
      const f = e.features?.[0]
      if (f?.properties?.id) select(f.properties.id as string)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [select])

  // sources + layers (style is async; run once data lands)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !rows.length) return

    const apply = () => {
      const projFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: projects.map((p) => ({
          type: 'Feature',
          properties: {
            util: p.utility.startsWith('Georgia') ? 'GPC' : 'DESC',
            id: p.project_id,
          },
          geometry: p.geometry as FeatureCollection['features'][number]['geometry'],
        })),
      }
      const haloFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: rows.map((r) => ({
          type: 'Feature',
          properties: { id: r.overlap_id, tier: r.tier },
          geometry: r.shortest_line,
        })),
      }

      const src = map.getSource('projects')
      if (src && 'setData' in src) {
        ;(src as { setData: (d: unknown) => void }).setData(projFC)
      } else {
        map.addSource('projects', { type: 'geojson', data: projFC })
        map.addLayer({
          id: 'project-lines',
          type: 'line',
          source: 'projects',
          filter: ['==', ['geometry-type'], 'LineString'],
          paint: {
            'line-color': utilityColor as unknown as string,
            'line-width': 1.4,
            'line-opacity': 0.75,
          },
        })
        map.addLayer({
          id: 'project-points',
          type: 'circle',
          source: 'projects',
          filter: ['==', ['geometry-type'], 'Point'],
          paint: {
            'circle-radius': 3.5,
            'circle-color': utilityColor as unknown as string,
            'circle-opacity': 0.8,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#ffffff',
          },
        })
      }

      if (!map.getSource('overlaps')) {
        map.addSource('overlaps', { type: 'geojson', data: haloFC })
        // glow casing — sits under the crisp halo line
        map.addLayer({
          id: 'halo-focus',
          type: 'line',
          source: 'overlaps',
          filter: ['==', ['get', 'id'], ''],
          paint: {
            'line-color': haloColor as unknown as string,
            'line-width': 10,
            'line-opacity': 0.35,
            'line-blur': 1.5,
          },
        })
        map.addLayer({
          id: 'halos',
          type: 'line',
          source: 'overlaps',
          paint: {
            'line-color': haloColor as unknown as string,
            'line-width': 3.5,
            'line-opacity': [
              'case',
              ['==', ['get', 'tier'], 'excluded'],
              EXCLUDED_OPACITY,
              0.95,
            ],
          },
        })
      } else {
        const ovl = map.getSource('overlaps')
        if (ovl && 'setData' in ovl) (ovl as { setData: (d: unknown) => void }).setData(haloFC)
      }
    }

    // style.load (init effect) invokes the latest apply; also apply now if
    // the style is already up (e.g. data arrived after load).
    applyRef.current = apply
    if (map.isStyleLoaded()) apply()
  }, [rows, projects, select])

  // two-way sync: focus + flyTo on hover/selection
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('halo-focus')) return
    const focus = selectedId ?? hoverId
    map.setFilter('halo-focus', ['==', ['get', 'id'], focus ?? ''])
    if (!focus) return
    const row = rows.find((r) => r.overlap_id === focus)
    const coords = row?.shortest_line.coordinates
    if (!coords?.length) return
    const xs = coords.map((c) => c[0])
    const ys = coords.map((c) => c[1])
    map.fitBounds(
      [
        [Math.min(...xs), Math.min(...ys)],
        [Math.max(...xs), Math.max(...ys)],
      ],
      { padding: 90, maxZoom: 10.5, duration: 700, essential: true },
    )
  }, [hoverId, selectedId, rows])

  // fullscreen expand needs a resize pass
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const t = setTimeout(() => map.resize(), 60)
    return () => clearTimeout(t)
  }, [expanded])

  const toggleProjects = () => {
    const map = mapRef.current
    const next = !showProjects
    setShowProjects(next)
    if (map) {
      for (const id of ['project-lines', 'project-points']) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', next ? 'visible' : 'none')
      }
    }
  }

  const chip =
    'h-7 px-2 rounded border border-rule bg-surface/95 text-[11px] font-medium shadow-sm hover:bg-surface-3'

  return (
    <div
      className={
        expanded ? 'fixed inset-0 z-40 bg-surface map-host' : 'absolute inset-0 map-host'
      }
    >
      {webgl2 ? (
        // h-full/w-full, not absolute inset-0: maplibre-gl.css forces
        // .maplibregl-map { position: relative }, which would kill inset-0
        // sizing and collapse the container to 0 height → blank pane.
        <div ref={hostRef} className="h-full w-full" />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-[13px] text-ink-dim">
          Map needs WebGL2 — unavailable in this browser.
        </div>
      )}

      {/* legend — always visible at all zooms */}
      <div className="absolute bottom-6 left-2 z-10 rounded border border-rule bg-surface/95 px-2.5 py-2 text-[10.5px] shadow-sm backdrop-blur">
        <div className="mb-1 font-semibold tracking-wide text-ink-dim uppercase">Distance tier</div>
        {(['crossing', '<1.6 km', '<8 km', '<40 km'] as const).map((t) => (
          <div key={t} className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: TIER_HALO[t] }} />
            {TIER_LABEL[t]}
          </div>
        ))}
        <div className="flex items-center gap-1.5 opacity-50">
          <span className="inline-block h-0.5 w-4" style={{ background: TIER_HALO.excluded }} />
          excluded &gt;40 km
        </div>
        <div className="my-1.5 h-px bg-rule" />
        <div className="mb-1 font-semibold tracking-wide text-ink-dim uppercase">Utility</div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4" style={{ background: UTILITY.DESC }} />
          Dominion (DESC)
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4" style={{ background: UTILITY.GPC }} />
          Georgia Power (GPC)
        </div>
      </div>

      {/* [+/-] [layers] [fullscreen] */}
      <div className="absolute top-2 right-2 z-10 flex gap-1.5">
        <button className={chip} onClick={toggleProjects} title="Toggle project corridors">
          {showProjects ? 'hide' : 'show'} corridors
        </button>
        <button
          className={chip}
          onClick={() => setMapExpanded(!expanded)}
          title="Required pan/zoom/click demo moment"
        >
          {expanded ? 'exit fullscreen' : 'expand map'}
        </button>
      </div>
    </div>
  )
}
