import os
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

# -----------------------------
# Clause location helpers
# -----------------------------
_PHONE_CONTACT_RE = re.compile(r"电话[：:]\s*([1*●][0-9\*●]{4,})")
_PHONE_CONTACT_ANY_RE = re.compile(r"电话[：:]\s*[\d*●]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]")
_ARTICLE_SPLIT_RE = re.compile(r"(?=^第[一二三四五六七八九十\d]+\s*[条节])", flags=re.MULTILINE)
# 增强的条款分割正则
_ARTICLE_SPLIT_ENHANCED = re.compile(r"(?=^(?:第[一二三四五六七八九十\d]+\s*[条节]|\d+\.|[一二三四五六七八九十]+\.|[A-Za-z]+\.))", flags=re.MULTILINE)
# 增强的合同结构关键词
_CONTRACT_STRUCTURE_KEYWORDS = [
    "第一条", "第二条", "第三条", "第四条", "第五条",
    "第六条", "第七条", "第八条", "第九条", "第十条",
    "第十一条", "第十二条", "第十三条", "第十四条", "第十五条",
    "一、", "二、", "三、", "四、", "五、",
    "六、", "七、", "八、", "九、", "十、",
    "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.",
    "(一)", "(二)", "(三)", "(四)", "(五)", "(六)", "(七)", "(八)", "(九)", "(十)",
    "甲方", "乙方", "出租方", "承租方", "房屋", "租金", "押金", "违约金", "违约责任", "维修责任"
]

# extract_relevant_clause：规则名 -> 定位关键词（模块级常量，避免每次调用新建大 dict）
CLAUSE_LOCATE_KEYWORDS: Dict[str, List[str]] = {
    "必须存在出租人": ["出租方", "甲方", "出租人", "房主", "房东"],
    "必须存在承租人": ["承租方", "乙方", "承租人", "租客", "租户"],
    "出租人必须有处分权": ["转租", "处分权", "所有权", "产权"],
    "房屋用途必须合法": ["违法用途", "商业经营", "用途", "使用", "居住"],
    "禁止群租风险": ["多人合租", "群租", "合租", "人数"],
    "必须约定租金": ["租金", "月租金", "租金标准", "租金金额"],
    "必须约定租期": ["租赁期限", "租期", "租赁期", "起止日期"],
    "必须约定支付周期": ["支付周期", "交纳期限", "支付方式", "付款方式"],
    "必须约定押金": ["押金", "乙方向甲方交纳押金", "保证金", "押金金额"],
    "必须约定交付时间": ["交付时间", "交房时间", "交付日期"],
    "押金不得超过两个月租金": ["乙方向甲方交纳押金", "押金", "月租金", "保证金"],
    "押金必须可退还": ["押金不退", "不予退还", "押金退还", "退还押金"],
    "押金扣除必须明确": ["押金视情况扣除", "押金扣除", "扣除押金"],
    "必须约定押金退还时间": ["押金退还时间", "合同到期后", "退还时间", "押金返还"],
    "禁止单方随意涨租": ["随意调整租金", "涨租", "租金调整", "调整租金"],
    "必须明确费用承担": ["费用", "水电", "物业费", "水电费", "宽带费", "电话费"],
    "禁止模糊费用条款": ["费用按实际情况", "费用另行协商", "费用待定"],
    "禁止商用水电未说明": ["商业用电", "商用水电", "商业用水"],
    "违约金不得过高": ["违约金", "违约方赔偿", "赔偿对方", "违约责任", "第八条", "违约赔偿"],
    "违约责任必须对等": ["违约责任", "违约方赔偿", "赔偿对方", "违约责任对等"],
    "禁止房东免责": ["房东不承担任何责任", "免责条款", "甲方不承担责任"],
    "必须约定违约情形": ["违约条件", "违约情形", "违约行为", "违约事由"],
    "禁止模糊违约责任": ["违约责任由租客承担", "违约责任由乙方承担", "模糊责任"],
    "禁止单方随意解约": ["房东可随时解除合同", "单方解除", "随意解除"],
    "解除条件必须明确": ["解除条件", "解约条件", "终止条件"],
    "解约责任必须对等": [
        "第七条",
        "租赁双方的变更",
        "解除",
        "转租",
        "优先购买",
        "终止",
        "解约",
        "变更",
        "转让"
    ],
    "必须约定提前通知时间": ["提前通知时间", "通知期限", "提前告知"],
    "必须约定维修责任": ["维修责任", "维修", "修缮", "维护", "修理", "装修", "改善", "增设", "房屋状况"],
    "维修责任必须区分": ["所有维修由租客承担", "维修责任", "维修义务", "甲方维修", "乙方维修"],
    "必须约定使用限制": ["使用限制", "使用规定", "使用要求", "使用范围"],
    "出租方电话号码格式必须正确": ["电话：", "甲方", "出租方", "联系方式", "联系电话"],
    "承租方电话号码格式必须正确": ["电话：", "乙方", "承租方", "联系方式", "联系电话"],
    "地址信息必须完整": ["坐落在", "地址", "坐落", "房屋地址", "位置"],
    "租金金额必须为正数": ["租金", "月租金", "租金金额"],
    "押金金额必须为正数": ["押金", "保证金", "押金金额"],
}


