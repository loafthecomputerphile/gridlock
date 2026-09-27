import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from '@tanstack/react-table'
import type { ColumnDef } from '@tanstack/react-table'
import type { OverlapRow } from './types'
import { TIER_HALO, TIER_LABEL, UTILITY } from './palette'
import { useStore } from './store'

const PAGE = 50

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() })
type Features = typeof features

const col = createColumnHelper<Features, OverlapRow>()

// ponytail: mixed accessor TValue (number|string|null) — cast once instead of
// fighting v9's per-column generics; every column here is read as ReactNode
const columns = [
  col.accessor('rank', { header: '#', enableSorting: false, cell: (c) => c.getValue() }),
  col.accessor('project_a', {
    header: 'Project A',
    cell: (c) => (
      <span title={c.row.original.name_a}>
        <Dot utility={c.row.original.utilities[0] ?? ''} /> {c.getValue()}
      </span>
    ),
  }),
  col.accessor('project_b', {
    header: 'Project B',
    cell: (c) => (
      <span title={c.row.original.name_b}>
        <Dot utility={c.row.original.utilities[1] ?? c.row.original.utilities[0] ?? ''} />{' '}
        {c.getValue()}
      </span>
    ),
  }),
  col.accessor('utilities', {
    header: 'Utility',
    enableSorting: false,
    cell: (c) => c.getValue().join(' × '),
  }),
  col.accessor('min_distance_km', {
    header: 'Min dist (km)',
    cell: (c) => c.getValue().toFixed(2),
  }),
  col.accessor('tier', {
    header: 'Tier',
    cell: (c) => (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: TIER_HALO[c.getValue()] }}
        />
        {TIER_LABEL[c.getValue()]}
      </span>
    ),
  }),
  col.accessor('shared_in_service_year', {
    header: 'Svc year',
    cell: (c) => c.getValue() ?? '—',
  }),
  col.accessor('time_gap', {
    header: 'Gap (d)',
    cell: (c) => (c.getValue() == null ? '—' : `${c.getValue()} d`),
  }),
  col.accessor('score', { header: 'Score', cell: (c) => c.getValue() }),
  // ponytail: no API field yet — plan schema keeps the column, always "--" until 05
  col.accessor(() => null, {
    id: 'est_shared_row_acres',
    header: 'Est. row acres',
    enableSorting: false,
    cell: () => '--',
  }),
] as unknown as ColumnDef<Features, OverlapRow>[]

function Dot({ utility }: { utility: string }) {
  const color = utility.startsWith('Georgia') ? UTILITY.GPC : UTILITY.DESC
  return <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
}

function TierChip({ tier }: { tier: OverlapRow['tier'] }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-rule bg-surface px-2 py-0.5 text-[10.5px]"
      style={{ color: TIER_HALO[tier] }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: TIER_HALO[tier] }}
      />
      {TIER_LABEL[tier]}
    </span>
  )
}

