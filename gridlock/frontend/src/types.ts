/** API shapes — mirrors backend/app.py pydantic models (phase 03). */

export type Tier = 'crossing' | '<1.6 km' | '<8 km' | '<40 km' | 'excluded'

export interface ShortestLine {
  type: 'LineString'
  coordinates: [number, number][] // [lon, lat] WGS84
}

export interface OverlapRow {
  rank: number
  overlap_id: string
  project_a: string
  project_b: string
  name_a: string
  name_b: string
  utilities: string[]
  min_distance_km: number
  distance_center_mi: number
  tier: Tier
  year_a: number | null
  year_b: number | null
  shared_in_service_year: number | null
  time_gap: number | null
  score: number
  year_unknown: boolean
  shortest_line: ShortestLine
}

export interface ProjectRow {
  project_id: string
  name: string
  utility: string
  type: string
  endpoint_a: string
  endpoint_b: string
  voltage_kv: string
  in_service_date: string
  status: string
  cost_usd: string
  county: string
  sponsor: string
  source_file: string
  source_page: string
  notes: string
  geometry_basis: string
  geometry_source: 'osm_snapped' | 'buffered_estimate' | 'straight_fallback'
  confidence: string
  geometry: { type: string; coordinates: unknown }
}

export interface PairDetail extends OverlapRow {
  project_a_detail: ProjectRow
  project_b_detail: ProjectRow
}
