import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from ..models import Contract


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class ContractView(View):
    """合同管理视图"""
    
    def get(self, request, contract_id=None):
        """获取合同列表或合同详情"""
        if contract_id:
            # 获取单个合同详情
            try:
                contract = Contract.objects.get(id=contract_id, user=request.user)
                return JsonResponse({
                    'code': 200,
                    'message': '获取成功',
                    'data': {
                        'id': str(contract.id),
                        'title': contract.title,
                        'content': contract.content,
                        'status': contract.status,
                        'created_at': contract.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'updated_at': contract.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                    }
                })
            except Contract.DoesNotExist:
                return JsonResponse({
                    'code': 404,
                    'message': '合同不存在'
                }, status=404)
        else:
            # 获取合同列表
            contracts = Contract.objects.filter(user=request.user).order_by('-created_at')
            contract_list = []
            for contract in contracts:
                contract_list.append({
                    'id': str(contract.id),
                    'title': contract.title,
                    'status': contract.status,
                    'created_at': contract.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': contract.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            return JsonResponse({
                'code': 200,
                'message': '获取成功',
                'data': {
                    'contracts': contract_list
                }
            })
    
    def post(self, request):
        """创建合同"""
        try:
            data = json.loads(request.body)
            title = data.get('title', '租房合同')
            content = data.get('content', '')
            status = data.get('status', 'draft')
            
            # 创建合同
            contract = Contract.objects.create(
                user=request.user,
                title=title,
                content=content,
                status=status
            )
            
            return JsonResponse({
                'code': 200,
                'message': '创建成功',
                'data': {
                    'id': str(contract.id),
                    'title': contract.title,
                    'status': contract.status
                }
            })
        except json.JSONDecodeError:
            return JsonResponse({
                'code': 400,
                'message': '无效的JSON数据'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'创建失败: {str(e)}'
            }, status=500)
    
    def put(self, request, contract_id):
        """更新合同"""
        try:
            contract = Contract.objects.get(id=contract_id, user=request.user)
            data = json.loads(request.body)
            
            # 更新合同字段
            if 'title' in data:
                contract.title = data['title']
            if 'content' in data:
                contract.content = data['content']
            if 'status' in data:
                contract.status = data['status']
            
            contract.save()
            
            return JsonResponse({
                'code': 200,
                'message': '更新成功',
                'data': {
                    'id': str(contract.id),
                    'title': contract.title,
                    'status': contract.status
                }
            })
        except Contract.DoesNotExist:
            return JsonResponse({
                'code': 404,
                'message': '合同不存在'
            }, status=404)
        except json.JSONDecodeError:
            return JsonResponse({
                'code': 400,
                'message': '无效的JSON数据'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'更新失败: {str(e)}'
            }, status=500)
    
    def delete(self, request, contract_id):
        """删除合同"""
        try:
            contract = Contract.objects.get(id=contract_id, user=request.user)
            contract.delete()
            return JsonResponse({
                'code': 200,
                'message': '删除成功'
            })
        except Contract.DoesNotExist:
            return JsonResponse({
                'code': 404,
                'message': '合同不存在'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'删除失败: {str(e)}'
            }, status=500)