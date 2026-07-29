#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD文件翻译处理Web系统 - 数据库配置
Database Configuration for CAD File Translation Web System
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Generator
import structlog

from .config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(
    settings.resolve_database_url(),
    connect_args={"check_same_thread": False} if "sqlite" in settings.resolve_database_url() else {},
    echo=settings.DEBUG
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基础模型类
Base = declarative_base()

class Project(Base):
    """项目模型"""
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="created", index=True)  # created, processing, completed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 配置信息
    source_language = Column(String(10), default="zh")
    target_language = Column(String(10), default="en")
    font_name = Column(String(100), default="Times New Roman")
    font_size_reduction = Column(Integer, default=4)
    translation_mode = Column(String(20), default="add")  # add, replace
    
    # 统计信息
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    total_texts = Column(Integer, default=0)
    translated_texts = Column(Integer, default=0)
    
    # 关联关系
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("ProcessingTask", back_populates="project", cascade="all, delete-orphan")

class ProjectFile(Base):
    """项目文件模型"""
    __tablename__ = "project_files"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String(10), nullable=False)  # dwg, dxf
    status = Column(String(50), default="uploaded")  # uploaded, converting, converted, extracting, extracted, translating, translated, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 处理结果路径
    converted_path = Column(String(500), nullable=True)  # DXF转换结果路径
    excel_path = Column(String(500), nullable=True)      # Excel提取结果路径
    translated_path = Column(String(500), nullable=True) # 翻译回填结果路径
    
    # 统计信息
    extracted_texts_count = Column(Integer, default=0)
    translated_texts_count = Column(Integer, default=0)
    
    # 关联关系
    project = relationship("Project", back_populates="files")

class ProcessingTask(Base):
    """处理任务模型"""
    __tablename__ = "processing_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    task_id = Column(String(255), unique=True, index=True)  # Celery任务ID
    task_type = Column(String(50), nullable=False)  # convert, extract, translate, backfill
    status = Column(String(50), default="pending")  # pending, running, success, failure, revoked
    progress = Column(Float, default=0.0)  # 0.0 - 1.0
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # 任务详情
    message = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    result_data = Column(Text, nullable=True)  # JSON格式的结果数据
    
    # 关联关系
    project = relationship("Project", back_populates="tasks")

class TextExtraction(Base):
    """文本提取记录模型"""
    __tablename__ = "text_extractions"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    file_id = Column(Integer, ForeignKey("project_files.id"), nullable=False)
    original_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=True)
    entity_type = Column(String(50), nullable=False)  # TEXT, MTEXT, etc.
    layer_name = Column(String(100), nullable=True)
    position_x = Column(Float, nullable=True)
    position_y = Column(Float, nullable=True)
    position_z = Column(Float, nullable=True)
    font_height = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TranslationCache(Base):
    """翻译缓存模型"""
    __tablename__ = "translation_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    source_text = Column(Text, nullable=False, index=True)
    translated_text = Column(Text, nullable=False)
    source_language = Column(String(10), nullable=False)
    target_language = Column(String(10), nullable=False)
    translation_service = Column(String(50), default="tencent")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), server_default=func.now())
    usage_count = Column(Integer, default=1)

# 数据库依赖注入
def get_db() -> Generator[Session, None, None]:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error("数据库会话错误", error=str(e))
        db.rollback()
        raise
    finally:
        db.close()

# 数据库初始化函数
def init_db():
    """初始化数据库"""
    logger.info("初始化数据库表")
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表创建完成")

# 数据库健康检查
def check_db_health() -> bool:
    """检查数据库连接健康状态"""
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        return True
    except Exception as e:
        logger.error("数据库健康检查失败", error=str(e))
        return False
