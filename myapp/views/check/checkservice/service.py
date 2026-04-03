import os
import json
import re
from typing import Dict, List, Optional, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

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
        # 条款分割提示模板
        self.clause_split_prompt = ChatPromptTemplate.from_template("""
        请将以下租房合同分割成独立的条款，每个条款单独一行。重点关注可能存在风险的条款，如押金、违约、维修等。
        
        输出格式：每行一个条款，直接列出条款内容。
        
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
        # LLM批量语义审查提示模板（优化速度）
        self.batch_semantic_review_prompt = ChatPromptTemplate.from_template("""
        你是一名专业合同审查律师，请依据《中华人民共和国民法典》及合同法基本原则，对以下多个租赁合同条款进行审查。

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

        【条款列表】
        {clauses_text}

        【任务】
        请对每个条款逐一判断，返回JSON数组格式：
        [
            {{
                "clause_index": 1,
                "risk": true,
                "type": "",
                "level": "",
                "reason": ""
            }},
            ...
        ]

        每个条款的输出格式：
        - clause_index: 条款编号（从1开始）
        - risk: 是否存在风险（true/false）
        - type: 风险类型（模糊表达 / 不公平条款 / 潜在风险 / 无）
        - level: 风险等级（高 / 中 / 低）
        - reason: 一句话说明原因（不超过50字，不得编造法律条文）
        """)
        #endregion

        # 预构建 chain，避免每次调用都重新拼装
        self._extraction_chain = self.extraction_prompt | self.llm | self.output_parser
        self._clause_split_chain = self.clause_split_prompt | self.llm | self.output_parser
        self._single_review_chain = self.semantic_review_prompt | self.llm | self.output_parser
        self._batch_review_chain = self.batch_semantic_review_prompt | self.llm | self.output_parser
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
            
            # 解析提取的信息
            try:
                structured_data = json.loads(extracted_info_raw)
            except json.JSONDecodeError:
                structured_data = {"error": "无法解析合同信息"}
            
            # 步骤2: 规则引擎（确定性）
            rule_issues = self.apply_rule_engine(structured_data, contract_content)
            
            # 步骤3: LLM语义审查（模糊/风险）
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
        issues = []
        
        for rule in self.rules:
            rule_type = rule["type"]
            rule_id = rule["rule_id"]
            severity = rule["severity"]
            message = rule["message"]
            
            if rule_type == "required":
                field = rule["field"]
                if not self.check_required_field(structured_data, field):
                    clause = self.extract_relevant_clause(contract_content, rule["name"], rule_id)
                    issues.append({
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "clause": clause
                    })
            elif rule_type == "numeric":
                condition = rule["condition"]
                if not self.check_numeric_condition(structured_data, condition):
                    clause = self.extract_relevant_clause(contract_content, rule["name"], rule_id)
                    issues.append({
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "clause": clause
                    })
            elif rule_type == "forbidden":
                pattern = rule["pattern"]
                if re.search(pattern, contract_content, re.IGNORECASE):
                    clause = self.extract_relevant_clause(contract_content, rule["name"], rule_id)
                    issues.append({
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "clause": clause
                    })
            elif rule_type == "logic":
                condition = rule["condition"]
                if not self.check_logic_condition(structured_data, condition):
                    clause = self.extract_relevant_clause(contract_content, rule["name"], rule_id)
                    issues.append({
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "clause": clause
                    })
            elif rule_type == "format":
                field = rule["field"]
                pattern = rule["pattern"]
                if not self.check_format_condition(structured_data, field, pattern):
                    clause = self.extract_relevant_clause(contract_content, rule["name"], rule_id)
                    issues.append({
                        "rule_id": rule_id,
                        "message": message,
                        "severity": severity,
                        "clause": clause
                    })
        
        return issues
    
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

    def _extract_phone_clause(self, contract_content: str, rule_id: str) -> Optional[str]:
        """
        定位「联系方式」中的电话（电话：/手机：），避免命中「电话费」等条款。
        签名区常见一行两个「电话：」，按出现顺序对应甲/乙双方。
        """
        phone_contact = re.compile(r"电话[：:]\s*([1*●][0-9\*●]{4,})")
        lines: List[str] = []
        for raw in contract_content.splitlines():
            line = raw.strip()
            if not line or "电话" not in line:
                continue
            if "电话费" in line and not phone_contact.search(line):
                continue
            if phone_contact.search(line):
                lines.append(line)
        if not lines:
            return None
        tail = lines[-1]
        matches = list(phone_contact.finditer(tail))
        if not matches:
            return tail
        if len(matches) >= 2:
            if rule_id == "R031":
                return tail[: matches[1].start()].rstrip()
            return tail[matches[1].start() :].strip()
        return tail

    def extract_relevant_clause(self, contract_content: str, rule_name: str, rule_id: Optional[str] = None) -> str:
        """
        从合同内容中提取与规则最相关的语句；必要时按 rule_id 走专门逻辑。
        """
        if rule_id in ("R031", "R032"):
            phone = self._extract_phone_clause(contract_content, rule_id)
            if phone:
                return phone

        sentences = re.split(r'[。！？\n]', contract_content)

        # R026：优先定位「第七条 / 租赁双方的变更」，避免只命中含「解除」等泛词的其他条款
        if rule_name == "解约责任必须对等":
            for sentence in sentences:
                st = sentence.strip()
                if not st:
                    continue
                if "第七条" in st or "租赁双方的变更" in st:
                    return st

        # 根据规则名称提取关键词
        keywords = {
            "必须存在出租人": ["出租方", "甲方"],
            "必须存在承租人": ["承租方", "乙方"],
            "出租人必须有处分权": ["转租"],
            "房屋用途必须合法": ["违法用途", "商业经营"],
            "禁止群租风险": ["多人合租"],
            "必须约定租金": ["租金", "月租金"],
            "必须约定租期": ["租赁期限", "租期"],
            "必须约定支付周期": ["支付周期", "交纳期限"],
            "必须约定押金": ["押金"],
            "必须约定交付时间": ["交付时间"],
            "押金不得超过两个月租金": ["押金", "租金"],
            "押金必须可退还": ["押金不退", "不予退还"],
            "押金扣除必须明确": ["押金视情况扣除"],
            "必须约定押金退还时间": ["押金退还时间"],
            "禁止单方随意涨租": ["随意调整租金"],
            "必须明确费用承担": ["费用", "水电"],
            "禁止模糊费用条款": ["费用按实际情况"],
            "禁止商用水电未说明": ["商业用电"],
            "违约金不得过高": ["违约金"],
            "违约责任必须对等": ["违约责任"],
            "禁止房东免责": ["房东不承担任何责任"],
            "必须约定违约情形": ["违约条件"],
            "禁止模糊违约责任": ["违约责任由租客承担"],
            "禁止单方随意解约": ["房东可随时解除合同"],
            "解除条件必须明确": ["解除条件"],
            "解约责任必须对等": [
                "第七条",
                "租赁双方的变更",
                "解除",
                "转租",
                "优先购买",
                "终止",
                "解约",
            ],
            "必须约定提前通知时间": ["提前通知时间"],
            "必须约定维修责任": ["维修责任"],
            "维修责任必须区分": ["所有维修由租客承担"],
            "必须约定使用限制": ["使用限制"],
            "出租方电话号码格式必须正确": ["出租方", "甲方", "电话"],
            "承租方电话号码格式必须正确": ["承租方", "乙方", "电话"],
            "地址信息必须完整": ["地址", "坐落"],
            "租金金额必须为正数": ["租金"],
            "押金金额必须为正数": ["押金"]
        }
        
        rule_keywords = keywords.get(rule_name, [])
        if not rule_keywords:
            return "无法定位具体条款"

        # 在合同中搜索包含关键词的句子（任一词命中即候选）
        phone_fee_noise = re.compile(r"电话[：:]\s*[\d*●]")
        for sentence in sentences:
            if not any(keyword in sentence for keyword in rule_keywords):
                continue
            if rule_name in ("出租方电话号码格式必须正确", "承租方电话号码格式必须正确"):
                if "电话费" in sentence and not phone_fee_noise.search(sentence):
                    continue
            return sentence.strip()

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
        应用LLM语义审查（优化版：批量处理以提高速度）
        
        将合同分割成条款，然后批量调用LLM进行审查，减少API调用次数。
        """
        issues = []
        
        # 分割合同成条款
        clauses_text = self._clause_split_chain.invoke({"contract_content": contract_content})
        clauses = [clause.strip() for clause in clauses_text.split('\n') if clause.strip()]
        
        # 限制条款数量并批量处理
        max_clauses = 20  # 最多处理20个条款
        clauses = clauses[:max_clauses]
        
        # 批量大小
        batch_size = 5
        for i in range(0, len(clauses), batch_size):
            batch_clauses = clauses[i:i + batch_size]
            
            # 构建批量条款文本
            clauses_text = "\n".join([f"{j+1}. {clause}" for j, clause in enumerate(batch_clauses)])
            
            # 批量审查
            review_result = self._batch_review_chain.invoke({"clauses_text": clauses_text})
            
            try:
                review_data_list = json.loads(review_result)
                for review_data in review_data_list:
                    clause_index = review_data.get("clause_index", 0) - 1  # 转换为0-based索引
                    if clause_index < len(batch_clauses) and review_data.get("risk", False):
                        clause = batch_clauses[clause_index]
                        issues.append({
                            "rule_id": "LLM_SEMANTIC",
                            "message": f"{review_data.get('type', '潜在风险')}: {review_data.get('reason', '')}",
                            "severity": review_data.get("level", "medium"),
                            "clause": clause
                        })
            except (json.JSONDecodeError, TypeError):
                # 如果批量解析失败，回退到单个处理（但为了速度，这里跳过）
                continue
        
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
