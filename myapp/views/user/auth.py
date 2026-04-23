import json
import os
from django.http import JsonResponse
from django.views import View
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import base64
from ...models import Contract


@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(View):
    """用户注册视图"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
            email = data.get('email', '')
            
            # 验证必填字段
            if not username or not password:
                return JsonResponse({
                    'code': 400,
                    'message': '用户名和密码不能为空'
                }, status=400)
            
            # 检查用户名是否已存在
            if User.objects.filter(username=username).exists():
                return JsonResponse({
                    'code': 400,
                    'message': '用户名已存在'
                }, status=400)
            
            # 创建用户
            user = User.objects.create(
                username=username,
                password=make_password(password),
                email=email
            )
            
            # 创建用户扩展信息
            from ...models import UserProfile
            UserProfile.objects.create(user=user)
            
            return JsonResponse({
                'code': 200,
                'message': '注册成功',
                'data': {
                    'user_id': str(user.id),
                    'username': user.username,
                    'email': user.email
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
                'message': f'注册失败: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class LoginView(View):
    """用户登录视图"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
            
            # 验证必填字段
            if not username or not password:
                return JsonResponse({
                    'code': 400,
                    'message': '用户名和密码不能为空'
                }, status=400)
            
            # 认证用户
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                return JsonResponse({
                    'code': 200,
                    'message': '登录成功',
                    'data': {
                        'user_id': str(user.id),
                        'username': user.username,
                        'email': user.email
                    }
                })
            else:
                return JsonResponse({
                    'code': 401,
                    'message': '用户名或密码错误'
                }, status=401)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'code': 400,
                'message': '无效的JSON数据'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'登录失败: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class LogoutView(View):
    """用户登出视图"""
    
    def post(self, request):
        try:
            logout(request)
            return JsonResponse({
                'code': 200,
                'message': '登出成功'
            })
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'登出失败: {str(e)}'
            }, status=500)


class UserProfileView(View):
    """用户信息视图"""
    
    def get(self, request):
        """获取用户信息"""
        if not request.user.is_authenticated:
            return JsonResponse({
                'code': 401,
                'message': '请先登录'
            }, status=401)
        
        user = request.user
        
        # 获取或创建用户扩展信息
        from ...models import UserProfile
        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={}
        )
        
        # 获取统计数据
        stats_data = profile.get_stats_dict()
        
        return JsonResponse({
            'code': 200,
            'message': '获取成功',
            'data': {
                'user_id': str(user.id),
                'username': user.username,
                'email': user.email,
                'avatar': profile.avatar,
                'date_joined': user.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
                'stats': stats_data
            }
        })
    
    def put(self, request):
        """更新用户信息"""
        if not request.user.is_authenticated:
            return JsonResponse({
                'code': 401,
                'message': '请先登录'
            }, status=401)
        
        try:
            user = request.user
            
            # 获取或创建用户扩展信息
            from ...models import UserProfile
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={}
            )
            
            # 处理头像上传（base64格式）
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                # 处理头像
                if 'avatar' in data:
                    profile.avatar = data['avatar']
                    profile.save()
                # 处理其他字段更新
                if 'email' in data:
                    user.email = data['email']
                    user.save()
            
            # 获取最新的用户信息
            from ...models import UserProfile
            profile = UserProfile.objects.get(user=user)
            
            return JsonResponse({
                'code': 200,
                'message': '更新成功',
                'data': {
                    'user_id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'avatar': profile.avatar
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
                'message': f'更新失败: {str(e)}'
            }, status=500)


class CSRFTokenView(View):
    """获取CSRF Token视图"""
    
    def get(self, request):
        token = get_token(request)
        return JsonResponse({
            'code': 200,
            'message': '获取成功',
            'data': {
                'csrf_token': token
            }
        })


@method_decorator(csrf_exempt, name='dispatch')
class UserStatsView(View):
    """用户统计数据视图"""
    
    def post(self, request):
        """增加用户统计数据"""
        if not request.user.is_authenticated:
            return JsonResponse({
                'code': 401,
                'message': '请先登录'
            }, status=401)
        
        try:
            data = json.loads(request.body)
            stat_type = data.get('type')
            
            # 获取或创建用户扩展信息
            from ...models import UserProfile
            profile, created = UserProfile.objects.get_or_create(
                user=request.user,
                defaults={}
            )
            
            # 根据类型更新统计数据
            if stat_type == 'generate':
                profile.increment_contract_generated()
                return JsonResponse({
                    'code': 200,
                    'message': '合同生成计数增加成功'
                })
            elif stat_type == 'check':
                profile.increment_contract_checked()
                return JsonResponse({
                    'code': 200,
                    'message': '合同检查计数增加成功'
                })
            elif stat_type == 'decrement_generate':
                # 减少生成合同计数
                if profile.total_contracts_generated > 0:
                    profile.total_contracts_generated -= 1
                    profile.save(update_fields=['total_contracts_generated', 'last_activity_at', 'updated_at'])
                return JsonResponse({
                    'code': 200,
                    'message': '合同生成计数减少成功'
                })
            elif stat_type == 'decrement_check':
                # 减少检查合同计数
                if profile.total_contracts_checked > 0:
                    profile.total_contracts_checked -= 1
                    profile.save(update_fields=['total_contracts_checked', 'last_activity_at', 'updated_at'])
                return JsonResponse({
                    'code': 200,
                    'message': '合同检查计数减少成功'
                })
            else:
                return JsonResponse({
                    'code': 400,
                    'message': '无效的统计类型'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'code': 400,
                'message': '无效的JSON数据'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'code': 500,
                'message': f'操作失败: {str(e)}'
            }, status=500)