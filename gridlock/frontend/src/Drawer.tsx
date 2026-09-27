import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { PairDetail } from './types'
import { TIER_HALO, TIER_LABEL } from './palette'
import { useStore } from './store'

function Field({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div>
      <div className="text-[9.5px] font-semibold tracking-wide text-ink-dim uppercase">{k}</div>
      <div className="text-[12px]">{v == null || v === '' ? '—' : v}</div>
    </div>
  )
}

function ProjectCard({ p, accent }: { p: PairDetail['project_a_detail']; accent: string }) {
  return (
    <div className="flex-1 rounded border border-rule bg-surface-2 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: accent }} />
        <span className="text-[12.5px] font-semibold">{p.project_id}</span>
        <span className="text-[11.5px] text-ink-dim">{p.name}</span>
      </div>
      <div className="grid grid-cols-3 gap-x-4 gap-y-2">
        <Field k="Utility" v={p.utility} />
        <Field k="Type" v={p.type} />
        <Field k="Voltage" v={p.voltage_kv} />
        <Field k="From" v={p.endpoint_a} />
        <Field k="To" v={p.endpoint_b} />
        <Field k="County" v={p.county} />
        <Field k="In service" v={p.in_service_date} />
        <Field k="Status" v={p.status} />
        <Field
          k="Cost"
          v={
            /redact/i.test(p.cost_usd) ? (
              <span title="Cost REDACTED in the source release — never invented (GPC side has no cost data)">
                -- <span className="text-ink-dim">(redacted in source)</span>
              </span>
            ) : (
              p.cost_usd
            )
          }
        />
        <Field k="Sponsor" v={p.sponsor} />
        <Field k="Confidence" v={p.confidence} />
        <Field k="Grounding" v={p.geometry_source} />
        <Field k="Geometry" v={p.geometry_basis} />
        <Field k="Source" v={p.source_file ? `${p.source_file} p.${p.source_page}` : null} />
        <Field k="Notes" v={p.notes} />
      </div>
    </div>
  )
}

/** phase-05 AI brief chip — hues deliberately outside the tier palette
 * (red/orange/yellow/blue/green are tier/utility colors). */
const BRIEF_CHIP: Record<string, { label: string; fg: string }> = {
  live: { label: 'AI live', fg: '#7C3AED' },
  cached: { label: 'cached', fg: '#0891B2' },
  'rate-limited': { label: 'rate-limited', fg: '#DB2777' },
  unavailable: { label: 'AI unavailable', fg: '#64748B' },
  loading: { label: 'asking model…', fg: '#64748B' },
}

interface BriefState {
  text: string | null
  status: string
  source: string | null
  model: string | null
  reason: string | null
}

/** 06-A: acres = width_ft × length_mi × 5,280 ÷ 43,560 (engine formula, live inputs) */
function AssumptionTable({ detail }: { detail: PairDetail }) {
  const widthFt = useStore((s) => s.rowWidthFt)
  const usdPerAcre = useStore((s) => s.usdPerAcre)
  const lengthMi = detail.min_distance_km / 1.609344
  const acres = (widthFt * lengthMi * 5280) / 43560
  const usd = acres * usdPerAcre
  const row = (k: string, v: string) => (
    <tr className="border-b border-rule last:border-0">
      <td className="py-1 pr-4 text-ink-dim">{k}</td>
      <td className="py-1 text-right tabular-nums">{v}</td>
    </tr>
  )
  return (
    <div className="mb-3 rounded border border-rule bg-surface-2 px-3 py-2.5">
      <div className="mb-1.5 text-[11.5px] font-semibold tracking-wide text-ink uppercase">
        Shared-ROW cost estimate{' '}
        <span className="font-normal italic text-ink-dim">illustrative assumption</span>
      </div>
      <table className="text-[12px]">
        <tbody>
          {row('Closest-approach segment length', `${lengthMi.toFixed(3)} mi (${detail.min_distance_km.toFixed(2)} km)`)}
          {row('ROW width (ledger control)', `${widthFt} ft`)}
          {row('Acre math', `width_ft × 5,280 ÷ 43,560 per mile → ${acres.toFixed(2)} ac`)}
          {row('$ / acre (ledger control)', `$${usdPerAcre.toLocaleString('en-US')}`)}
          {row('Est. $ (illustrative)', `$${Math.round(usd).toLocaleString('en-US')}`)}
        </tbody>
      </table>
      <div className="mt-1.5 text-[10.5px] text-ink-dim">
        Not a quote. Inputs shown above; GPC project costs are REDACTED in the source
        release, so no project-side dollar is inferred from them.
      </div>
    </div>
  )
}