class RentalContractChecker:
    def __init__(self):
        # 初始化AI模型（审查是主要耗时点，可用更快模型）
        review_model = os.getenv("CHECK_REVIEW_MODEL", "qwen3.5-plus").strip() or "qwen3.5-plus"
        self.llm = ChatOpenAI(
            model=review_model,
            temperature=0.0,
            api_key=os.getenv("LLM_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.output_parser = StrOutputParser()
        
        # 规则库
        #region
        self.rules = [
            # 一、主体与合法性规则（R001 - R005）
            {
                "rule_id": "R001",
                "name": "必须存在出租人",
                "type": "required",
                "field": "parties.landlord",
                "severity": "high",
                "message": "缺少出租人信息"
            },
            {
                "rule_id": "R002",
                "name": "必须存在承租人",
                "type": "required",
                "field": "parties.tenant",
                "severity": "high",
                "message": "缺少承租人信息"
            },
            {
                "rule_id": "R003",
                "name": "出租人必须有处分权",
                "type": "forbidden",
                "pattern": "未经允许转租",
                "severity": "high",
                "message": "存在未经授权转租风险"
            },
            {
                "rule_id": "R004",
                "name": "房屋用途必须合法",
                "type": "forbidden",
                "pattern": "违法用途|商业经营（未约定）",
                "severity": "high",
                "message": "房屋用途可能违法"
            },
            {
                "rule_id": "R005",
                "name": "禁止群租风险",
                "type": "forbidden",
                "pattern": "多人合租未说明",
                "severity": "medium",
                "message": "可能存在群租风险"
            },
            # 二、核心条款完整性（R006 - R010）
            {
                "rule_id": "R006",
                "name": "必须约定租金",
                "type": "required",
                "field": "rent.amount",
                "severity": "high",
                "message": "缺少租金条款"
            },
            {
                "rule_id": "R007",
                "name": "必须约定租期",
                "type": "required",
                "field": "lease_term",
                "severity": "high",
                "message": "缺少租期条款"
            },
            {
                "rule_id": "R008",
                "name": "必须约定支付周期",
                "type": "required",
                "field": "rent.payment_cycle",
                "severity": "medium",
                "message": "缺少租金支付方式"
            },
            {
                "rule_id": "R009",
                "name": "必须约定押金",
                "type": "required",
                "field": "deposit.amount",
                "severity": "medium",
                "message": "未明确押金条款"
            },
            {
                "rule_id": "R010",
                "name": "必须约定交付时间",
                "type": "required",
                "field": "delivery_time",
                "severity": "medium",
                "message": "缺少房屋交付时间"
            },
            # 三、押金规则（R011 - R014）
            {
                "rule_id": "R011",
                "name": "押金不得超过两个月租金",
                "type": "numeric",
                "condition": {
                    "field": "deposit.amount",
                    "operator": "<=",
                    "value": "2 * rent.amount"
                },
                "severity": "high",
                "message": "押金超过合理范围"
            },
            {
                "rule_id": "R012",
                "name": "押金必须可退还",
                "type": "forbidden",
                "pattern": "押金不退|不予退还",
                "severity": "high",
                "message": "押金条款不公平"
            },
            {
                "rule_id": "R013",
                "name": "押金扣除必须明确",
                "type": "forbidden",
                "pattern": "押金视情况扣除",
                "severity": "medium",
                "message": "押金扣除规则不明确"
            },
            {
                "rule_id": "R014",
                "name": "必须约定押金退还时间",
                "type": "required",
                "field": "deposit.return_time",
                "severity": "medium",
                "message": "未明确押金退还时间"
            },
            # 四、租金与费用规则（R015 - R018）
            {
                "rule_id": "R015",
                "name": "禁止单方随意涨租",
                "type": "forbidden",
                "pattern": "房东可随时调整租金",
                "severity": "high",
                "message": "租金调整条款不公平"
            },
            {
                "rule_id": "R016",
                "name": "必须明确费用承担",
                "type": "required",
                "field": "fees",
                "severity": "medium",
                "message": "未明确水电物业费用"
            },
            {
                "rule_id": "R017",
                "name": "禁止模糊费用条款",
                "type": "forbidden",
                "pattern": "费用按实际情况",
                "severity": "medium",
                "message": "费用条款不明确"
            },
            {
                "rule_id": "R018",
                "name": "禁止商用水电未说明",
                "type": "forbidden",
                "pattern": "商业用电",
                "severity": "medium",
                "message": "可能存在高额费用风险"
            },
            # 五、违约责任规则（R019 - R023）
            {
                "rule_id": "R019",
                "name": "违约金不得过高",
                "type": "numeric",
                "condition": {
                    "field": "penalty.amount",
                    "operator": "<=",
                    "value": "2 * rent.amount"
                },
                "severity": "high",
                "message": "违约金过高"
            },
            {
                "rule_id": "R020",
                "name": "违约责任必须对等",
                "type": "logic",
                "condition": "only_tenant_has_penalty",
                "severity": "high",
                "message": "违约责任不对等"
            },
            {
                "rule_id": "R021",
                "name": "禁止房东免责",
                "type": "forbidden",
                "pattern": "房东不承担任何责任",
                "severity": "high",
                "message": "免责条款不合法"
            },
            {
                "rule_id": "R022",
                "name": "必须约定违约情形",
                "type": "required",
                "field": "penalty.conditions",
                "severity": "medium",
                "message": "未明确违约条件"
            },
            {
                "rule_id": "R023",
                "name": "禁止模糊违约责任",
                "type": "forbidden",
                "pattern": "违约责任由租客承担",
                "severity": "medium",
                "message": "违约责任不明确"
            },
            # 六、合同解除规则（R024 - R027）
            {
                "rule_id": "R024",
                "name": "禁止单方随意解约",
                "type": "forbidden",
                "pattern": "房东可随时解除合同",
                "severity": "high",
                "message": "单方解约条款不公平"
            },
            {
                "rule_id": "R025",
                "name": "解除条件必须明确",
                "type": "required",
                "field": "termination.conditions",
                "severity": "medium",
                "message": "未明确解约条件"
            },
            {
                "rule_id": "R026",
                "name": "解约责任必须对等",
                "type": "logic",
                "condition": "termination_not_equal",
                "severity": "high",
                "message": "解约权利不对等"
            },
            {
                "rule_id": "R027",
                "name": "必须约定提前通知时间",
                "type": "required",
                "field": "termination.notice_period",
                "severity": "medium",
                "message": "未明确解约通知时间"
            },
            # 七、维修与使用规则（R028 - R030）
            {
                "rule_id": "R028",
                "name": "必须约定维修责任",
                "type": "required",
                "field": "maintenance",
                "severity": "medium",
                "message": "未明确维修责任"
            },
            {
                "rule_id": "R029",
                "name": "维修责任必须区分",
                "type": "forbidden",
                "pattern": "所有维修由租客承担",
                "severity": "high",
                "message": "维修责任不公平"
            },
            {
                "rule_id": "R030",
                "name": "必须约定使用限制",
                "type": "required",
                "field": "usage",
                "severity": "low",
                "message": "未明确房屋使用规则"
            },
            # 八、信息格式验证规则（R031 - R035）
            {
                "rule_id": "R031",
                "name": "出租方电话号码格式必须正确",
                "type": "format",
                "field": "parties.landlord",
                "pattern": r"1[3-9]\d{9}",
                "severity": "medium",
                "message": "出租方电话号码格式不正确"
            },
            {
                "rule_id": "R032",
                "name": "承租方电话号码格式必须正确",
                "type": "format",
                "field": "parties.tenant",
                "pattern": r"1[3-9]\d{9}",
                "severity": "medium",
                "message": "承租方电话号码格式不正确"
            },
            {
                "rule_id": "R033",
                "name": "地址信息必须完整",
                "type": "format",
                "field": "property",
                "pattern": r"^(?!.*XX).*市.*区.*路.*号",
                "severity": "medium",
                "message": "房屋地址信息不完整或包含占位符"
            },
            {
                "rule_id": "R034",
                "name": "租金金额必须为正数",
                "type": "format",
                "field": "rent.amount",
                "pattern": r"^\d+(\.\d{1,2})?$",
                "severity": "high",
                "message": "租金金额格式不正确"
            },
            {
                "rule_id": "R035",
                "name": "押金金额必须为正数",
                "type": "format",
                "field": "deposit.amount",
                "pattern": r"^\d+(\.\d{1,2})?$",
                "severity": "high",
                "message": "押金金额格式不正确"
            }
        ]
        #endregion
        # 合同内容提取提示模板（更新为匹配规则字段）
        #region
        self.extraction_prompt = ChatPromptTemplate.from_template("""
        请从以下租房合同中提取关键信息，按照JSON格式输出。确保字段名称与以下结构匹配：
        
        {{
            "parties": {{
                "landlord": "出租方信息（姓名、身份证等）",
                "tenant": "承租方信息（姓名、身份证等）"
            }},
            "property": "房屋信息（地址、面积、户型等）",
            "lease_term": "租赁期限（起止日期）",
            "rent": {{
                "amount": "租金金额（数字）",
                "payment_cycle": "支付周期（如月付）"
            }},
            "deposit": {{
                "amount": "押金金额（数字）",
                "return_time": "押金退还时间"
            }},
            "delivery_time": "房屋交付时间",
            "fees": "水电物业等费用承担",
            "penalty": {{
                "amount": "违约金金额（数字）",
                "conditions": "违约条件"
            }},
            "termination": {{
                "conditions": "解除条件",
                "notice_period": "提前通知时间"
            }},
            "maintenance": "维修责任",
            "usage": "房屋使用限制",
            "other_terms": "其他重要条款"
        }}
        
        如果信息缺失，请用空字符串或null表示。
        
        合同内容：
        {contract_content}
        """)
        #endregion
        
        #region
        # 单条款语义审查提示模板（直接审查review_single_clause）
        self.semantic_review_prompt = ChatPromptTemplate.from_template("""
        你是一名专业合同审查律师，请依据《中华人民共和国民法典》及合同法基本原则，对以下租赁合同条款进行审查。

        【审查标准】

        1. 模糊表达：
        - 条款内容不具体或存在歧义
        - 无法量化执行（如"视情况""合理处理"）

        2. 不公平条款：
        - 明显偏向一方利益
        - 加重一方责任或免除另一方责任
        - 剥夺一方合法权益

        3. 潜在法律风险：
        - 条款可能引发纠纷
        - 权利义务不清晰或不完整

        条款内容：
        {clause}

        返回JSON格式：
        {{
            "risk": true/false,
            "type": "模糊表达/不公平条款/潜在风险/无",
            "level": "high/medium/low",
            "reason": "一句话说明原因（不超过50字）"
        }}
        """)
        #endregion

        #region
        # 合同级语义审查（带上下文）：一次性阅读全文，输出风险点列表
        self.contract_semantic_review_prompt = ChatPromptTemplate.from_template("""
        你是一名专业合同审查律师。请依据《中华人民共和国民法典》及一般租赁实务，对【整份租房合同】进行上下文一致的风险审查。

        【要求】
        - 必须结合上下文判断，不要把条款从上下文中断章取义
        - 不要编造法条条号；如果需要提及依据，请用“依据：相关法律法规/民法典租赁编”等泛化表达
        - 每条风险点必须给出合同原文中的“摘录片段”（excerpt），用于定位
        - 只输出 JSON 数组，不要 markdown，不要额外解释

        返回格式（JSON 数组）：
        [
          {{
            "type": "模糊表达/不公平条款/潜在风险/上下文逻辑冲突",
            "level": "high/medium/low",
            "reason": "不超过60字",
            "excerpt": "合同原文摘录（不超过200字）"
          }}
        ]

        【合同原文】
        {contract_content}
        """)
        #endregion

        #region
        # 条款定位（启发式失败时可选 LLM 摘录，见 CHECK_CLAUSE_LOCATE_LLM）
        self.clause_locate_prompt = ChatPromptTemplate.from_template("""
        你是租房合同定位助手。根据规则说明，从「合同原文」中原样摘录**一段**与问题最相关的连续文字。
        不要总结、不要改写、不要编造；若确实找不到相关内容，extract 为空字符串。

        规则ID：{rule_id}
        规则名称：{rule_name}
        审查提示：{message}
        关键词参考：{keywords_hint}

        【合同原文】
        {contract_content}

        仅输出 JSON（不要 markdown）：{{"extract": "摘录的原文，若无则空字符串"}}
        """)
        #endregion

        # 预构建 chain，避免每次调用都重新拼装
        self._extraction_chain = self.extraction_prompt | self.llm | self.output_parser
        self._single_review_chain = self.semantic_review_prompt | self.llm | self.output_parser
        self._contract_review_chain = self.contract_semantic_review_prompt | self.llm | self.output_parser
        self._clause_locate_chain = self.clause_locate_prompt | self.llm | self.output_parser
        self._clause_locate_llm_enabled = os.getenv("CHECK_CLAUSE_LOCATE_LLM", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        self._clause_locate_max_chars = int(os.getenv("CHECK_CLAUSE_LOCATE_MAX_CHARS", "14000"))
        self._semantic_review_max_chars = int(os.getenv("CHECK_SEMANTIC_REVIEW_MAX_CHARS", "14000"))

    def check_compliance(self, contract_content: str) -> Dict[str, Any]:
        """
        检查租房合同的合规性
        
        Args:
            contract_content: 租房合同内容
            
        Returns:
            包含合规性检查结果的字典
        """
        try:
            # 步骤1: 解析模块（NLP） - 结构化合同（JSON）
            extracted_info_raw = self._extraction_chain.invoke({"contract_content": contract_content})

            try:
                structured_data = json.loads(extracted_info_raw)
            except json.JSONDecodeError:
                structured_data = {"error": "无法解析合同信息"}

            # 步骤2: 规则引擎（确定性；多条命中时条款定位并行）
            rule_issues = self.apply_rule_engine(structured_data, contract_content)

            # 步骤3: LLM 语义审查（合同级，带上下文；更符合整体语境）
            semantic_issues = self.apply_semantic_review(contract_content)
            
            # 合并所有问题
            all_issues = rule_issues + semantic_issues
            
            # 确定风险等级
            risk_level = self.determine_risk_level(all_issues)
            
            # 步骤4: 审查报告生成
            result = {
                "structured_data": structured_data,
                "risk_level": risk_level,
                "issues": all_issues,
                "status": "success"
            }
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "status": "error"
            }
    
    def apply_rule_engine(self, structured_data: Dict[str, Any], contract_content: str) -> List[Dict[str, Any]]:
        """
        应用规则引擎检查确定性规则
        
        Args:
            structured_data: 结构化合同数据
            contract_content: 原始合同内容
            
        Returns:
            发现的问题列表
        """
        pending: List[Dict[str, Any]] = []

        # R010 交付时间兜底：若抽取出的 delivery_time 缺失，
        # 使用 lease_term 的起始日期推导一个 delivery_time，避免必然误报。
        try:
            if (
                isinstance(structured_data, dict)
                and (structured_data.get("delivery_time") is None or str(structured_data.get("delivery_time")).strip() == "")
            ):
                lease_term = structured_data.get("lease_term")
                if isinstance(lease_term, str) and lease_term.strip():
                    m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", lease_term)
                    if not m:
                        m = re.search(r"(\d{4}\s*-\s*\d{1,2}\s*-\s*\d{1,2})", lease_term)
                    if m:
                        structured_data = dict(structured_data)
                        structured_data["delivery_time"] = m.group(1).replace(" ", "")
        except Exception:
            # 推导失败不影响其它规则；最多仍会触发 R010
            pass

        for rule in self.rules:
            rule_type = rule["type"]
            rule_id = rule["rule_id"]
            severity = rule["severity"]
            message = rule["message"]
            hit = False

            if rule_type == "required":
                field = rule["field"]
                if not self.check_required_field(structured_data, field):
                    hit = True
            elif rule_type == "numeric":
                condition = rule["condition"]
                if not self.check_numeric_condition(structured_data, condition):
                    hit = True
            elif rule_type == "forbidden":
                pattern = rule["pattern"]
                if re.search(pattern, contract_content, re.IGNORECASE):
                    hit = True
            elif rule_type == "logic":
                condition = rule["condition"]
                if not self.check_logic_condition(structured_data, condition):
                    hit = True
            elif rule_type == "format":
                field = rule["field"]
                pattern = rule["pattern"]
                if not self.check_format_condition(structured_data, field, pattern):
                    hit = True

            if hit:
                pending.append(
                    {
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "name": rule["name"],
                    }
                )

        if not pending:
            return []

        def _build_issue(spec: Dict[str, Any]) -> Dict[str, Any]:
            """单条规则条款摘录；异常时返回占位，避免线程池中一条失败导致整批 map 中止。"""
            base = {
                "rule_id": spec["rule_id"],
                "message": spec["message"],
                "severity": spec["severity"],
            }
            try:
                clause = self.extract_relevant_clause(
                    contract_content, spec["name"], spec["rule_id"], spec["message"]
                )
            except Exception:
                clause = "条款摘录失败（处理异常）"
            return {**base, "clause": clause}

        n = len(pending)
        max_workers = int(os.getenv("CHECK_RULE_CLAUSE_EXTRACT_MAX_WORKERS", "8"))
        max_workers = max(1, min(max_workers, n))

        if n == 1:
            return [_build_issue(pending[0])]

        # pool.map 按 pending 顺序收集结果，与串行遍历顺序一致
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(_build_issue, pending))
    
    def check_required_field(self, data: Dict[str, Any], field_path: str) -> bool:
        """
        检查必填字段是否存在且不为空
        """
        keys = field_path.split('.')
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return False
        return current is not None and str(current).strip() != ""

    def get_field_value(self, data: Dict[str, Any], field_path: str) -> Optional[Any]:
        """
        根据点路径（如 rent.amount / parties.tenant）从结构化数据中取值。

        - 支持 dict 逐层取值
        - 支持 list 的数字下标（如 items.0.name）
        - 找不到路径或值为空时返回 None
        - 若结果看起来是数值字符串，会尽量转换为 float，便于数值规则比较
        - 对于 parties 相关字段，保留原始字符串，不进行数值转换
        """
        if data is None or not field_path:
            return None

        current: Any = data
        for key in field_path.split("."):
            if current is None:
                return None

            if isinstance(current, dict):
                if key not in current:
                    return None
                current = current[key]
                continue

            if isinstance(current, list):
                if not key.isdigit():
                    return None
                idx = int(key)
                if idx < 0 or idx >= len(current):
                    return None
                current = current[idx]
                continue

            return None

        if current is None:
            return None

        if isinstance(current, str):
            s = current.strip()
            if s == "":
                return None

            # 对于 parties 相关字段，保留原始字符串，不进行数值转换
            if "parties" in field_path:
                return s

            # 对于其他字段，尝试提取数值
            num_match = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
            if num_match:
                try:
                    return float(num_match.group(0))
                except ValueError:
                    return s
            return s

        return current
    
    def check_numeric_condition(self, data: Dict[str, Any], condition: Dict[str, Any]) -> bool:
        """
        检查数值条件
        """
        field = condition["field"]
        operator = condition["operator"]
        value_expr = condition["value"]
        
        # 获取字段值
        field_value = self.get_field_value(data, field)
        if field_value is None:
            return True  # 如果字段不存在，不触发数值检查
        
        # 解析值表达式
        if "*" in value_expr:
            parts = value_expr.split(" * ")
            if len(parts) == 2:
                multiplier = float(parts[0]) if parts[0].isdigit() else 1
                ref_field = parts[1]
                ref_value = self.get_field_value(data, ref_field)
                if ref_value is not None:
                    expected_value = multiplier * float(ref_value)
                else:
                    return True
            else:
                expected_value = float(value_expr) if value_expr.isdigit() else 0
        else:
            expected_value = float(value_expr) if value_expr.isdigit() else 0
        
        # 比较
        if operator == "<=":
            return float(field_value) <= expected_value
        elif operator == ">=":
            return float(field_value) >= expected_value
        elif operator == "==":
            return float(field_value) == expected_value
        return True
    
    def check_logic_condition(self, data: Dict[str, Any], condition: str) -> bool:
        """
        检查逻辑条件
        """
        if condition == "only_tenant_has_penalty":
            # 检查是否只有租客有违约责任
            penalty = data.get("penalty", {})
            # 简单检查：如果有违约金，且没有房东违约条款，则认为不对等
            return "amount" in penalty and penalty["amount"] is not None
        elif condition == "termination_not_equal":
            # 检查解约/变更权利是否对双方均有表述（兼容 房东/租客 与 甲方/乙方）
            termination = data.get("termination", {})
            conditions = str(termination.get("conditions", "") or "")
            if not conditions.strip():
                return False
            if "双方" in conditions:
                return True
            if "房东" in conditions and "租客" in conditions:
                return True
            if "甲方" in conditions and "乙方" in conditions:
                return True
            return False
        return True
    
    def check_format_condition(self, data: Dict[str, Any], field_path: str, pattern: str) -> bool:
        """
        检查格式条件
        """
        field_value = self.get_field_value(data, field_path)
        if field_value is None:
            return True  # 如果字段不存在，不触发格式检查
        
        return bool(re.search(pattern, str(field_value)))

    def _phone_clause_snippet(self, tail: str, matches: List[re.Match], rule_id: str) -> str:
        """
        从含「电话：」的一行中截取展示用短句（只保留对应号码）。

        目的：
        - R031：只返回第一个「电话：号码」片段，避免把行后面的签署日期等内容也带进 clause。
        - R032：只返回第二个「电话：号码」片段。
        """
        if not matches:
            return ""

        if len(matches) >= 2:
            idx = 0 if rule_id == "R031" else 1
            idx = min(idx, len(matches) - 1)
            m = matches[idx]
            # 提取整个匹配项，包括「电话：」前缀
            return tail[m.start() : m.end()].strip()

        # 只有一个号码：只返回匹配到的「电话：号码」
        m0 = matches[0]
        return tail[m0.start() : m0.end()].strip()

    def _extract_phone_clause(self, contract_content: str, rule_id: str) -> Optional[str]:
        """
        定位「联系方式」中的电话（电话：/手机：），避免命中「电话费」等条款。
        签名区常见一行两个「电话：」，按出现顺序对应甲/乙双方。
        增强版：支持更多电话号码格式，提高匹配准确性。
        """
        # 增强的电话正则表达式，支持更多格式
        enhanced_phone_re = re.compile(r"(电话|手机|联系方式)[：:]\s*([1*●][0-9\*●]{4,})")
        
        # 收集所有包含电话信息的行
        phone_lines = []
        for raw in contract_content.splitlines():
            line = raw.strip()
            if not line:
                continue
            
            # 跳过「电话费」等费用条款
            if "电话费" in line and not enhanced_phone_re.search(line):
                continue
            
            # 查找电话信息
            phone_matches = list(enhanced_phone_re.finditer(line))
            if phone_matches:
                phone_lines.append((line, phone_matches))
        
        if not phone_lines:
            # 尝试在签名区查找
            signature_section = contract_content.split("出租方：")[-1] if "出租方：" in contract_content else contract_content
            signature_lines = signature_section.splitlines()
            for line in signature_lines:
                line = line.strip()
                if "电话：" in line or "手机：" in line:
                    phone_matches = list(enhanced_phone_re.finditer(line))
                    if phone_matches:
                        phone_lines.append((line, phone_matches))
        
        if not phone_lines:
            return None
        
        # 使用最后一行电话信息（通常在签名区）
        tail, matches = phone_lines[-1]
        if not matches:
            return tail[:500] if len(tail) > 500 else tail
        
        return self._phone_clause_snippet(tail, matches, rule_id)

    def _split_into_article_blocks(self, text: str) -> List[str]:
        """按「第…条/节」标题切分；无标题时按逻辑段落分割。"""
        text = (text or "").strip()
        if not text:
            return []
        
        # 1. 首先尝试使用增强的条款分割正则
        parts = _ARTICLE_SPLIT_ENHANCED.split(text)
        if len(parts) > 1:
            blocks = [p.strip() for p in parts if p.strip()]
            if len(blocks) > 1:
                return blocks
        
        # 2. 如果增强分割效果不好，回退到原有的分割方式
        parts = _ARTICLE_SPLIT_RE.split(text)
        if len(parts) > 1:
            blocks = [p.strip() for p in parts if p.strip()]
            if len(blocks) > 1:
                return blocks
        
        # 3. 尝试按常见合同结构关键词分割
        for keyword in _CONTRACT_STRUCTURE_KEYWORDS:
            if keyword in text:
                # 简单按关键词分割
                parts = text.split(keyword)
                if len(parts) > 1:
                    result = []
                    for i, part in enumerate(parts[1:]):
                        block = keyword + part.strip()
                        if block:
                            result.append(block)
                    if len(result) > 1:
                        return result
        
        # 4. 尝试按空行分割成段落
        paragraphs = text.split('\n\n')
        if len(paragraphs) > 1:
            blocks = [p.strip() for p in paragraphs if p.strip()]
            if len(blocks) > 1:
                return blocks
        
        # 5. 尝试按单行分割（适用于没有空行的情况）
        lines = text.split('\n')
        if len(lines) > 1:
            # 合并连续的非空行作为一个块
            blocks = []
            current_block = []
            for line in lines:
                line = line.strip()
                if line:
                    current_block.append(line)
                else:
                    if current_block:
                        blocks.append(' '.join(current_block))
                        current_block = []
            if current_block:
                blocks.append(' '.join(current_block))
            if len(blocks) > 1:
                return blocks
        
        # 6. 最后回退到整篇为一块
        return [text]

    def _score_block_keywords(
        self, block: str, rule_keywords: List[str], rule_name: Optional[str] = None
    ) -> int:
        """块内关键词命中越多分越高；标题行命中加权。电话格式类规则惩罚「仅电话费、无联系方式」块。"""
        if not block or not rule_keywords:
            return 0
        score = 0
        
        # 1. 基础关键词匹配得分
        for kw in rule_keywords:
            if kw in block:
                # 关键词出现次数，最多加3分
                count = min(block.count(kw), 3)
                score += 1 + count
                
                # 关键词位置权重：越靠前得分越高
                position = block.find(kw)
                if position < 100:
                    score += 2  # 前100字符内出现
                elif position < 300:
                    score += 1  # 前300字符内出现
        
        # 2. 标题行命中加权
        head = block.split("\n", 1)[0][:120]
        for kw in rule_keywords:
            if kw in head:
                score += 3  # 标题行命中权重更高
        
        # 3. 规则特定惩罚和增强
        if rule_name:
            # 电话号码规则惩罚
            if "电话号码" in rule_name:
                if "电话费" in block and not re.search(r"电话[：:]\s*[\d*●]", block):
                    score -= 10  # 更强的惩罚
            # 维修责任规则增强
            elif "维修责任" in rule_name:
                if "维修" in block or "修缮" in block or "维护" in block:
                    score += 5
                if "甲方维修" in block or "乙方维修" in block:
                    score += 8
            # 违约金规则增强
            elif "违约金" in rule_name or "违约" in rule_name:
                if "违约金" in block or "违约方赔偿" in block or "赔偿对方" in block:
                    score += 5
                if block.startswith("第八条") or "违约责任" in block[:100]:
                    score += 8
            # 押金规则增强
            elif "押金" in rule_name:
                if "乙方向甲方交纳押金" in block or "押金" in block[:200]:
                    score += 8
        
        # 4. 合同结构关键词增强
        for struct_kw in _CONTRACT_STRUCTURE_KEYWORDS[:20]:  # 使用前20个最常见的结构关键词
            if struct_kw in block[:100]:  # 结构关键词在块开头
                score += 1
        
        # 5. 长度惩罚：过长的块得分适当降低
        if len(block) > 1000:
            score = int(score * 0.8)
        # 长度奖励：适中长度的块得分适当提高
        elif len(block) > 50 and len(block) < 800:
            score = int(score * 1.1)
        
        # 6. 内容质量评估
        # 检查是否包含具体信息（如金额、日期、具体责任等）
        if re.search(r"\d+元|\d+年|\d+月|\d+日", block):
            score += 2
        if re.search(r"甲方|乙方|出租方|承租方", block):
            score += 2
        
        return max(0, score)  # 确保得分不为负

    def _pick_best_article_block(
        self,
        contract_content: str,
        rule_keywords: List[str],
        rule_name: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> Optional[str]:
        """在「第X条」块中选取关键词得分最高的一块（截断展示）。"""
        blocks = self._split_into_article_blocks(contract_content)
        if not blocks:
            return None
        
        # 计算每个块的得分和其他相关因素
        block_scores = []
        for i, block in enumerate(blocks):
            score = self._score_block_keywords(block, rule_keywords, rule_name)
            
            # 特殊规则：押金相关规则应该优先匹配包含"押金"的块
            if rule_name and "押金" in rule_name:
                if "乙方向甲方交纳押金" in block or "押金" in block[:200]:
                    score += 10  # 大幅加分
                # 避免匹配到租金条款
                if "月租金" in block and "押金" not in block[:100]:
                    score -= 5
            
            # 特殊规则：违约金相关规则应该优先匹配包含"违约金"或"赔偿"的块
            if rule_name and ("违约金" in rule_name or "违约" in rule_name):
                if "违约金" in block or "违约方赔偿" in block or "赔偿对方" in block:
                    score += 10
                # 优先匹配第八条
                if block.startswith("第八条") or "违约责任" in block[:100]:
                    score += 5
            
            # 计算关键词密度（关键词出现次数 / 块长度）
            keyword_count = sum(1 for kw in rule_keywords if kw in block)
            density = keyword_count / max(len(block), 1)
            
            # 计算块长度得分（适中长度的块得分更高）
            length_score = 1.0
            if len(block) < 50:
                length_score = 0.5  # 太短的块可能信息不足
            elif len(block) > 2000:
                length_score = 0.7  # 太长的块可能包含不相关内容
            
            # 综合得分
            total_score = score * length_score * (1 + density * 10)  # 密度因子放大
            
            block_scores.append((total_score, score, block))
        
        # 按综合得分排序
        block_scores.sort(reverse=True, key=lambda x: x[0])
        
        if not block_scores or block_scores[0][1] <= 0:
            return None
        
        best_block = block_scores[0][2]
        picked = best_block[:2500].strip()
        
        # 电话格式类规则：尽量只返回“电话：xxx”片段，避免夹带“电话费”等费用条款
        if rule_name and "电话号码" in rule_name and rule_id in ("R031", "R032"):
            phone = self._extract_phone_clause(picked, rule_id)
            if phone:
                return phone
        
        return picked
        #endregion

    def _sentence_keyword_fallback(
        self, contract_content: str, rule_name: str, rule_keywords: List[str]
    ) -> Optional[str]:
        """按句号切句，关键词先命中先返回（与旧版行为一致）。"""
        sentences = _SENTENCE_SPLIT_RE.split(contract_content)
        
        # 收集所有包含关键词的句子并评分
        candidate_sentences = []
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # 检查是否包含关键词
            matched_keywords = [kw for kw in rule_keywords if kw in sentence]
            if not matched_keywords:
                continue
            
            # 电话格式类规则的特殊处理
            if rule_name in ("出租方电话号码格式必须正确", "承租方电话号码格式必须正确"):
                if "电话费" in sentence and not _PHONE_CONTACT_ANY_RE.search(sentence):
                    continue
            
            # 押金相关规则的特殊处理
            if rule_name and "押金" in rule_name:
                # 优先匹配包含"押金"且不是"租金"的句子
                if "押金" in sentence:
                    if "乙方向甲方交纳押金" in sentence or "押金" in sentence[:50]:
                        matched_keywords.append("押金优先")
                    # 避免匹配到纯租金条款
                    if "月租金" in sentence and "押金" not in sentence:
                        continue
            
            # 违约金相关规则的特殊处理
            if rule_name and ("违约金" in rule_name or "违约" in rule_name):
                # 优先匹配包含"违约金"或"赔偿"的句子
                if "违约金" in sentence or "违约方赔偿" in sentence or "赔偿对方" in sentence:
                    matched_keywords.append("违约金优先")
            
            # 计算句子得分
            # 1. 关键词匹配数量
            keyword_score = len(matched_keywords)
            # 2. 句子长度得分（适中长度的句子得分更高）
            length_score = 1.0
            if len(sentence) < 20:
                length_score = 0.5  # 太短的句子可能信息不足
            elif len(sentence) > 500:
                length_score = 0.7  # 太长的句子可能包含不相关内容
            # 3. 关键词位置得分（关键词越靠前得分越高）
            position_score = 1.0
            for kw in matched_keywords:
                pos = sentence.find(kw)
                if pos < 50:
                    position_score += 0.5
            
            total_score = keyword_score * length_score * position_score
            candidate_sentences.append((total_score, sentence))
        
        # 按得分排序并返回最高分的句子
        if candidate_sentences:
            candidate_sentences.sort(reverse=True, key=lambda x: x[0])
            # 如果有多个句子，返回前几个相关句子的组合
            if len(candidate_sentences) > 1 and candidate_sentences[0][0] < 2:
                # 如果最高得分较低，返回前两个句子
                combined = "。".join([s[1] for s in candidate_sentences[:2]]) + "。"
                return combined.strip()
            return candidate_sentences[0][1]
        
        return None

    def _llm_fallback_clause(
        self,
        contract_content: str,
        rule_id: Optional[str],
        rule_name: str,
        message: Optional[str],
        rule_keywords: List[str],
    ) -> Optional[str]:
        """启发式均失败时，可选由 LLM 从原文摘录（需 CHECK_CLAUSE_LOCATE_LLM=1）。"""
        if not self._clause_locate_llm_enabled:
            return None
        
        # 准备合同内容，确保不超过长度限制
        text = (contract_content or "")[: self._clause_locate_max_chars]
        if not text.strip():
            return None
        
        # 准备关键词提示，使用更清晰的格式
        hint = "、".join(rule_keywords[:20])
        
        # 构建更详细的提示信息
        context_info = {
            "rule_id": rule_id or "",
            "rule_name": rule_name,
            "message": (message or "").strip(),
            "keywords_hint": hint,
            "contract_content": text,
            # 添加额外的上下文信息
            "extra_context": "请重点关注与规则名称和关键词相关的内容，确保提取的条款能够直接反映规则所涉及的问题。"
        }
        
        try:
            raw = self._clause_locate_chain.invoke(context_info)
            
            # 解析LLM响应
            data = json.loads(raw)
            if isinstance(data, dict):
                ex = data.get("extract", "")
                if isinstance(ex, str) and ex.strip():
                    # 对提取的内容进行后处理
                    extracted = ex.strip()[:3000]
                    # 确保提取的内容是完整的句子或段落
                    if extracted and not any(extracted.endswith(punc) for punc in ["。", "！", "？", ".", "!", "?"]):
                        # 尝试找到最近的标点符号
                        for i in range(len(extracted)-1, max(0, len(extracted)-100), -1):
                            if extracted[i] in ["。", "！", "？", ".", "!", "?"]:
                                extracted = extracted[:i+1]
                                break
                    return extracted
        except Exception as e:
            # 记录错误但不影响整体流程
            print(f"LLM fallback clause extraction failed: {e}")
        return None

    def extract_relevant_clause(
        self,
        contract_content: str,
        rule_name: str,
        rule_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> str:
        """
        分层定位相关条款：
        1）按「第X条」切块打分；
        2）按句关键词回退；
        3）可选 LLM 摘录（CHECK_CLAUSE_LOCATE_LLM）；
        4）全文搜索最相关段落；
        5）针对特定规则的精确匹配。

        增强版：添加更多通用匹配策略，提高对不同合同格式的适应性。
        """
        rule_keywords = CLAUSE_LOCATE_KEYWORDS.get(rule_name, [])
        if not rule_keywords:
            return "无法定位具体条款"

        # 特殊规则：电话号码提取
        if rule_name and "电话号码" in rule_name and rule_id in ("R031", "R032"):
            phone_clause = self._extract_phone_clause(contract_content, rule_id)
            if phone_clause:
                return phone_clause

        # 1. 首先尝试按「第X条」切块打分
        block_hit = self._pick_best_article_block(contract_content, rule_keywords, rule_name, rule_id)
        if block_hit:
            # 对提取的块进行质量评估
            if len(block_hit) > 50 and any(kw in block_hit for kw in rule_keywords):
                return block_hit

        # 2. 按句关键词回退
        sent_hit = self._sentence_keyword_fallback(contract_content, rule_name, rule_keywords)
        if sent_hit:
            # 对提取的句子进行质量评估
            if len(sent_hit) > 20 and any(kw in sent_hit for kw in rule_keywords):
                return sent_hit

        # 3. 可选 LLM 摘录
        llm_hit = self._llm_fallback_clause(
            contract_content, rule_id, rule_name, message, rule_keywords
        )
        if llm_hit:
            # 对LLM提取的内容进行质量评估
            if len(llm_hit) > 30 and any(kw in llm_hit for kw in rule_keywords):
                return llm_hit

        # 4. 全文搜索最相关段落
        # 首先尝试按段落分割
        paragraphs = contract_content.split('\n\n')
        if not paragraphs:
            # 如果没有空行分割，尝试按单行分割
            paragraphs = contract_content.split('\n')
        
        relevant_sections = []
        
        for section in paragraphs:
            section = section.strip()
            if not section or len(section) < 10:
                continue
            
            # 计算基础相关性得分
            keyword_count = sum(1 for kw in rule_keywords if kw in section)
            if keyword_count == 0:
                continue
            
            # 计算关键词密度
            density = keyword_count / len(section)
            # 计算位置得分（越靠前得分越高）
            position_score = 1.0
            for kw in rule_keywords:
                pos = section.find(kw)
                if pos != -1:
                    position_score = max(position_score, 1.0 - (pos / len(section)))
            
            # 基础得分
            base_score = keyword_count * 10
            # 密度得分
            density_score = density * 100
            # 长度得分（适中长度得分更高）
            length_score = 1.0
            if len(section) < 50:
                length_score = 0.5
            elif len(section) > 1000:
                length_score = 0.7
            
            # 综合得分
            total_score = (base_score + density_score) * position_score * length_score
            
            # 特殊规则增强
            # 押金相关规则
            if rule_name and "押金" in rule_name:
                if "乙方向甲方交纳押金" in section:
                    total_score += 100
                elif "押金" in section[:100]:
                    total_score += 50
                # 避免匹配到纯租金条款
                if "月租金" in section and "押金" not in section[:200]:
                    total_score -= 30
            
            # 违约金相关规则
            if rule_name and ("违约金" in rule_name or "违约" in rule_name):
                if "违约金" in section or "违约方赔偿" in section or "赔偿对方" in section:
                    total_score += 80
                if section.startswith("第八条") or "违约责任" in section[:150]:
                    total_score += 60
            
            # 维修责任相关规则
            if rule_name and "维修责任" in rule_name:
                if "维修责任" in section or "维修" in section or "修缮" in section:
                    total_score += 80
                if "甲方维修" in section or "乙方维修" in section:
                    total_score += 60
            
            # 电话号码相关规则
            if rule_name and "电话号码" in rule_name:
                if "电话：" in section:
                    total_score += 80
                if "电话费" in section and "电话：" not in section:
                    total_score -= 50
            
            # 地址相关规则
            if rule_name and "地址" in rule_name:
                if "坐落在" in section or "地址" in section:
                    total_score += 80
                if "市" in section and "区" in section:
                    total_score += 40
            
            relevant_sections.append((total_score, section))
        
        if relevant_sections:
            # 按得分排序
            relevant_sections.sort(reverse=True, key=lambda x: x[0])
            best_section = relevant_sections[0][1]
            
            # 截取适当长度
            if len(best_section) > 800:
                # 尝试找到自然断点
                for i in range(800, min(900, len(best_section))):
                    if best_section[i] in ["。", "！", "？", ".", "!", "?", "\n"]:
                        best_section = best_section[:i+1]
                        break
                else:
                    best_section = best_section[:800] + "..."
            return best_section

        # 5. 最后尝试全局关键词搜索，返回包含关键词的上下文
        for kw in rule_keywords:
            if kw in contract_content:
                # 找到关键词位置
                pos = contract_content.find(kw)
                # 提取关键词前后的上下文
                start = max(0, pos - 200)
                end = min(len(contract_content), pos + 400)
                context = contract_content[start:end].strip()
                # 确保返回的是完整的句子
                if context:
                    # 尝试找到句子边界
                    for i in range(len(context)-1, max(0, len(context)-100), -1):
                        if context[i] in ["。", "！", "？", ".", "!", "?"]:
                            context = context[:i+1]
                            break
                    return context

        # 6. 特殊规则兜底：对于必须约定类规则，返回最接近的相关条款
        if rule_name and "必须约定" in rule_name:
            # 尝试找到与规则相关的任何内容
            related_keywords = []
            if "维修" in rule_name:
                related_keywords = ["房屋", "装修", "改善", "增设", "主体结构"]
            elif "押金" in rule_name:
                related_keywords = ["押金", "保证金", "退还"]
            elif "违约" in rule_name:
                related_keywords = ["违约", "责任", "赔偿", "解除"]
            elif "租金" in rule_name:
                related_keywords = ["租金", "支付", "费用"]
            elif "地址" in rule_name:
                related_keywords = ["房屋", "坐落", "位置", "地址"]
            
            for kw in related_keywords:
                if kw in contract_content:
                    pos = contract_content.find(kw)
                    start = max(0, pos - 150)
                    end = min(len(contract_content), pos + 350)
                    context = contract_content[start:end].strip()
                    if context:
                        # 尝试找到句子边界
                        for i in range(len(context)-1, max(0, len(context)-100), -1):
                            if context[i] in ["。", "！", "？", ".", "!", "?"]:
                                context = context[:i+1]
                                break
                        return context

        return "相关条款未找到"
    
    def review_single_clause(self, clause: str) -> Dict[str, Any]:
        """
        审查单个条款的合规性
        
        使用LLM对单个合同条款进行语义审查，检查模糊表达、不公平条款和潜在法律风险。
        
        Args:
            clause: 单个合同条款内容
            
        Returns:
            审查结果字典，包含风险判断、类型、等级和原因
        """
        norm = (clause or "").strip()
        if not norm:
            return {"risk": False, "type": "无", "level": "low", "reason": "条款为空"}

        try:
            review_result = self._single_review_chain.invoke({"clause": norm})
            
            review_data = json.loads(review_result)
            return review_data if isinstance(review_data, dict) else {
                "risk": False,
                "type": "解析错误",
                "level": "low",
                "reason": "无法解析LLM响应"
            }
        except json.JSONDecodeError:
            return {
                "risk": False,
                "type": "解析错误",
                "level": "low",
                "reason": "无法解析LLM响应"
            }
        except Exception as e:
            return {
                "risk": False,
                "type": "系统错误",
                "level": "low",
                "reason": f"审查过程中发生错误: {str(e)}"
            }
    
    def apply_semantic_review(self, contract_content: str) -> List[Dict[str, Any]]:
        """
        应用 LLM 语义审查（合同级，上下文一致）。
        """
        text = (contract_content or "")[: self._semantic_review_max_chars]
        if not text.strip():
            return []
        try:
            raw = self._contract_review_chain.invoke({"contract_content": text})
            data = json.loads(raw)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        issues: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            tp = item.get("type", "潜在风险")
            level = item.get("level", "medium")
            reason = item.get("reason", "")
            excerpt = item.get("excerpt", "")
            if not isinstance(excerpt, str):
                excerpt = ""
            if not isinstance(reason, str):
                reason = ""
            msg = f"{tp}: {reason}".strip(": ").strip()
            issues.append(
                {
                    "rule_id": "LLM_SEMANTIC",
                    "message": msg or "潜在风险",
                    "severity": level,
                    "clause": excerpt.strip()[:800],
                }
            )
        return issues
    
    def determine_risk_level(self, issues: List[Dict[str, Any]]) -> str:
        """
        确定整体风险等级
        """
        if any(issue["severity"] == "high" for issue in issues):
            return "high"
        elif any(issue["severity"] == "medium" for issue in issues):
            return "medium"
        else:
            return "low"

class RentalContractAgent:
    def __init__(self):

        self.checker = RentalContractChecker()
    
    def analyze_contract(self, contract_content: str) -> Dict[str, Any]:
        """
        智能体分析租房合同
        
        Args:
            contract_content: 租房合同内容
            
        Returns:
            分析结果
        """
        # 检查合同长度
        if len(contract_content) < 100:
            return {
                "error": "合同内容过短，请提供完整的租房合同",
                "status": "error"
            }
        
        # 执行合规性检查
        result = self.checker.check_compliance(contract_content)
        
        return result
    
    def generate_summary(self, analysis_result: Dict[str, Any]) -> str:
        """
        生成分析结果摘要
        
        Args:
            analysis_result: 分析结果
            
        Returns:
            摘要文本
        """
        if analysis_result.get("status") != "success":
            return f"分析失败：{analysis_result.get('error', '未知错误')}"
        
        risk_level = analysis_result.get("risk_level", "unknown")
        issues = analysis_result.get("issues", [])
        
        summary = f"租房合同合规性分析摘要：\n"
        summary += f"风险等级：{risk_level}\n"
        summary += f"发现问题数量：{len(issues)}\n"
        
        if issues:
            summary += "\n问题列表：\n"
            for issue in issues:
                summary += f"- {issue['rule_id']}: {issue['message']} (严重程度: {issue['severity']})\n"
        
        return summary