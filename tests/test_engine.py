# -*- coding: utf-8 -*-
"""引擎单元测试 —— 用标准库 unittest，零依赖。

重点锁定的行为：
  1. 积分奖模型比值与汇率无关；券确定性下界为零
  2. 情景净期望与真实回本概率分离
  3. 估值模型的诱导消费扣减（高频无扣减，低频有扣减）
  4. 奖品名解析（真实奖池里的各种命名模式）
  5. 欧皇鉴定的诚实性（过期券价值归零）
"""

import os
import sys
import unittest
import contextlib
import io
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 导入测试模块时禁读 .env，不访问任何凭据或真实 MCP。
_exists = os.path.exists
with patch("os.path.exists", side_effect=lambda path: False if str(path).endswith(".env") else _exists(path)):
    from bureau.engine import lottery as lot
    from bureau.engine import value as val
    from bureau import normalize, mcp_client, render


def _prize(name, kind, net_value, points=None):
    return {"name": name, "kind": kind, "net_value": net_value, "points": points}


class TestFloorRecovery(unittest.TestCase):
    def test_real_activity_floor(self):
        """24 积分/抽，积分档模型回收率 125%，券确定性下界为零。"""
        prizes = [
            _prize("30积分", "points", 0.45, points=30),
            _prize("下单立减3元券", "cash_coupon", 2.76),
        ]
        result = lot.floor_recovery(prizes, 24, val.point_unit_value(3.2))
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["recovery"], 30 / 24)
        self.assertEqual(result["min_prize_name"], "30积分")
        self.assertEqual(result["lower_bound_recovery"], 0)
        self.assertFalse(result["guarantee_proven"])

    def test_recovery_is_rate_invariant(self):
        """保底回血率与积分汇率无关 —— 换任何汇率结果不变。"""
        prizes = [_prize("30积分", "points", 1.0, points=30)]
        r1 = lot.floor_recovery(prizes, 24, val.point_unit_value(1.0))
        r2 = lot.floor_recovery(prizes, 24, val.point_unit_value(9.9))
        self.assertAlmostEqual(r1["recovery"], r2["recovery"], places=6)

    def test_empty_prizes(self):
        self.assertFalse(lot.floor_recovery([], 24, 0.032)["ok"])


