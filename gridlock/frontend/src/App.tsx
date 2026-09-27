import { useEffect, useMemo } from 'react'
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
  const setTier = useStore((s) => s.setTier)
  const setWindowOnly = useStore((s) => s.setWindowOnly)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const select = useStore((s) => s.select)
  const load = useStore((s) => s.load)

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
      <main className="relative flex min-h-0 flex-1">
        <section className="flex w-[60%] min-w-0 flex-col border-r border-rule">
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

        <section className="relative w-[40%]">
          <MapInset />
        </section>
      </main>

      <Drawer />

      {/* honesty footer (report) */}
      <footer className="shrink-0 border-t border-rule bg-surface-2 px-4 py-1 text-[10.5px] text-ink-dim">
        Distances are straight-line separations between corridor geometries — not as-built
        clearances. Tiers &amp; score from the v0.3 engine; ≥160&nbsp;m halo bands are schematic.
        Basemap © <a href="https://openfreemap.org/" className="underline">OpenFreeMap</a>, ©{' '}
        <a href="https://www.openstreetmap.org/copyright" className="underline">OpenStreetMap</a>{' '}
        contributors (ODbL). Distances, tiers and scores are computed — verify before relying on
        them.
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
