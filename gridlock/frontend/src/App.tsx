import { useEffect, useMemo, useRef, useState } from 'react'
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

function qValue(v: unknown): string {
  return Array.isArray(v) ? v.join(', ') : String(v)
}

/** parsed query chips, above the table (START-GATE 05-3) */
function QueryChips() {
  const query = useStore((s) => s.query)
  const clearQuery = useStore((s) => s.clearQuery)
  if (!query || query.error || !query.parsed) return null
  const ai = query.source === 'local' ? 'local parser' : 'AI parsed'
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-rule bg-surface-2 px-3 py-1.5">
      <span
        className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
        style={
          query.source === 'local'
            ? { color: '#64748B', background: '#64748B1a' }
            : { color: '#7C3AED', background: '#7C3AED1a' }
        }
      >
        {ai}
      </span>
      <span className="text-[11px] text-ink-dim">“{query.text}”</span>
      <span className="text-[10px] text-ink-dim">→</span>
      {query.parsed.filters.map((f, i) => (
        <span
          key={i}
          className="rounded-full border border-rule bg-surface px-2 py-0.5 text-[11px] font-medium"
        >
          {f.col} {f.op} {qValue(f.value)}
        </span>
      ))}
      {query.parsed.sort && (
        <span className="rounded-full border border-rule bg-surface px-2 py-0.5 text-[11px] font-medium">
          sort {query.parsed.sort.col} {query.parsed.sort.dir}
        </span>
      )}
      {query.parsed.intent === 'count' && (
        <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-bold tabular-nums">
          count = {query.row_count}
        </span>
      )}
      <span className="ml-auto text-[11px] tabular-nums text-ink-dim">
        n = {query.row_count}
      </span>
      <button
        className="rounded px-1.5 py-0.5 text-[11px] text-ink-dim hover:bg-surface-3"
        onClick={clearQuery}
      >
        clear ✕
      </button>
    </div>
  )
}

export default function App() {
  const { rows, loading, error, tier, windowOnly } = useStore()
  const query = useStore((s) => s.query)
  const runQuery = useStore((s) => s.runQuery)
  const locatedCount = useStore((s) => s.projects.length)
  const setTier = useStore((s) => s.setTier)
  const setWindowOnly = useStore((s) => s.setWindowOnly)
  const projFilter = useStore((s) => s.projFilter)
  const selectProject = useStore((s) => s.selectProject)
  const setMapExpanded = useStore((s) => s.setMapExpanded)
  const select = useStore((s) => s.select)
  const load = useStore((s) => s.load)
  const ledgerPct = useStore((s) => s.ledgerPct)
  const setLedgerPct = useStore((s) => s.setLedgerPct)
  const [ask, setAsk] = useState('')

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

  // NL query narrows the base set; tier/window chips + map-icon projFilter apply on top
  const base = query?.rows ?? rows
  const filtered = useMemo(
    () =>
      base.filter(
        (r) =>
          (tier === 'all' ||
            (tier === 'touch' ? r.tier === 'crossing' : r.tier === tier)) &&
          (!windowOnly || r.shared_in_service_year != null) &&
          (!projFilter || r.project_a === projFilter || r.project_b === projFilter),
      ),
    [base, tier, windowOnly, projFilter],
  )
  const sortKey = query?.parsed?.sort
    ? `${query.parsed.sort.col}:${query.parsed.sort.dir}`
    : 'default'

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
          <span className="text-[15px] font-bold tracking-[0.18em]">CHUD</span>
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

        {projFilter && (
          <button
            className={chip(true)}
            onClick={() => selectProject(null)}
            title="Clear the linked-pairs filter (map icon click)"
          >
            linked: {projFilter} ✕
          </button>
        )}

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
          {!loading && !error && (
            <>
              <QueryChips />
              <Ledger key={sortKey} rows={filtered} />
            </>
          )}
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

      {/* fixed command bar — NL table query (filter/sort/count only)
      <div className="flex h-10 shrink-0 items-center gap-3 border-t border-rule bg-surface px-4">
        <input
          className="h-7 flex-1 rounded border border-rule bg-surface-2 px-2.5 text-[12.5px] outline-none placeholder:text-ink-dim"
          placeholder="ask the table — e.g. “tier &lt;8 with 2026 service year, sort by score desc”"
          value={ask}
          disabled={query?.running}
          onChange={(e) => setAsk(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && ask.trim()) void runQuery(ask.trim())
          }}
        />
        {query?.running && (
          <span className="rounded-full border border-rule px-2 py-0.5 text-[10.5px] text-ink-dim">
            parsing…
          </span>
        )}
        {query?.error && (
          <span
            className="max-w-[38ch] truncate rounded-full px-2 py-0.5 text-[10.5px]"
            style={{ color: '#DB2777', background: '#DB27771a' }}
            title={query.error}
          >
            rejected — {query.error}
          </span>
        )}
        {query && !query.running && !query.error && (
          <span
            className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
            style={
              query.source === 'local'
                ? { color: '#64748B', background: '#64748B1a' }
                : { color: '#7C3AED', background: '#7C3AED1a' }
            }
          >
            {query.source === 'local' ? 'local parser' : 'AI'} · {query.row_count} rows
          </span>
        )}
        {query && (
          <button
            className="rounded px-1.5 py-0.5 text-[11px] text-ink-dim hover:bg-surface-3"
            onClick={() => {
              setAsk('')
              useStore.getState().clearQuery()
            }}
          >
            clear
          </button>
        )}
        {!query && (
          <span className="rounded-full border border-rule px-2 py-0.5 text-[10.5px] text-ink-dim">
            filter / sort / count only
          </span>
        )}
      </div>
      */}
    </div>
  )
}
