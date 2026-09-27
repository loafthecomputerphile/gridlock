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

// dome height (m) per tier for the extruded pair-zone puck
const tierHeight = [
  'match', ['get', 'tier'],
  '<1.6 km', 900,
  '<8 km', 1600,
  '<40 km', 2600,
  2000,
] as const

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
  const selectProject = useStore((s) => s.selectProject)
  const setHover = useStore((s) => s.setHover)
  const toggleTier = useStore((s) => s.toggleTier)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const [showHifld, setShowHifld] = useState(true)
  const [hifldStatus, setHifldStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [showOsm, setShowOsm] = useState(true)
  const [osmStatus, setOsmStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [legendOpen, setLegendOpen] = useState(true)
  const [webgl2, setWebgl2] = useState(true)
  const projMarkers = useRef<maplibregl.Marker[]>([])
  const applyRef = useRef<() => void>(() => {})
  // HIFLD reference overlay (user request): fetched once, applied when ready
  const hifldRef = useRef<FeatureCollection | null>(null)
  const hifldLoading = useRef(false)
  // toggle intent lives in a ref so layer creation (async, after fetch) reads
  // the CURRENT choice even when the user toggled before the fetch resolved
  const hifldVisRef = useRef(true)
  // OSM power=line overlay (Overpass GA/SC download) — same pattern as HIFLD
  const osmRef = useRef<FeatureCollection | null>(null)
  const osmLoading = useRef(false)
  const osmVisRef = useRef(true)

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
      // 3D: tilted camera so extrusions read as vertical
      pitch: 60,
      bearing: -18,
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
      projMarkers.current.forEach((m) => m.remove())
      projMarkers.current = []
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

  // OSM overlay: same independent fetch as HIFLD (10 MB — own status chip)
  useEffect(() => {
    if (osmLoading.current || osmRef.current) return
    osmLoading.current = true
    fetch('/api/ref/osm-lines')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((fc: FeatureCollection) => {
        osmLoading.current = false
        if (!fc?.features?.length) throw new Error('empty FeatureCollection')
        osmRef.current = fc
        setOsmStatus('ok')
        applyRef.current()
      })
      .catch((e) => {
        osmLoading.current = false
        setOsmStatus('error')
        console.warn('[map] OSM lines fetch failed:', e)
      })
  }, [])

  // sources + layers (style is async; run once data lands)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !rows.length) return

    const apply = () => {
      const projFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: projects.map((p) => {
          // full record rides along so icon hovers can show the rest of the data
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          const { geometry, ...meta } = p
          return {
            type: 'Feature',
            properties: {
              ...meta,
              util: p.utility.startsWith('Georgia') ? 'GPC' : 'DESC',
              id: p.project_id,
            },
            geometry: geometry as FeatureCollection['features'][number]['geometry'],
          }
        }),
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
      // gap-point dots: for the selected pair, one dot where each project's
      // corridor sits closest (shortest_line emits [on A, on B] → utilities order)
      const dotFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: rows.flatMap((r) =>
          r.tier === 'crossing'
            ? [] // touch dot already drawn by halo-dots
            : r.shortest_line.coordinates.map((c, i) => ({
                type: 'Feature' as const,
                properties: {
                  id: r.overlap_id,
                  tier: r.tier,
                  util: r.utilities[i] === 'Georgia Power' ? 'GPC' : 'DESC',
                },
                geometry: { type: 'Point' as const, coordinates: c },
              })),
        ),
      }

      const src = map.getSource('projects')
      if (src && 'setData' in src) {
        ;(src as { setData: (d: unknown) => void }).setData(projFC)
      } else {
        map.addSource('projects', { type: 'geojson', data: projFC })
        // corridor line layer removed (user: "remove all lines") — points only
        // flat dot layer suppressed: projects render as floating 3D icons below
        map.addLayer({
          id: 'project-points',
          type: 'circle',
          source: 'projects',
          filter: ['==', ['geometry-type'], 'Point'],
          layout: { visibility: 'none' },
          paint: { 'circle-radius': 0 },
        })
      }

      // hovering 3D project icons — every project gets one; non-point geometries
      // (corridor lines/polygons) anchor at their middle coordinate.
      // wrapper (MapLibre positions it via transform) + animated inner ball —
      // putting the animation on the marker element itself clobbers its position
      const midCoord = (g: unknown): [number, number] | null => {
        const leaves: [number, number][] = []
        const walk = (x: unknown) => {
          if (Array.isArray(x)) {
            if (typeof x[0] === 'number' && typeof x[1] === 'number') leaves.push([x[0], x[1]])
            else x.forEach(walk)
          } else if (x && typeof x === 'object') {
            Object.values(x).forEach(walk)
          }
        }
        walk(g)
        return leaves.length ? leaves[Math.floor(leaves.length / 2)] : null
      }
      projMarkers.current.forEach((m) => m.remove())
      projMarkers.current = projFC.features.flatMap((f) => {
        const pos = midCoord(f.geometry)
        if (!pos) return []
        const props = f.properties ?? {}
        const el = document.createElement('div')
        const ball = document.createElement('div')
        ball.className = 'proj-icon'
        ball.style.background = props.util === 'GPC' ? UTILITY.GPC : UTILITY.DESC
        // hover card: full project record (everything /api/projects returned)
        const tip = document.createElement('div')
        tip.className = 'proj-tip'
        const show: [string, unknown][] = [
          ['Name', props.name],
          ['ID', props.id],
          ['Utility', props.utility],
          ['Type', props.type],
          ['Voltage', props.voltage_kv],
          ['From', props.endpoint_a],
          ['To', props.endpoint_b],
          ['County', props.county],
          ['In service', props.in_service_date],
          ['Status', props.status],
          ['Cost', props.cost_usd],
          ['Sponsor', props.sponsor],
          ['Confidence', props.confidence],
          ['Grounding', props.geometry_source],
          ['Source', props.source_file ? `${props.source_file} p.${props.source_page}` : ''],
          ['Notes', props.notes],
        ]
        for (const [k, v] of show) {
          const s = v == null ? '' : String(v)
          if (!s) continue
          const row = document.createElement('div')
          row.className = 'proj-tip-row'
          const kk = document.createElement('span')
          kk.textContent = k
          const vv = document.createElement('span')
          vv.textContent = s
          row.append(kk, vv)
          tip.appendChild(row)
        }
        ball.onclick = () => selectProject(String(props.id))
        ball.onmouseenter = () => {
          tip.style.display = 'block'
          setHover(String(props.id))
        }
        ball.onmouseleave = () => {
          tip.style.display = 'none'
          setHover(null)
        }
        el.append(ball, tip)
        return [new maplibregl.Marker({ element: el }).setLngLat(pos).addTo(map)]
      })

      // pair zone circles — no corridor layer below anymore, HIFLD anchors under them
      const circleBefore: string | undefined = undefined
      if (!map.getSource('pair-circles')) {
        // circles + gap dots show ONLY for the clicked row (user spec) — an
        // explicit row click beats the tier chips, which still gate the many
        // crossing dots below
        const sel = ['==', ['get', 'id'], useStore.getState().selectedId ?? ''] as unknown as maplibregl.ExpressionSpecification
        map.addSource('pair-circles', { type: 'geojson', data: circleFC })
        map.addLayer(
          {
            id: 'pair-circles',
            type: 'fill-extrusion',
            source: 'pair-circles',
            filter: ['all', sel],
            paint: {
              'fill-extrusion-color': haloColor as unknown as string,
              'fill-extrusion-height': tierHeight as unknown as number,
              'fill-extrusion-base': 0,
              'fill-extrusion-opacity': 0.4,
            },
          },
          circleBefore,
        )
        map.addLayer(
          {
            id: 'pair-circle-edge',
            type: 'line',
            source: 'pair-circles',
            filter: ['all', sel],
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
            filter: ['all', sel],
            paint: {
              'line-color': haloColor as unknown as string,
              'line-width': 3,
              'line-opacity': 0.9,
            },
          },
          circleBefore,
        )
        map.addSource('pair-dots', { type: 'geojson', data: dotFC })
        map.addLayer(
          {
            id: 'pair-dots',
            type: 'circle',
            source: 'pair-dots',
            filter: ['all', sel],
            paint: {
              'circle-radius': 5,
              'circle-color': utilityColor as unknown as string,
              'circle-opacity': 0.9,
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#ffffff',
            },
          },
          circleBefore,
        )
      } else {
        const cs = map.getSource('pair-circles')
        if (cs && 'setData' in cs) (cs as { setData: (d: unknown) => void }).setData(circleFC)
        const ds = map.getSource('pair-dots')
        if (ds && 'setData' in ds) (ds as { setData: (d: unknown) => void }).setData(dotFC)
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

      // HIFLD reference lines — sits under the pair circles (beforeId), muted slate
      if (hifldRef.current) {
        const hs = map.getSource('hifld-lines')
        if (hs && 'setData' in hs) {
          ;(hs as { setData: (d: unknown) => void }).setData(hifldRef.current)
        } else {
          map.addSource('hifld-lines', { type: 'geojson', data: hifldRef.current })
          const before = map.getLayer('pair-circles') ? 'pair-circles' : undefined
          // white glow casing under the lines — reads as "lifted" at pitch
          // (MapLibre can't extrude lines; casing is the cheap stand-in)
          map.addLayer(
            {
              id: 'hifld-lines-glow',
              type: 'line',
              source: 'hifld-lines',
              layout: { visibility: hifldVisRef.current ? 'visible' : 'none' },
              paint: {
                'line-color': '#cbd5e1',
                'line-opacity': 0.5,
                'line-width': 5,
                'line-blur': 3,
              },
            },
            before,
          )
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
            before,
          )
        }
      }

      // OSM power=line overlay (Overpass GA/SC) — violet to read apart from
      // the slate HIFLD layer, width by kV (0 = voltage tag missing)
      if (osmRef.current) {
        const os = map.getSource('osm-lines')
        if (os && 'setData' in os) {
          ;(os as { setData: (d: unknown) => void }).setData(osmRef.current)
        } else {
          map.addSource('osm-lines', { type: 'geojson', data: osmRef.current })
          const beforeOsm = map.getLayer('pair-circles') ? 'pair-circles' : undefined
          // violet glow casing — pops the lines "upward" against the basemap
          map.addLayer(
            {
              id: 'osm-lines-glow',
              type: 'line',
              source: 'osm-lines',
              layout: { visibility: osmVisRef.current ? 'visible' : 'none' },
              paint: {
                'line-color': '#C4B5FD',
                'line-opacity': 0.55,
                'line-width': 6,
                'line-blur': 3,
              },
            },
            beforeOsm,
          )
          map.addLayer(
            {
              id: 'osm-lines',
              type: 'line',
              source: 'osm-lines',
              layout: {
                visibility: osmVisRef.current ? 'visible' : 'none',
              },
              paint: {
                'line-color': '#7C3AED',
                'line-opacity': 0.9,
                'line-width': [
                  'case',
                  ['>=', ['get', 'kv'], 345], 2.8,
                  ['>=', ['get', 'kv'], 100], 1.8,
                  1.1,
                ],
              },
            },
            beforeOsm,
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
    if (
      !map ||
      !map.getLayer('pair-circle-edge') ||
      !map.getLayer('pair-dots') ||
      !map.getLayer('halo-dots')
    )
      return
    const focus = hoverId ?? selectedId ?? ''
    const vis = tierVisible(hiddenTiers)
    // circles + gap dots track the clicked row only (no tier gate — one
    // explicit selection; hiddenTiers still filters the crossing dots)
    const sel = ['==', ['get', 'id'], selectedId ?? ''] as unknown as maplibregl.ExpressionSpecification
    map.setFilter('pair-circles', ['all', sel] as never)
    map.setFilter('pair-circle-edge', ['all', sel] as never)
    map.setFilter('pair-circle-focus', ['all', sel] as never)
    map.setFilter('pair-dots', ['all', sel] as never)
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
    if (map.getLayer('hifld-lines-glow'))
      map.setLayoutProperty('hifld-lines-glow', 'visibility', showHifld ? 'visible' : 'none')
  }, [showHifld])

  // OSM overlay toggle — same ref-then-push pattern as HIFLD
  useEffect(() => {
    osmVisRef.current = showOsm
    const map = mapRef.current
    if (!map || !map.getLayer('osm-lines')) return
    map.setLayoutProperty('osm-lines', 'visibility', showOsm ? 'visible' : 'none')
    if (map.getLayer('osm-lines-glow'))
      map.setLayoutProperty('osm-lines-glow', 'visibility', showOsm ? 'visible' : 'none')
  }, [showOsm])

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
        <div
          className="flex items-start gap-1.5"
          title="OSM power=line ways inside US-GA + US-SC (Overpass API), width by voltage tag. Reference only — corridor scoring never uses it."
        >
          <span style={{ color: '#7C3AED' }}>┃</span>
          <span>violet lines: OSM power lines, GA + SC (width = kV)</span>
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
          title="Shown only for the clicked row: circle centered between the two projects, diameter = the tier limit itself (1.6 / 8 / 40 km) so both projects sit inside; the dots mark each project's closest point."
        >
          <span className="text-ink-dim">◯</span>
          <span>
            circle: clicked pair&apos;s zone — diameter = tier limit (1.6 / 8 / 40 km); dots = its
            two locations
          </span>
        </div>
        <div className="flex items-start gap-1.5">
          <span className="text-ink-dim">✦</span>
          <span>bright glow: hovered / selected pair — hover a row</span>
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
        {osmStatus === 'loading' && (
          <span className={`${chip} text-ink-dim`} title="Fetching OSM power=line overlay…">
            OSM loading…
          </span>
        )}
        {osmStatus === 'error' && (
          <span
            className={chip}
            title="OSM overlay unavailable — is the backend running on :8000? If the cache is missing run: uv run python backend.convert_overpass_lines"
          >
            OSM unavailable
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
          onClick={() => setShowOsm((v) => !v)}
          title="Toggle OSM power=line overlay (Overpass, GA+SC states)"
        >
          {showOsm ? 'hide' : 'show'} OSM
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