export default function Drawer() {
  const selectedId = useStore((s) => s.selectedId)
  const select = useStore((s) => s.select)
  const [detail, setDetail] = useState<PairDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [brief, setBrief] = useState<BriefState | null>(null)
  const [briefAttempt, setBriefAttempt] = useState(0)
  const drawerH = useStore((s) => s.drawerH)
  const setDrawerH = useStore((s) => s.setDrawerH)
  const hDrag = useRef<{ y0: number; h0: number } | null>(null)

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setBrief(null)
      return
    }
    let live = true
    setError(null)
    setDetail(null)
    setBrief({ text: null, status: 'loading', source: null, model: null, reason: null })
    fetch(`/api/pairs/${encodeURIComponent(selectedId)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`api ${r.status}`)
        return r.json()
      })
      .then((d: PairDetail) => live && setDetail(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)))
    fetch('/api/ai/brief', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pair_id: selectedId }),
    })
      .then((r) => r.json())
      .then((d) =>
        live &&
        setBrief({
          text: d.text ?? null,
          status: d.status ?? 'unavailable',
          source: d.source ?? null,
          model: d.model ?? null,
          reason: d.reason ?? null,
        }),
      )
      .catch(() =>
        live &&
        setBrief({ text: null, status: 'unavailable', source: null, model: null, reason: 'network error' }),
      )
    return () => {
      live = false
    }
  }, [selectedId, briefAttempt])

  if (!selectedId) return null

  const mid = detail?.shortest_line.coordinates?.length
    ? detail.shortest_line.coordinates[Math.floor(detail.shortest_line.coordinates.length / 2)]
    : null
  const chipKey = !brief
    ? null
    : brief.status === 'ok'
      ? brief.source === 'cached'
        ? 'cached'
        : 'live'
      : brief.status
  const chip = chipKey ? (BRIEF_CHIP[chipKey] ?? BRIEF_CHIP.unavailable) : null

  return (
    <div
      className="relative flex shrink-0 flex-col border-t border-rule bg-surface shadow-[0_-4px_12px_rgba(15,23,42,0.06)]"
      style={{ height: drawerH }}
    >
      {/* height drag handle — pointer capture, clamp 140px–70vh in the setter */}
      <div
        role="separator"
        aria-orientation="horizontal"
        className="absolute inset-x-0 -top-[3px] z-10 h-1.5 cursor-row-resize"
        style={{ touchAction: 'none' }}
        onPointerDown={(e) => {
          e.preventDefault()
          e.currentTarget.setPointerCapture(e.pointerId)
          hDrag.current = { y0: e.clientY, h0: useStore.getState().drawerH }
        }}
        onPointerMove={(e) => {
          const d = hDrag.current
          if (!d) return
          setDrawerH(d.h0 - (e.clientY - d.y0))
        }}
        onPointerUp={() => (hDrag.current = null)}
        onPointerCancel={() => (hDrag.current = null)}
      />
      <div className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="font-semibold tracking-wide">Pair detail</span>
          {detail && (
            <span
              className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
              style={{
                color: TIER_HALO[detail.tier],
                background: `${TIER_HALO[detail.tier]}1a`,
              }}
            >
              {TIER_LABEL[detail.tier]}
            </span>
          )}
          {detail && <span className="text-[12px] text-ink-dim">score {detail.score}</span>}
        </div>
        <button
          className="rounded px-2 py-0.5 text-[12px] text-ink-dim hover:bg-surface-3"
          onClick={() => select(null)}
          title="Escape also closes"
        >
          close ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {error && <div className="text-[12px] text-[#DC2626]">failed to load pair: {error}</div>}
        {!error && !detail && <div className="text-[12px] text-ink-dim">loading…</div>}
        {detail && (
          <>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-[12.5px]">
              <span className="font-semibold">
                {detail.project_a} × {detail.project_b}
              </span>
              <span>{detail.min_distance_km.toFixed(2)} km min separation</span>

              <span>
                service years {detail.year_a ?? '?'} / {detail.year_b ?? '?'}

              </span>
              <span>{detail.time_gap != null ? `${detail.time_gap} d apart` : 'time gap —'}</span>
              <span>
                shared:{' '}
                {detail.shared_in_service_year != null
                  ? detail.shared_in_service_year
                  : 'none'}
              </span>
              {mid && (
                <span className="text-ink-dim">
                  closest point {mid[1].toFixed(3)}, {mid[0].toFixed(3)}
                </span>
              )}
              {detail.hifld_ref && (
                <span
                  className="text-ink-dim"
                  title={`Nearest HIFLD line: ${detail.hifld_ref.sub_1 ?? '?'} — ${detail.hifld_ref.sub_2 ?? '?'} (${detail.hifld_ref.status ?? 'status ?'}), HIFLD/ORNL reference layer`}
                >
                  nearest HIFLD: {detail.hifld_ref.voltage_class} kV class
                  {detail.hifld_ref.owner ? ` · ${detail.hifld_ref.owner}` : ''} ·{' '}
                  {(detail.hifld_ref.dist_m / 1000).toFixed(1)} km
                </span>
              )}
            </div>

            <div className="mb-3 flex gap-3">
              <ProjectCard p={detail.project_a_detail} accent="#2563EB" />
              <ProjectCard p={detail.project_b_detail} accent="#059669" />
            </div>

            {/* phase 06 bonus: shared-ROW cost assumption table (inputs live in the ledger bar) */}
            <AssumptionTable detail={detail} />

            {/* phase-05: AI pair brief — status chip + retry, degraded states honest 
            <div className="rounded border border-rule bg-surface-2 px-3 py-2.5">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-[11.5px] font-semibold tracking-wide text-ink uppercase">
                  AI pair brief
                </span>
                {brief && chip && (
                  <span
                    className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                    style={{ color: chip.fg, background: `${chip.fg}1a` }}
                  >
                    {chip.label}
                  </span>
                )}
                {brief?.model && (
                  <span className="text-[10px] text-ink-dim">{brief.model}</span>
                )}
                {brief && brief.status !== 'ok' && brief.status !== 'loading' && (
                  <button
                    className="rounded border border-rule px-2 py-0.5 text-[10.5px] hover:bg-surface-3"
                    onClick={() => setBriefAttempt((n) => n + 1)}
                  >
                    retry
                  </button>
                )}
              </div>
              {!brief || brief.status === 'loading' ? (
                <div className="text-[12px] text-ink-dim">asking the model…</div>
              ) : brief.text ? (
                <p className="text-[12.5px] leading-relaxed">{brief.text}</p>
              ) : (
                <div className="text-[12px] text-ink-dim">
                  Brief unavailable{brief.reason ? ` — ${brief.reason}` : ''}. No cached
                  copy for this pair yet; add OPENROUTER_API_KEY and retry to generate
                  one for the offline demo.
                </div>
              )}
            </div>
            */}
          </>
        )}
      </div>
    </div>
  )
}