class TestScenarioAnalysis(unittest.TestCase):
    def test_guaranteed_win(self):
        """模型估值覆盖成本但无完整奖池证据，不能保证回本。"""
        prizes = [
            _prize("积分", "points", 2.0),
            _prize("券A", "cash_coupon", 3.0),
        ]
        r = lot.scenario_analysis(prizes, 100, 0.01)  # 成本 1 元
        self.assertEqual(r["verdict"], "likely_win")
        self.assertFalse(r["guarantee_proven"])

    def test_impossible(self):
        """最高模型估值低于成本，列表内情景净期望为负。"""
        prizes = [
            _prize("积分", "points", 0.2),
            _prize("券A", "cash_coupon", 0.5),
        ]
        r = lot.scenario_analysis(prizes, 100, 0.01)  # 成本 1 元
        self.assertEqual(r["verdict"], "impossible")

    def test_likely_win(self):
        """90% 最低估值档情景仍非负，不能推断真实回本概率。"""
        # 最低档 0.5（<成本1.0），其余 [5.0, 6.0]
        # 悲观 EV = 0.9*0.5 + 0.1*5.5 = 1.0 —— 恰好临界，调高其余档
        prizes = [
            _prize("积分", "points", 0.5),
            _prize("券A", "cash_coupon", 6.0),
            _prize("券B", "cash_coupon", 7.0),
        ]
        r = lot.scenario_analysis(prizes, 100, 0.01)  # 成本 1 元
        # 悲观 EV = 0.9*0.5 + 0.1*6.5 = 1.1 > 1.0
        self.assertEqual(r["verdict"], "likely_win")
        self.assertAlmostEqual(r["ev_pessimistic"], 1.1, places=4)

    def test_likely_lose(self):
        """均分情景净期望为负；不推断真实亏损概率。"""
        # 成本 1.0；最好档 1.5（>成本，排除 impossible）
        # 均分 EV = (0.1+0.5+0.6+1.5)/4 = 0.675 < 1.0 → likely_lose
        prizes = [
            _prize("积分", "points", 0.1),
            _prize("券A", "cash_coupon", 0.5),
            _prize("券B", "cash_coupon", 0.6),
            _prize("大奖", "cash_coupon", 1.5),
        ]
        r = lot.scenario_analysis(prizes, 100, 0.01)
        self.assertEqual(r["verdict"], "likely_lose")
        self.assertGreater(r["best_value"], r["cost"])
        self.assertLess(r["ev_uniform"], r["cost"])

    def test_real_activity_structure(self):
        """真实活动结构（10 档）：24分/抽、最低档1元券、汇率3.2。
        最差档 0.63 < 成本 0.768，但悲观 EV 应远高于成本 → likely_win。"""
        unit = val.point_unit_value(3.2)
        # 按真实奖池折算：1/2/3元券 + 六张折扣券 + 30积分
        prizes = [
            _prize("1元券", "cash_coupon", 0.63),
            _prize("2元券", "cash_coupon", 1.26),
            _prize("3元券", "cash_coupon", 1.90),
            _prize("麦辣三件套5折券", "discount_coupon", 10.75),
            _prize("板烧三件套5折券", "discount_coupon", 11.22),
            _prize("双层鳕鱼三件套6折券", "discount_coupon", 9.61),
            _prize("甜辣小食组合5折券", "discount_coupon", 7.59),
            _prize("小食四件套5.5折券", "discount_coupon", 7.96),
            _prize("麦旋风5折券", "discount_coupon", 4.27),
            _prize("30积分", "points", 0.96),
        ]
        r = lot.scenario_analysis(prizes, 24, unit)
        self.assertEqual(r["verdict"], "likely_win")
        self.assertAlmostEqual(r["cost"], 0.768, places=3)
        self.assertAlmostEqual(r["worst_value"], 0.63, places=2)
        # 悲观 EV = 0.9*0.63 + 0.1*avg(其余9档) 应 > 0.768
        self.assertGreater(r["ev_pessimistic"], r["cost"])


class TestValueModel(unittest.TestCase):
    def test_high_frequency_no_penalty(self):
        """高频用户（>=1次/周）无诱导消费扣减。"""
        profile = {"orders_per_week": 2.5, "avg_order_value": 36.0}
        r = val.value_prize(
            {"name": "立减3元券", "kind": "cash_coupon", "face_value": 3.0, "valid_days": 7},
            profile, 3.2)
        self.assertEqual(r["penalty"], 0.0)
        self.assertGreater(r["net_value"], 2.0)

    def test_low_frequency_penalty(self):
        """低频用户（0.5次/周）有诱导消费扣减，价值被压低但不为负。"""
        profile = {"orders_per_week": 0.5, "avg_order_value": 36.0}
        r = val.value_prize(
            {"name": "立减3元券", "kind": "cash_coupon", "face_value": 3.0, "valid_days": 7},
            profile, 3.2)
        self.assertGreater(r["penalty"], 0.0)
        self.assertGreaterEqual(r["net_value"], 0.0)

    def test_never_negative(self):
        """极端情况（从不消费 + 大客单价）价值钳制在 0，不出现负数。"""
        profile = {"orders_per_week": 0.0, "avg_order_value": 200.0}
        r = val.value_prize(
            {"name": "立减1元券", "kind": "cash_coupon", "face_value": 1.0, "valid_days": 7},
            profile, 3.2)
        self.assertEqual(r["net_value"], 0.0)

    def test_points_value(self):
        """积分奖价值 = 积分数 × 单位汇率。"""
        profile = {"orders_per_week": 2.0, "avg_order_value": 30.0}
        r = val.value_prize({"name": "30积分", "kind": "points", "points": 30},
                            profile, 3.2)
        self.assertAlmostEqual(r["net_value"], 30 * 0.032, places=4)

    def test_discount_coupon(self):
        """5折券价值 = 原价 × 50% × 使用概率。"""
        profile = {"orders_per_week": 10.0, "avg_order_value": 30.0}  # 概率≈1
        r = val.value_prize(
            {"name": "麦辣三件套5折", "kind": "discount_coupon",
             "reference_price": 34.0, "discount": 0.5, "valid_days": 30},
            profile, 3.2)
        self.assertAlmostEqual(r["net_value"], 17.0, places=1)


