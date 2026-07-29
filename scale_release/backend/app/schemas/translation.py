#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译相关数据模型
Translation Related Data Models
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class TranslationRequest(BaseModel):
    """单个文本翻译请求"""
    text: str = Field(..., description="要翻译的文本", max_length=5000)
    source_lang: str = Field(default="auto", description="源语言代码")
    target_lang: str = Field(default="zh", description="目标语言代码")

class TranslationResponse(BaseModel):
    """翻译响应"""
    original_text: str = Field(..., description="原始文本")
    translated_text: str = Field(..., description="翻译后的文本")
    source_lang: str = Field(..., description="源语言代码")
    target_lang: str = Field(..., description="目标语言代码")
    success: bool = Field(..., description="翻译是否成功")
    error_message: Optional[str] = Field(None, description="错误信息")

class BatchTranslationRequest(BaseModel):
    """批量翻译请求"""
    texts: List[str] = Field(..., description="要翻译的文本列表", max_items=100)
    source_lang: str = Field(default="auto", description="源语言代码")
    target_lang: str = Field(default="zh", description="目标语言代码")

class ExcelTranslationRequest(BaseModel):
    """Excel翻译请求"""
    text_columns: Optional[List[str]] = Field(None, description="需要翻译的列名列表")
    source_lang: str = Field(default="auto", description="源语言代码")
    target_lang: str = Field(default="zh", description="目标语言代码")
    translation_mode: str = Field(default="add", description="翻译模式: add(添加新列) 或 replace(替换原列)")

class TranslationStatsResponse(BaseModel):
    """翻译统计响应"""
    total_rows: int = Field(..., description="总行数")
    text_columns: List[str] = Field(..., description="翻译的列名")
    translated_cells: int = Field(..., description="翻译成功的单元格数")
    skipped_cells: int = Field(..., description="跳过的空单元格数")
    error_cells: int = Field(..., description="翻译失败的单元格数")

class ExcelTranslationResponse(BaseModel):
    """Excel翻译响应"""
    success: bool = Field(..., description="翻译是否成功")
    message: str = Field(..., description="响应消息")
    output_filename: Optional[str] = Field(None, description="输出文件名")
    download_url: Optional[str] = Field(None, description="下载链接")
    report_filename: Optional[str] = Field(None, description="翻译报告文件名")
    stats: Optional[TranslationStatsResponse] = Field(None, description="翻译统计信息")

class TranslationTaskStatus(BaseModel):
    """翻译任务状态"""
    task_id: str = Field(..., description="任务ID")
    state: str = Field(..., description="任务状态")
    status: str = Field(..., description="状态描述")
    message: str = Field(..., description="状态消息")
    current: Optional[int] = Field(None, description="当前进度")
    total: Optional[int] = Field(None, description="总进度")
    result: Optional[Dict[str, Any]] = Field(None, description="任务结果")
    error: Optional[str] = Field(None, description="错误信息")

class LanguageInfo(BaseModel):
    """语言信息"""
    code: str = Field(..., description="语言代码")
    name: str = Field(..., description="语言名称")
    native_name: Optional[str] = Field(None, description="本地语言名称")

class TranslationConfigResponse(BaseModel):
    """翻译配置响应"""
    supported_languages: Dict[str, str] = Field(..., description="支持的语言列表")
    default_source_language: str = Field(..., description="默认源语言")
    default_target_language: str = Field(..., description="默认目标语言")
    translation_modes: Dict[str, str] = Field(..., description="翻译模式")
    max_batch_size: int = Field(..., description="批量翻译最大数量")
    supported_file_types: List[str] = Field(..., description="支持的文件类型")

class TranslationHistory(BaseModel):
    """翻译历史记录"""
    id: int = Field(..., description="记录ID")
    original_text: str = Field(..., description="原始文本")
    translated_text: str = Field(..., description="翻译文本")
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")
    created_at: datetime = Field(..., description="创建时间")
    user_id: Optional[int] = Field(None, description="用户ID")

class TranslationHistoryResponse(BaseModel):
    """翻译历史响应"""
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    size: int = Field(..., description="每页大小")
    items: List[TranslationHistory] = Field(..., description="历史记录列表")

# 翻译质量评估
class TranslationQuality(BaseModel):
    """翻译质量评估"""
    confidence_score: float = Field(..., description="置信度分数 0-1")
    quality_level: str = Field(..., description="质量等级: high/medium/low")
    suggestions: Optional[List[str]] = Field(None, description="改进建议")

class EnhancedTranslationResponse(TranslationResponse):
    """增强的翻译响应（包含质量评估）"""
    quality: Optional[TranslationQuality] = Field(None, description="翻译质量评估")
    processing_time: Optional[float] = Field(None, description="处理时间（秒）")

# 翻译项目管理
class TranslationProject(BaseModel):
    """翻译项目"""
    id: Optional[int] = Field(None, description="项目ID")
    name: str = Field(..., description="项目名称", max_length=200)
    description: Optional[str] = Field(None, description="项目描述", max_length=1000)
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    status: str = Field(default="active", description="项目状态: active/completed/archived")

class TranslationProjectCreate(BaseModel):
    """创建翻译项目"""
    name: str = Field(..., description="项目名称", max_length=200)
    description: Optional[str] = Field(None, description="项目描述", max_length=1000)
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")

