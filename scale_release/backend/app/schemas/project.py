#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目相关的Pydantic模型
Project-related Pydantic models
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class TranslationMode(str, Enum):
    """翻译模式枚举"""
    ADD = "add"      # 添加模式
    REPLACE = "replace"  # 替换模式

class ProjectStatus(str, Enum):
    """项目状态枚举"""
    CREATED = "created"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ProjectCreate(BaseModel):
    """创建项目请求模型"""
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, max_length=500, description="项目描述")
    source_language: str = Field("zh", description="源语言代码")
    target_language: str = Field("en", description="目标语言代码")
    font_name: str = Field("Arial", description="字体名称")
    font_size_reduction: float = Field(0.8, ge=0.1, le=2.0, description="字体缩放比例")
    translation_mode: TranslationMode = Field(TranslationMode.ADD, description="翻译模式")
    
    @validator('name')
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('项目名称不能为空')
        return v.strip()
    
    @validator('source_language', 'target_language')
    def validate_language_codes(cls, v):
        # 支持的语言代码列表
        supported_languages = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'ru', 'ar']
        if v not in supported_languages:
            raise ValueError(f'不支持的语言代码: {v}')
        return v

class ProjectUpdate(BaseModel):
    """更新项目请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, max_length=500, description="项目描述")
    source_language: Optional[str] = Field(None, description="源语言代码")
    target_language: Optional[str] = Field(None, description="目标语言代码")
    font_name: Optional[str] = Field(None, description="字体名称")
    font_size_reduction: Optional[float] = Field(None, ge=0.1, le=2.0, description="字体缩放比例")
    translation_mode: Optional[TranslationMode] = Field(None, description="翻译模式")
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError('项目名称不能为空')
        return v.strip() if v else v

class ProjectResponse(BaseModel):
    """项目响应模型"""
    id: int
    name: str
    description: Optional[str]
    source_language: str
    target_language: str
    font_name: str
    font_size_reduction: float
    translation_mode: str
    status: str
    total_files: int = 0
    processed_files: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ProjectListResponse(BaseModel):
    """项目列表响应模型"""
    id: int
    name: str
    description: Optional[str]
    status: str
    total_files: int = 0
    processed_files: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class FileInfo(BaseModel):
    """文件信息模型"""
    id: int
    filename: str
    original_filename: str
    file_size: int
    file_type: str
    status: str
    created_at: datetime
    updated_at: datetime

class TaskInfo(BaseModel):
    """任务信息模型"""
    id: int
    task_id: str
    task_type: str
    status: str
    progress: Optional[int] = 0
    message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

class ProjectDetailResponse(BaseModel):
    """项目详情响应模型"""
    id: int
    name: str
    description: Optional[str]
    source_language: str
    target_language: str
    font_name: str
    font_size_reduction: float
    translation_mode: str
    status: str
    total_files: int = 0
    processed_files: int = 0
    created_at: datetime
    updated_at: datetime
    files: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    
    class Config:
        from_attributes = True

class ProcessingConfig(BaseModel):
    """处理配置模型"""
    font_name: str = Field("Arial", description="字体名称")
    translation_mode: TranslationMode = Field(TranslationMode.ADD, description="翻译模式")
    font_size_reduction: float = Field(0.8, ge=0.1, le=2.0, description="字体缩放比例")
    source_language: str = Field("zh", description="源语言代码")
    target_language: str = Field("en", description="目标语言代码")
    auto_translate: bool = Field(False, description="是否自动翻译")
    
class ProjectStats(BaseModel):
    """项目统计信息模型"""
    total_projects: int = 0
    active_projects: int = 0
    completed_projects: int = 0
    failed_projects: int = 0
    total_files: int = 0
    processed_files: int = 0