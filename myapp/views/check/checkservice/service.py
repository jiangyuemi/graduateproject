import os
import json
from typing import Dict, List, Optional, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

class RentalContractChecker:
    def __init__(self):
        # 初始化AI模型
        self.llm = ChatOpenAI(
            model="qwen3.5-plus",
            temperature=0.1,
            api_key=os.getenv("LLM_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.output_parser = StrOutputParser()
        #region
        # 租房合同合规检查提示模板
        self.compliance_prompt = ChatPromptTemplate.from_template("""
        你是一名专业的租房合同合规检查员，负责分析租房合同的合法性和合规性。
        
        请仔细分析以下租房合同内容，检查以下方面：
        
        1. 合同基本信息完整性
           - 出租方和承租方的身份信息是否完整
           - 房屋基本信息是否明确（地址、面积、户型等）
           - 租赁期限是否明确
           - 租金及支付方式是否明确
        
        2. 法律法规合规性
           - 是否符合《民法典》相关规定
           - 是否符合《城市房屋租赁管理办法》
           - 是否存在违法条款
           - 是否有不公平格式条款
        
        3. 关键条款检查
           - 押金条款是否合理（通常不超过2个月租金）
           - 违约责任是否明确
           - 房屋维修责任是否明确
           - 转租条款是否合法
           - 房屋用途是否明确
           - 提前解除合同的条件是否合理
        
        4. 风险提示
           - 合同中可能存在的风险点
           - 需要特别注意的条款
           - 建议补充的条款
        
        请提供详细的检查报告，包括：
        - 合规性评分（0-100分）
        - 发现的问题及风险
        - 具体的修改建议
        - 合规性总结
        
        合同内容：
        {contract_content}
        """)
        #endregion
        #region
        # 合同内容提取提示模板
        self.extraction_prompt = ChatPromptTemplate.from_template("""
        请从以下租房合同中提取关键信息，按照JSON格式输出：
        
        {{"basic_info": {{
            "landlord": "出租方信息",
            "tenant": "承租方信息",
            "property": "房屋信息",
            "rent_period": "租赁期限",
            "rent_amount": "租金金额",
            "payment_method": "支付方式",
            "deposit": "押金金额"
        }},
        "key_terms": {{
            "deposit_terms": "押金条款",
            "repair_responsibility": "维修责任",
            "sublease": "转租条款",
            "breach": "违约责任",
            "early_termination": "提前解除条件"
        }}
        }}
        
        合同内容：
        {contract_content}
        """)
        #endregion
    def check_compliance(self, contract_content: str) -> Dict[str, Any]:
        """
        检查租房合同的合规性
        
        Args:
            contract_content: 租房合同内容
            
        Returns:
            包含合规性检查结果的字典
        """
        try:
            # 提取合同关键信息
            extraction_chain = self.extraction_prompt | self.llm | self.output_parser
            extracted_info = extraction_chain.invoke({"contract_content": contract_content})
            
            # 解析提取的信息
            try:
                parsed_info = json.loads(extracted_info)
            except json.JSONDecodeError:
                parsed_info = {"error": "无法解析合同信息"}
            
            # 进行合规性检查
            compliance_chain = self.compliance_prompt | self.llm | self.output_parser
            compliance_result = compliance_chain.invoke({"contract_content": contract_content})
            
            # 构建完整的检查结果
            result = {
                "extracted_info": parsed_info,
                "compliance_report": compliance_result,
                "status": "success"
            }
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "status": "error"
            }
    
    def get_compliance_score(self, report: str) -> int:
        """
        从合规性报告中提取评分
        
        Args:
            report: 合规性报告内容
            
        Returns:
            合规性评分（0-100）
        """
        # 简单的评分提取逻辑
        import re
        score_match = re.search(r'合规性评分\s*[:：]\s*(\d+)', report)
        if score_match:
            return int(score_match.group(1))
        return 0

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
        
        if result["status"] == "success":
            # 提取评分
            score = self.checker.get_compliance_score(result["compliance_report"])
            result["compliance_score"] = score
        
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
        
        score = analysis_result.get("compliance_score", 0)
        report = analysis_result.get("compliance_report", "")
        
        summary = f"租房合同合规性分析摘要：\n"
        summary += f"合规性评分：{score}/100\n"
        summary += "\n详细报告：\n"
        summary += report
        
        return summary
