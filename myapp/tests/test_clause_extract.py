"""
条款定位逻辑单元测试（不调用 LLM 摘录回退；需设置 CHECK_CLAUSE_LOCATE_LLM=0）。
运行：python manage.py test myapp.tests.test_clause_extract
"""
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from myapp.views.check.checkservice.service import RentalContractChecker

os.environ.setdefault("CHECK_CLAUSE_LOCATE_LLM", "0")


class ClauseExtractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from myapp.views.check.checkservice.service import RentalContractChecker

        cls.checker = RentalContractChecker()

    def test_split_article_blocks(self):
        c = self.checker
        text = "前言说明\n第一条 租金每月3000元。\n第二条 押金5000元。\n第七条 租赁双方的变更 甲方可转让。"
        blocks = c._split_into_article_blocks(text)
        self.assertGreaterEqual(len(blocks), 3)
        self.assertTrue(any("第七条" in b for b in blocks))

    def test_phone_prefers_contact_line_not_phone_fee(self):
        c = self.checker
        text = (
            "第六条、乙方租房期间水、电、燃气、电话费、宽带费由乙方承担。\n"
            "出租方：王某  承租方：李某\n"
            "电话：13812345678  电话：13987654321"
        )
        r1 = c._extract_phone_clause(text, "R031")
        r2 = c._extract_phone_clause(text, "R032")
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertNotIn("电话费", r1)
        self.assertNotIn("电话费", r2)
        self.assertIn("13812345678", r1.replace(" ", ""))
        self.assertIn("13987654321", r2.replace(" ", ""))

    def test_phone_r031_not_entire_contract_when_two_on_long_line(self):
        """同一行先长篇正文再写两个「电话：」时，R031 只截取甲方号码段，不附带行首全文。"""
        c = self.checker
        noise = "出租方（以下简称甲方）：王建国 承租方（以下简称乙方）：李丽 第一条 租金2800元。" * 20
        text = noise + " 电话：13811110000  电话：13922220000"
        r1 = c._extract_phone_clause(text, "R031")
        self.assertNotIn("第一条", r1)
        self.assertIn("13811110000", r1.replace(" ", ""))
        self.assertNotIn("13922220000", r1.replace(" ", ""))

    def test_phone_single_on_very_long_line_returns_only_fragment(self):
        c = self.checker
        text = ("合同正文" * 300) + "电话：138****1234"
        r = c._extract_phone_clause(text, "R031")
        self.assertLess(len(r), 120)
        self.assertIn("138****1234", r.replace(" ", ""))

    def test_r010_delivery_time_derived_from_lease_term(self):
        """当 delivery_time 缺失但 lease_term 有起始日期时，不应再触发 R010。"""
        c = self.checker
        structured = {
            "lease_term": "租赁期限共12个月，从2025年3月1日至2026年2月28日。",
        }
        contract = "测试合同正文（无需包含交付时间关键词）。"
        os.environ["CHECK_RULE_CLAUSE_EXTRACT_MAX_WORKERS"] = "1"
        issues = c.apply_rule_engine(structured, contract)
        self.assertFalse(any(x.get("rule_id") == "R010" for x in issues))

    def test_article_block_scores_rent_keyword(self):
        c = self.checker
        contract = (
            "第一条 双方信息\n"
            "第二条 租金每月2800元，押一付三。\n"
            "第三条 乙方不得从事违法活动。"
        )
        block = c._pick_best_article_block(contract, ["租金", "月租金"])
        self.assertIsNotNone(block)
        self.assertIn("租金", block)

    def test_extract_relevant_clause_format_rule_uses_block_or_sentence(self):
        c = self.checker
        contract = (
            "第二条、租金和支付\n月租金人民币2800元。\n"
            "第六条、费用\n电话费由乙方承担。\n"
            "电话：13800001111"
        )
        clause = c.extract_relevant_clause(
            contract,
            "出租方电话号码格式必须正确",
            "R031",
            "出租方电话格式不对",
        )
        self.assertNotIn("电话费", clause)
        self.assertIn("13800001111", clause.replace(" ", ""))

    @patch.object(RentalContractChecker, "extract_relevant_clause", return_value="摘录占位")
    def test_apply_rule_engine_parallel_matches_serial_rule_order(self, _mock_extract):
        """并行与单线程 worker 的规则顺序一致；mock 摘录避免全量规则跑慢。"""
        c = self.checker
        data: dict = {}
        contract = "测试合同正文。未经允许转租。"
        os.environ["CHECK_RULE_CLAUSE_EXTRACT_MAX_WORKERS"] = "1"
        serial = c.apply_rule_engine(data, contract)
        os.environ["CHECK_RULE_CLAUSE_EXTRACT_MAX_WORKERS"] = "8"
        parallel = c.apply_rule_engine(data, contract)
        self.assertEqual(
            [x["rule_id"] for x in serial],
            [x["rule_id"] for x in parallel],
        )
        self.assertEqual(len(serial), len(parallel))