class TestParsePrizeName(unittest.TestCase):
    def test_cash_coupon(self):
        p = normalize.parse_prize_name("下单立减3元券")
        self.assertEqual(p["kind"], "cash_coupon")
        self.assertEqual(p["face_value"], 3.0)

    def test_yuan_coupon(self):
        p = normalize.parse_prize_name("5元无门槛券")
        self.assertEqual(p["kind"], "cash_coupon")
        self.assertEqual(p["face_value"], 5.0)

    def test_discount_coupon(self):
        p = normalize.parse_prize_name("麦辣三件套5折")
        self.assertEqual(p["kind"], "discount_coupon")
        self.assertEqual(p["discount"], 0.5)
        self.assertEqual(p["reference_price"], 34.0)

    def test_discount_decimal(self):
        p = normalize.parse_prize_name("小食四件套5.5折")
        self.assertEqual(p["kind"], "discount_coupon")
        self.assertAlmostEqual(p["discount"], 0.55)

    def test_points(self):
        p = normalize.parse_prize_name("30积分")
        self.assertEqual(p["kind"], "points")
        self.assertEqual(p["points"], 30.0)

    def test_unknown(self):
        p = normalize.parse_prize_name("神秘大奖")
        self.assertEqual(p["kind"], "other")


class TestLuckAudit(unittest.TestCase):
    def test_expired_coupon_zeroed(self):
        """过期券价值归零，且不计入有效券命中。"""
        history = [
            {"name": "30积分", "kind": "points", "net_value": 0.96},
            {"name": "立减2元券", "kind": "cash_coupon", "net_value": 0.0, "_expired": True},
            {"name": "30积分", "kind": "points", "net_value": 0.96},
            {"name": "30积分", "kind": "points", "net_value": 0.96},
            {"name": "30积分", "kind": "points", "net_value": 0.96},
        ]
        r = lot.luck_audit(history, 24, val.point_unit_value(3.2))
        self.assertTrue(r["ok"])
        self.assertEqual(r["coupon_hits"], 0)
        self.assertEqual(r["expired_coupons"], 1)

    def test_insufficient_sample(self):
        history = [{"name": "30积分", "kind": "points", "net_value": 0.96}]
        r = lot.luck_audit(history, 24, val.point_unit_value(3.2))
        self.assertEqual(r["verdict"], "insufficient")

    def test_empty(self):
        self.assertFalse(lot.luck_audit([], 24, 0.032)["ok"])


