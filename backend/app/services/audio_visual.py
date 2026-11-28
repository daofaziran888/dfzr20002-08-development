"""影音布置领域服务：设备安装位置合规检查、信号线路连通性校验、展位关联。

调试设备不再只看回路是否核验，而是要消费一张有效的用电核验回执并办理调试放行
回执（一个回路同一时段只能有一个有效放行额度）。试音开始后即使原核验额度失效，
仍允许通过「登记试音完成」收尾；失效额度不能再发起新的调试放行。
"""
from __future__ import annotations
import re
from typing import Any
from app.services.base import BaseModuleService
from app.services import power_receipt
from app.store import store

_BOOTH_PATTERN = re.compile(r"BOOT-[A-Za-z0-9]+")


def extract_booth_no(text: str) -> str:
    """从备注文本中提取展位编号，兼容 'BOOT-A01投影' 这类无空格写法。"""
    match = _BOOTH_PATTERN.search(str(text or ""))
    return match.group(0) if match else ""


class AudioVisualService(BaseModuleService):
    MODULE = "audio_visual"
    ENTITY = "影音设备"
    OPERATION_TERM = "调试设备"
    LIST_FIELDS = ["设备型号", "安装位置", "信号线路", "调试试音", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["设备型号", "安装位置", "信号线路"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {
        "调试设备": "已确认",
        "登记试音完成": "已确认",
        "提交确认": "待确认",
        "撤回记录": "已撤回",
    }
    NEGATIVE_ACTIONS = []
    RELATED_MODULES = ["electrical", "booth"]

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        model = str(values.get("设备型号", "")).strip()
        if not model:
            errors.append("设备型号不能为空")
        # 跨模块校验：影音设备备注说明应对应有效展位
        remark = str(values.get("备注说明", "")).strip()
        booth_no = extract_booth_no(remark)
        if booth_no:
            booth = store.find_booth(booth_no)
            if booth is None:
                errors.append(f"展位 {booth_no} 不存在，请先登记展位")
        return errors

    def _booth_no(self, entry: dict[str, Any]) -> str:
        return extract_booth_no(entry.get("备注说明", ""))

    def validate_action(self, entry_id: int, action: str) -> tuple[bool, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return False, "影音设备不存在"
        booth_no = self._booth_no(entry)
        if action == "调试设备":
            if not booth_no:
                return False, "影音设备未关联展位，不能调试放行"
            circuits = store.booth_electrical(booth_no)
            confirmed = [c for c in circuits if c.get("status") == "已确认"]
            if not confirmed:
                return False, f"展位 {booth_no} 用电回路尚未核验，影音设备不可调试"
            # 放行前提：至少一张有效用电核验回执，且回路没有占用中的额度
            for circuit in confirmed:
                circuit_no = str(circuit.get("回路编号", ""))
                if power_receipt.active_release_for_circuit(circuit_no) is not None:
                    occupying = power_receipt.active_release_for_circuit(circuit_no)
                    return (
                        False,
                        f"回路 {circuit_no} 已有占用中的放行额度 {occupying.get('receipt_no')}，"
                        "一个回路同一时段只能有一个有效放行额度，请先登记完成并结清",
                    )
            valid_receipt = any(
                power_receipt.active_receipt_for_circuit(str(c.get("回路编号", ""))) is not None
                for c in confirmed
            )
            if not valid_receipt:
                return (
                    False,
                    f"展位 {booth_no} 暂无有效用电核验回执，请先在用电配置出具核验回执后再调试放行",
                )
        elif action == "登记试音完成":
            if power_receipt.release_for_av(entry_id) is None:
                return False, "该影音设备没有占用中的调试放行回执，不能登记试音完成"
        return True, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action == "调试设备":
            # 先跑领域校验，再由回执服务办理放行（占用回路额度）
            allowed, reason = self.validate_action(entry_id, "调试设备")
            if not allowed:
                return None, reason
            result = power_receipt.grant_release_for_av(entry_id, granted_by="值班员")
            if not result.get("ok"):
                return None, result["reason"]
            release = result["release"]
            entry = store.find(self.MODULE, entry_id)
            before = dict(entry)
            entry["status"] = "已确认"
            entry["pending"] = False
            entry["调试试音"] = "试音中"
            store.event_log.record(
                module=self.MODULE,
                entry_id=entry_id,
                action="调试设备-放行",
                before=before,
                after=dict(entry),
                extra={"release_no": release["receipt_no"], "booth_no": release["booth_no"]},
            )
            return entry, (
                f"调试放行回执 {release['receipt_no']} 已办理，占用回路 {release['circuit_no']}，"
                f"关联核验回执 {release['power_receipt_no']}"
            )
        if action == "登记试音完成":
            allowed, reason = self.validate_action(entry_id, "登记试音完成")
            if not allowed:
                return None, reason
            release = power_receipt.release_for_av(entry_id)
            result = power_receipt.submit_completion(int(release["id"]), "现场提交试音完成记录")
            if not result.get("ok"):
                return None, result["reason"]
            entry = store.find(self.MODULE, entry_id)
            before = dict(entry)
            entry["调试试音"] = (
                "试音完成-待复核" if result["release"].get("review_required") else "试音完成"
            )
            store.event_log.record(
                module=self.MODULE,
                entry_id=entry_id,
                action="登记试音完成",
                before=before,
                after=dict(entry),
                extra={"release_no": release["receipt_no"], "booth_no": release["booth_no"]},
            )
            tail = "，原核验额度已失效，完成记录需复核后结清" if result["release"].get("review_required") else ""
            return entry, f"放行回执 {release['receipt_no']} 已登记试音完成{tail}"
        return super().run_action(entry_id, action)

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        rows = store.rows(self.MODULE)
        booth_linked = sum(1 for r in rows if "BOOT-" in str(r.get("备注说明", "")))
        base["booth_linked_count"] = booth_linked
        base["active_release_count"] = len(
            power_receipt.releases(status=power_receipt.RELEASE_OCCUPYING)
        )
        return base
