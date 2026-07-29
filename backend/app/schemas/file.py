#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件相关的Pydantic模型
File-related Pydantic models
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

class FileStatus(str, Enum):
    """文件状态枚举"""
    UPLOADED = "uploaded"
    CONVERTING = "converting"
    CONVERTED = "converted"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    BACKFILLING = "backfilling"
    COMPLETED = "completed"
    FAILED = "failed"

class FileType(str, Enum):
    """支持的文件类型"""
    DWG = "dwg"
    DXF = "dxf"

class FileUploadResponse(BaseModel):
    """文件上传响应模型"""
    filename: str
    success: bool
    file_id: Optional[int] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    error: Optional[str] = None

class FileListResponse(BaseModel):
    """文件列表响应模型"""
    id: int
    filename: str
    original_filename: str
    file_size: int
    file_type: str
    status: str
    progress: Optional[int] = 0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # 处理结果文件路径状态
    has_converted: bool = False
    has_excel: bool = False
    has_translated: bool = False
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_orm(cls, obj):
        """从ORM对象创建响应模型"""
        data = {
            'id': obj.id,
            'filename': obj.filename,
            'original_filename': obj.original_filename,
            'file_size': obj.file_size,
            'file_type': obj.file_type,
            'status': obj.status,
            'progress': obj.progress or 0,
            'error_message': obj.error_message,
            'created_at': obj.created_at,
            'updated_at': obj.updated_at,
            'has_converted': bool(obj.converted_path),
            'has_excel': bool(obj.excel_path),
            'has_translated': bool(obj.translated_path)
        }
        return cls(**data)

class FileDetailResponse(BaseModel):
    """文件详情响应模型"""
    id: int
    project_id: int
    filename: str
    original_filename: str
    file_path: str
    file_size: int
    file_type: str
    status: str
    progress: Optional[int] = 0
    error_message: Optional[str] = None
    
    # 处理结果路径
    converted_path: Optional[str] = None
    excel_path: Optional[str] = None
    translated_path: Optional[str] = None
    
    # 处理统计
    total_texts: Optional[int] = 0
    translated_texts: Optional[int] = 0
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class FileProcessingRequest(BaseModel):
    """文件处理请求模型"""
    file_ids: List[int] = Field(..., min_items=1, description="要处理的文件ID列表")
    config: Optional[dict] = Field(None, description="处理配置")

class FileProcessingStatus(BaseModel):
    """文件处理状态模型"""
    file_id: int
    filename: str
    status: str
    progress: int = 0
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    estimated_time: Optional[int] = None  # 预估剩余时间（秒）

class BatchProcessingStatus(BaseModel):
    """批量处理状态模型"""
    total_files: int
    completed_files: int
    failed_files: int
    processing_files: int
    overall_progress: int = 0
    files: List[FileProcessingStatus] = []

class FileValidationResult(BaseModel):
    """文件验证结果模型"""
    valid: bool
    error: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    warnings: List[str] = []

class TextExtractionResult(BaseModel):
    """文本提取结果模型"""
    total_texts: int = 0
    extracted_texts: List[dict] = []
    excel_path: Optional[str] = None
    extraction_time: Optional[float] = None

class TranslationResult(BaseModel):
    """翻译结果模型"""
    total_texts: int = 0
    translated_texts: int = 0
    translation_time: Optional[float] = None
    translated_file_path: Optional[str] = None
    errors: List[str] = []