class TestDecide(unittest.TestCase):
    def test_ineligible_insufficient_points(self):
        """积分不足时：结论必须是"无法抽奖"，并指引去兑换临期积分。"""
        floor = {"ok": True, "recovery": 0.82, "min_prize_name": "1元券", "min_value": 0.63, "cost": 0.77}
        sc = {"ok": True, "verdict": "likely_win"}
        d = lot.decide(floor, sc, expiring_points=0, available_points=14,
                       draw_cost_points=24, eligible=False,
                       ineligible_reason="积分不足")
        self.assertEqual(d["stance"], "cannot_draw")
        self.assertIn("积分不足", d["label"])

    def test_ineligible_with_expiring(self):
        """积分不足但有临期积分：应指引兑换而非抽奖。"""
        floor = {"ok": True, "recovery": 0.82, "min_prize_name": "1元券", "min_value": 0.63, "cost": 0.77}
        sc = {"ok": True, "verdict": "likely_win"}
        d = lot.decide(floor, sc, expiring_points=50, available_points=14,
                       draw_cost_points=24, eligible=False)
        self.assertEqual(d["stance"], "cannot_draw")
        joined = " ".join(d["reasons"])
        self.assertIn("兑换", joined)

    def test_expiring_priority(self):
        """临期仅追加次数限制，不覆盖不利情景。"""
        floor = {"ok": True, "recovery": 0.3, "min_prize_name": "x", "min_value": 0.1, "cost": 0.3}
        sc = {"ok": True, "verdict": "likely_lose"}
        d = lot.decide(floor, sc, expiring_points=100, available_points=500,
                       draw_cost_points=24, eligible=True)
        self.assertEqual(d["stance"], "avoid")
        self.assertEqual(d["max_draws_for_expiring"], 4)

    def test_floor_wins(self):
        """未经完整奖池证明，即使模型估值回本也不能放心抽。"""
        floor = {"ok": True, "recovery": 1.25, "min_prize_name": "30积分", "min_value": 0.96, "cost": 0.77}
        sc = {"ok": True, "verdict": "guaranteed_win"}
        d = lot.decide(floor, sc, expiring_points=0, available_points=500,
                       draw_cost_points=24, eligible=True)
        self.assertEqual(d["stance"], "small")
        self.assertIn("不能保证回本", " ".join(d["reasons"]))

    def test_likely_win_small(self):
        """悲观情景非负 → 仅少量尝试，不保证回本。"""
        floor = {"ok": True, "recovery": 0.82, "min_prize_name": "1元券", "min_value": 0.63, "cost": 0.77}
        sc = {"ok": True, "verdict": "likely_win", "note": "x", "worst_prize": "1元券",
              "worst_value": 0.63, "ev_pessimistic": 0.9, "ev_uniform": 3.0, "cost": 0.77}
        d = lot.decide(floor, sc, expiring_points=0, available_points=500,
                       draw_cost_points=24, eligible=True)
        self.assertEqual(d["stance"], "small")

    def test_likely_lose_avoid(self):
        """均分情景负期望 → 优先兑换。"""
        floor = {"ok": True, "recovery": 0.5, "min_prize_name": "x", "min_value": 0.4, "cost": 0.77}
        sc = {"ok": True, "verdict": "likely_lose", "note": "x", "ev_pessimistic": 0.4,
              "ev_uniform": 0.5, "cost": 0.77}
        d = lot.decide(floor, sc, expiring_points=0, available_points=500,
                       draw_cost_points=24, eligible=True)
        self.assertEqual(d["stance"], "avoid")


class TestNormalizeAccount(unittest.TestCase):
    def test_mouth_spelling(self):
        """官方拼写坑：currentMouthExpirePoint（Mouth 不是 Month）。"""
        raw = {"data": {"availablePoint": "2741.9", "currentMouthExpirePoint": "129.8"}}
        r = normalize.normalize_account(raw)
        self.assertAlmostEqual(r["available"], 2741.9)
        self.assertAlmostEqual(r["expire_this_month"], 129.8)


class TestNormalizeOrders(unittest.TestCase):
    def test_order_profile(self):
        """订单列表 → 频率与客单价。"""
        raw = {"data": [{"hasNext": False, "lastId": 0, "list": [
            {"orderTime": "2026-09-18 12:00:00", "totalAmount": "42.0"},
            {"orderTime": "2026-09-25 12:00:00", "totalAmount": "28.0"},
            {"orderTime": "2026-10-02 12:00:00", "totalAmount": "30.0"},
            {"orderTime": "2026-10-09 12:00:00", "totalAmount": "40.0"},
        ]}]}
        r = normalize.normalize_orders(raw)
        self.assertEqual(r["n_orders"], 4)
        self.assertAlmostEqual(r["avg_order_value"], 35.0)
        # 21 天 4 单 → 4/(21/7) ≈ 1.33 次/周
        self.assertAlmostEqual(r["orders_per_week"], 4 / 3, places=2)


