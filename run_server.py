"""
运行 Web 服务器
"""
import logging
import uvicorn
from src.utils import setup_logging

if __name__ == "__main__":
    setup_logging()
    logging.getLogger(__name__).info("Starting web server")
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
