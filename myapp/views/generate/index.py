from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema,OpenApiParameter,OpenApiExample,OpenApiRequest
from myapp.views.generate.ragservice.rag_service import get_rag
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
        rag = get_rag()
        return Response(data = rag.query(demand))
    