class TestNormalizeLottery(unittest.TestCase):
    def test_real_structure(self):
        """真实活动结构归一化。"""
        raw = {"data": {
            "activityName": "麦麦积分抽奖",
            "drawPoint": "24",
            "activityStatusText": "进行中",
            "drawDecision": {"resourceEligible": True, "reason": ""},
            "prizes": [
                {"name": "下单立减3元券"},
                {"name": "30积分"},
            ],
        }}
        r = normalize.normalize_lottery(raw)
        self.assertEqual(r["activity"]["draw_points"], 24.0)
        self.assertTrue(r["activity"]["eligible"])
        self.assertEqual(len(r["prizes"]), 2)
        self.assertFalse(r["_meta"]["probability_disclosed"])


class TestReviewRegressions(unittest.TestCase):
    def test_coupon_probability_not_guarantee(self):
        prize = val.value_prize({"name": "3元券", "kind": "cash_coupon", "face_value": 3},
                                {"orders_per_week": 10, "avg_order_value": 35}, 3.2)
        self.assertGreater(prize["net_value"], 0.768)
        floor = lot.floor_recovery([prize], 24, 0.032, pool_complete=True)
        self.assertEqual(floor["lower_bound_recovery"], 0)
        self.assertFalse(floor["guarantee_proven"])
        scenario = lot.scenario_analysis([prize], 24, 0.032, pool_complete=True)
        self.assertNotEqual(scenario["verdict"], "guaranteed_win")
        self.assertIn("不代表真实回本概率", scenario["note"])

    def test_points_choose_worst_in_points_units(self):
        prizes = [_prize("30积分", "points", 0.01, 30), _prize("20积分", "points", 99, 20)]
        for unit in (0, 0.01, 1):
            r = lot.floor_recovery(prizes, 24, unit)
            self.assertAlmostEqual(r["lower_bound_recovery"], 20 / 24)
            self.assertFalse(r["guarantee_proven"])
        certified = lot.scenario_analysis([_prize("30积分", "points", 99, 30)],
                                          24, 0.032, pool_complete=True)
        self.assertEqual(certified["verdict"], "guaranteed_win")
        self.assertAlmostEqual(certified["worst_value"], 0.96)
        missing = lot.floor_recovery([_prize("积分未知", "points", 99)], 24, 0.032)
        self.assertIsNone(missing["lower_bound_points"])
        self.assertFalse(missing["guarantee_proven"])

    def test_expiry_never_overrides_unknown_or_balance(self):
        d = lot.decide({"ok": False}, {"ok": False}, 100, 50, 24)
        self.assertEqual(d["stance"], "unknown")
        self.assertEqual(d["max_draws_for_expiring"], 2)
        partial = lot.decide({"ok": False}, {"ok": True, "verdict": "likely_win"}, 100, 50, 24)
        self.assertEqual(partial["stance"], "unknown")
        self.assertEqual(lot.decide({}, {}, 100, 10, 24)["stance"], "cannot_draw")
        unknown = val.value_prize({"name": "神秘奖", "kind": "other"}, {}, 3.2)
        self.assertFalse(lot.scenario_analysis([unknown], 24, 0.032)["ok"])

    def test_zero_values_and_threshold(self):
        profile = {"orders_per_week": 10, "avg_order_value": 35}
        coupon = {"kind": "cash_coupon", "face_value": 3, "valid_days": 0}
        self.assertEqual(val.value_prize(coupon, profile, 3.2)["use_prob"], 0)
        free = {"kind": "discount_coupon", "discount": 0, "reference_price": 30}
        self.assertGreater(val.value_prize(free, profile, 3.2)["net_value"], 29)
        for name in ("满100减10", "满100元立减10元券", "满额立减10元券"):
            parsed = normalize.parse_prize_name(name)
            self.assertEqual(val.value_prize(parsed, profile, 3.2)["net_value"], 0)
        parsed = normalize.parse_prize_name("满0减0")
        self.assertEqual(parsed["min_spend"], 0)
        self.assertEqual(parsed["face_value"], 0)
        self.assertEqual(val.value_prize(parsed, profile, 3.2)["net_value"], 0)
        self.assertEqual(normalize.parse_prize_name("满30.5减10")["min_spend"], 30.5)

    def test_audit_records_not_real_gain(self):
        history = [_prize("券", "cash_coupon", 2), _prize("未知", "other", 0)] * 3
        audit = lot.luck_audit(history, 24, 0.032)
        self.assertEqual(audit["n_records"], audit["n_draws"])
        self.assertEqual(audit["coupon_hits"], 3)
        self.assertNotIn("净赚", audit["comment"])
        self.assertIn("当前", audit["cost_note"])
        self.assertIn("单页", audit["sample_note"])
        self.assertFalse(lot.luck_audit(history, 0, 0.032)["ok"])
        self.assertFalse(lot.luck_audit(history, 24, 0)["ok"])
        unknown = {"kind": "other", "valuation_known": False, "net_value": 0}
        self.assertFalse(lot.luck_audit([unknown], 24, 0.032)["ok"])
        self.assertTrue(lot.luck_audit([{**unknown, "_expired": True}], 24, 0.032)["ok"])


