from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema,OpenApiParameter,OpenApiExample,OpenApiRequest
from myapp.views.generate.ragservice.rag_service import get_rag
from myapp.views.check.checkservice.service import RentalContractChecker
from rest_framework import serializers

# 用于实现POST方式发送请求
class GenerateSerializer(serializers.Serializer):
    demand = serializers.CharField(required=True)

@extend_schema(tags=["租房合同的生成"])
class GenerateHandler(APIView):
    @extend_schema(summary="生成文件", description="生成文件")
    def get(self, request):
        return Response()
    

    @extend_schema(summary="根据参数生成租房合同",
                description="生成合同可支持用户预览",
                request=GenerateSerializer,
            )
    def post(self, request):
        demand = request.data.get("demand")
        
        # 初始化RAG和合规检查器
        rag = get_rag()
        checker = RentalContractChecker()
        
        max_iterations = 2  # 最大迭代次数，避免无限循环
        iteration = 0
        current_demand = demand
        final_contract = None
        iteration_history = []
        
        while iteration < max_iterations:
            iteration += 1
            
            # 使用RAG生成合同
            rag_result = rag.query(current_demand)
            generated_contract = rag_result.get("result", "")
            
            # 记录本次迭代
            iteration_info = {
                "iteration": iteration,
                "demand": current_demand,
                "generated_contract": generated_contract
            }
            
            # 对生成的合同进行合规审查（RAG输出通常是单条款）
            review_result = checker.review_single_clause(generated_contract)
            issues = []
            if review_result.get("risk", False):
                issues.append({
                    "message": f"{review_result.get('type', '潜在风险')}: {review_result.get('reason', '')}",
                    "severity": review_result.get("level", "medium"),
                    "clause": generated_contract
                })
            
            iteration_info["issues"] = issues
            iteration_history.append(iteration_info)
            
            # 如果没有问题，结束循环
            if not issues:
                final_contract = generated_contract
                break
            
            # 如果有问题，构造新的需求，包含问题反馈
            problem_descriptions = []
            for issue in issues:
                problem_descriptions.append(f"{issue['message']} (严重程度: {issue['severity']})")
            
            feedback = f"发现以下合规性问题：{'；'.join(problem_descriptions)}。请重新生成符合法律法规的租房合同。"
            current_demand = f"{demand}\n\n{feedback}"
        
        # 返回最终结果
        response_data = {
            "final_contract": final_contract,
            "iterations": iteration_history,
            "total_iterations": iteration,
            "success": final_contract is not None
        }
        
        if not final_contract:
            response_data["message"] = f"在{max_iterations}次迭代后仍未生成合规合同，请检查需求或联系管理员。"
        
        return Response(data=response_data)
    