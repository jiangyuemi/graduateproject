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
                self._inner = inner
                self._max_batch = max_batch

            def embed_documents(self, texts: Iterable[str]):
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

        self.embeddings = BatchedEmbeddings(base_embeddings, max_batch=10)
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
        基于当前向量库构建检索增强问答链

        注意：调用前必须确保 `self.vectorstore` 已经初始化。
        """
        # 将向量库封装为检索器
        retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 1},  # 只取最相关的一条文档，进一步减少上下文污染
        )

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

        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            retriever=retriever,
            chain_type='stuff',
            chain_type_kwargs={'prompt': prompt_obj},
            verbose=True,
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

        query_text = demand
        if use_jieba:
            query_text = self.tokenize_query_with_jieba(demand)

        return self.qa_chain.invoke({"question": query_text})
    #endregion



# region
# 用于实例化RAGService对象

_rag = None

def get_rag():
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