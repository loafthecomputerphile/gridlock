/**
 * Locked report palette — these hues are non-negotiable (phase 04).
 * Every map layer and legend swatch reads from here; grep for these hexes
 * is part of scripts/check_04.
 */
export const UTILITY = {
  DESC: '#2563EB',
  GPC: '#059669',
} as const

export const TIER_HALO = {
  crossing: '#DC2626', // "touching"
  '<1.6 km': '#F97316',
  '<8 km': '#FBBF24',
  '<40 km': '#FDE68A',
  excluded: '#9CA3AF', // grey
} as const

/** Excluded halos render at 20% opacity (report color language). */
export const EXCLUDED_OPACITY = 0.2

export const TIER_LABEL: Record<string, string> = {
  crossing: 'touching',
  '<1.6 km': '<1.6 km',
  '<8 km': '<8 km',
  '<40 km': '<40 km',
  excluded: 'excluded >40 km',
}
