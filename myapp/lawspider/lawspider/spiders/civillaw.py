import scrapy
import sys
import os
import asyncio
import re

# 添加Django项目路径以便导入模型
sys.path.insert(0, '/home/jxh/GraduateProject')
sys.path.insert(0, '/home/jxh/GraduateProject/mysite')

# 确保使用正确的设置模块
os.environ['DJANGO_SETTINGS_MODULE'] = 'mysite.settings'

# 导入Django并设置
import django
from django.conf import settings
from asgiref.sync import sync_to_async

# 确保设置已经配置
if not settings.configured:
    django.setup()

from myapp.models import LegalClause


class CivillawSpider(scrapy.Spider):
    name = "civillaw"
    allowed_domains = ["court.gov.cn"]
    start_urls = ["https://www.court.gov.cn/zixun/xiangqing/233181.html"]

    async def parse(self, response):
        # 提取所有段落
        all_paragraphs = response.xpath('//p')
        
        # 过滤出具体的条款（使用正则表达式确保只匹配"第X条"格式）
        clause_nodes = []
        for para in all_paragraphs:
            text = para.xpath('text()').get()
            if text:
                text = text.strip()
                # 使用正则表达式匹配"第X条"格式
                if re.match(r'^第[一二三四五六七八九十百千\d]+条', text):
                    clause_nodes.append(para)
        
        self.logger.info(f"找到 {len(clause_nodes)} 个具体条款")
        
        for i, clause_node in enumerate(clause_nodes):
            # 提取标题（只保留"第X条"格式）
            title_text = clause_node.xpath('text()').get().strip()
            # 使用正则表达式提取"第X条"部分
            title_match = re.match(r'^第[一二三四五六七八九十百千\d]+条', title_text)
            if title_match:
                title = title_match.group(0)
            else:
                title = title_text  # 如果正则匹配失败，使用原始文本
            
            # 提取内容：从当前条款节点开始，收集内容直到下一个条款节点
            content_parts = []
            current_node = clause_node.xpath('following-sibling::p[1]')
            
            while current_node:
                # 提取当前节点文本
                current_text = current_node.xpath('text()').get()
                if not current_text:
                    current_node = current_node.xpath('following-sibling::p[1]')
                    continue
                
                current_text = current_text.strip()
                
                # 检查是否是下一个条款
                if re.match(r'^第[一二三四五六七八九十百千\d]+条', current_text):
                    break
                
                # 检查是否是章节标题（包含"编"、"章"或"节"）
                if '编' in current_text or '章' in current_text or '节' in current_text:
                    # 跳过章节标题
                    current_node = current_node.xpath('following-sibling::p[1]')
                    continue
                
                # 提取内容
                content_parts.append(current_text)
                
                # 移动到下一个兄弟节点
                current_node = current_node.xpath('following-sibling::p[1]')
            
            # 合并内容
            content = ' '.join(content_parts)
            
            # 保存到数据库
            if title and content:
                try:
                    # 使用sync_to_async包装数据库操作
                    await sync_to_async(LegalClause.objects.create)(
                        title=title,
                        content=content,
                        type="民法",
                        area="国家"
                    )
                    self.logger.info(f"保存条款: {title}")
                except Exception as e:
                    self.logger.error(f"保存条款失败: {title}, 错误: {str(e)}")