class TestStrictNormalize(unittest.TestCase):
    def test_failed_business_and_invalid_data(self):
        functions = (normalize.normalize_lottery, normalize.normalize_account,
                     normalize.normalize_orders, normalize.normalize_prizes_history)
        for function in functions:
            for raw in ({"success": False, "data": {}}, {"success": "false", "data": {}},
                        {"code": 500, "data": {}}, {"data": None}, {"data": "wrong"}, []):
                with self.subTest(function=function.__name__, raw=raw):
                    with self.assertRaises(normalize.NormalizeError):
                        function(raw)

    def test_eligibility_strict_and_false_string(self):
        raw = {"data": {"drawPoint": "24", "drawDecision": {"resourceEligible": "false"},
                        "prizes": ["30积分"]}}
        self.assertFalse(normalize.normalize_lottery(raw)["activity"]["eligible"])
        raw["data"]["drawDecision"]["resourceEligible"] = "true"
        self.assertTrue(normalize.normalize_lottery(raw)["activity"]["eligible"])
        for value in (1, 0, None, "False", "yes"):
            raw["data"]["drawDecision"]["resourceEligible"] = value
            with self.assertRaises(normalize.NormalizeError):
                normalize.normalize_lottery(raw)
        raw["data"]["drawDecision"] = []
        with self.assertRaises(normalize.NormalizeError):
            normalize.normalize_lottery(raw)

    def test_bad_lists_and_numbers(self):
        for raw in ({"data": {"prizes": {}}}, {"data": {"prizes": [1]}}):
            with self.assertRaises(normalize.NormalizeError):
                normalize.normalize_prizes_history(raw)
        for value in ("NaN", "inf", -1, True, None):
            with self.assertRaises(normalize.NormalizeError):
                normalize.normalize_account({"data": {"availablePoint": value}})
        profile = normalize.build_profile({"orders_per_week": 0, "avg_order_value": 0})
        self.assertEqual(profile["orders_per_week"], 0)
        self.assertEqual(profile["avg_order_value"], 0)
        orders = normalize.normalize_orders({"data": {"list": [{"totalAmount": 0, "amount": 99}]}})
        self.assertEqual(orders["avg_order_value"], 0)