export default function Ledger({ rows }: { rows: OverlapRow[] }) {
  const [visible, setVisible] = useState(PAGE)
  const { selectedId, setHover, select } = useStore()
  const bodyRef = useRef<HTMLTableSectionElement>(null)

  const table = useTable({
    features,
    columns,
    data: rows,
    initialState: { sorting: [{ id: 'score', desc: true }] },
    enableSortingRemoval: false,
    enableMultiSort: false,
  })

  const allRows = table.getRowModel().rows
  const shown = allRows.slice(0, visible)

  // halo click on a paged-out row: grow the page until it renders, then center it
  useEffect(() => {
    if (!selectedId) return
    const idx = allRows.findIndex((r) => r.original.overlap_id === selectedId)
    if (idx < 0) return
    if (idx >= visible) {
      setVisible(idx + 1)
      return
    }
    bodyRef.current
      ?.querySelector(`[data-row="${CSS.escape(selectedId)}"]`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, allRows])

  const resetPage = () => setVisible(PAGE)
  useEffect(resetPage, [rows])

  const th =
    'px-2 py-1.5 text-left text-[10.5px] font-semibold tracking-wide text-ink-dim uppercase select-none border-b border-rule bg-surface-2 sticky top-0 z-10'

  if (!rows.length) return <EmptyState />

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-[12px]">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => {
                  const sorted = header.column.getIsSorted()
                  return (
                    <th key={header.id} className={th}>
                      <button
                        className="flex w-full items-center gap-1 cursor-pointer hover:text-ink disabled:cursor-default"
                        disabled={!header.column.getCanSort()}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <table.FlexRender header={header} />
                        <span className="text-[9px]">
                          {sorted === 'asc' ? '▲' : sorted === 'desc' ? '▼' : ''}
                        </span>
                      </button>
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody ref={bodyRef}>
            {shown.map((row) => {
              const id = row.original.overlap_id
              const excluded = row.original.tier === 'excluded'
              const selected = id === selectedId
              return (
                <tr
                  key={id}
                  data-row={id}
                  onMouseEnter={() => setHover(id)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => select(id)}
                  className={[
                    'cursor-pointer border-b border-rule transition-colors',
                    selected
                      ? 'bg-surface-2 shadow-[inset_2px_0_0_var(--color-desc)]'
                      : 'hover:bg-surface-2',
                    excluded ? 'opacity-45' : '',
                  ].join(' ')}
                >
                  {row.getAllCells().map((cell) => (
                    <td key={cell.id} className="px-2 py-1.5 align-middle">
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>

        {visible < allRows.length && (
          <div className="border-b border-rule p-3 text-center">
            <button
              className="rounded border border-rule bg-surface px-3 py-1.5 text-[11.5px] hover:bg-surface-3"
              onClick={() => setVisible((v) => v + PAGE)}
            >
              load next {Math.min(PAGE, allRows.length - visible)} of{' '}
              {allRows.length - visible} remaining
            </button>
          </div>
        )}
      </div>
      <TierChipLegend />
    </div>
  )
}

/** compact always-visible tier key under the ledger (report: legend always visible) */
function TierChipLegend() {
  return (
    <div className="flex items-center gap-3 border-t border-rule bg-surface-2 px-3 py-1.5 text-[10.5px] text-ink-dim">
      <span className="font-semibold tracking-wide uppercase">Tiers</span>
      {(['crossing', '<1.6 km', '<8 km', '<40 km'] as const).map((t) => (
        <span key={t} className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: TIER_HALO[t] }} />
          {TIER_LABEL[t]}
        </span>
      ))}
      <span className="inline-flex items-center gap-1 opacity-50">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: TIER_HALO.excluded }} />
        excluded
      </span>
    </div>
  )
}

/** START-GATE 04-4: explainer + nearest candidates when nothing survives the filter */
function EmptyState() {
  const all = useStore((s) => s.rows)
  const select = useStore((s) => s.select)
  const nearest = useMemo(
    () => [...all].sort((a, b) => a.min_distance_km - b.min_distance_km).slice(0, 5),
    [all],
  )
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="max-w-md">
        <h2 className="mb-1 text-base font-semibold">No pairs survive this filter</h2>
        <p className="text-[12.5px] text-ink-dim">
          Every candidate either exceeds the 40&nbsp;km analysis radius or falls outside the
          selected service-year window. Loosen the tier filter or turn off “window only”.
        </p>
      </div>
      <div className="w-full max-w-sm rounded border border-rule bg-surface-2 p-3 text-left">
        <div className="mb-1.5 text-[10.5px] font-semibold tracking-wide text-ink-dim uppercase">
          Nearest candidates regardless of filter
        </div>
        {nearest.map((r) => (
          <button
            key={r.overlap_id}
            className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-[12px] hover:bg-surface-3"
            onClick={() => select(r.overlap_id)}
          >
            <span className="truncate">
              {r.project_a} × {r.project_b}
            </span>
            <TierChip tier={r.tier} />
          </button>
        ))}
      </div>
    </div>
  )
}
