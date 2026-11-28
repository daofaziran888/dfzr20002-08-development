"""用电核验回执与调试放行回执路由。

覆盖：回执出具/查询/按原编号反查/重新核验、放行额度办理/完成登记/结清、
设计负荷变更联动失效、回路占用一致性核对。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import power_receipt as pr

router = APIRouter(prefix="/api/exhibition/power", tags=["用电核验与调试放行"])


class ReleaseGrantPayload(BaseModel):
    receipt_id: int
    av_id: int | None = None
    granted_by: str = "值班员"


class CompletionPayload(BaseModel):
    completion: str = "现场试音完成"


class LoadChangePayload(BaseModel):
    new_load_kw: float = Field(gt=0)


def _require(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "操作被拒绝"))
    return result


# ---------- 用电核验回执 ----------

@router.get("/receipts")
def list_receipts(
    circuit_no: str | None = None,
    booth_no: str | None = None,
    status: str | None = None,
    receipt_no: str | None = None,
) -> dict[str, Any]:
    items = pr.power_receipts(
        circuit_no=circuit_no, booth_no=booth_no, status=status, receipt_no=receipt_no
    )
    return {"items": items, "total": len(items)}


@router.get("/receipts/by-no/{receipt_no}")
def receipt_by_no(receipt_no: str) -> dict[str, Any]:
    """审核员按原编号查出当时的负荷明细（快照不可变）。"""
    receipt = pr.find_power_receipt_by_no(receipt_no)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"核验回执 {receipt_no} 不存在")
    return receipt


@router.get("/receipts/{receipt_id}")
def receipt_detail(receipt_id: int) -> dict[str, Any]:
    receipt = pr.find_power_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"核验回执 {receipt_id} 不存在")
    return receipt


@router.post("/receipts/{receipt_id}/reissue")
def reissue_receipt(receipt_id: int) -> dict[str, Any]:
    """从新单重新核验同一回路；旧回执编号与负荷明细保留。"""
    result = pr.reissue_power_receipt(receipt_id)
    _require(result)
    return result


# ---------- 调试放行回执 ----------

@router.get("/releases")
def list_releases(
    circuit_no: str | None = None,
    booth_no: str | None = None,
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    items = pr.releases(circuit_no=circuit_no, booth_no=booth_no, status=status)
    return {"items": items, "total": len(items)}


@router.post("/releases")
def grant_release(payload: ReleaseGrantPayload) -> dict[str, Any]:
    """从另一张新单（有效核验回执）为同一回路办理调试放行额度。"""
    result = pr.grant_release(
        payload.receipt_id, av_id=payload.av_id, granted_by=payload.granted_by
    )
    _require(result)
    return result


@router.post("/releases/{release_id}/completion")
def submit_completion(release_id: int, payload: CompletionPayload) -> dict[str, Any]:
    """只处理已开始试音的收尾：登记完成记录，失效额度下挂复核要求。"""
    result = pr.submit_completion(release_id, payload.completion)
    _require(result)
    return result


@router.post("/releases/{release_id}/settle")
def settle_release(release_id: int) -> dict[str, Any]:
    """结清本次占用并释放回路；待复核记录结清后仍保留复核标记。"""
    result = pr.settle_release(release_id)
    _require(result)
    return result


# ---------- 设计负荷变更联动 ----------

@router.post("/design/{design_id}/load-change")
def change_design_load(design_id: int, payload: LoadChangePayload) -> dict[str, Any]:
    """设计负荷下调：超限回执立即失效，占用中的试音保留并要求复核。"""
    result = pr.apply_design_load_change(design_id, payload.new_load_kw)
    _require(result)
    return result


# ---------- 回路占用一致性核对 ----------

@router.get("/circuit/{circuit_no}/occupancy")
def circuit_occupancy(circuit_no: str) -> dict[str, Any]:
    """核对回执与用电侧占用是否一致、何时释放、谁需复核旧记录。"""
    result = pr.circuit_occupancy(circuit_no)
    _require(result)
    return result
