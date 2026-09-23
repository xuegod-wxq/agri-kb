# -*- coding: utf-8 -*-
"""
agri-kb：新疆农业知识库 RAG 问答系统
=====================================

分层结构::

    app/
      config.py        配置中心（.env / 环境变量）
      factory.py       应用工厂 + 生命周期管理
      schemas.py       API 出入参模型
      api/             传输层：HTTP 路由，只做参数校验与协议转换
      core/            跨层通用：提示词、日志
      retrieval/       检索层：分词 / 分块 / BM25 / 向量 / 混合检索
      ingest/          数据接入层：文档加载、解析、仓库
      llm/             LLM 适配层：供应商抽象与实现
      session/         会话层：对话历史存储（JSON / SQLite）

依赖方向自上而下：api -> retrieval|llm|session|ingest -> core，
下层不反向依赖上层。
"""

__version__ = "4.3.0"
