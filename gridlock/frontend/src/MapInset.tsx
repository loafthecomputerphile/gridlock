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

// Pair zone: circle centered at the gap midpoint with DIAMETER = the tier's
// km limit (user spec) — tiering guarantees d < limit, so both projects sit
// inside. crossing → no circle (rendered as a dot below).
const TIER_DIAMETER_M: Record<string, number | undefined> = {
  '<1.6 km': 1600,
  '<8 km': 8000,
  '<40 km': 40000,
  excluded: 40000,
}

// Ring around a point, radius in meters. ponytail: equirectangular degrees —
// <0.1% error at the ≤20 km radii we use; go spherical only if precision complaints.
const circleRing = (lon: number, lat: number, r: number): [number, number][] => {
  const dLat = r / 111320
  const dLon = r / (111320 * Math.cos((lat * Math.PI) / 180))
  const pts: [number, number][] = []
  for (let i = 0; i < 64; i++) {
    const a = (i / 64) * 2 * Math.PI
    pts.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)])
  }
  pts.push(pts[0])
  return pts
}

// Base circles sit dim; pair-circle-focus/halo-dot-focus pop the hovered/selected pair.
// 0.35 was invisible for the pale <40/<8 tiers on the light basemap (user bug:
// "cannot see 8 and 40 km lines when selected") — 0.65 keeps focus distinct.
const DIM_OPACITY = 0.65
const tierVisible = (hidden: string[]) =>
  ['!', ['in', ['get', 'tier'], ['literal', hidden]]] as unknown as maplibregl.ExpressionSpecification

