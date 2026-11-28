"""用电配置领域服务：功率校验、展位负荷比对、断路器型号合规检查。

用电配置本身只做即时容量核对；核验通过后通过「出具核验回执」动作把设计负荷、
回路额定功率与核验结论固化为用电核验回执，供影音布置的调试放行回执关联。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services import power_receipt
from app.store import store
from app.services import exhibition


class ElectricalService(BaseModuleService):
    MODULE = "electrical"
    ENTITY = "用电回路"
    OPERATION_TERM = "核验用电"
    LIST_FIELDS = ["回路编号", "额定功率", "所属展位", "断路器型号", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["回路编号", "额定功率", "所属展位"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"核验用电": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []
    RELATED_MODULES = ["booth", "design"]

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        booth_no = str(values.get("所属展位", "")).strip()
        if booth_no:
            booth = store.find_booth(booth_no)
            if booth is None:
                errors.append(f"所属展位 {booth_no} 不存在，请先登记展位")
        try:
            power = float(str(values.get("额定功率", "0")).replace("kW", "").replace("W", "").strip())
            if power <= 0:
                errors.append("额定功率必须大于0")
        except (ValueError, AttributeError):
            errors.append("额定功率格式不正确")
        return errors

    def validate_action(self, entry_id: int, action: str) -> tuple[bool, str]:
        if action == "核验用电":
            entry = store.find(self.MODULE, entry_id)
            if entry is None:
                return False, "用电回路不存在"
            booth_no = str(entry.get("所属展位", ""))
            if booth_no:
                result = exhibition.check_electrical_quota(booth_no)
                if not result["ok"]:
                    return False, result["reason"]
        elif action == "出具核验回执":
            entry = store.find(self.MODULE, entry_id)
            if entry is None:
                return False, "用电回路不存在"
            if entry.get("status") != "已确认":
                return False, "回路尚未核验通过，不能出具用电核验回执"
            circuit_no = str(entry.get("回路编号", ""))
            occupying = power_receipt.active_release_for_circuit(circuit_no)
            if occupying is not None:
                return (
                    False,
                    f"回路 {circuit_no} 存在占用中的放行额度 {occupying.get('receipt_no')}，"
                    "须先结清占用再重新出具回执",
                )
        return True, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action == "出具核验回执":
            result = power_receipt.issue_power_receipt(entry_id, operator="值班员")
            if not result.get("ok"):
                return None, result["reason"]
            receipt = result["receipt"]
            entry = store.find(self.MODULE, entry_id)
            return entry, (
                f"用电核验回执 {receipt['receipt_no']} 已出具（结论：{receipt['verification']}，"
                f"设计负荷 {receipt['design_load_kw']:g}kW，"
                f"回路总功率 {receipt['total_circuit_power_kw']:g}kW）"
            )
        return super().run_action(entry_id, action)

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        rows = store.rows(self.MODULE)
        confirmed = [r for r in rows if r.get("status") == "已确认"]
        total_power = 0.0
        for c in confirmed:
            try:
                total_power += float(str(c.get("额定功率", "0")).replace("kW", "").replace("W", "").strip())
            except (ValueError, AttributeError):
                pass
        base["total_circuit_power"] = total_power
        return base
