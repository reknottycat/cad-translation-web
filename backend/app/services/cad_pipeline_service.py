from __future__ import annotations

import contextlib
import threading
import json
import os
import re
import stat
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from tempfile import mkdtemp, mkstemp
from typing import Any, Callable, Iterator

import structlog
import pandas as pd
from fastapi import UploadFile

from app.config import get_settings
from app.services.cad_text_processor import cad_text_processor
from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service
from app.services.docutranslate_adapter import CadTextRecord, DocuTranslateConfig, DocuTranslateJsonAdapter
from app.utils.file_utils import get_safe_filename, resolve_within_directory
from app.utils.locking import atomic_write_json, atomic_write_text, file_lock
from app.workflow.pipeline import CADPipeline, get_pipeline
from app.functions.dwg_converter import DWGConverter
from app.functions.text_extractor import TextExtractor
from app.functions.text_applier import TextApplier

logger = structlog.get_logger(__name__)
from app.services.cad_task_types import TaskCancelledError, validate_task_id, is_valid_task_id
from app.services.cad_task_jobs import task_execution

from app.services.cad_task_storage import CadTaskStorageMixin
from app.services.cad_task_translation import CadTaskTranslationMixin
from app.services.cad_task_processing import CadTaskProcessingMixin
from app.services.cad_task_artifacts import CadTaskArtifactsMixin
from app.services.cad_task_jobs import TaskJobsMixin, TaskBusyError


class CADPipelineService(TaskJobsMixin, CadTaskStorageMixin, CadTaskTranslationMixin, CadTaskProcessingMixin, CadTaskArtifactsMixin):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.processor = cad_text_processor
        # 使用模块化工作流管道处理新任务
        self._pipeline = get_pipeline()
        self._summary_cache = {}
        self._summary_cache_lock = threading.Lock()
        self._task_indexes = {}
        self._index_lock = threading.Lock()


cad_pipeline_service = CADPipelineService()