class TestMCPResponses(unittest.TestCase):
    def setUp(self):
        # 不运行客户端构造函数，不查询环境中的 Token。
        self.client = object.__new__(mcp_client.MCPClient)

    def test_structured_precedes_text(self):
        envelope = {"jsonrpc": "2.0", "id": 101, "result": {
            "content": [{"type": "text", "text": '{"data": "stale"}'}],
            "structuredContent": {"data": {"correct": True}}}}
        self.assertEqual(self.client._parse_response(json.dumps(envelope), 101),
                         {"data": {"correct": True}})
        envelope["result"]["isError"] = True
        with self.assertRaises(mcp_client.MCPError):
            self.client._parse_response(json.dumps(envelope), 101)

    def test_progress_sse_matches_request(self):
        sse = ': heartbeat\r\nevent: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\r\n\r\n'
        sse += 'data: {"jsonrpc":"2.0","id":999,"result":{"data":{"wrong":true}}}\n\n'
        sse += 'event: message\ndata: {"jsonrpc":"2.0","id":101,\ndata: "result":{"structuredContent":{"data":{"ok":true}}}}\n\n'
        self.assertEqual(self.client._parse_response(sse, 101), {"data": {"ok": True}})
        with self.assertRaises(mcp_client.MCPError):
            self.client._parse_response(sse, 102)

    def test_null_invalid_and_rpc_errors(self):
        for response in ('null', '[]', '{"jsonrpc":"2.0","id":101,"result":null}',
                         '{"jsonrpc":"2.0","id":101,"error":{"message":"error"}}',
                         '{"jsonrpc":"2.0","id":999,"result":{}}',
                         '{"result":{"structuredContent":null}}'):
            with self.subTest(response=response), self.assertRaises(mcp_client.MCPError):
                self.client._parse_response(response, 101)
        raw = self.client._parse_response('{"result":{"structuredContent":{"data":null}}}')
        with self.assertRaises(normalize.NormalizeError):
            normalize.normalize_account(raw)


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = runpy.run_path(str(ROOT / "bureau.py"), run_name="bureau_test")

    def demo(self):
        inputs = self.cli["load_demo_data"]()
        result = self.cli["analyze"](*inputs)
        self.cli["_mark_source"](result, True)
        return result

    def test_analyze_safe_decision_and_render(self):
        result = self.demo()
        self.assertNotEqual(result["scenario"]["verdict"], "guaranteed_win")
        self.assertNotIn(result["decision"]["stance"], ("draw", "must_draw"))
        self.assertEqual(result["floor"]["lower_bound_recovery"], 0)
        self.assertEqual(result["floor"]["min_prize_name"], result["scenario"]["worst_prize"])
        markdown = render.render_markdown(result)
        self.assertIn("Demo 示例数据（非真实账户）", markdown)
        self.assertIn("| 模型回本线 | 净收益为零 | 0.00 元 |", markdown)
        svg = render.render_luck_card(result["audit"])
        self.assertIn("Demo 示例数据", svg)
        self.assertIn("奖品记录", svg)
        self.assertIn(str(result["audit"]["n_records"]), svg)
        raw = {"data": {"drawPoint": 24, "drawDecision": {"resourceEligible": True},
                        "prizes": ["神秘奖"]}}
        unknown = self.cli["analyze"]({"available": 50, "expire_this_month": 100}, raw)
        self.assertEqual(unknown["decision"]["stance"], "unknown")
        self.assertEqual(unknown["decision"]["max_draws_for_expiring"], 2)

    def test_real_luck_loads_orders_without_network_or_files(self):
        args = SimpleNamespace(demo=False, out=None)
        globals_ = self.cli["cmd_luck"].__globals__
        data = ({"available": 100}, {"data": {}}, {"orders_per_week": 2}, [])
        fake = SimpleNamespace(available=lambda: True)
        with patch.object(mcp_client, "MCPClient", return_value=fake), \
                patch.dict(globals_, {"load_real_data": lambda client: data}), \
                patch.dict(globals_, {"analyze": unittest.mock.Mock(return_value={"audit": None})}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cli["cmd_luck"](args), 0)
            globals_["analyze"].assert_called_once_with(*data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
