"""用电核验回执 + 调试放行回执：负荷快照、失效额度、回路占用一致性测试。

完整复刻业务场景：
- 80kW 设计负荷下核验通过并出具回执，影音试音取得专用回路并开始；
- 设计负荷降为 70kW 后原核验额度失效，75kW 试音完成记录仍允许登记并要求复核；
- 失效额度不能办新试音，结清旧占用后才能从新单为同一回路办理新额度；
- 审核员可按原编号查出当时负荷明细；占用核对给出释放时间与复核责任人。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import audio_visual, power_receipt as pr
from app.services import service_for
from app.store import store


class PowerReceiptScenarioTest(unittest.TestCase):
    """独立展位 BOOT-T01，测试结束后清理，避免污染种子数据。"""

    BOOTH = "BOOT-T01"
    CIRCUIT_NO = "ELEC-T01-1"

    def setUp(self) -> None:
        # 展位 + 设计方案（80kW）+ 专用回路（75kW，已核验）+ 影音设备
        booth_rows = store.rows("booth")
        self._booth_id = store.next_id("booth")
        booth_rows.append({
            "id": self._booth_id, "status": "已确认", "pending": False, "abnormal": False,
            "展位编号": self.BOOTH, "面积尺寸": "100", "开口方向": "北", "所属区域": "A馆主展厅",
            "登记编号": "BOOT-T001", "负责人": "测试", "生效版本": "v1.0", "备注说明": "回执测试展位",
        })
        design_rows = store.rows("design")
        self._design_id = store.next_id("design")
        design_rows.append({
            "id": self._design_id, "status": "已确认", "pending": False, "abnormal": False,
            "设计风格": "测试风", "结构材料": "型材", "搭建高度": "4", "用电负荷": "80",
            "登记编号": "DESI-T01", "负责人": "陈设计", "生效版本": "v1.0", "备注说明": self.BOOTH,
        })
        elec_rows = store.rows("electrical")
        self._circuit_id = store.next_id("electrical")
        elec_rows.append({
            "id": self._circuit_id, "status": "已确认", "pending": False, "abnormal": False,
            "回路编号": self.CIRCUIT_NO, "额定功率": "75", "所属展位": self.BOOTH,
            "断路器型号": "C63/3P", "登记编号": "ELEC-T01", "负责人": "周电工",
            "生效版本": "v1.0", "备注说明": "试音专用回路",
        })
        av_rows = store.rows("audio_visual")
        self._av_id = store.next_id("audio_visual")
        av_rows.append({
            "id": self._av_id, "status": "待确认", "pending": True, "abnormal": False,
            "设备型号": "Test-LineArray", "安装位置": "展位两侧", "信号线路": "XLR",
            "调试试音": "未开始", "登记编号": "AUDI-T01", "负责人": "吴影音",
            "生效版本": "v1.0", "备注说明": f"{self.BOOTH} 试音",
        })
        store.rebuild_indices()

    def tearDown(self) -> None:
        for table, fixture_id in (
            ("booth", self._booth_id),
            ("design", self._design_id),
            ("electrical", self._circuit_id),
            ("audio_visual", self._av_id),
        ):
            store.rows(table)[:] = [r for r in store.rows(table) if r.get("id") != fixture_id]
        store.rows(pr.POWER_RECEIPT_TABLE)[:] = [
            r for r in store.rows(pr.POWER_RECEIPT_TABLE) if r.get("booth_no") != self.BOOTH
        ]
        store.rows(pr.RELEASE_TABLE)[:] = [
            r for r in store.rows(pr.RELEASE_TABLE) if r.get("booth_no") != self.BOOTH
        ]
        store.rebuild_indices()

    # ---- 1. 即时核对通过 → 出具核验回执，快照固化负荷明细 ----

    def test_01_issue_receipt_snapshots_load_detail(self):
        quota = self._quota()
        self.assertTrue(quota["ok"], "80kW 设计负荷下 75kW 回路应通过即时核对")

        result = pr.issue_power_receipt(self._circuit_id)
        self.assertTrue(result["ok"], result.get("reason"))
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], pr.RECEIPT_VALID)
        self.assertEqual(receipt["verification"], pr.VERIFY_PASS)
        self.assertEqual(receipt["design_load_kw"], 80.0)
        self.assertEqual(receipt["rated_power_kw"], 75.0)
        self.assertEqual(receipt["total_circuit_power_kw"], 75.0)
        # 审核员按原编号可反查当时负荷明细
        looked = pr.find_power_receipt_by_no(receipt["receipt_no"])
        self.assertIsNotNone(looked)
        self.assertTrue(any(d["circuit_id"] == self.CIRCUIT_NO for d in looked["load_detail"]))

    # ---- 2. 试音取得专用回路并开始（一回路一时段一额度）----

    def test_02_grant_release_occupies_circuit(self):
        receipt = pr.issue_power_receipt(self._circuit_id)["receipt"]
        grant = pr.grant_release(int(receipt["id"]), av_id=self._av_id)
        self.assertTrue(grant["ok"], grant.get("reason"))
        release = grant["release"]
        self.assertEqual(release["status"], pr.RELEASE_OCCUPYING)
        self.assertEqual(release["circuit_no"], self.CIRCUIT_NO)
        self.assertEqual(release["power_receipt_no"], receipt["receipt_no"])
        self.assertEqual(release["reviewer"], "吴影音")

        # 同一回路同一时段不能再开第二个有效放行额度
        second = pr.grant_release(int(receipt["id"]))
        self.assertFalse(second["ok"])
        self.assertIn("一个回路同一时段只能有一个有效放行额度", second["reason"])

        # 占用未结清时也不能重新出具核验回执
        re_verify = pr.issue_power_receipt(self._circuit_id)
        self.assertFalse(re_verify["ok"])
        self.assertIn("占用中的放行额度", re_verify["reason"])

    # ---- 3. 设计降为 70kW：原回执失效，已开始试音允许收尾 ----

    def test_03_design_downgrade_invalidates_receipt_but_allows_finishing(self):
        receipt = pr.issue_power_receipt(self._circuit_id)["receipt"]
        release = pr.grant_release(int(receipt["id"]), av_id=self._av_id)["release"]

        change = pr.apply_design_load_change(self._design_id, 70)
        self.assertTrue(change["ok"])
        self.assertFalse(change["quota_ok"], "75kW 回路对 70kW 设计负荷应超限")
        self.assertEqual(len(change["invalidated_receipts"]), 1)
        self.assertEqual(pr.find_power_receipt(int(receipt["id"]))["status"], pr.RECEIPT_INVALID)
        # 原编号与负荷明细仍可查，且快照保持 80kW 当时值
        archived = pr.find_power_receipt_by_no(receipt["receipt_no"])
        self.assertEqual(archived["design_load_kw"], 80.0)
        self.assertTrue(archived["load_detail"])

        # 失效额度不能再办新的试音
        blocked = pr.grant_release(int(receipt["id"]))
        self.assertFalse(blocked["ok"])
        self.assertIn("已失效", blocked["reason"])

        # 已开始的试音允许登记完成记录，并挂复核要求
        completion = pr.submit_completion(int(release["id"]), "现场提交 75kW 试音完成记录")
        self.assertTrue(completion["ok"], completion.get("reason"))
        updated = pr.find_release(int(release["id"]))
        self.assertEqual(updated["completion"], "现场提交 75kW 试音完成记录")
        self.assertTrue(updated["review_required"])
        self.assertIn("吴影音", updated["reviewer"])

    # ---- 4. 结清旧占用 → 释放回路；新单可再办同一回路 ----

    def test_04_settle_then_reissue_and_grant_again(self):
        receipt = pr.issue_power_receipt(self._circuit_id)["receipt"]
        release = pr.grant_release(int(receipt["id"]), av_id=self._av_id)["release"]
        pr.apply_design_load_change(self._design_id, 70)
        pr.submit_completion(int(release["id"]), "试音完成")

        # 占用未结清前新工作不允许
        occupancy_before = pr.circuit_occupancy(self.CIRCUIT_NO)
        self.assertFalse(occupancy_before["new_work_allowed"])
        self.assertFalse(occupancy_before["consistent"], "占用在、回执失效应判为不一致")

        settle = pr.settle_release(int(release["id"]))
        self.assertTrue(settle["ok"])
        self.assertEqual(settle["release"]["status"], pr.RELEASE_SETTLED)
        # 结清后复核标记保留，供审核员追查旧记录
        self.assertTrue(settle["release"]["review_required"])

        occupancy_free = pr.circuit_occupancy(self.CIRCUIT_NO)
        self.assertEqual(occupancy_free["release_state"], "已释放")
        self.assertIsNotNone(occupancy_free["released_at"])
        self.assertEqual(occupancy_free["reviewer"], "吴影音")
        self.assertTrue(occupancy_free["review_required"])

        # 旧单已失效，重新核验会被即时核对拦截（75 > 70）
        blocked = pr.reissue_power_receipt(int(receipt["id"]))
        self.assertFalse(blocked["ok"])
        self.assertIn("超过", blocked["reason"])

        # 把回路功率降到 65kW（新单数据），即时核对通过后出新回执
        circuit = store.find("electrical", self._circuit_id)
        circuit["额定功率"] = "65"
        new_receipt = pr.reissue_power_receipt(int(receipt["id"]))
        self.assertTrue(new_receipt["ok"], new_receipt.get("reason"))
        fresh = new_receipt["receipt"]
        self.assertEqual(fresh["status"], pr.RECEIPT_VALID)
        self.assertEqual(fresh["design_load_kw"], 70.0)
        self.assertEqual(fresh["rated_power_kw"], 65.0)

        # 从新单为同一回路办理新放行，占用状态恢复一致
        grant = pr.grant_release(int(fresh["id"]), av_id=self._av_id)
        self.assertTrue(grant["ok"], grant.get("reason"))
        occupancy_new = pr.circuit_occupancy(self.CIRCUIT_NO)
        self.assertTrue(occupancy_new["consistent"])
        self.assertEqual(occupancy_new["occupying_release"]["power_receipt_no"], fresh["receipt_no"])
        self.assertFalse(occupancy_new["new_work_allowed"], "新占用生效后不能再叠加额度")

    # ---- 5. 影音服务动作与资源路由语义一致 ----

    def test_05_audio_visual_actions_enforce_receipt_rules(self):
        av_service = service_for("audio_visual")

        # 没有有效核验回执时调试设备被拒
        allowed, reason = av_service.validate_action(self._av_id, "调试设备")
        self.assertFalse(allowed)
        self.assertIn("用电核验回执", reason)

        receipt = pr.issue_power_receipt(self._circuit_id)["receipt"]
        entry, message = av_service.run_action(self._av_id, "调试设备")
        self.assertIsNotNone(entry, message)
        self.assertIn("调试放行回执", message)
        self.assertEqual(entry["调试试音"], "试音中")

        # 调试占用期间再次调试被拒（一回路一时段一额度）
        allowed, reason = av_service.validate_action(self._av_id, "调试设备")
        self.assertFalse(allowed)

        # 设计降负荷后通过动作登记完成：收尾允许，状态标注待复核
        pr.apply_design_load_change(self._design_id, 70)
        entry, message = av_service.run_action(self._av_id, "登记试音完成")
        self.assertIsNotNone(entry, message)
        self.assertEqual(entry["调试试音"], "试音完成-待复核")
        self.assertIn("复核", message)

    # ---- 6. 用电配置「出具核验回执」动作 ----

    def test_06_electrical_action_issues_receipt(self):
        elec_service = service_for("electrical")
        entry, message = elec_service.run_action(self._circuit_id, "出具核验回执")
        self.assertIsNotNone(entry, message)
        self.assertIn("用电核验回执", message)
        receipts = pr.power_receipts(circuit_no=self.CIRCUIT_NO)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["status"], pr.RECEIPT_VALID)

    def test_07_release_rejects_av_from_other_booth(self):
        """放行额度只能挂接同展位的影音设备，跨展位挂接必须拒绝。"""
        other_booth = "BOOT-T02"
        booth_rows = store.rows("booth")
        other_booth_id = store.next_id("booth")
        booth_rows.append({
            "id": other_booth_id, "status": "已确认", "pending": False, "abnormal": False,
            "展位编号": other_booth, "面积尺寸": "80", "开口方向": "南", "所属区域": "A馆主展厅",
            "登记编号": "BOOT-T002", "负责人": "测试", "生效版本": "v1.0", "备注说明": "跨展位校验",
        })
        other_av_id = store.next_id("audio_visual")
        store.rows("audio_visual").append({
            "id": other_av_id, "status": "待确认", "pending": True, "abnormal": False,
            "设备型号": "Other-Speaker", "安装位置": "他展位", "信号线路": "XLR",
            "调试试音": "未开始", "登记编号": "AUDI-T02", "负责人": "吴影音",
            "生效版本": "v1.0", "备注说明": f"{other_booth} 试音",
        })
        store.rebuild_indices()
        try:
            receipt = pr.issue_power_receipt(self._circuit_id)["receipt"]
            result = pr.grant_release(int(receipt["id"]), av_id=other_av_id)
            self.assertFalse(result["ok"])
            self.assertIn("不一致", result["reason"])
        finally:
            store.rows("booth")[:] = [r for r in store.rows("booth") if r.get("id") != other_booth_id]
            store.rows("audio_visual")[:] = [
                r for r in store.rows("audio_visual") if r.get("id") != other_av_id
            ]
            store.rebuild_indices()

    def _quota(self):
        from app.services import exhibition
        return exhibition.check_electrical_quota(self.BOOTH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
