# -*- coding: utf-8 -*-
"""
agri-kb 启动入口
================

保留本文件是为了兼容既有的启动方式::

    uvicorn main:app --host 0.0.0.0 --port 8000

真正的实现都在 app/ 包内，本文件只负责创建应用实例。
也可以直接运行 ``python main.py``（HOST / PORT 从 .env 读取）。
"""
from app.config import get_settings
from app.factory import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "main:app",
        host=_settings.server.host,
        port=_settings.server.port,
        reload=_settings.server.reload,
        log_level=_settings.server.log_level,
    )
