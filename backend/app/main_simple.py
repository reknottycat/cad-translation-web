"""
简化版CAD文件翻译处理Web系统 - FastAPI主应用
Simplified Main FastAPI Application for CAD File Translation Web System
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import settings
from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service
from app.services.excel_processor import excel_processor
from app.api.routes.cad import router as cad_router

# 创建FastAPI应用
app = FastAPI(
    title="CAD文件翻译处理系统",
    description="专业的CAD文件翻译处理平台，支持DWG/DXF文件处理和AI自动翻译",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 确保输出目录存在
Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# 挂载静态文件服务
if Path("frontend/dist").exists():
    app.mount("/static", StaticFiles(directory="frontend/dist", html=True), name="static")

# 注册CAD处理路由
app.include_router(cad_router)

@app.get("/")
async def root():
    """根路径 - 返回API信息"""
    return {
        "message": "CAD文件翻译处理系统API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "services": {
            "translation": "active",
            "excel_processor": "active",
            "cad_processor": "active"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main_simple:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )