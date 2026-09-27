import { create } from 'zustand'
import type { OverlapRow, ProjectRow, Tier } from './types'

/** Tier chip filter — 'touch' maps to the engine's "crossing" tier. */
export type TierFilter = 'all' | 'touch' | '<1.6 km' | '<8 km' | '<40 km'

/** Phase 05 NL query — server-parsed filters/sort shown as chips above the table. */
export interface QFilter {
  col: string
  op: string
  value: unknown
}
export interface ParsedQuery {
  filters: QFilter[]
  sort: { col: string; dir: 'asc' | 'desc' } | null
  intent: 'count' | 'filter'
}
export interface QueryState {
  text: string
  parsed: ParsedQuery | null
  source: 'live' | 'cached' | 'local' | ''
  row_count: number
  rows: OverlapRow[] | null
  error: string | null
  running: boolean
}

interface State {
  rows: OverlapRow[]
  projects: ProjectRow[]
  loading: boolean
  error: string | null
  tier: TierFilter
  windowOnly: boolean
  hoverId: string | null
  selectedId: string | null
  /** Project id clicked on the map — table shows only pairs linking it. */
  projFilter: string | null
  mapExpanded: boolean
  ledgerPct: number
  drawerH: number
  /** Tiers hidden ON THE MAP (legend toggles; independent of the table chips). */
  hiddenTiers: Tier[]
  /** Active NL query (null = none; rows null on parse error). */
  query: QueryState | null
  /** Phase 06 bonus — illustrative shared-ROW assumptions (visible controls). */
  rowWidthFt: number
  usdPerAcre: number
  load: () => Promise<void>
  runQuery: (text: string) => Promise<void>
  clearQuery: () => void
  setTier: (t: TierFilter) => void
  toggleTier: (t: Tier) => void
  setWindowOnly: (v: boolean) => void
  setHover: (id: string | null) => void
  select: (id: string | null) => void
  selectProject: (pid: string | null) => void
  setMapExpanded: (v: boolean) => void
  setLedgerPct: (pct: number) => void
  setDrawerH: (px: number) => void
  setRowWidthFt: (ft: number) => void
  setUsdPerAcre: (v: number) => void
}

export const useStore = create<State>((set, get) => ({
  rows: [],
  projects: [],
  loading: true,
  error: null,
  tier: 'all',
  windowOnly: false,
  hoverId: null,
  selectedId: null,
  projFilter: null,
  mapExpanded: false,
  ledgerPct: 50,
  drawerH: 300,
  // start tight: touching + <1.6 only, rest via legend toggles
  hiddenTiers: ['<8 km', '<40 km', 'excluded'],
  query: null,
  // illustrative bonus assumptions — defaults match engine DEFAULT_ROW_WIDTH_FT;
  // $/acre is a placeholder multiplier, always labeled "illustrative assumption"
  rowWidthFt: 150,
  usdPerAcre: 50_000,

  load: async () => {
    set({ loading: true, error: null })
    try {
      const [r, p] = await Promise.all([fetch('/api/overlaps'), fetch('/api/projects')])
      if (!r.ok || !p.ok) throw new Error(`api ${r.status}/${p.status}`)
      const rows: OverlapRow[] = await r.json()
      const projects: ProjectRow[] = await p.json()
      set({ rows, projects, loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false })
    }
  },

  runQuery: async (text) => {
    set({
      query: { text, parsed: null, source: '', row_count: 0, rows: null, error: null, running: true },
    })
    try {
      const r = await fetch('/api/ai/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      const d = await r.json()
      if (!r.ok) {
        const msg: string = d?.detail?.detail ?? d?.detail?.[0]?.msg ?? d?.detail ?? `api ${r.status}`
        set({
          query: { text, parsed: null, source: '', row_count: 0, rows: null, error: String(msg), running: false },
        })
        return
      }
      set({
        query: {
          text,
          parsed: d.parsed,
          source: d.source,
          row_count: d.row_count,
          rows: d.rows,
          error: null,
          running: false,
        },
      })
    } catch (e) {
      set({
        query: { text, parsed: null, source: '', row_count: 0, rows: null, error: e instanceof Error ? e.message : String(e), running: false },
      })
    }
  },
  clearQuery: () => set({ query: null }),

  // chip selection also reveals its tier(s) on the map (legend stays independently toggleable)
  setTier: (tier) =>
    set((s) => {
      const reveal: Tier[] =
        tier === 'all'
          ? ['crossing', '<1.6 km', '<8 km', '<40 km', 'excluded']
          : tier === 'touch'
            ? ['crossing']
            : [tier as Tier]
      return { tier, hiddenTiers: s.hiddenTiers.filter((t) => !reveal.includes(t)) }
    }),
  toggleTier: (t) =>
    set((s) => ({
      hiddenTiers: s.hiddenTiers.includes(t)
        ? s.hiddenTiers.filter((x) => x !== t)
        : [...s.hiddenTiers, t],
    })),
  setWindowOnly: (windowOnly) => set({ windowOnly }),
  setHover: (hoverId) => set({ hoverId }),
  select: (selectedId) => set({ selectedId, hoverId: null }),
  // map icon click: filter table to pairs linking this project, open the first
  // one in the drawer; reset tier chips so none of them are chip-filtered out
  selectProject: (pid) => {
    if (!pid) return set({ projFilter: null })
    const linked = get().rows.filter((r) => r.project_a === pid || r.project_b === pid)
    set({
      projFilter: pid,
      tier: 'all',
      hiddenTiers: [],
      selectedId: linked[0]?.overlap_id ?? null,
      hoverId: null,
    })
  },
  setMapExpanded: (mapExpanded) => set({ mapExpanded }),
  setLedgerPct: (pct) => set({ ledgerPct: Math.min(75, Math.max(25, pct)) }),
  setDrawerH: (px) =>
    set({ drawerH: Math.min(Math.round(window.innerHeight * 0.7), Math.max(140, px)) }),
  setRowWidthFt: (rowWidthFt) =>
    set({ rowWidthFt: Math.min(300, Math.max(10, rowWidthFt || 0)) }),
  setUsdPerAcre: (usdPerAcre) =>
    set({ usdPerAcre: Math.max(0, usdPerAcre || 0) }),
}))
