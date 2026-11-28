"""用电核验回执与调试放行回执领域服务。

规则：
- 用电配置只做即时容量核对；核验通过后出具「用电核验回执」，把当时的设计负荷、
  回路额定功率与核验结论固化成快照，影音布置的调试放行回执必须挂在有效回执下。
- 一个回路在同一时段只能有一个有效放行额度（占用中的放行回执）。
- 设计负荷下调导致原核验结论失效时，原回执标记失效；已经开始的试音允许收尾
  （登记完成记录、结清占用），但失效额度不能再办新的试音。
- 审核员可按回执原编号查出当时的负荷明细；回路占用核对给出回执与用电侧占用
  是否一致、何时释放、谁需要复核旧记录。
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.services import exhibition
from app.store import store

_BOOTH_PATTERN = re.compile(r"BOOT-[A-Za-z0-9]+")

POWER_RECEIPT_TABLE = "power_receipt"
RELEASE_TABLE = "release_receipt"

# 核验回执状态
RECEIPT_VALID = "有效"
RECEIPT_INVALID = "失效"
# 放行回执状态
RELEASE_OCCUPYING = "占用中"
RELEASE_SETTLED = "已结清"
RELEASE_INVALID = "已失效"

VERIFY_PASS = "通过"
VERIFY_OVER = "超限"


def _parse_kw(value: Any) -> float:
    try:
        return float(str(value).replace("kW", "").replace("W", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _now() -> float:
    return time.time()


def _next_receipt_no(prefix: str) -> str:
    count = len(store.rows(POWER_RECEIPT_TABLE if prefix == "PWR" else RELEASE_TABLE))
    return f"{prefix}-{count + 1:04d}"


# ---------- 回执查询 ----------

def power_receipts(
    *,
    circuit_no: str | None = None,
    booth_no: str | None = None,
    status: str | None = None,
    receipt_no: str | None = None,
) -> list[dict[str, Any]]:
    rows = store.rows(POWER_RECEIPT_TABLE)
    if circuit_no:
        rows = [r for r in rows if r.get("circuit_no") == circuit_no]
    if booth_no:
        rows = [r for r in rows if r.get("booth_no") == booth_no]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if receipt_no:
        rows = [r for r in rows if receipt_no.casefold() in str(r.get("receipt_no", "")).casefold()]
    return rows


def find_power_receipt(receipt_id: int) -> dict[str, Any] | None:
    return store.find(POWER_RECEIPT_TABLE, receipt_id)


def find_power_receipt_by_no(receipt_no: str) -> dict[str, Any] | None:
    """审核员按原编号反查回执（含当时的负荷明细快照）。"""
    for row in store.rows(POWER_RECEIPT_TABLE):
        if row.get("receipt_no") == receipt_no:
            return row
    return None


def active_receipt_for_circuit(circuit_no: str) -> dict[str, Any] | None:
    for row in store.rows(POWER_RECEIPT_TABLE):
        if row.get("circuit_no") == circuit_no and row.get("status") == RECEIPT_VALID:
            return row
    return None


def releases(
    *,
    circuit_no: str | None = None,
    booth_no: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    rows = store.rows(RELEASE_TABLE)
    if circuit_no:
        rows = [r for r in rows if r.get("circuit_no") == circuit_no]
    if booth_no:
        rows = [r for r in rows if r.get("booth_no") == booth_no]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def find_release(release_id: int) -> dict[str, Any] | None:
    return store.find(RELEASE_TABLE, release_id)


def active_release_for_circuit(circuit_no: str) -> dict[str, Any] | None:
    """回路当前占用中的放行额度；同一回路同一时段至多一个。"""
    for row in store.rows(RELEASE_TABLE):
        if row.get("circuit_no") == circuit_no and row.get("status") == RELEASE_OCCUPYING:
            return row
    return None


def release_for_av(av_id: int) -> dict[str, Any] | None:
    for row in store.rows(RELEASE_TABLE):
        if row.get("av_id") == av_id and row.get("status") == RELEASE_OCCUPYING:
            return row
    return None


# ---------- 用电核验回执 ----------

def issue_power_receipt(circuit_id: int, operator: str = "值班员") -> dict[str, Any]:
    """对已核验回路出具用电核验回执，快照设计负荷、回路功率与核验结论。

    回路存在占用中的放行额度时拒绝出新回执，必须先结清旧占用；
    同一回路已有有效回执时，旧回执被新回执顶替（标记失效、保留编号可查）。
    """
    circuit = store.find("electrical", circuit_id)
    if circuit is None:
        return {"ok": False, "reason": f"用电回路 {circuit_id} 不存在"}
    if circuit.get("status") != "已确认":
        return {"ok": False, "reason": "回路尚未核验通过（状态非已确认），不能出具用电核验回执"}

    circuit_no = str(circuit.get("回路编号", ""))
    booth_no = str(circuit.get("所属展位", ""))

    occupying = active_release_for_circuit(circuit_no)
    if occupying is not None:
        return {
            "ok": False,
            "reason": (
                f"回路 {circuit_no} 存在占用中的放行额度 {occupying.get('receipt_no')}，"
                "须先登记试音完成并结清占用，才能重新出具核验回执"
            ),
            "occupying_release": occupying,
        }

    quota = exhibition.check_electrical_quota(booth_no)
    if not quota.get("ok"):
        return {
            "ok": False,
            "reason": f"核验不通过：{quota.get('reason', '')}",
            "quota": quota.get("quota", {}),
        }

    previous = active_receipt_for_circuit(circuit_no)
    receipt_id = store.next_id(POWER_RECEIPT_TABLE)
    receipt = {
        "id": receipt_id,
        "receipt_no": _next_receipt_no("PWR"),
        "status": RECEIPT_VALID,
        "booth_no": booth_no,
        "circuit_no": circuit_no,
        "circuit_id": circuit_id,
        "operator": operator,
        "verification": VERIFY_PASS,
        "design_load_kw": quota["quota"]["design_load"],
        "rated_power_kw": _parse_kw(circuit.get("额定功率")),
        "total_circuit_power_kw": quota["quota"]["total_circuit_power"],
        "load_detail": copy_detail(quota["quota"].get("circuits", [])),
        "reason": "",
        "superseded_by": None,
        "created_at": _now(),
        "invalidated_at": None,
    }
    store.rows(POWER_RECEIPT_TABLE).append(receipt)

    if previous is not None:
        previous["status"] = RECEIPT_INVALID
        previous["superseded_by"] = receipt_id
        previous["invalidated_at"] = _now()
        previous["reason"] = f"被新核验回执 {receipt['receipt_no']} 顶替"
        store.event_log.record(
            module=POWER_RECEIPT_TABLE,
            entry_id=previous["id"],
            action="回执顶替失效",
            before=None,
            after=dict(previous),
            extra={"booth_no": booth_no, "circuit_no": circuit_no},
        )

    store.event_log.record(
        module=POWER_RECEIPT_TABLE,
        entry_id=receipt_id,
        action="出具用电核验回执",
        after=dict(receipt),
        extra={"booth_no": booth_no, "circuit_no": circuit_no, "receipt_no": receipt["receipt_no"]},
    )
    return {"ok": True, "reason": "", "receipt": receipt}


def copy_detail(detail: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in detail]


def invalidate_power_receipt(receipt_id: int, reason: str) -> dict[str, Any]:
    """手动失效回执；占用中的放行额度保留，但挂上复核要求，不能再办新试音。"""
    receipt = find_power_receipt(receipt_id)
    if receipt is None:
        return {"ok": False, "reason": f"用电核验回执 {receipt_id} 不存在"}
    if receipt.get("status") == RECEIPT_INVALID:
        return {"ok": False, "reason": f"回执 {receipt['receipt_no']} 已是失效状态"}

    receipt["status"] = RECEIPT_INVALID
    receipt["invalidated_at"] = _now()
    receipt["reason"] = reason
    flagged = _flag_occupying_for_review(receipt, reason)

    store.event_log.record(
        module=POWER_RECEIPT_TABLE,
        entry_id=receipt_id,
        action="核验回执失效",
        after=dict(receipt),
        extra={
            "booth_no": receipt.get("booth_no"),
            "circuit_no": receipt.get("circuit_no"),
            "receipt_no": receipt.get("receipt_no"),
            "flagged_releases": flagged,
        },
    )
    return {"ok": True, "reason": "", "receipt": receipt, "flagged_releases": flagged}


def _flag_occupying_for_review(receipt: dict[str, Any], reason: str) -> list[str]:
    flagged: list[str] = []
    for rel in store.rows(RELEASE_TABLE):
        if (
            rel.get("circuit_no") == receipt.get("circuit_no")
            and rel.get("status") == RELEASE_OCCUPYING
        ):
            rel["review_required"] = True
            rel["review_note"] = (
                f"原核验回执 {receipt.get('receipt_no')} 已失效（{reason}），"
                "本次试音按收尾处理，完成记录需复核后结清"
            )
            flagged.append(str(rel.get("receipt_no")))
    return flagged


def reissue_power_receipt(receipt_id: int, operator: str = "值班员") -> dict[str, Any]:
    """按旧回执上的回路从新单重新核验（旧回执编号与负荷明细保留可查）。"""
    previous = find_power_receipt(receipt_id)
    if previous is None:
        return {"ok": False, "reason": f"用电核验回执 {receipt_id} 不存在"}
    return issue_power_receipt(int(previous["circuit_id"]), operator=operator)


# ---------- 设计负荷变更联动 ----------

def apply_design_load_change(design_id: int, new_load_kw: float) -> dict[str, Any]:
    """设计负荷下调后重新核对：结论由通过变超限的回执立即失效。

    已开始的试音不中断：占用中的放行回执保留并挂复核要求；失效额度不再接受
    新的放行申请，直到占用结清、重新核验。
    """
    design = store.find("design", design_id)
    if design is None:
        return {"ok": False, "reason": f"设计方案 {design_id} 不存在"}
    try:
        new_load = float(new_load_kw)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "新设计负荷格式不正确"}
    if new_load <= 0:
        return {"ok": False, "reason": "设计负荷必须大于0"}

    old_load = _parse_kw(design.get("用电负荷"))
    booth_no = str(design.get("备注说明", ""))
    design["用电负荷"] = str(new_load)
    store.event_log.record(
        module="design",
        entry_id=design_id,
        action="设计负荷变更",
        before={"用电负荷": old_load},
        after=dict(design),
        extra={"booth_no": booth_no},
    )

    quota = exhibition.check_electrical_quota(booth_no)
    invalidated: list[dict[str, Any]] = []
    if not quota.get("ok"):
        reason = f"设计负荷由{old_load:g}kW下调为{new_load:g}kW，{quota.get('reason', '')}"
        for receipt in power_receipts(booth_no=booth_no, status=RECEIPT_VALID):
            result = invalidate_power_receipt(int(receipt["id"]), reason)
            if result.get("ok"):
                invalidated.append(result["receipt"])

    occupying = [
        rel for rel in releases(booth_no=booth_no)
        if rel.get("status") == RELEASE_OCCUPYING
    ]
    return {
        "ok": True,
        "booth_no": booth_no,
        "old_load_kw": old_load,
        "new_load_kw": new_load,
        "quota": quota.get("quota", {}),
        "quota_ok": bool(quota.get("ok")),
        "invalidated_receipts": invalidated,
        "occupying_releases": occupying,
        "new_work_blocked": bool(invalidated) and bool(occupying),
    }


# ---------- 调试放行回执 ----------

def grant_release(receipt_id: int, av_id: int | None = None, granted_by: str = "值班员") -> dict[str, Any]:
    """基于有效用电核验回执办理调试放行，占用回路额度。"""
    receipt = find_power_receipt(receipt_id)
    if receipt is None:
        return {"ok": False, "reason": f"用电核验回执 {receipt_id} 不存在"}
    if receipt.get("status") != RECEIPT_VALID:
        return {
            "ok": False,
            "reason": f"回执 {receipt.get('receipt_no')} 已失效，失效额度不能再办新的试音放行",
        }

    circuit_no = str(receipt.get("circuit_no", ""))
    occupying = active_release_for_circuit(circuit_no)
    if occupying is not None:
        return {
            "ok": False,
            "reason": (
                f"回路 {circuit_no} 在该时段已有有效放行额度 {occupying.get('receipt_no')}，"
                "一个回路同一时段只能有一个有效放行额度"
            ),
            "occupying_release": occupying,
        }

    av_row = store.find("audio_visual", av_id) if av_id else None
    if av_row is not None:
        av_booth = _booth_of_av(av_row)
        if av_booth and av_booth != str(receipt.get("booth_no", "")):
            return {
                "ok": False,
                "reason": (
                    f"影音设备属于展位 {av_booth}，与核验回执 {receipt.get('receipt_no')} "
                    f"的展位 {receipt.get('booth_no')} 不一致，不能挂接该放行额度"
                ),
            }
    release_id = store.next_id(RELEASE_TABLE)
    release = {
        "id": release_id,
        "receipt_no": _next_receipt_no("REL"),
        "status": RELEASE_OCCUPYING,
        "power_receipt_id": receipt_id,
        "power_receipt_no": receipt.get("receipt_no"),
        "booth_no": receipt.get("booth_no"),
        "circuit_no": circuit_no,
        "av_id": av_id,
        "av_name": str(av_row.get("设备型号", "")) if av_row else "",
        "granted_power_kw": receipt.get("rated_power_kw"),
        "sound_test_power_kw": receipt.get("rated_power_kw"),
        "granted_by": granted_by,
        "reviewer": str(av_row.get("负责人", "")) if av_row else granted_by,
        "completion": "",
        "review_required": False,
        "review_note": "",
        "created_at": _now(),
        "completion_at": None,
        "settled_at": None,
        "invalidated_at": None,
    }
    store.rows(RELEASE_TABLE).append(release)
    store.event_log.record(
        module=RELEASE_TABLE,
        entry_id=release_id,
        action="办理调试放行",
        after=dict(release),
        extra={
            "booth_no": release["booth_no"],
            "circuit_no": circuit_no,
            "receipt_no": release["receipt_no"],
        },
    )
    return {"ok": True, "reason": "", "release": release}


def grant_release_for_av(av_id: int, granted_by: str = "值班员") -> dict[str, Any]:
    """影音布置调试：为设备所在展位挑选有效回执并占用回路额度。"""
    av_row = store.find("audio_visual", av_id)
    if av_row is None:
        return {"ok": False, "reason": f"影音设备 {av_id} 不存在"}
    booth_no = _booth_of_av(av_row)
    if not booth_no:
        return {"ok": False, "reason": "影音设备未关联展位，不能办理调试放行"}

    circuits = store.booth_electrical(booth_no)
    circuit_nos = [str(c.get("回路编号", "")) for c in circuits]
    occupying_circuits = [
        str(rel.get("circuit_no")) for rel in releases(booth_no=booth_no, status=RELEASE_OCCUPYING)
    ]
    for circuit_no in circuit_nos:
        if circuit_no in occupying_circuits:
            rel = active_release_for_circuit(circuit_no)
            return {
                "ok": False,
                "reason": (
                    f"回路 {circuit_no} 已有占用中的放行额度 {rel.get('receipt_no') if rel else ''}，"
                    "须先结清本次占用再调试"
                ),
            }
        receipt = active_receipt_for_circuit(circuit_no)
        if receipt is not None:
            return grant_release(int(receipt["id"]), av_id=av_id, granted_by=granted_by)

    return {
        "ok": False,
        "reason": f"展位 {booth_no} 没有有效用电核验回执，影音设备不可调试放行，请先在用电配置出具核验回执",
    }


def _booth_of_av(av_row: dict[str, Any]) -> str:
    match = _BOOTH_PATTERN.search(str(av_row.get("备注说明", "")))
    return match.group(0) if match else ""


def submit_completion(release_id: int, completion: str) -> dict[str, Any]:
    """登记试音完成记录。只处理已开始试音的收尾，失效额度下也允许登记并要求复核。"""
    rel = find_release(release_id)
    if rel is None:
        return {"ok": False, "reason": f"放行回执 {release_id} 不存在"}
    if rel.get("status") != RELEASE_OCCUPYING:
        return {"ok": False, "reason": f"放行回执 {rel.get('receipt_no')} 当前状态 {rel.get('status')}，不能登记完成记录"}

    text = completion.strip() if completion else "现场试音完成"
    rel["completion"] = text
    rel["completion_at"] = _now()

    receipt = find_power_receipt(int(rel["power_receipt_id"]))
    if receipt is not None and receipt.get("status") == RECEIPT_INVALID:
        rel["review_required"] = True
        rel["review_note"] = (
            f"试音期间原核验回执 {receipt.get('receipt_no')} 已失效，"
            "完成记录需审核员复核旧额度后再结清"
        )

    av_id = rel.get("av_id")
    if av_id:
        av_row = store.find("audio_visual", int(av_id))
        if av_row is not None:
            av_row["调试试音"] = "试音完成-待复核" if rel.get("review_required") else "试音完成"

    store.event_log.record(
        module=RELEASE_TABLE,
        entry_id=release_id,
        action="登记试音完成",
        after=dict(rel),
        extra={
            "booth_no": rel.get("booth_no"),
            "circuit_no": rel.get("circuit_no"),
            "receipt_no": rel.get("receipt_no"),
            "review_required": rel.get("review_required", False),
        },
    )
    return {"ok": True, "reason": "", "release": rel}


def settle_release(release_id: int) -> dict[str, Any]:
    """结清占用，释放回路额度。待复核记录结清后仍保留复核标记供审核员追查。"""
    rel = find_release(release_id)
    if rel is None:
        return {"ok": False, "reason": f"放行回执 {release_id} 不存在"}
    if rel.get("status") != RELEASE_OCCUPYING:
        return {"ok": False, "reason": f"放行回执 {rel.get('receipt_no')} 已{rel.get('status')}，无需重复结清"}

    rel["status"] = RELEASE_SETTLED
    rel["settled_at"] = _now()
    store.event_log.record(
        module=RELEASE_TABLE,
        entry_id=release_id,
        action="结清放行占用",
        after=dict(rel),
        extra={
            "booth_no": rel.get("booth_no"),
            "circuit_no": rel.get("circuit_no"),
            "receipt_no": rel.get("receipt_no"),
            "review_required": rel.get("review_required", False),
        },
    )
    return {"ok": True, "reason": "", "release": rel}


# ---------- 回路占用一致性核对 ----------

def circuit_occupancy(circuit_no: str) -> dict[str, Any]:
    """核对核验回执与用电侧占用状态是否一致，给出释放时间与复核责任人。"""
    circuit_nos = {str(row.get("回路编号", "")) for row in store.rows("electrical")}
    if circuit_no not in circuit_nos:
        return {"ok": False, "reason": f"回路 {circuit_no} 不存在"}

    receipt = active_receipt_for_circuit(circuit_no)
    receipt_history = [r for r in power_receipts(circuit_no=circuit_no)]
    occupying = active_release_for_circuit(circuit_no)
    latest_release = None
    circuit_releases = releases(circuit_no=circuit_no)
    if circuit_releases:
        latest_release = sorted(circuit_releases, key=lambda r: r.get("id", 0))[-1]

    consistent = True
    conflict = ""
    if occupying is not None:
        linked = find_power_receipt(int(occupying["power_receipt_id"]))
        if linked is None or linked.get("status") == RECEIPT_INVALID:
            consistent = False
            conflict = "用电侧仍有占用，但所依据的核验回执已失效"
    if receipt is None and occupying is None:
        # 无有效额度且无占用：空闲可办新单（历史回执失效属正常）
        consistent = True

    if occupying is not None:
        release_state = "占用中，登记试音完成并结清后释放"
        released_at = None
    elif latest_release is not None and latest_release.get("status") == RELEASE_SETTLED:
        release_state = "已释放"
        released_at = latest_release.get("settled_at")
    else:
        release_state = "回路空闲"
        released_at = None

    reviewer = ""
    review_items: list[dict[str, Any]] = []
    for rel in circuit_releases:
        if rel.get("review_required"):
            review_items.append({
                "release_no": rel.get("receipt_no"),
                "reviewer": rel.get("reviewer", ""),
                "note": rel.get("review_note", ""),
                "status": rel.get("status"),
            })
            if not reviewer:
                reviewer = str(rel.get("reviewer", ""))

    return {
        "ok": True,
        "circuit_no": circuit_no,
        "consistent": consistent,
        "conflict": conflict,
        "active_receipt": receipt,
        "receipt_history": receipt_history,
        "occupying_release": occupying,
        "latest_release": latest_release,
        "release_state": release_state,
        "released_at": released_at,
        "new_work_allowed": receipt is not None and occupying is None,
        "review_required": bool(review_items),
        "reviewer": reviewer,
        "review_items": review_items,
    }