export default function MapInset() {
  const hostRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const rows = useStore((s) => s.rows)
  const projects = useStore((s) => s.projects)
  const hoverId = useStore((s) => s.hoverId)
  const selectedId = useStore((s) => s.selectedId)
  const expanded = useStore((s) => s.mapExpanded)
  const hiddenTiers = useStore((s) => s.hiddenTiers)
  const select = useStore((s) => s.select)
  const setHover = useStore((s) => s.setHover)
  const toggleTier = useStore((s) => s.toggleTier)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const [showProjects, setShowProjects] = useState(true)
  const [showHifld, setShowHifld] = useState(true)
  const [hifldStatus, setHifldStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [legendOpen, setLegendOpen] = useState(true)
  const [webgl2, setWebgl2] = useState(true)
  const applyRef = useRef<() => void>(() => {})
  // HIFLD reference overlay (user request): fetched once, applied when ready
  const hifldRef = useRef<FeatureCollection | null>(null)
  const hifldLoading = useRef(false)
  // toggle intent lives in a ref so layer creation (async, after fetch) reads
  // the CURRENT choice even when the user toggled before the fetch resolved
  const hifldVisRef = useRef(true)

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
    // ponytail: dev-only probe hook for headless browser checks (stripped from prod builds)
    if (import.meta.env.DEV) (window as unknown as { __map?: MLMap }).__map = map

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
    map.on('mouseenter', 'pair-circles', (e) => {
      map.getCanvas().style.cursor = 'pointer'
      setHover((e.features?.[0]?.properties?.id as string | undefined) ?? null)
    })
    map.on('mouseleave', 'pair-circles', () => {
      map.getCanvas().style.cursor = ''
      setHover(null)
    })
    map.on('click', 'pair-circles', (e) => {
      const f = e.features?.[0]
      if (f?.properties?.id) select(f.properties.id as string)
    })
    map.on('mouseenter', 'halo-dots', (e) => {
      map.getCanvas().style.cursor = 'pointer'
      setHover((e.features?.[0]?.properties?.id as string | undefined) ?? null)
    })
    map.on('mouseleave', 'halo-dots', () => {
      map.getCanvas().style.cursor = ''
      setHover(null)
    })
    map.on('click', 'halo-dots', (e) => {
      const f = e.features?.[0]
      if (f?.properties?.id) select(f.properties.id as string)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [select, setHover])

  // HIFLD overlay: fetched on its own (NOT gated on /api/overlaps rows) so a
  // slow or failing 9 MB fetch can't be silently skipped — status surfaces in a chip.
  useEffect(() => {
    if (hifldLoading.current || hifldRef.current) return
    hifldLoading.current = true
    fetch('/api/ref/hifld-lines')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((fc: FeatureCollection) => {
        hifldLoading.current = false
        if (!fc?.features?.length) throw new Error('empty FeatureCollection')
        hifldRef.current = fc
        setHifldStatus('ok')
        // no-op if the data effect hasn't run yet — it picks the ref up when it does
        applyRef.current()
      })
      .catch((e) => {
        hifldLoading.current = false
        setHifldStatus('error')
        console.warn('[map] HIFLD fetch failed:', e)
      })
  }, [])

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
          // crossing pairs have zero-length lines → render as a dot at the touch point
          geometry:
            r.tier === 'crossing'
              ? ({ type: 'Point', coordinates: r.shortest_line.coordinates[0] } as const)
              : r.shortest_line,
        })),
      }
      // pair zones: tier-limit-diameter circle around each non-crossing pair
      const circleFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: rows.flatMap((r) => {
          const dia = TIER_DIAMETER_M[r.tier]
          if (dia === undefined) return [] // crossing → dot only
          const [a, b] = r.shortest_line.coordinates
          return [
            {
              type: 'Feature' as const,
              properties: { id: r.overlap_id, tier: r.tier },
              geometry: {
                type: 'Polygon' as const,
                coordinates: [circleRing((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, dia / 2)],
              },
            },
          ]
        }),
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

      // pair zone circles — inserted under corridors (hifld → circles → corridors,
      // bottom to top) so the translucent fills never mute the proposals
      const circleBefore = map.getLayer('project-lines') ? 'project-lines' : undefined
      if (!map.getSource('pair-circles')) {
        const { hiddenTiers, hoverId, selectedId } = useStore.getState()
        const focus = hoverId ?? selectedId ?? ''
        const vis = tierVisible(hiddenTiers)
        map.addSource('pair-circles', { type: 'geojson', data: circleFC })
        map.addLayer(
          {
            id: 'pair-circles',
            type: 'fill',
            source: 'pair-circles',
            filter: ['all', ['!=', ['get', 'tier'], 'crossing'], vis],
            paint: { 'fill-color': haloColor as unknown as string, 'fill-opacity': 0.1 },
          },
          circleBefore,
        )
        map.addLayer(
          {
            id: 'pair-circle-edge',
            type: 'line',
            source: 'pair-circles',
            filter: ['all', ['!=', ['get', 'tier'], 'crossing'], vis],
            paint: {
              'line-color': haloColor as unknown as string,
              'line-width': 1.5,
              'line-opacity': [
                'case',
                ['==', ['get', 'tier'], 'excluded'],
                EXCLUDED_OPACITY,
                // palest color needs the most opacity to read on light basemap
                ['==', ['get', 'tier'], '<40 km'],
                0.8,
                DIM_OPACITY,
              ],
            },
          },
          circleBefore,
        )
        map.addLayer(
          {
            id: 'pair-circle-focus',
            type: 'line',
            source: 'pair-circles',
            filter: ['all', ['==', ['get', 'id'], focus], ['!=', ['get', 'tier'], 'crossing'], vis],
            paint: {
              'line-color': haloColor as unknown as string,
              'line-width': 3,
              'line-opacity': 0.9,
            },
          },
          circleBefore,
        )
      } else {
        const cs = map.getSource('pair-circles')
        if (cs && 'setData' in cs) (cs as { setData: (d: unknown) => void }).setData(circleFC)
      }

      if (!map.getSource('overlaps')) {
        map.addSource('overlaps', { type: 'geojson', data: haloFC })
        // Fresh state at creation; the spotlight effect re-applies on change.
        const { hiddenTiers, hoverId, selectedId } = useStore.getState()
        const focus = hoverId ?? selectedId ?? ''
        const vis = tierVisible(hiddenTiers)
        // touching pairs are zero-length lines → draw as dots
        map.addLayer({
          id: 'halo-dots',
          type: 'circle',
          source: 'overlaps',
          filter: ['all', ['==', ['get', 'tier'], 'crossing'], vis],
          paint: {
            'circle-radius': 4,
            'circle-opacity': 0.55,
            'circle-color': haloColor as unknown as string,
          },
        })
        map.addLayer({
          id: 'halo-dot-focus',
          type: 'circle',
          source: 'overlaps',
          filter: ['all', ['==', ['get', 'id'], focus], ['==', ['get', 'tier'], 'crossing'], vis],
          paint: {
            'circle-radius': 8.5,
            'circle-opacity': 1,
            'circle-color': haloColor as unknown as string,
            'circle-stroke-width': 1.5,
            'circle-stroke-color': '#ffffff',
          },
        })
      } else {
        const ovl = map.getSource('overlaps')
        if (ovl && 'setData' in ovl) (ovl as { setData: (d: unknown) => void }).setData(haloFC)
      }

      // HIFLD reference lines — sits under our corridors (beforeId), muted slate
      if (hifldRef.current) {
        const hs = map.getSource('hifld-lines')
        if (hs && 'setData' in hs) {
          ;(hs as { setData: (d: unknown) => void }).setData(hifldRef.current)
        } else {
          map.addSource('hifld-lines', { type: 'geojson', data: hifldRef.current })
          map.addLayer(
            {
              id: 'hifld-lines',
              type: 'line',
              source: 'hifld-lines',
              layout: {
                visibility: hifldVisRef.current ? 'visible' : 'none',
              },
              paint: {
                'line-color': '#64748b',
                'line-opacity': 0.65,
                // 31% of lines are 'NOT AVAILABLE'/'Under 100' and fell to the
                // 0.7px default = invisible at default zoom 6.3 — floor everything
                'line-width': [
                  'match',
                  ['get', 'VOLT_CLASS'],
                  '500', 2.6,
                  '220-287', 2.0,
                  '100-161', 1.4,
                  'Under 100', 1.0,
                  'NOT AVAILABLE', 1.0,
                  1.0,
                ],
              },
            },
            // under our corridors so overlay never buries the proposal
            map.getLayer('project-lines') ? 'project-lines' : undefined,
          )
        }
      }
    }

    // style.load (init effect) invokes the latest apply; also apply now if
    // the style is already up (e.g. data arrived after load).
    applyRef.current = apply
    if (map.isStyleLoaded()) apply()
  }, [rows, projects, select])

  // spotlight + tier visibility (filters only — hover never moves the camera)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('pair-circle-edge') || !map.getLayer('halo-dots')) return
    const focus = hoverId ?? selectedId ?? ''
    const vis = tierVisible(hiddenTiers)
    const notCrossing = ['!=', ['get', 'tier'], 'crossing'] as const
    map.setFilter('pair-circles', ['all', notCrossing, vis] as never)
    map.setFilter('pair-circle-edge', ['all', notCrossing, vis] as never)
    map.setFilter(
      'pair-circle-focus',
      ['all', ['==', ['get', 'id'], focus], notCrossing, vis] as never,
    )
    map.setFilter('halo-dots', ['all', ['==', ['get', 'tier'], 'crossing'], vis] as never)
    map.setFilter(
      'halo-dot-focus',
      ['all', ['==', ['get', 'id'], focus], ['==', ['get', 'tier'], 'crossing'], vis] as never,
    )
  }, [hoverId, selectedId, hiddenTiers])

  // camera moves on selection only
  useEffect(() => {
    const map = mapRef.current
    if (!map || !selectedId) return
    const row = rows.find((r) => r.overlap_id === selectedId)
    const coords = row?.shortest_line.coordinates
    if (!row || !coords?.length) return
    // frame the whole pair circle when one exists, else the gap segment (crossing)
    const dia = TIER_DIAMETER_M[row.tier]
    let xs: number[]
    let ys: number[]
    if (dia) {
      const [a, b] = coords
      const mLon = (a[0] + b[0]) / 2
      const mLat = (a[1] + b[1]) / 2
      const rad = dia / 2
      const dLat = rad / 111320
      const dLon = rad / (111320 * Math.cos((mLat * Math.PI) / 180))
      xs = [mLon - dLon, mLon + dLon]
      ys = [mLat - dLat, mLat + dLat]
    } else {
      xs = coords.map((c) => c[0])
      ys = coords.map((c) => c[1])
    }
    map.fitBounds(
      [
        [Math.min(...xs), Math.min(...ys)],
        [Math.max(...xs), Math.max(...ys)],
      ],
      { padding: 90, maxZoom: 10.5, duration: 700, essential: true },
    )
  }, [selectedId, rows])

  // fullscreen expand needs a resize pass
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const t = setTimeout(() => map.resize(), 60)
    return () => clearTimeout(t)
  }, [expanded])

  // HIFLD overlay toggle — always record intent in the ref (layer creation
  // reads it), push to the layer only once it exists
  useEffect(() => {
    hifldVisRef.current = showHifld
    const map = mapRef.current
    if (!map || !map.getLayer('hifld-lines')) return
    map.setLayoutProperty('hifld-lines', 'visibility', showHifld ? 'visible' : 'none')
  }, [showHifld])

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

  // legend counts for the grounding section (geometry_source per project)
  const counts = { osm_snapped: 0, buffered_estimate: 0, straight_fallback: 0 }
  for (const p of projects) {
    if (p.geometry_source in counts) counts[p.geometry_source as keyof typeof counts]++
  }

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

      {/* legend — collapsible so it doesn't block the map */}
      {legendOpen ? (
      <div className="absolute bottom-6 left-2 z-10 rounded border border-rule bg-surface/95 px-2.5 py-2 text-[10.5px] shadow-sm backdrop-blur">
        <button
          className="mb-1 flex w-full items-center justify-between font-semibold tracking-wide text-ink-dim uppercase hover:text-ink"
          onClick={() => setLegendOpen(false)}
          title="Collapse legend"
        >
          <span>
            Distance tier <span className="font-normal normal-case">· click to toggle</span>
          </span>
          <span className="ml-2 text-[12px]">–</span>
        </button>
        {(['crossing', '<1.6 km', '<8 km', '<40 km', 'excluded'] as const).map((t) => {
          const on = !hiddenTiers.includes(t)
          return (
            <button
              key={t}
              onClick={() => toggleTier(t)}
              aria-pressed={on}
              title={on ? 'Hide this tier on the map' : 'Show this tier on the map'}
              className={`flex w-full items-center gap-1.5 rounded px-0.5 text-left hover:bg-surface-3 ${
                on ? '' : 'opacity-40'
              }`}
            >
              <span className="inline-block h-0.5 w-4" style={{ background: TIER_HALO[t] }} />
              <span className={on ? '' : 'line-through'}>{TIER_LABEL[t]}</span>
            </button>
          )
        })}
        <div className="my-1.5 h-px bg-rule" />
        <div className="mb-1 font-semibold tracking-wide text-ink-dim uppercase">What you see</div>
        <div
          className="flex items-start gap-1.5"
          title="HIFLD_US_Electric_Power_Transmission_Lines (HIFLD/ORNL), SC/GA bbox subset, width by VOLT_CLASS. Reference only — corridor scoring never uses it."
        >
          <span className="text-ink-dim">┃</span>
          <span>grey lines: HIFLD existing transmission network (reference)</span>
        </div>
        <div className="flex items-start gap-1.5">
          <span className="text-ink-dim">—</span>
          <span>thin line: transmission corridor — the power lines between two points</span>
        </div>
        <div
          className="flex items-start gap-1.5"
          title="Point features sit at the one geocoded endpoint (often a substation or line terminal) or an approximate project center — not a dedicated substation layer."
        >
          <span className="text-ink-dim">●</span>
          <span>dot: single-endpoint project, or a touching pair (tier color)</span>
        </div>
        <div
          className="flex items-start gap-1.5"
          title="Circle centered between the two projects; its diameter is the tier limit itself (1.6 / 8 / 40 km), so both projects always sit inside."
        >
          <span className="text-ink-dim">◯</span>
          <span>circle: pair zone — diameter = tier limit (1.6 / 8 / 40 km), color = tier</span>
        </div>
        <div className="flex items-start gap-1.5">
          <span className="text-ink-dim">✦</span>
          <span>bright glow: hovered / selected pair — hover a row or a circle</span>
        </div>
        <div className="my-1.5 h-px bg-rule" />
        <div className="mb-1 font-semibold tracking-wide text-ink-dim uppercase">Corridor grounding</div>
        <div
          className="flex items-start gap-1.5"
          title="Guide-only location policy (DATA-NOTES §6): projects the Finding guide could not locate are excluded from the map and pairs, not plotted at a guessed point."
        >
          <span className="text-ink-dim">▣</span>
          <span>projects on map: {projects.length}</span>
        </div>
        <div
          className="flex items-start gap-1.5"
          title="geometry_source=osm_snapped — corridor follows an actual OSM power=line way within 10 km (routing proxy), snap distance on the detail drawer."
        >
          <span className="text-ink-dim">≈</span>
          <span>snapped: routed along a real OSM power line ({counts.osm_snapped})</span>
        </div>
        <div
          className="flex items-start gap-1.5"
          title="geometry_source=buffered_estimate — no OSM power line within 10 km; straight corridor kept with a declared 10 km uncertainty buffer."
        >
          <span className="text-ink-dim">~</span>
          <span>buffered: straight sketch ±10 km, no OSM line nearby ({counts.buffered_estimate})</span>
        </div>
        <div
          className="flex items-start gap-1.5"
          title="geometry_source=straight_fallback — single-endpoint project with no OSM power line within 10 km; plotted at its geocoded point."
        >
          <span className="text-ink-dim">·</span>
          <span>fallback: single point, no OSM line nearby ({counts.straight_fallback})</span>
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
      ) : (
        <button
          className={`absolute bottom-6 left-2 z-10 ${chip}`}
          onClick={() => setLegendOpen(true)}
          title="Show legend"
        >
          legend ▲
        </button>
      )}

      {/* [+/-] [layers] [fullscreen] */}
      <div className="absolute top-2 right-2 z-10 flex gap-1.5">
        <button className={chip} onClick={toggleProjects} title="Toggle project corridors">
          {showProjects ? 'hide' : 'show'} corridors
        </button>
        {hifldStatus === 'loading' && (
          <span className={`${chip} text-ink-dim`} title="Fetching HIFLD transmission overlay…">
            HIFLD loading…
          </span>
        )}
        {hifldStatus === 'error' && (
          <span
            className={chip}
            title="HIFLD overlay unavailable — is the backend running on :8000? If the cache is missing run: uv run python backend/fetch_hifld_lines.py"
          >
            HIFLD unavailable
          </span>
        )}
        <button
          className={chip}
          onClick={() => setShowHifld((v) => !v)}
          title="Toggle HIFLD existing transmission lines (HIFLD/ORNL, SC/GA subset)"
        >
          {showHifld ? 'hide' : 'show'} HIFLD
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
