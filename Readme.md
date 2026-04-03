# Python 模块导入机制说明

## 核心概念

1. **谁把目录加入 sys.path？**  
   不是 `manage.py`，而是 **Python 解释器**。运行 `python manage.py` 时，Python 会自动将「脚本所在目录」（即项目根目录）加入 `sys.path[0]`。

2. **导入如何查找模块？**  
   Python 在 `sys.path` 中的每个目录下查找对应的包/模块，按顺序遍历，找到即停止。**导入路径与当前文件所在位置无关**，只与 `sys.path` 中的搜索根有关。

3. **"根目录"的含义**  
   `sys.path` 中的每个目录都是一个「搜索根」。Python 在这些根下查找顶层包名（如 `myapp`），再按导入路径逐级查找子模块。项目根目录只是其中一个搜索根。

---

## 查找流程

```
from myapp.fronthandler import home
```

1. 依次遍历 `sys.path` 中的目录；
2. 在某个目录下查找包 `myapp`（目录且含 `__init__.py` 或符合包规则）；
3. 找到后，在 `myapp` 中查找 `fronthandler` 模块；
4. 从 `fronthandler` 中取出 `home`。

---

## 本项目的目录结构

```
mysite/                    ← 项目根，自动加入 sys.path
├── manage.py
├── myapp/                 ← 顶层包，可直接 from myapp.xxx import
│   ├── __init__.py
│   ├── fronthandler.py
│   └── ...
└── mysite/                ← 顶层包，可直接 from mysite.xxx import
    ├── urls.py
    └── settings.py
```

`myapp` 与 `mysite` 同为项目根下的顶层包，因此可以互相导入，无需「退回上一级」。

---

## 常见误解澄清

| 误解 | 实际情况 |
|------|----------|
| 导入是相对于当前文件的 | 导入是相对于 `sys.path` 中的目录，与当前文件无关 |
| 需要「退回上一级」才能导入兄弟包 | 不需要，只要项目根在 sys.path 中即可 |
| manage.py 负责把目录加入 sys.path | Python 解释器自动完成，与 manage.py 无关 |

---

# Django 模板笔记

## 核心要点

- **`render(request, 'myapp/index.html')`** 中的 `'myapp/index.html'` 是**模板名**，不是文件系统路径。
- 模板查找由 **TEMPLATES** 配置决定，模板名相对于 `DIRS` 和 app 的 `templates/` 目录。

## 查找顺序

1. **DIRS**：在 `TEMPLATES[0]['DIRS']` 中的每个目录下查找；
2. **APP_DIRS**：`APP_DIRS: True` 时，在每个已安装 app 的 `templates/` 下查找。

---

## Django AppConfig.ready() 调用说明

- **何时调用**：Django 在应用注册并完成应用注册表（app registry）准备后，会自动调用每个已启用应用对应的 `AppConfig.ready()` 方法。每个运行中的进程会各自调用一次。
- **确保自定义 AppConfig 生效**：在 `INSTALLED_APPS` 中使用 `myapp.apps.MyAppConfig` 的形式引用你的 AppConfig；否则 Django 会使用默认生成的 `AppConfig`，你的 `ready()` 可能不会被执行。
- **常见用途**：在 `ready()` 中注册信号处理器（signals）、导入并初始化一次性运行的模块、或绑定第三方库的钩子。示例：

```python
from django.apps import AppConfig

class MyAppConfig(AppConfig):
        name = 'myapp'

        def ready(self):
                # 在 ready() 中导入信号模块以注册信号处理器
                from . import signals

                # 或者做一次性初始化（避免副作用）
                # init_things()
```

- **注意事项 / 最佳实践**：
    - 避免在 `ready()` 中执行可能修改数据库模式或依赖迁移状态的操作（如创建表、运行复杂的迁移逻辑）。
    - 尽量不要在模块顶层直接导入大量模型或执行重操作，优先在 `ready()` 内部做按需导入以避免循环导入或在启动时触发意外访问。
    - `runserver` 的自动重载器会在主/子进程中多次调用 `ready()`（即每个进程各自调用一次），因此 `ready()` 中的操作应为幂等或能够安全重复执行。
    - 在测试环境中，`ready()` 也会被调用；若 `ready()` 做了与外部服务的连接或自定义初始化，建议在条件下跳过或使用配置开关控制。

