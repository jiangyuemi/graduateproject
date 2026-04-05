"""
RAG 服务 - 使用 LangChain 实现检索增强生成
支持 OpenAI 和 Ollama 两种后端
"""
import os
from pathlib import Path
from typing import Iterable, List, Optional, Dict, Any
import json
import re
import jieba
from collections import OrderedDict
import math

from langchain_community.document_loaders import (
    TextLoader,
    PyPDFLoader,
    DirectoryLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_classic.chains.retrieval_qa.base import RetrievalQA
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI

class RAGService:
    """
    RAG 服务类

    负责：
    - 文档加载与预处理
    - 构建与加载向量索引
    - 基于检索结果进行大模型问答
    """

    #region 初始化与模型构建
    def __init__(
        self,
        persist_dir: str = "./myapp/views/generate/ragservice/chroma_db",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        """
        初始化 RAG 服务

        Args:
            persist_dir: 向量库持久化目录（Chroma 持久化路径）
            chunk_size: 文本切分块大小
            chunk_overlap: 切分块重叠长度
        """

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.persist_dir = persist_dir  
        # 可选的 system prompt，会作为 chat 模式下的 system 消息传递给 LLM
        p = Path(__file__).parent / "system_promot.txt"
        if not p.exists():
            raise FileNotFoundError(f"System prompt 文件不存在: {p}")
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError("读取到的 system prompt 内容为空")
        self.system_prompt = content
        # 嵌入模型：负责将文本编码为向量

               # 原始嵌入器
        base_embeddings = OpenAIEmbeddings(
            model="text-embedding-v4",
            api_key=os.getenv("LLM_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            check_embedding_ctx_length=False,
        )

        # 为防止后端对 batch size 有严格限制（如 10），包装一个小的批调用器
        class BatchedEmbeddings:
            def __init__(self, inner, max_batch: int = 10):
                """对 embeddings 做 batch 封装，避免后端对单次批量大小有限制。"""
                self._inner = inner
                self._max_batch = max_batch

            def embed_documents(self, texts: Iterable[str]):
                """批量计算一组文本的 embedding（自动按 max_batch 分批请求）。"""
                texts = list(texts)
                # 规范化输入：支持 Document、dict 等，取其文本表示
                norm_texts = []
                for t in texts:
                    if hasattr(t, 'page_content'):
                        norm_texts.append(t.page_content)
                    elif isinstance(t, (list, tuple)):
                        # flatten if nested
                        norm_texts.extend([str(x) for x in t])
                    else:
                        norm_texts.append(str(t))
                results = []
                for i in range(0, len(norm_texts), self._max_batch):
                    batch = norm_texts[i : i + self._max_batch]
                    res = self._inner.embed_documents(batch)
                    results.extend(res)
                return results

            def embed_query(self, text: str):
                """计算单条 query embedding；兼容 Document/list 等输入。"""
                # 大多数 embeddings 实现会提供 embed_query；兜底使用 embed_documents
                # 兼容非字符串输入（Document、dict 等）
                if hasattr(text, 'page_content'):
                    q = text.page_content
                elif isinstance(text, (list, tuple)):
                    # join list items
                    q = "\n".join([str(x) for x in text])
                else:
                    q = str(text)

                if hasattr(self._inner, "embed_query"):
                    return self._inner.embed_query(q)
                return self._inner.embed_documents([q])[0]

        self.embeddings = BatchedEmbeddings(base_embeddings, max_batch=20)
        # 大语言模型：负责在检索结果基础上生成自然语言回答
        # 使用阿里云 DashScope 服务，支持 OpenAI 兼容 API
        self.llm = ChatOpenAI(
            model="qwen3.5-plus",  # 可选：qwen-turbo, qwen-plus, qwen-max 等
            api_key=os.getenv("LLM_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        # 向量库与 QA 链在构建索引 / 加载索引后初始化
        self.vectorstore: Optional[VectorStore] = None
        self.qa_chain = None
        self.retriever = None
        self.prompt_obj = None

        # 性能相关：轻量缓存
        # 说明：
        # - 真实耗时主要来自两次网络调用：embedding（检索用）+ LLM 生成
        # - 下面通过“缓存 + 限制上下文 token + 可选复用答案”来减少平均响应时间
        self.max_context_chars = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "4500"))

        # 1) 精确缓存：key 为分词后的 query_text（必须完全一致才命中）
        #    价值：重复提问时避免 retriever/embedding 的开销，命中代价接近 0
        self._retrieval_cache_max = int(os.getenv("RAG_RETRIEVAL_CACHE_SIZE", "128"))
        self._retrieval_cache: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()

        # 2) 语义缓存：对 query 做 embedding，再与历史 query embedding 做余弦相似度匹配。
        #    命中后可跳过向量库检索（通常可省下“向量检索 + embedding”的大头耗时）。
        #
        # mode（通过环境变量 `RAG_SEMANTIC_CACHE_MODE` 控制）：
        # - "docs"（默认，更稳妥）：命中时复用“检索到的 docs”，但仍按当前问题重新生成答案
        # - "answer"（更快，更激进）：命中时直接复用历史答案（相似但不等价的问法可能不严谨）
        self._semantic_cache_mode = os.getenv("RAG_SEMANTIC_CACHE_MODE", "docs").strip().lower()
        self._semantic_cache_threshold = float(os.getenv("RAG_SEMANTIC_CACHE_THRESHOLD", "0.92"))
        self._semantic_cache_max = int(os.getenv("RAG_SEMANTIC_CACHE_SIZE", "256"))
        self._semantic_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    #endregion

    #region 文档加载
    def load_documents(
        self,
        path: str,
        glob: str = "**/*.{pdf,txt,docx,doc}",
        loader_type: str = "auto",
    ) -> List[Document]:
        """
        加载文档为 LangChain `Document` 列表

        Args:
            path: 文件或目录路径
            glob: 目录加载时的文件匹配模式
            loader_type: "auto" | "text" | "pdf" | "directory"

        Returns:
            文档列表
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"路径不存在: {path}")

        # 根据路径类型与后缀自动推断加载器
        if loader_type == "auto":
            if path.is_file():
                suffix = path.suffix.lower()
                if suffix == ".txt":
                    loader_type = "text"
                elif suffix == ".pdf":
                    loader_type = "pdf"
                else:
                    loader_type = "text"  # 未知格式用 TextLoader 尝试
            else:
                loader_type = "directory"

        # 不同类型文件对应的 loader
        loader_map = {
            "text": lambda: TextLoader(str(path), encoding="utf-8"),
            "pdf": lambda: PyPDFLoader(str(path)),
            "directory": lambda: DirectoryLoader(
                str(path),
                glob=glob,
                loader_cls=TextLoader,
                loader_kwargs={"encoding": "utf-8"},
            ),
        }

        # 优先使用指定 loader_type，找不到就回退到 text
        loader = loader_map.get(loader_type, loader_map["text"])()
        return loader.load()
    #endregion

    #region 条款分块
    def split_documents_by_clause(self, documents: List[Document]) -> List[Document]:
        """
        以“第 N 条”作为分块单位，支持阿拉伯数字和中文数字（如“第三百七十三条”）。
        """
        # 匹配类似：第1条、第 12 条、第十三条、第 三百七十三条等
        # 在断点处向前查找下一个“第X条”或文本结尾。
        clause_pattern = re.compile(
            r"(第\s*[0-9零一二三四五六七八九十百千万亿〇○]+\s*条[\s\S]*?)(?=第\s*[0-9零一二三四五六七八九十百千万亿〇○]+\s*条|$)"
        )
        result = []
        for doc in documents:
            text = (doc.page_content or "").strip()
            if not text:
                continue
            matches = list(clause_pattern.finditer(text))
            if matches:
                for m in matches:
                    clause_text = m.group(1).strip()
                    if clause_text:
                        result.append(Document(page_content=clause_text, metadata=doc.metadata or {}))
            else:
                # 未找到“第 N 条”时，退回原文
                result.append(doc)
        return result
    #endregion

    #region jieba分词
    def tokenize_documents_with_jieba(self, documents: List[Document]) -> List[Document]:
        """
        使用jieba对文档进行中文分词，优化向量化效果。
        """
        result = []
        for doc in documents:
            text = doc.page_content or ""
            if text.strip():
                # 使用jieba精确模式分词
                words = jieba.cut(text, cut_all=False)
                # 用空格连接分词结果，便于嵌入模型处理
                tokenized_text = " ".join(words)
                result.append(Document(page_content=tokenized_text, metadata=doc.metadata or {}))
            else:
                result.append(doc)
        return result
    #endregion

    #region 向量索引构建与加载
    def index_documents(
        self,
        documents: List[Document],
        split: bool = True,
        split_by_clause: bool = True,
        use_jieba: bool = True,
    ) -> "RAGService":
        """
        将文档构建为 Chroma 向量索引

        Args:
            documents: 文档列表
            split: 是否先切分文本（长文档建议开启）

        Returns:
            self，支持链式调用
        """
        # 可选：先对文档做分块切分以提高召回效果
        if split:
            if split_by_clause:
                clause_docs = self.split_documents_by_clause(documents)
                # 如果拆出来的条款仍然过长，可再做字符分割
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                    separators=["\n\n", "\n", "。", "！", "？", " ", ""],
                )
                splits = splitter.split_documents(clause_docs)
            else:
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                    separators=["\n\n", "\n", "。", "！", "？", " ", ""],
                )
                splits = splitter.split_documents(documents)
        else:
            splits = documents

        # 可选：使用jieba进行中文分词，优化向量化
        if use_jieba:
            splits = self.tokenize_documents_with_jieba(splits)

        # 创建并持久化 Chroma 向量库
        self.vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=str(self.persist_dir),
        )

        # 构建基于向量库的问答链
        self._build_qa_chain()
        return self
     #endregion

    # region
    def load_index(self) -> "RAGService":
        """
        从已有向量库目录加载 Chroma 索引

        一般用于应用重启后，直接复用之前构建好的向量库。
        """
        self.vectorstore = Chroma(
            persist_directory=str(self.persist_dir),
            embedding_function=self.embeddings,
        )
        self._build_qa_chain()
        return self
        #endregion

    # region
    def _build_qa_chain(self):
        """
        基于当前向量库构建检索增强问答链。

        注意：调用前必须确保 `self.vectorstore` 已经初始化。

        说明：
        - 这里仍然构建 `RetrievalQA` 作为兜底/兼容路径（例如未来需要直接用 chain 调用）
        - `query()` 会优先走“先检索再生成”的路径，以便做缓存、限长与计时
        """
        # 将向量库封装为检索器
        retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 2},  # 只取最相关的一条文档，进一步减少上下文污染
        )
        self.retriever = retriever

        # 自定义 Prompt，引导模型严格基于检索到的上下文回答
        if self.system_prompt:
            # 使用 ChatPromptTemplate，支持 system message
            chat_prompt = ChatPromptTemplate.from_messages([
                ("system", self.system_prompt),
                ("human", "基于以下上下文回答问题。如果上下文中没有相关信息，请说\"根据现有资料无法回答\"。\n\n上下文:\n{context}\n\n问题: {question}"),
            ])
            prompt_obj = chat_prompt
        else:
            prompt_template = (
                "基于以下上下文回答问题。如果上下文中没有相关信息，请说\"根据现有资料无法回答\"。\n\n"
                "上下文:\n{context}\n\n问题: {question}"
            )
            prompt_obj = PromptTemplate(template=prompt_template, input_variables=["context", "question"]) 

        self.prompt_obj = prompt_obj
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            retriever=retriever,
            chain_type='stuff',
            chain_type_kwargs={'prompt': prompt_obj},
            verbose=False,
            return_source_documents=True,
            input_key="question",
        )
    #endregion



    #region 对外问答接口

    # 类型注解和返回值类型注解
    def tokenize_query_with_jieba(self, query: str) -> str:
        """
        对问题做 jieba 分词（用于向量检索）。
        返回带空格分隔的分词文本，可提高中文语义检索效果。
        """
        if not query or not query.strip():
            return query
        tokens = jieba.cut(query, cut_all=False)
        return " ".join(tokens)

    def _cache_get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """精确缓存读取（LRU）。命中时把条目移动到队尾。"""
        hit = self._retrieval_cache.get(key)
        if hit is None:
            return None
        self._retrieval_cache.move_to_end(key)
        return hit

    def _cache_set(self, key: str, value: List[Dict[str, Any]]) -> None:
        """精确缓存写入（LRU）。超过容量则淘汰最老条目。"""
        self._retrieval_cache[key] = value
        self._retrieval_cache.move_to_end(key)
        while len(self._retrieval_cache) > self._retrieval_cache_max:
            self._retrieval_cache.popitem(last=False)

    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        """计算两个 embedding 向量的余弦相似度。"""
        if not a or not b or len(a) != len(b):
            return -1.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        denom = math.sqrt(na) * math.sqrt(nb)
        if denom <= 1e-12:
            return -1.0
        return dot / denom

    def _semantic_cache_set(self, key: str, entry: Dict[str, Any]) -> None:
        """语义缓存写入（LRU）。entry 里通常包含 qvec（query embedding）与 docs/answer。"""
        self._semantic_cache[key] = entry
        self._semantic_cache.move_to_end(key)
        while len(self._semantic_cache) > self._semantic_cache_max:
            self._semantic_cache.popitem(last=False)

    def _semantic_cache_find(self, query_vec: List[float]) -> Optional[Dict[str, Any]]:
        """
        在线性扫描语义缓存（容量默认 256）中，找“最相似且超过阈值”的条目。

        设计取舍：
        - 这里用线性扫描是为了实现简单、可控；容量不大时开销可接受
        - 如果你后续把语义缓存开得很大（比如几千），建议换成 FAISS/HNSW 做近邻索引

        返回：
        - 命中条目（复制一份），并附带 `_hit_key`（命中 key）与 `_sim`（相似度）
        """
        best_key = None
        best_entry = None
        best_sim = self._semantic_cache_threshold

        for k, entry in self._semantic_cache.items():
            v = entry.get("qvec")
            if not isinstance(v, list):
                continue
            sim = self._cosine_sim(query_vec, v)
            if sim >= best_sim:
                best_sim = sim
                best_key = k
                best_entry = entry

        if best_entry is None or best_key is None:
            return None

        self._semantic_cache.move_to_end(best_key)
        hit = dict(best_entry)
        hit["_hit_key"] = best_key
        hit["_sim"] = best_sim
        return hit

    def _docs_to_cacheable(self, docs: List[Document]) -> List[Dict[str, Any]]:
        """把 LangChain Document 转成可序列化结构，便于放进缓存（避免直接缓存对象）。"""
        out: List[Dict[str, Any]] = []
        for d in docs:
            out.append(
                {
                    "page_content": d.page_content,
                    "metadata": d.metadata or {},
                }
            )
        return out

    def _cacheable_to_docs(self, items: List[Dict[str, Any]]) -> List[Document]:
        """把缓存里的可序列化结构恢复成 LangChain Document 列表。"""
        return [Document(page_content=i.get("page_content", ""), metadata=i.get("metadata", {})) for i in items]

    def _format_context(self, docs: List[Document]) -> str:
        # 限制上下文长度，减少 LLM 处理 token（对速度很敏感）
        # `RAG_MAX_CONTEXT_CHARS` 越小越快，但上下文信息可能不足（准确率下降）
        parts: List[str] = []
        total = 0
        for d in docs:
            t = (d.page_content or "").strip()
            if not t:
                continue
            remaining = self.max_context_chars - total
            if remaining <= 0:
                break
            if len(t) > remaining:
                t = t[:remaining]
            parts.append(t)
            total += len(t)
        return "\n\n".join(parts)

    def _prepare_query(self, demand: str, use_jieba: bool) -> str:
        """
        把用户输入标准化为检索用 query_text。

        - 当前策略：可选 jieba 分词（用空格连接），提升中文向量检索效果
        - 注意：缓存 key 也是基于 query_text，因此分词策略会影响缓存命中率
        """
        query_text = demand
        if use_jieba:
            query_text = self.tokenize_query_with_jieba(demand)
        return query_text

    def _retriever_invoke(self, query_text: str) -> List[Document]:
        """
        兼容不同 LangChain 版本的 retriever 调用方式，返回相关文档列表。
        - 新版：Retriever 通常实现 Runnable 接口，用 invoke()
        - 旧版：使用 get_relevant_documents()
        """
        if self.retriever is None:
            return []
        if hasattr(self.retriever, "invoke"):
            return self.retriever.invoke(query_text)
        return self.retriever.get_relevant_documents(query_text)

    def _get_docs_with_cache(self, query_text: str) -> tuple[List[Document], Optional[float], Optional[str]]:
        """
        统一封装“精确缓存 + 保守语义缓存（复用 docs）+ 真实检索”的取 docs 逻辑。

        Returns:
            docs: 检索得到的文档（可能来自缓存或真实检索）
            semantic_hit_sim: 若命中语义缓存，返回相似度；否则 None
            semantic_hit_key: 若命中语义缓存，返回命中条目的 key；否则 None
        """
        cache_key = query_text

        # 1) 精确缓存：同一分词结果的重复提问，直接命中
        cached = self._cache_get(cache_key)
        if cached is not None:
            return self._cacheable_to_docs(cached), None, None

        # 2) 语义缓存：相似问法复用历史 docs（跳过向量库检索）
        qvec = self.embeddings.embed_query(query_text)
        hit = self._semantic_cache_find(qvec)
        if hit is not None and isinstance(hit.get("docs"), list):
            docs = self._cacheable_to_docs(hit["docs"])
            # 回填精确缓存：后续完全相同 query_text 0 成本命中
            self._cache_set(cache_key, self._docs_to_cacheable(docs))
            return docs, hit.get("_sim"), hit.get("_hit_key")

        # 3) 未命中：走真实检索，并写入两类缓存
        docs = self._retriever_invoke(query_text)
        docs_cacheable = self._docs_to_cacheable(docs)
        self._cache_set(cache_key, docs_cacheable)
        self._semantic_cache_set(cache_key, {"q": query_text, "qvec": qvec, "docs": docs_cacheable})
        return docs, None, None

    def cache_compliant_answer_only(self, demand: str, answer: str, use_jieba: bool = True) -> None:
        """
        仅当“内容合规”时，才把最终条款答案写入语义缓存（供 `RAG_SEMANTIC_CACHE_MODE=answer` 复用）。

        说明：
        - docs 的缓存由 query() 阶段正常写入（用于加速检索）
        - 这里仅补写 answer，不主动重建/覆盖 docs，避免额外检索开销与污染
        """
        if self._semantic_cache_mode != "answer":
            return
        if not isinstance(answer, str) or not answer.strip():
            return

        query_text = self._prepare_query(demand, use_jieba)
        entry = self._semantic_cache.get(query_text)
        if entry is None:
            # 没有 entry 也允许写入：创建最小 entry 以支持后续语义命中
            qvec = self.embeddings.embed_query(query_text)
            entry = {"q": query_text, "qvec": qvec, "docs": []}

        updated = dict(entry)
        updated["answer"] = answer
        self._semantic_cache_set(query_text, updated)

    #region 语义缓存
    def _try_semantic_answer_hit(
        self,
        semantic_hit_key: Optional[str],
        semantic_hit_sim: Optional[float],
        docs: List[Document],
    ) -> Optional[dict]:
        """
        激进语义缓存：当 mode=answer 且语义命中时，尝试直接返回历史答案。
        """
        if self._semantic_cache_mode != "answer":
            return None
        if semantic_hit_key is None or semantic_hit_sim is None:
            return None

        hit_entry = self._semantic_cache.get(semantic_hit_key) or {}
        cached_answer = hit_entry.get("answer")
        if not (isinstance(cached_answer, str) and cached_answer.strip()):
            return None

        return {"result": cached_answer, "source_documents": docs}
    #endregion
    def _invoke_llm(self, demand: str, context: str) -> str:
        """
        统一封装 LLM 调用，兼容 ChatPromptTemplate / PromptTemplate 两种 prompt 形态。
        """
        if isinstance(self.prompt_obj, ChatPromptTemplate):
            messages = self.prompt_obj.format_messages(context=context, question=demand)
            resp = self.llm.invoke(messages)
            return getattr(resp, "content", str(resp))
        prompt_str = self.prompt_obj.format(context=context, question=demand)
        resp = self.llm.invoke(prompt_str)
        return getattr(resp, "content", str(resp))

    def cache_compliant_answer(self, demand: str, answer: str, use_jieba: bool = True) -> None:
        """
        仅当“内容合规”时，才把答案写入语义缓存（供 `RAG_SEMANTIC_CACHE_MODE=answer` 复用）。

        为什么不在 `query()` 里直接缓存答案：
        - `query()` 并不知道答案是否通过你的合规审查
        - 按你的需求：只有合规条款才允许做“内容缓存”（答案缓存）

        行为：
        - 只影响语义缓存中的 `answer` 字段（docs 的缓存仍用于加速检索）
        - 若语义缓存里还没有该 query 的 entry，会补建一个（并尽量补齐 docs）
        """
        if self._semantic_cache_mode != "answer":
            return
        if not isinstance(answer, str) or not answer.strip():
            return

        query_text = self._prepare_query(demand, use_jieba)
        entry = self._semantic_cache.get(query_text)
        if entry is None:
            # 为了让“相似问法 answer 命中”成立，需要 qvec；同时尽量补齐 docs，方便返回引用
            qvec = self.embeddings.embed_query(query_text)
            docs = self._retriever_invoke(query_text)
            entry = {
                "q": query_text,
                "qvec": qvec,
                "docs": self._docs_to_cacheable(docs),
            }
            self._semantic_cache_set(query_text, entry)
            # 同步写入精确缓存，后续完全相同 query_text 更快
            self._cache_set(query_text, entry["docs"])

        updated = dict(entry)
        updated["answer"] = answer
        self._semantic_cache_set(query_text, updated)

    def query(self, demand: str, use_jieba: bool = True) -> dict:
        """
        对外暴露的问答接口：给定问题，返回答案与引用的文档。

        Args:
            demand: 用户要求
            use_jieba: 是否对问题使用 jieba 分词（默认为 True）

        Returns:
            {"result": 答案文本, "source_documents": 来源文档列表}
        """
        if self.qa_chain is None:
            raise RuntimeError("请先调用 index_documents 或 load_index 构建索引")

        query_text = self._prepare_query(demand, use_jieba)
        print(f"[RAG] query start | demand_len={len(demand or '')} | query_len={len(query_text or '')}")

        # 更快的执行路径：先检索再生成（便于缓存/限长/计时）
        # 注意：这里的“检索”包含两部分成本：
        # - query embedding（把问题变成向量）
        # - 向量库近邻搜索（Chroma/向量数据库）
        if self.retriever is not None and self.prompt_obj is not None:
            docs, semantic_hit_sim, semantic_hit_key = self._get_docs_with_cache(query_text)

            context = self._format_context(docs)

            early = self._try_semantic_answer_hit(
                semantic_hit_key=semantic_hit_key,
                semantic_hit_sim=semantic_hit_sim,
                docs=docs,
            )
            if early is not None:
                print(
                    f"[RAG] query end   | path=semantic_answer_hit | docs={len(early.get('source_documents') or [])} | result_len={len(early.get('result') or '')}"
                )
                return early

            result_text = self._invoke_llm(demand=demand, context=context)

            out = {"result": result_text, "source_documents": docs}
            print(
                f"[RAG] query end   | path=llm_generated | docs={len(docs)} | result_len={len(result_text or '')}"
            )
            return out

        # 兜底：保持原来的 RetrievalQA 行为
        out = self.qa_chain.invoke({"question": query_text})
        print(
            f"[RAG] query end   | path=retrievalqa_fallback | docs={len(out.get('source_documents') or [])} | result_len={len(out.get('result') or '')}"
        )
        return out
    #endregion



# region
# 用于实例化RAGService对象

_rag = None

def get_rag():
    """
    获取全局单例 RAGService（进程内复用）。

    - 如果检测到持久化向量库目录 `chroma_db` 存在：直接 load_index()，避免重建索引
    - 否则：加载 `knowlege.pdf` 并构建索引（首次启动会比较慢）
    """
    global _rag
    if _rag is None:
        path_is_exist = Path(__file__).parent / "chroma_db"
        if path_is_exist.exists():
            _rag = RAGService(
                chunk_size=100,
                chunk_overlap=10,
            ).load_index()
        else:
            _rag = RAGService(
                chunk_size=100,
                chunk_overlap=10,
            )
            docpath = Path(__file__).parent / "knowlege.pdf"
            docs = _rag.load_documents(str(docpath), loader_type="pdf")
            _rag.index_documents(docs)
    return _rag


# endregion

