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

export interface ConversationOut {
  id: string
  is_group: boolean
  title: string | null
  created_at: string
  participant_ids: string[]
}

export interface MessageOut {
  id: string
  conversation_id: string
  sender_id: string
  body: string
  created_at: string
}

export interface ProjectOut {
  id: string
  creator_id: string
  title: string
  description: string | null
  assignee_id: string | null
  conversation_id: string | null
  created_at: string
  updated_at: string
}

export interface AnnotationOut {
  id: string
  project_id: string
  creator_id: string
  label: string | null
  geometry: Record<string, unknown>
  created_at: string
}

export interface TaskOut {
  id: string
  project_id: string
  creator_id: string
  title: string
  description: string | null
  assignee_ids: string[]
  due_date: string
  status: string
  reviewed_by_id: string | null
  reviewed_at: string | null
  rejection_reason: string | null
  created_at: string
  updated_at: string
}

export interface CommentOut {
  id: string
  project_id: string
  author_id: string
  body: string
  created_at: string
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

export interface SiteDetail {
  site: { site_id: string; region: string; cluster: string; latitude: number; longitude: number } | null
  congested: boolean
  sectors: SectorMetricRow[]
  forecast: ForecastRow[]
  capex_upgrades: Record<string, unknown>[]
}

export interface CoverageHoleSummary {
  cluster_id: number
  data_source: string
  point_count: number
  avg_signal: number | null
}

export interface MapStats {
  total_sites: number
  congested_sites: number
  healthy_sites: number
  coverage_holes: number
  worst_coverage_hole: CoverageHoleSummary | null
  total_capex: number
}

export interface OverviewStats {
  total_sites: number
  total_congested_sites: number
  total_capex: number
  worst_ookla_cluster: CoverageHoleSummary | null
  worst_mr_cluster: CoverageHoleSummary | null
}

export interface MapBounds {
  south: number
  west: number
  north: number
  east: number
}

export interface CapexPriceItem {
  price?: number
  price_min: number
  price_max: number
}

export type CapexPricing = Record<string, Record<string, CapexPriceItem>>

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

  listUsers: () => request<UserOut[]>('/auth/users'),

  ganttRows: () => request<TaskOut[]>('/tasks/gantt/rows'),

  currentStatus: () => request<CurrentStatusRow[]>('/analytics/current-status'),

  forecastStatus: (year: number, week: number) =>
    request<CurrentStatusRow[]>(`/analytics/forecast-status?year=${year}&week=${week}`),

  siteDetail: (siteId: string) => request<SiteDetail>(`/analytics/site-detail/${siteId}`),

  mapStats: (bounds: MapBounds, year?: number, week?: number) => {
    const params = new URLSearchParams({
      south: String(bounds.south), west: String(bounds.west),
      north: String(bounds.north), east: String(bounds.east),
    })
    if (year != null) params.set('year', String(year))
    if (week != null) params.set('week', String(week))
    return request<MapStats>(`/analytics/map-stats?${params}`)
  },

  overviewStats: () => request<OverviewStats>('/analytics/overview-stats'),

  filterOptions: () => request<FilterOptions>('/analytics/filter-options'),

  summary: (filters: AnalyticsFilters = {}) => request<SummaryStats>(`/analytics/summary${filterParams(filters)}`),

  sectorMetrics: (filters: AnalyticsFilters = {}) =>
    request<SectorMetricRow[]>(`/analytics/sector-metrics${filterParams(filters)}`),

  congestedSectors: (filters: AnalyticsFilters = {}) =>
    request<SectorMetricRow[]>(`/analytics/congested-sectors${filterParams(filters)}`),

  forecastTable: (filters: AnalyticsFilters = {}) =>
    request<ForecastRow[]>(`/analytics/forecast-table${filterParams(filters)}`),

  createProject: (input: { title: string; description?: string; assignee_id?: string }) =>
    request<ProjectOut>('/projects', { method: 'POST', body: JSON.stringify(input) }),

  listProjects: () => request<ProjectOut[]>('/projects'),

  getProject: (id: string) => request<ProjectOut>(`/projects/${id}`),

  assignProject: (id: string, assignee_id: string) =>
    request<ProjectOut>(`/projects/${id}/assign`, { method: 'POST', body: JSON.stringify({ assignee_id }) }),

  addAnnotation: (projectId: string, geometry: Record<string, unknown>, label?: string) =>
    request<AnnotationOut>(`/projects/${projectId}/annotations`, {
      method: 'POST',
      body: JSON.stringify({ geometry, label }),
    }),

  listAnnotations: (projectId: string) => request<AnnotationOut[]>(`/projects/${projectId}/annotations`),

  createTask: (
    projectId: string,
    input: { title: string; assignee_ids: string[]; due_date: string; description?: string },
  ) => request<TaskOut>(`/projects/${projectId}/tasks`, { method: 'POST', body: JSON.stringify(input) }),

  listTasks: (projectId: string) => request<TaskOut[]>(`/tasks/gantt/rows?project_id=${projectId}`),

  startTask: (id: string) => request<TaskOut>(`/tasks/${id}/start`, { method: 'POST' }),

  submitTask: (id: string) => request<TaskOut>(`/tasks/${id}/submit`, { method: 'POST' }),

  approveTask: (id: string) => request<TaskOut>(`/tasks/${id}/approve`, { method: 'POST' }),

  rejectTask: (id: string, reason: string) =>
    request<TaskOut>(`/tasks/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),

  addProjectComment: (projectId: string, body: string) =>
    request<CommentOut>(`/projects/${projectId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    }),

  listProjectComments: (projectId: string) => request<CommentOut[]>(`/projects/${projectId}/comments`),

  capexPricing: () => request<CapexPricing>('/capex-pricing'),

  upsertCapexPrice: (category: string, itemName: string, input: { price: number; price_min?: number; price_max?: number }) =>
    request<CapexPricing>(`/capex-pricing/${category}/${encodeURIComponent(itemName)}`, {
      method: 'PUT',
      body: JSON.stringify(input),
    }),

  listConversations: () => request<ConversationOut[]>('/chat/conversations'),

  createDirectConversation: (otherUserId: string) =>
    request<ConversationOut>('/chat/conversations/direct', {
      method: 'POST',
      body: JSON.stringify({ other_user_id: otherUserId }),
    }),

  createGroupConversation: (title: string, participantIds: string[]) =>
    request<ConversationOut>('/chat/conversations/group', {
      method: 'POST',
      body: JSON.stringify({ title, participant_ids: participantIds }),
    }),

  listMessages: (conversationId: string) => request<MessageOut[]>(`/chat/conversations/${conversationId}/messages`),

  sendMessage: (conversationId: string, body: string) =>
    request<MessageOut>(`/chat/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    }),

  agentChat: (message: string) =>
    request<{ reply: string }>('/agent/chat', { method: 'POST', body: JSON.stringify({ message }) }),
}