class TranslationProjectUpdate(BaseModel):
    """更新翻译项目"""
    name: Optional[str] = Field(None, description="项目名称", max_length=200)
    description: Optional[str] = Field(None, description="项目描述", max_length=1000)
    source_lang: Optional[str] = Field(None, description="源语言")
    target_lang: Optional[str] = Field(None, description="目标语言")
    status: Optional[str] = Field(None, description="项目状态")

# 翻译术语管理
class TranslationTerm(BaseModel):
    """翻译术语"""
    id: Optional[int] = Field(None, description="术语ID")
    source_term: str = Field(..., description="源术语", max_length=200)
    target_term: str = Field(..., description="目标术语", max_length=200)
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")
    category: Optional[str] = Field(None, description="术语分类", max_length=100)
    notes: Optional[str] = Field(None, description="备注", max_length=500)
    created_at: Optional[datetime] = Field(None, description="创建时间")

class TranslationTermCreate(BaseModel):
    """创建翻译术语"""
    source_term: str = Field(..., description="源术语", max_length=200)
    target_term: str = Field(..., description="目标术语", max_length=200)
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")
    category: Optional[str] = Field(None, description="术语分类", max_length=100)
    notes: Optional[str] = Field(None, description="备注", max_length=500)

# 翻译缓存
class TranslationCache(BaseModel):
    """翻译缓存"""
    source_text: str = Field(..., description="源文本")
    translated_text: str = Field(..., description="翻译文本")
    source_lang: str = Field(..., description="源语言")
    target_lang: str = Field(..., description="目标语言")
    cache_key: str = Field(..., description="缓存键")
    hit_count: int = Field(default=0, description="命中次数")
    created_at: datetime = Field(..., description="创建时间")
    last_used_at: datetime = Field(..., description="最后使用时间")

class RuntimeConfigUpdateRequest(BaseModel):
    """Runtime model gateway config update payload."""

    provider: str = Field(..., description="Current provider id")
    format: Optional[str] = Field(None, description="API format such as openai_compatible/anthropic/google/ollama/lmstudio")
    base_url: Optional[str] = Field(None, description="OpenAI-compatible endpoint base url")
    api_key: Optional[str] = Field(None, description="API key for the selected provider")
    model: Optional[str] = Field(None, description="Active model id")
    system_prompt_mode: Optional[str] = Field(None, description="default/cad_specialized/custom")
    custom_system_prompt: Optional[str] = Field(None, description="Full custom system prompt when custom mode is selected")
    glossary_file: Optional[str] = Field(None, description="Optional CSV/XLS/XLSX glossary file path")
    reasoning_enabled: Optional[bool] = Field(None, description="Enable OpenRouter/OpenAI-compatible reasoning when supported")
    timeout_seconds: Optional[int] = Field(None, ge=1, le=600, description="Request timeout")
    temperature: Optional[float] = Field(None, ge=0, le=2, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, ge=1, le=32000, description="Max output tokens")
    batch_size: Optional[int] = Field(None, ge=1, le=100, description="Batch translation size")
    batch_json: Optional[bool] = Field(None, description="Whether to use JSON batch prompts")
    parallel_count: Optional[int] = Field(None, ge=1, le=32, description="Parallel request count")
    retry_count: Optional[int] = Field(None, ge=0, le=10, description="Retry count")
    rpm: Optional[int] = Field(None, ge=1, le=20000, description="Requests per minute")
    tpm: Optional[str] = Field(None, description="Tokens per minute limit")
    extra_body: Optional[str] = Field(None, description="Extra JSON body for provider-specific payloads")
    use_system_proxy: Optional[bool] = Field(None, description="Enable system proxy")
    target_language: Optional[str] = Field(None, description="Default CAD target language")
    translation_mode: Optional[str] = Field(None, description="Default CAD translation mode")
    font_name: Optional[str] = Field(None, description="Default CAD output font name")
    font_size_reduction: Optional[int] = Field(None, ge=0, description="Default CAD font size reduction")
    default_output_dir: Optional[str] = Field(None, description="Default CAD output directory")
    converter_backend: Optional[str] = Field(None, description="Default CAD converter backend")
    system_prompt: Optional[str] = Field(None, description="System prompt text")
    allow_demo_fallback: Optional[bool] = Field(None, description="Allow demo fallback when API key is missing")
    provider_api_keys: Optional[Dict[str, str]] = Field(
        None, description="Provider-specific API keys map"
    )
    fallback_models: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Optional ordered fallback model configs checked before use",
    )


class CustomProviderPayload(BaseModel):
    """Payload for adding a custom translation provider preset."""
    id: str = Field(..., description="Unique provider ID (e.g., 'my-custom-endpoint')")
    name: str = Field(..., description="Display name for the provider")
    base_url: str = Field(..., description="The base URL of the OpenAI-compatible API")
    default_model: str = Field(..., description="The default model to use")
    notes: Optional[str] = Field("Custom provider", description="Optional notes for display")


class RuntimeConnectionTestResponse(BaseModel):
    """Connection test result for the model gateway."""

    success: bool = Field(..., description="Whether the upstream request succeeded")
    reachable: bool = Field(..., description="Whether the upstream endpoint was reachable")
    status_code: int = Field(..., description="HTTP status code returned by upstream")
    provider: str = Field(..., description="Provider under test")
    format: str = Field(..., description="Resolved API format under test")
    endpoint: str = Field(..., description="Resolved upstream endpoint")
    model: str = Field(..., description="Resolved model id")
    message: str = Field(..., description="Test result details")