- **调试建议**：可以在 `ready()` 中临时加入日志或打印以确认它是否被调用，例如 `import logging; logging.getLogger(__name__).info('myapp ready')`。

---
## 推荐目录结构

```
myapp/
└── templates/
    └── myapp/           ← 用 app 名再包一层，避免同名冲突
        └── index.html
```

模板名：`'myapp/index.html'`

## 与 Python 导入对比

| 机制 | 查找依据 | 配置 |
|------|----------|------|
| Python 导入 | sys.path | 解释器自动 |
| Django 模板 | TEMPLATES (DIRS + APP_DIRS) | settings.py |

---

# rest_framework.response.Response 笔记

```python
from rest_framework.response import Response
```

- **作用**：DRF 的 JSON 响应类，自动序列化数据并设置 `Content-Type`。
- **用法**：`Response(data, status=200, headers={...})`
- **注意**：`data` 必须是可序列化类型（dict、list 等），不能直接传自定义对象。
- **常用状态码**：`201` 创建成功、`204` 删除成功无内容、`400` 参数错误。

---

# Django ALLOWED_HOSTS 笔记

## 核心作用

`ALLOWED_HOSTS` 是 Django 的安全配置，用来限制**哪些 Host 头（域名/IP）可以访问你的应用**。

## 工作原理

HTTP 请求会携带 `Host` 头（如 `Host: example.com`），Django 会检查该值是否在 `ALLOWED_HOSTS` 中。若不在，直接返回 **400 Bad Request**，不继续处理请求。

## 为什么需要它？

防止 **Host Header 攻击**，例如：
- 缓存投毒：攻击者伪造 Host 头，诱导应用缓存恶意内容
- 密码重置劫持：在重置链接中注入恶意域名
- 跨站请求伪造：利用 Host 头绕过部分安全检查

## 配置建议

| 环境 | 示例配置 |
|------|----------|
| 本地开发 | `['localhost', '127.0.0.1']` |
| 带端口访问 | `['localhost', '127.0.0.1', '[::1]']` |
| 生产环境 | `['example.com', 'www.example.com', 'your-server-ip']` |

## 小结

- **开发时**：`['*']` 或 `['localhost', '127.0.0.1']` 均可
- **上线时**：应改为明确的域名/IP，避免使用 `['*']`，以降低 Host 头攻击风险

---

# Swagger + DRF 集成与注解使用

## 一、安装与配置

### 1. 安装 drf-spectacular

```bash
pip install drf-spectacular
```

注意：包名为 `drf-spectacular`（spectacular），不是 `drf-sectacular`。

### 2. 配置 settings.py

在 `INSTALLED_APPS` 中添加：

```python
INSTALLED_APPS = [
    # ... 其他 app
    'rest_framework',
    'drf_spectacular',
]

# DRF + Swagger 配置
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
```

### 3. 配置 urls.py

添加 Swagger 路由：

```python
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # ... 其他路由
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
```

## 二、访问 Swagger 文档

启动项目后访问：

| 地址 | 说明 |
|------|------|
| `http://localhost:8000/api/docs/` | Swagger UI 文档页面（可浏览、调试接口） |
| `http://localhost:8000/api/schema/` | OpenAPI Schema（JSON/YAML） |

## 三、使用注解增强文档

只有 DRF 视图（`APIView`、`ViewSet`、`@api_view`）会自动出现在 Swagger 中。可通过 `extend_schema` 等注解补充说明。

### 1. 类视图注解

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

@extend_schema(
    summary="获取用户列表",
    description="返回系统中所有用户的简要信息，支持分页。",
    tags=["用户管理"],
)
class UserHandler(APIView):
    def get(self, request):
        return Response({"users": []})
```

### 2. 方法注解（多 HTTP 方法）

```python
@extend_schema(tags=["用户管理"])
class UserDetailView(APIView):
    @extend_schema(summary="获取单个用户", description="根据 ID 返回用户详情")
    def get(self, request, pk):
        return Response({})

    @extend_schema(summary="更新用户", description="根据 ID 更新用户信息")
    def put(self, request, pk):
        return Response({})

    @extend_schema(summary="删除用户")
    def delete(self, request, pk):
        return Response(status=204)
