const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function getToken(): string | null {
  return localStorage.getItem('access_token')
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem('access_token', token)
  else localStorage.removeItem('access_token')
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(response.status, body.detail ?? 'Request failed')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface UserOut {
  id: string
  username: string
  email: string
  role: 'admin' | 'planner' | 'staff'
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface AnnotationOut {
  id: string
  creator_id: string
  title: string
  description: string | null
  geometry: Record<string, unknown>
  priority: string | null
  assignee_id: string | null
  due_date: string | null
  status: string | null
  reviewed_by_id: string | null
  reviewed_at: string | null
  rejection_reason: string | null
  created_at: string
  updated_at: string
}

export interface CurrentStatusRow {
  site_id: string
  zoom_sector_id: string
  region: string
  congested: boolean
  latitude: number | null
  longitude: number | null
}

export interface SectorMetricRow {
  site_id: string
  zoom_sector_id: string
  region: string
  cluster: string
  ibc_macro: string
  f1f2f3: string
  eric_data_volume_ul_dl: number
  eric_prb_util_rate: number
  eric_dl_user_ip_thpt: number
  eric_max_rrc_user: number
  dataset_type: string
  operator: string
  congested: boolean
  congested_weeks: number
  year: number
  week: number
}

export interface ForecastRow {
  zoom_sector_id: string
  region: string
  predicted_eric_data_volume_ul_dl: number
  predicted_eric_prb_util_rate: number
  predicted_eric_dl_user_ip_thpt: number
  congested: boolean
  year: number
  week: number
  month: number
}

export interface SummaryStats {
  total_sectors: number
  congested_count: number
  avg_volume_gb: number
}

export interface FilterOptions {
  regions: string[]
  years: number[]
  weeks: number[]
  operators: string[]
}

export interface AnalyticsFilters {
  region?: string
  year?: number
  week?: number
  operator?: string
  cluster?: string
}

function filterParams(filters: AnalyticsFilters = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '' && value !== 'All') {
      params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export const api = {
  login: (username: string, password: string) =>
    request<TokenPair>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

  register: (username: string, email: string, password: string, role = 'staff') =>
    request<UserOut>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password, role }),
    }),

  me: () => request<UserOut>('/auth/me'),

  ganttRows: () => request<AnnotationOut[]>('/annotations/gantt/rows'),

  currentStatus: () => request<CurrentStatusRow[]>('/analytics/current-status'),

  filterOptions: () => request<FilterOptions>('/analytics/filter-options'),

  summary: (filters: AnalyticsFilters = {}) => request<SummaryStats>(`/analytics/summary${filterParams(filters)}`),

  sectorMetrics: (filters: AnalyticsFilters = {}) =>
    request<SectorMetricRow[]>(`/analytics/sector-metrics${filterParams(filters)}`),

  congestedSectors: (filters: AnalyticsFilters = {}) =>
    request<SectorMetricRow[]>(`/analytics/congested-sectors${filterParams(filters)}`),

  forecastTable: (filters: AnalyticsFilters = {}) =>
    request<ForecastRow[]>(`/analytics/forecast-table${filterParams(filters)}`),
}
