from django.db import models
from django.contrib.auth.models import User
import uuid
import json


class UserProfile(models.Model):
    """用户扩展信息模型"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="手机号")
    avatar = models.TextField(blank=True, null=True, verbose_name="头像(base64)")
    
    # 用户使用统计
    total_contracts_generated = models.IntegerField(default=0, verbose_name="生成合同总数")
    total_contracts_checked = models.IntegerField(default=0, verbose_name="检查合同总数")
    last_activity_at = models.DateTimeField(auto_now=True, verbose_name="最后活动时间")
    first_used_at = models.DateTimeField(auto_now_add=True, verbose_name="首次使用时间")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'user_profiles'
        verbose_name = '用户扩展信息'
        verbose_name_plural = verbose_name
    
    def increment_contract_generated(self):
        """增加合同生成计数"""
        self.total_contracts_generated += 1
        self.save(update_fields=['total_contracts_generated', 'last_activity_at', 'updated_at'])
    
    def increment_contract_checked(self):
        """增加合同检查计数"""
        self.total_contracts_checked += 1
        self.save(update_fields=['total_contracts_checked', 'last_activity_at', 'updated_at'])
    
    def get_stats_dict(self):
        """获取统计数据字典"""
        return {
            'totalContracts': self.total_contracts_generated,
            'checkedContracts': self.total_contracts_checked,
            'lastActivityAt': self.last_activity_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_activity_at else None,
            'firstUsedAt': self.first_used_at.strftime('%Y-%m-%d %H:%M:%S') if self.first_used_at else None
        }


class Contract(models.Model):
    """合同模型"""
    CONTRACT_STATUS_CHOICES = [
        ('draft', '草稿'),
        ('generated', '已生成'),
        ('checked', '已审查'),
        ('modified', '已修改'),
        ('final', '最终版'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contracts', verbose_name="用户")
    title = models.CharField(max_length=200, verbose_name="合同标题")
    
    # 合同内容（直接存储文本）
    content = models.TextField(blank=True, null=True, verbose_name="合同内容")
    
    # 状态
    status = models.CharField(max_length=20, choices=CONTRACT_STATUS_CHOICES, default='draft', verbose_name="状态")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'contracts'
        verbose_name = '合同'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']





class ContractTemplate(models.Model):
    """合同模板模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, verbose_name="模板名称")
    description = models.TextField(blank=True, null=True, verbose_name="模板描述")
    
    # 模板内容
    content = models.TextField(verbose_name="模板内容")
    
    # 模板类型
    template_type = models.CharField(max_length=50, default='rental', verbose_name="模板类型")
    
    # 是否启用
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    
    # 使用次数
    usage_count = models.IntegerField(default=0, verbose_name="使用次数")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'contract_templates'
        verbose_name = '合同模板'
        verbose_name_plural = verbose_name


class LegalKnowledge(models.Model):
    """法律知识库模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="内容")
    
    # 法律类型
    law_type = models.CharField(max_length=50, verbose_name="法律类型")
    
    # 地区（如果有）
    region = models.CharField(max_length=100, blank=True, null=True, verbose_name="适用地区")
    
    # 向量ID（用于Chroma检索）
    vector_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="向量ID")
    
    # 是否启用
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'legal_knowledge'
        verbose_name = '法律知识'
        verbose_name_plural = verbose_name


class CheckRule(models.Model):
    """合规检查规则模型"""
    RULE_TYPE_CHOICES = [
        ('required', '必填项'),
        ('forbidden', '禁止项'),
        ('numeric', '数值检查'),
        ('format', '格式检查'),
        ('logic', '逻辑检查'),
    ]
    
    SEVERITY_CHOICES = [
        ('high', '高'),
        ('medium', '中'),
        ('low', '低'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_id = models.CharField(max_length=20, unique=True, verbose_name="规则ID")
    name = models.CharField(max_length=100, verbose_name="规则名称")
    description = models.TextField(verbose_name="规则描述")
    
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES, verbose_name="规则类型")
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, verbose_name="严重等级")
    
    # 规则配置（JSON格式）
    rule_config = models.JSONField(default=dict, verbose_name="规则配置")
    
    # 关键词（用于条款定位）
    keywords = models.JSONField(default=list, verbose_name="关键词")
    
    # 是否启用
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'check_rules'
        verbose_name = '检查规则'
        verbose_name_plural = verbose_name