```

### 3. 参数与响应注解

```python
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

@extend_schema(
    summary="搜索用户",
    parameters=[
        OpenApiParameter(name='keyword', description='搜索关键词', required=True, type=str),
        OpenApiParameter(name='page', description='页码', required=False, type=int),
    ],
    examples=[
        OpenApiExample('示例请求', value={'keyword': '张三', 'page': 1}),
    ],
)
def get(self, request):
    return Response({})
```

### 4. 使用 @extend_schema_view（ViewSet）

```python
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema_view, extend_schema

@extend_schema_view(
    list=extend_schema(summary="列表", tags=["商品"]),
    retrieve=extend_schema(summary="详情", tags=["商品"]),
    create=extend_schema(summary="创建", tags=["商品"]),
    update=extend_schema(summary="更新", tags=["商品"]),
    destroy=extend_schema(summary="删除", tags=["商品"]),
)
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
```

### 5. 常用注解参数说明

| 参数 | 说明 |
|------|------|
| `summary` | 接口简短标题 |
| `description` | 详细说明 |
| `tags` | 分组标签，用于在 Swagger 中归类 |
| `parameters` | 请求参数（OpenApiParameter） |
| `responses` | 响应示例（OpenApiResponse） |
| `examples` | 示例数据（OpenApiExample） |

## 四、注意事项

- **仅 DRF 视图会出现在 Swagger 中**：普通 Django 视图（`View`、FBV、`TemplateView`）不会自动被扫描。
- **Serializer 会自动推断**：若使用 `serializer_class` 或 `get_serializer_class`，请求/响应结构会自动生成。
- 生产环境建议通过 `DEBUG` 或权限控制限制 `/api/docs/` 的访问。

---

# Django 原生 SQL 查询笔记

## 一、为什么用原生 SQL？

- ORM 难以表达的复杂 JOIN、子查询、统计逻辑
- 对性能有极致要求的场景
- 遗留系统或非 Django 风格的数据库结构

优先考虑 ORM，无法满足时再使用原生 SQL。

## 二、connection.cursor（底层 API）

适合**任意 SQL**，返回原始行数据（元组或字典）。

### 1. 基本用法

```python
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT id, title FROM myapp_book WHERE author_id = %s", [1])
    rows = cursor.fetchall()  # [(1, '书名1'), (2, '书名2')]
```

### 2. 按列名返回（DictCursor）

```python
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT id, title FROM myapp_book WHERE id = %s", [1])
    columns = [col[0] for col in cursor.description]
    row = dict(zip(columns, cursor.fetchone()))
    # {'id': 1, 'title': '书名1'}
```

### 3. 参数化查询（防 SQL 注入）

**必须**用 `%s` 占位符，不要用字符串拼接：

```python
# ✅ 正确：参数化
cursor.execute("SELECT * FROM myapp_book WHERE title = %s", [user_input])

# ❌ 错误：字符串拼接，存在 SQL 注入风险
cursor.execute(f"SELECT * FROM myapp_book WHERE title = '{user_input}'")
```

不同数据库的占位符由 Django 自动处理（MySQL 用 `%s`，SQLite 用 `?` 等）。

### 4. 多表 JOIN 示例

```python
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT b.id, b.title, a.name as author_name
        FROM myapp_book b
        JOIN myapp_author a ON b.author_id = a.id
        WHERE a.name = %s
    """, ['张三'])
    rows = cursor.fetchall()
```

### 5. 执行 INSERT / UPDATE / DELETE

```python
with connection.cursor() as cursor:
    cursor.execute(
        "INSERT INTO myapp_book (title, author_id) VALUES (%s, %s)",
        ['新书', 1]
    )
    # 获取自增 ID（MySQL）
    new_id = cursor.lastrowid

    cursor.execute("UPDATE myapp_book SET title = %s WHERE id = %s", ['新标题', 1])
    cursor.execute("DELETE FROM myapp_book WHERE id = %s", [1])
```

## 三、Model.objects.raw（映射到模型）

`raw()` 执行 SELECT 并**映射到模型实例**，适合简单原生查询。

### 1. 基本用法

```python
from myapp.models import Book

books = Book.objects.raw("SELECT * FROM myapp_book WHERE author_id = %s", [1])
for book in books:
    print(book.id, book.title)  # book 是 Book 实例
```

### 2. 表名与主键

- 主表必须包含模型的主键字段（通常为 `id`）
- 表名通常为 `app_label_modelname`（如 `myapp_book`）

```python
# 主键必须在 SELECT 中
Book.objects.raw("SELECT id, title, author_id FROM myapp_book")
```

### 3. 添加计算列（需设 pk）

```python
books = Book.objects.raw("""
    SELECT b.*, a.name as author_name
    FROM myapp_book b
    JOIN myapp_author a ON b.author_id = a.id
