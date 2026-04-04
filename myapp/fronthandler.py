from django.shortcuts import render

def home(request):
    """首页"""
    return render(request, 'myapp/index.html')

def create(request):
    """信息录入页面"""
    return render(request, 'myapp/create.html')




def check(request):
    """合规检查页面"""
    return render(request, 'myapp/check.html')

def history(request):
    """历史记录页面"""
    return render(request, 'myapp/history.html')

def profile(request):
    """个人中心页面"""
    return render(request, 'myapp/profile.html')
