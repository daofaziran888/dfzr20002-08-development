/** 用电核验回执与调试放行回执 API。 */
import { request } from './client'
import type {
  CircuitOccupancy,
  LoadChangeResult,
  PowerReceipt,
  ReleaseReceipt,
} from '@/data/exhibition-types'

const BASE = '/api/exhibition/power'

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `接口返回 ${response.status}`)
  }
  return (await response.json()) as T
}

export async function fetchPowerReceipts(params: {
  circuit_no?: string
  booth_no?: string
  status?: string
  receipt_no?: string
} = {}): Promise<{ items: PowerReceipt[]; total: number }> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][],
  ).toString()
  return readJson(await request(`${BASE}/receipts?${query}`))
}

export async function fetchReceiptByNo(receiptNo: string): Promise<PowerReceipt> {
  return readJson(await request(`${BASE}/receipts/by-no/${encodeURIComponent(receiptNo)}`))
}

export async function reissueReceipt(receiptId: number): Promise<{ ok: boolean; receipt: PowerReceipt }> {
  return readJson(
    await request(`${BASE}/receipts/${receiptId}/reissue`, { method: 'POST', body: '{}' }),
  )
}

export async function fetchReleases(params: {
  circuit_no?: string
  booth_no?: string
  status?: string
} = {}): Promise<{ items: ReleaseReceipt[]; total: number }> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][],
  ).toString()
  return readJson(await request(`${BASE}/releases?${query}`))
}

export async function grantRelease(
  receiptId: number,
  avId: number | null,
): Promise<{ ok: boolean; release: ReleaseReceipt }> {
  return readJson(
    await request(`${BASE}/releases`, {
      method: 'POST',
      body: JSON.stringify({ receipt_id: receiptId, av_id: avId }),
    }),
  )
}

export async function submitReleaseCompletion(
  releaseId: number,
  completion: string,
): Promise<{ ok: boolean; release: ReleaseReceipt }> {
  return readJson(
    await request(`${BASE}/releases/${releaseId}/completion`, {
      method: 'POST',
      body: JSON.stringify({ completion }),
    }),
  )
}

export async function settleRelease(
  releaseId: number,
): Promise<{ ok: boolean; release: ReleaseReceipt }> {
  return readJson(
    await request(`${BASE}/releases/${releaseId}/settle`, { method: 'POST', body: '{}' }),
  )
}

export async function applyDesignLoadChange(
  designId: number,
  newLoadKw: number,
): Promise<LoadChangeResult> {
  return readJson(
    await request(`${BASE}/design/${designId}/load-change`, {
      method: 'POST',
      body: JSON.stringify({ new_load_kw: newLoadKw }),
    }),
  )
}

export async function fetchCircuitOccupancy(circuitNo: string): Promise<CircuitOccupancy> {
  return readJson(
    await request(`${BASE}/circuit/${encodeURIComponent(circuitNo)}/occupancy`),
  )
}
