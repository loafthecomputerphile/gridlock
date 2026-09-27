import { useEffect, useMemo, useRef } from 'react'
import { useStore, type TierFilter } from './store'
import Ledger from './Ledger'
import MapInset from './MapInset'
import Drawer from './Drawer'

const TIERS: { id: TierFilter; label: string }[] = [
  { id: 'all', label: 'all' },
  { id: 'touch', label: 'touch' },
  { id: '<1.6 km', label: '<1.6' },
  { id: '<8 km', label: '<8' },
  { id: '<40 km', label: '<40' },
]

export default function App() {
  const { rows, loading, error, tier, windowOnly } = useStore()
  const locatedCount = useStore((s) => s.projects.length)
  const setTier = useStore((s) => s.setTier)
  const setWindowOnly = useStore((s) => s.setWindowOnly)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const select = useStore((s) => s.select)
  const load = useStore((s) => s.load)
  const ledgerPct = useStore((s) => s.ledgerPct)
  const setLedgerPct = useStore((s) => s.setLedgerPct)

  const mainRef = useRef<HTMLElement>(null)
  const splitDrag = useRef<{ x0: number; pct0: number; w: number } | null>(null)

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (useStore.getState().mapExpanded) setMapExpanded(false)
      else select(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setMapExpanded, select])

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (tier === 'all' ||
            (tier === 'touch' ? r.tier === 'crossing' : r.tier === tier)) &&
          (!windowOnly || r.shared_in_service_year != null),
      ),
    [rows, tier, windowOnly],
  )

  const chip = (active: boolean) =>
    `h-6 px-2 rounded-full border text-[11px] font-medium ${
      active
        ? 'border-transparent bg-ink text-surface'
        : 'border-rule bg-surface text-ink-dim hover:bg-surface-3'
    }`

  return (
    <div className="flex h-full flex-col">
      {/* header — Concept C command strip */}
      <header className="flex shrink-0 items-center gap-4 border-b border-rule bg-surface px-4 py-2">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-bold tracking-[0.18em]">GRIDLOCK</span>
          <span className="text-[11px] text-ink-dim">DESC × Georgia Power corridor overlaps</span>
        </div>

        <div className="flex items-center gap-1">
          {TIERS.map((t) => (
            <button key={t.id} className={chip(tier === t.id)} onClick={() => setTier(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <button
          className={chip(windowOnly)}
          onClick={() => setWindowOnly(!windowOnly)}
          title="Only pairs sharing a service year"
        >
          window: {windowOnly ? 'shared year' : 'any'}
        </button>

        <span className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium tabular-nums">
          n = {filtered.length}
          {filtered.length !== rows.length ? ` / ${rows.length}` : ''}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <a
            className="h-6 rounded-full border border-rule bg-surface px-2.5 leading-6 text-[11px] text-ink-dim hover:bg-surface-3"
            href="/api/export/overlaps.csv"
            download
          >
            export CSV
          </a>
        </div>
      </header>

      {/* content: ledger (primary) + linked map inset */}
      <main ref={mainRef} className="relative flex min-h-0 flex-1">
        <section
          className="flex min-w-0 flex-col border-r border-rule"
          style={{ width: `${ledgerPct}%` }}
        >
          {loading && (
            <div className="flex h-full items-center justify-center text-ink-dim">
              loading overlaps…
            </div>
          )}
          {error && (
            <div className="flex h-full flex-col items-center justify-center gap-2">
              <div className="text-[13px] text-[#DC2626]">API unreachable: {error}</div>
              <button
                className="rounded border border-rule px-3 py-1 text-[12px] hover:bg-surface-3"
                onClick={() => void load()}
              >
                retry
              </button>
            </div>
          )}
          {!loading && !error && <Ledger rows={filtered} />}
        </section>

        {/* pane divider — pointer-capture drag, clamped 25–75% in the setter */}
        <div
          role="separator"
          aria-orientation="vertical"
          className="w-1.5 shrink-0 cursor-col-resize bg-rule hover:bg-ink-dim/40 active:bg-ink-dim/60"
          style={{ touchAction: 'none' }}
          onPointerDown={(e) => {
            e.preventDefault()
            e.currentTarget.setPointerCapture(e.pointerId)
            splitDrag.current = {
              x0: e.clientX,
              pct0: useStore.getState().ledgerPct,
              w: mainRef.current?.getBoundingClientRect().width ?? 1,
            }
          }}
          onPointerMove={(e) => {
            const d = splitDrag.current
            if (!d) return
            setLedgerPct(d.pct0 + ((e.clientX - d.x0) / d.w) * 100)
          }}
          onPointerUp={() => (splitDrag.current = null)}
          onPointerCancel={() => (splitDrag.current = null)}
        />

        <section className="relative min-w-0 flex-1 overflow-hidden">
          <MapInset />
        </section>
      </main>

      <Drawer />

      {/* honesty footer (report) */}
      <footer className="shrink-0 border-t border-rule bg-surface-2 px-4 py-1 text-[10.5px] text-ink-dim">
        Locations follow the release folder&apos;s Finding-guide method only (OSM power
        infrastructure + in-state Nominatim); projects the guide couldn&apos;t locate are
        excluded from this map, never plotted at a guessed point ({locatedCount} of 168 shown).
        Route-aware corridors snap to real OSM power lines within 10&nbsp;km (grounding tag
        per project: snapped / buffered / fallback), with a declared 10&nbsp;km uncertainty
        buffer where no line exists. Distances are computed separations between
        corridor geometries — not as-built clearances. Tiers &amp; score from the v0.3 engine;
        ≥160&nbsp;m halo bands are schematic. Basemap ©{' '}
        <a href="https://openfreemap.org/" className="underline">OpenFreeMap</a>, ©{' '}
        <a href="https://www.openstreetmap.org/copyright" className="underline">OpenStreetMap</a>{' '}
        contributors (ODbL). Verify before relying on them.
      </footer>

      {/* fixed command bar — phase-05 slots stubbed */}
      <div className="flex h-10 shrink-0 items-center gap-3 border-t border-rule bg-surface px-4">
        <input
          className="h-7 flex-1 rounded border border-rule bg-surface-2 px-2.5 text-[12.5px] outline-none placeholder:text-ink-dim"
          placeholder="Ask about a pair…"
          disabled
        />
        <span className="rounded-full border border-rule px-2 py-0.5 text-[10.5px] text-ink-dim">
          AI offline — wired in phase 05
        </span>
      </div>
    </div>
  )
}