""")
for book in books:
    print(book.author_name)  # 额外列可直接访问
```

## 四、多数据库

```python
from django.db import connections

# 指定数据库
with connections['other_db'].cursor() as cursor:
    cursor.execute("SELECT * FROM other_table")
```

## 五、事务中的原生 SQL

```python
from django.db import transaction

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO myapp_book ...")
        cursor.execute("UPDATE myapp_author SET ...")
    # 任一失败则整体回滚
```

## 六、常用方法速查

| 方法 | 说明 |
|------|------|
| `cursor.execute(sql, params)` | 执行 SQL |
| `cursor.fetchone()` | 取一行 |
| `cursor.fetchall()` | 取所有行 |
| `cursor.fetchmany(size)` | 取指定行数 |
| `cursor.rowcount` | 影响行数 |
| `cursor.lastrowid` | 最后插入的自增 ID（部分数据库） |
| `cursor.description` | 列信息（名称、类型等） |

## 七、安全与性能建议

1. **参数化**：始终用 `%s` + 参数列表，避免字符串拼接。
2. **权限**：生产环境限制可执行 SQL 的权限。
3. **索引**：复杂查询确保 WHERE、JOIN 字段有索引。
4. **日志**：对高危 SQL 做审计和日志记录。
5. **优先 ORM**：能用 ORM 实现的尽量用 ORM，便于维护和迁移。

---

# Django 事务机制笔记

## 一、transaction.atomic()（上下文管理器）

把一段代码包在一个事务里，正常结束时提交，异常时回滚：

```python
from django.db import transaction
from django.db.models import F

def transfer_money(from_id, to_id, amount):
    with transaction.atomic():
        Account.objects.filter(id=from_id).update(balance=F('balance') - amount)
        Account.objects.filter(id=to_id).update(balance=F('balance') + amount)
```

- 块内所有操作要么全部提交，要么全部回滚。
- 若块内抛出异常，整个事务回滚。

## 二、@transaction.atomic 装饰器

将整个函数体视为一个事务：

```python
from django.db import transaction

@transaction.atomic
def create_order_with_items(order_data, items):
    order = Order.objects.create(**order_data)
    for item in items:
        OrderItem.objects.create(order=order, **item)
```

- 函数正常返回 → 事务提交。
- 函数抛出异常 → 事务回滚。

## 三、嵌套事务与保存点

`atomic()` 可以嵌套，内层会创建**保存点（savepoint）**，回滚时只回滚到保存点，不影响外层：

```python
with transaction.atomic():  # 外层事务
    Order.objects.create(...)
    try:
        with transaction.atomic():  # 内层 = 保存点
            OrderItem.objects.create(...)
            raise ValueError("测试")  # 只回滚到保存点
    except ValueError:
        pass
    # 外层事务继续，Order 已创建
```

手动使用保存点：

```python
with transaction.atomic():
    order = Order.objects.create(...)
    sid = transaction.savepoint()  # 创建保存点
    try:
        OrderItem.objects.create(...)
        raise ValueError("出错")
    except ValueError:
        transaction.savepoint_rollback(sid)  # 只回滚到保存点
    # order 已提交，OrderItem 被回滚
```

---

# Django ORM 返回值类型笔记（QuerySet vs 实例）

## 一、返回 QuerySet 的方法

以下方法返回 **QuerySet**，支持链式调用，且是**惰性求值**（执行 SQL 时才真正查询）：

| 方法 | 说明 |
|------|------|
| `Model.objects.all()` | 全部记录 |
| `Model.objects.filter(...)` | 过滤 |
| `Model.objects.exclude(...)` | 排除 |
| `Model.objects.order_by(...)` | 排序 |
| `Model.objects.reverse()` | 反向排序 |
| `Model.objects.distinct()` | 去重 |
| `Model.objects.values(...)` | 返回字典列表的 QuerySet |
| `Model.objects.values_list(...)` | 返回元组列表的 QuerySet |
| `Model.objects.select_related(...)` | 预取外键 |
| `Model.objects.prefetch_related(...)` | 预取反向/多对多 |
| `Model.objects.annotate(...)` | 聚合注解 |
| `Model.objects.none()` | 空 QuerySet |

```python
qs = User.objects.filter(role='admin').order_by('-id')  # 仍是 QuerySet
for user in qs:  # 遍历时才执行 SQL
    print(user.username)
```

## 二、返回模型实例的方法

| 方法 | 返回 | 无数据时 |
|------|------|----------|
| `.get(...)` | 单个实例 | 抛 `DoesNotExist` 或 `MultipleObjectsReturned` |
| `.first()` | 单个实例或 None | `None` |
| `.last()` | 单个实例或 None | `None` |
| `queryset[0]` | 单个实例 | 抛 `IndexError` |

| `Model.objects.create(...)` | 新建的实例 | - |

```python
user = User.objects.get(pk=1)        # 实例
user = User.objects.filter(pk=1).first()  # 实例或 None
```

## 三、返回其他类型

| 方法 | 返回类型 | 说明 |
|------|----------|------|
| `.exists()` | `bool` | 是否存在 |
| `.count()` | `int` | 记录数 |
| `.update(...)` | `int` | 更新的行数 |
| `.delete()` | `(int, dict)` | 删除的行数及明细 |
| `.aggregate(...)` | `dict` | 聚合结果 |
| `.get_or_create(...)` | `(instance, bool)` | 实例 + 是否新建 |
| `.update_or_create(...)` | `(instance, bool)` | 实例 + 是否新建 |
| `.in_bulk([id1, id2])` | `dict` | `{id: instance}` |

## 四、从 QuerySet 取实例

```python
qs = User.objects.filter(role='admin')

# 方式 1：取唯一一条
user = qs.get()   # 必须恰好 1 条

# 方式 2：取第一条（推荐，无则 None）
user = qs.first()

# 方式 3：索引
user = qs[0]      # 无则 IndexError

# 方式 4：遍历
for user in qs:
    ...
```

## 五、总结

- **QuerySet**：可链式、惰性、可迭代；`filter`、`all`、`order_by` 等返回。
- **实例**：`get`、`first`、`last`、`create`、索引 `[0]` 等返回。
- **其他**：`count`、`exists`、`update`、`delete`、`aggregate` 等返回非 QuerySet 类型。


# Serializer 与 `request.data` 说明

简要要点：
- `drf-spectacular`（Swagger）使用 `extend_schema(request=...)` 的值来生成 POST 请求体的 schema；没有为方法提供 `request` 时，文档生成器倾向于把参数当作 query/path 参数处理，导致 Swagger UI 在尝试时看起来像 GET 请求。
- 使用 `Serializer` 可以明确声明请求体字段（字段名、类型、是否必需），从而让 Swagger 渲染请求体表单并正确发送 POST body。
- `OpenApiParameter` 主要用于描述 query/path/header 参数，而不是 request body。

关于 `request.POST` 与 `request.data` 的区别：

- `request.POST`（Django 原生 `HttpRequest`）：
    - 只在 `Content-Type: application/x-www-form-urlencoded` 或 `multipart/form-data`（浏览器表单）时包含解析后的数据；类型是 `QueryDict`。
    - 对 `application/json` 请求体通常为空，需手动使用 `request.body` 并解析 JSON。
    - 仅适用于 HTTP POST（不会包含 PUT/PATCH 的 body）。

- `request.data`（DRF 的 `Request`）：
    - 推荐用于 DRF 的 `APIView`/`ViewSet`，会根据 `Content-Type` 自动解析 JSON、表单、multipart 等。
    - 支持 POST/PUT/PATCH 等方法，能直接与序列化器（Serializer）协作。
    - 更适合用于 API 场景，且在 Swagger 中配合 `Serializer` 会有更好的文档展示。

示例：在视图中声明 Serializer 并让 Swagger 渲染 POST body

```python
from rest_framework import serializers

class GenerateSerializer(serializers.Serializer):
        question = serializers.CharField(required=True)

@extend_schema(request=GenerateSerializer)
def post(self, request):
        question = request.data.get('question')
        # ...
```

实用建议：在使用 DRF 编写 API 时，统一使用 `request.data` 并为重要的输入定义 `Serializer`，这样既能获得自动校验，也能让文档工具（如 drf-spectacular）生成正确的请求体表单。

---

# RAG 缓存机制说明（`myapp/views/generate/ragservice/rag_service.py`）

这里的目标很简单：**降低平均响应时间**。RAG 的慢点通常来自两类网络调用：

- **检索阶段**：把问题做 embedding + 向量库近邻搜索（Chroma）
- **生成阶段**：把“上下文 + 问题”发给大模型生成答案

为了让“重复提问 / 换个说法再问”也更快，`RAGService.query()` 做了 **两级缓存**，并提供可调开关。

## 两级缓存是怎么工作的

### 1）精确缓存（Exact Cache）

- **key**：`query_text`（对 `demand` 做了 jieba 分词后的字符串）
- **存什么**：检索得到的 `source_documents`
- **何时命中**：两次问题分词结果**完全一致**（比如用户重复问同一句）
- **收益**：命中时几乎 0 成本跳过检索

### 2）语义缓存（Semantic Cache，解决“相似问法”）

- **思路**：对 `query_text` 做 embedding，和历史问题的 embedding 计算**余弦相似度**
- **何时命中**：相似度 \(\ge\) `RAG_SEMANTIC_CACHE_THRESHOLD`（默认 0.92）
- **命中后做什么**：
  - 默认模式 `docs`：**复用历史检索到的 docs**，但仍用“当前问题”重新生成答案（更稳妥）
  - 激进模式 `answer`：直接复用历史答案（最快，但“相似不等价”的问法可能会答偏）
- **收益**：命中时可以跳过向量库检索（经常是慢点之一）

## 为什么要“先检索再生成”

原来 `RetrievalQA` 把流程封装成黑盒：检索 + 生成揉在一次调用里，不方便做缓存与细粒度计时。

现在 `query()` 拆成了：

- 先拿到 docs（可命中缓存）
- 再拼上下文并调用 LLM（并对上下文做长度限制）

这样就能做到：**缓存命中时减少检索成本**，同时通过限制上下文长度减少 LLM 的 token 处理时间。

## 可用的环境变量（调参入口）

- **`RAG_MAX_CONTEXT_CHARS`**：上下文最大字符数（默认 4500）。越小越快，但可能降低准确率
- **`RAG_RETRIEVAL_CACHE_SIZE`**：精确缓存容量（默认 128）
- **`RAG_SEMANTIC_CACHE_SIZE`**：语义缓存容量（默认 256）
- **`RAG_SEMANTIC_CACHE_THRESHOLD`**：语义命中阈值（默认 0.92）
- **`RAG_SEMANTIC_CACHE_MODE`**：`docs`（默认）或 `answer`

## 推荐默认配置（用户体验优先）

- **先用稳妥模式**：
  - `RAG_SEMANTIC_CACHE_MODE=docs`
  - `RAG_SEMANTIC_CACHE_THRESHOLD=0.92`（命中更严格，减少“答偏”）
  - `RAG_MAX_CONTEXT_CHARS=3000~4500`（结合你的知识库大小调整）

如果你特别追求速度、且问法非常固定，可以再试：

- `RAG_SEMANTIC_CACHE_MODE=answer`

但要明确：它是用“相似问法直接复用旧答案”换速度，适合 FAQ 类场景，不适合需要严格逐字对齐上下文的场景。