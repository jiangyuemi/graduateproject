from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser  # 添加JSON解析器
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiRequest
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
import os
import uuid
from .checkservice.service import RentalContractAgent

# 尝试导入文件处理库
try:
    import docx
    from PyPDF2 import PdfReader
except ImportError:
    pass

# 用于实现POST方式发送请求
class CheckSerializer(serializers.Serializer):
    upload_file = serializers.FileField(required=False, help_text="上传的文件")
    contract_content = serializers.CharField(required=False, help_text="直接输入的合同内容", allow_blank=True)

@extend_schema(tags=["合同合规检查"])
class CheckHandler(APIView):
    permission_classes = [IsAuthenticated]
    # 关键：添加解析器以支持文件上传和JSON请求
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    
    @extend_schema(
        summary="进行合规检查",
        description="上传合同文件进行合规性检查",
        request=CheckSerializer,
    )
    def post(self, request):
        # 1. 使用序列化器验证数据
        serializer = CheckSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "code": 400,
                "message": "数据验证失败",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 2. 获取验证后的数据
        uploaded_file = serializer.validated_data.get('upload_file')
        contract_content = serializer.validated_data.get('contract_content', '')
        
        # 3. 验证至少提供一种输入方式
        if not uploaded_file and not contract_content:
            return Response({
                "code": 400,
                "message": "请上传合同文件或直接输入合同内容"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 4. 处理文件上传
            file_info = None
            if uploaded_file:
                # 验证文件类型
                allowed_extensions = ['.pdf', '.doc', '.docx', '.txt']
                file_name, file_extension = os.path.splitext(uploaded_file.name)
                
                if file_extension.lower() not in allowed_extensions:
                    return Response({
                        "code": 400,
                        "message": "不支持的文件类型",
                        "allowed_types": allowed_extensions,
                        "uploaded_type": file_extension
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 验证文件大小
                max_size = 10 * 1024 * 1024  # 10MB
                if uploaded_file.size > max_size:
                    return Response({
                        "code": 400,
                        "message": f"文件大小超过限制（最大{max_size//1024//1024}MB）",
                        "uploaded_size": uploaded_file.size,
                        "max_size": max_size
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 保存文件
                from django.conf import settings
                upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                
                unique_filename = f"{uuid.uuid4()}{file_extension}"
                file_path = os.path.join(upload_dir, unique_filename)
                
                with open(file_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                
                # 提取文件内容
                contract_content = self.extract_file_content(file_path, file_extension)
                
                file_info = {
                    "original_name": uploaded_file.name,
                    "file_size": uploaded_file.size,
                    "file_type": file_extension,
                    "saved_path": file_path,
                    "unique_name": unique_filename
                }
            
            # 5. 执行合规检查
            if contract_content:
                check_result = self.perform_compliance_check(contract_content)
                
                # 6. 返回成功响应
                if check_result.get("status") == "success":
                    response_data = {
                        "code": 200,
                        "message": "合规检查已完成",
                        "data": {
                            "risk_level": check_result.get("risk_level"),
                            "issues": check_result.get("issues", []),
                            "structured_data": check_result.get("structured_data"),
                            "summary": check_result.get("summary"),
                            "content": contract_content
                        }
                    }
                else:
                    response_data = {
                        "code": 500,
                        "message": "合规检查失败",
                        "error": check_result.get("error")
                    }
            else:
                return Response({
                    "code": 400,
                    "message": "无法提取合同内容，请检查文件格式或直接输入合同内容"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if file_info:
                response_data["file_info"] = file_info
            
            return Response(response_data)
            
        except Exception as e:
            # 处理异常
            return Response({
                "code": 500,
                "message": "处理过程中发生错误",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def extract_file_content(self, file_path, file_extension):
        """
        提取不同文件类型的内容
        
        Args:
            file_path: 文件路径
            file_extension: 文件扩展名
            
        Returns:
            提取的文本内容
        """
        try:
            if file_extension.lower() == '.txt':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            
            elif file_extension.lower() == '.docx':
                if 'docx' in globals():
                    doc = docx.Document(file_path)
                    content = []
                    for para in doc.paragraphs:
                        content.append(para.text)
                    return '\n'.join(content)
                else:
                    return "需要安装python-docx库来处理docx文件"
            
            elif file_extension.lower() == '.pdf':
                if 'PdfReader' in globals():
                    reader = PdfReader(file_path)
                    content = []
                    for page_num in range(len(reader.pages)):
                        page = reader.pages[page_num]
                        content.append(page.extract_text())
                    return '\n'.join(content)
                else:
                    return "需要安装PyPDF2库来处理PDF文件"
            
            else:
                return "不支持的文件类型"
                
        except Exception as e:
            return f"提取文件内容时出错: {str(e)}"
    
    def perform_compliance_check(self, contract_content):
        """
        执行合同合规检查的具体逻辑
        调用智能体进行合规检查
        
        Args:
            contract_content: 合同内容
            
        Returns:
            合规检查结果字典
        """
        try:
            # 初始化智能体
            agent = RentalContractAgent()
            
            # 分析合同
            analysis_result = agent.analyze_contract(contract_content)
            
            # 如果分析成功，返回完整结果；否则返回错误信息
            if analysis_result.get("status") == "success":
                # 生成摘要用于显示
                summary = agent.generate_summary(analysis_result)
                analysis_result["summary"] = summary
                return analysis_result
            else:
                return analysis_result
            
        except Exception as e:
            return {
                "status": "error",
                "error": f"合规检查过程中发生错误: {str(e)}"
            }