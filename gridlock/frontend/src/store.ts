import { create } from 'zustand'
import type { OverlapRow, ProjectRow } from './types'

/** Tier chip filter — 'touch' maps to the engine's "crossing" tier. */
export type TierFilter = 'all' | 'touch' | '<1.6 km' | '<8 km' | '<40 km'

interface State {
  rows: OverlapRow[]
  projects: ProjectRow[]
  loading: boolean
  error: string | null
  tier: TierFilter
  windowOnly: boolean
  hoverId: string | null
  selectedId: string | null
  mapExpanded: boolean
  ledgerPct: number
  drawerH: number
  load: () => Promise<void>
  setTier: (t: TierFilter) => void
  setWindowOnly: (v: boolean) => void
  setHover: (id: string | null) => void
  select: (id: string | null) => void
  setMapExpanded: (v: boolean) => void
  setLedgerPct: (pct: number) => void
  setDrawerH: (px: number) => void
}

export const useStore = create<State>((set) => ({
  rows: [],
  projects: [],
  loading: true,
  error: null,
  tier: 'all',
  windowOnly: false,
  hoverId: null,
  selectedId: null,
  mapExpanded: false,
  ledgerPct: 60,
  drawerH: 300,

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

  setTier: (tier) => set({ tier }),
  setWindowOnly: (windowOnly) => set({ windowOnly }),
  setHover: (hoverId) => set({ hoverId }),
  select: (selectedId) => set({ selectedId, hoverId: null }),
  setMapExpanded: (mapExpanded) => set({ mapExpanded }),
  setLedgerPct: (pct) => set({ ledgerPct: Math.min(75, Math.max(25, pct)) }),
  setDrawerH: (px) =>
    set({ drawerH: Math.min(Math.round(window.innerHeight * 0.7), Math.max(140, px)) }),
}))
