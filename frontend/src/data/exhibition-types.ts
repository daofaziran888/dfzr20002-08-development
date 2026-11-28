/** 会展引擎专用类型 */

export interface EventRecord {
  id: number
  timestamp: number
  module: string
  entry_id: number
  action: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  extra: Record<string, unknown>
}

export interface SafetyStatus {
  ok: boolean
  reason: string
  total_inspections: number
  failed_inspections: Record<string, unknown>[]
}

export interface ElectricalQuota {
  booth_no: string
  design_load: number
  total_circuit_power: number
  over_draw: number
  circuits: Record<string, unknown>[]
}

export interface ExhibitionHistory {
  booth_no: string
  booth: Record<string, unknown> | null
  design: Record<string, unknown> | null
  events: EventRecord[]
  event_count: number
  current_safety: SafetyStatus
  current_electrical: { ok: boolean; reason: string; quota: ElectricalQuota }
  schedule_conflicts: Record<string, unknown>[]
}

export interface QuotaItem {
  venue: string
  venue_id: number
  ok: boolean
  reason: string
  quota: Record<string, unknown>
}

export interface PowerQuotaItem {
  ok: boolean
  reason: string
  quota: ElectricalQuota
}

export interface ScheduleConflict {
  transport_id: number
  exhibit: string
  arrival: string
  schedule_id: number
  event: string
  setup_start: string
  conflict: string
}

export interface QuotaSummary {
  area_quotas: QuotaItem[]
  power_quotas: PowerQuotaItem[]
  schedule_conflicts: ScheduleConflict[]
  schedule_conflict_count: number
  dag_cycle: string[] | null
  dag_ok: boolean
  overall_ok: boolean
}

export interface DAGStatus {
  cycle: string[] | null
  has_cycle: boolean
  topological_order: string[]
  node_count: number
}

export interface HandoverResult {
  ok: boolean
  reason: string
  handover?: Record<string, unknown>
  validation?: Record<string, unknown>
}

/** 用电核验回执：固化核验当时的设计负荷与回路额定功率快照。 */
export interface PowerReceipt {
  id: number
  receipt_no: string
  status: string
  booth_no: string
  circuit_no: string
  circuit_id: number
  operator: string
  verification: string
  design_load_kw: number
  rated_power_kw: number
  total_circuit_power_kw: number
  load_detail: { circuit_id: string; power: number; status: string }[]
  reason: string
  superseded_by: number | null
  created_at: number
  invalidated_at: number | null
}

/** 调试放行回执：一个回路同一时段至多一张占用中的额度。 */
export interface ReleaseReceipt {
  id: number
  receipt_no: string
  status: string
  power_receipt_id: number
  power_receipt_no: string
  booth_no: string
  circuit_no: string
  av_id: number | null
  av_name: string
  granted_power_kw: number
  sound_test_power_kw: number
  granted_by: string
  reviewer: string
  completion: string
  review_required: boolean
  review_note: string
  created_at: number
  completion_at: number | null
  settled_at: number | null
  invalidated_at: number | null
}

export interface CircuitOccupancy {
  ok: boolean
  circuit_no: string
  consistent: boolean
  conflict: string
  active_receipt: PowerReceipt | null
  receipt_history: PowerReceipt[]
  occupying_release: ReleaseReceipt | null
  latest_release: ReleaseReceipt | null
  release_state: string
  released_at: number | null
  new_work_allowed: boolean
  review_required: boolean
  reviewer: string
  review_items: { release_no: string; reviewer: string; note: string; status: string }[]
}

export interface LoadChangeResult {
  ok: boolean
  booth_no: string
  old_load_kw: number
  new_load_kw: number
  quota: Record<string, unknown>
  quota_ok: boolean
  invalidated_receipts: PowerReceipt[]
  occupying_releases: ReleaseReceipt[]
  new_work_blocked: boolean
}