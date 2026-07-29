#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件管理API路由
File Management API Routes
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import structlog
import aiofiles
import os
from pathlib import Path
import uuid
from datetime import datetime

from ..database import get_db, Project, ProjectFile
from ..config import get_settings
from ..schemas.file import FileUploadResponse, FileListResponse, FileDetailResponse
from ..utils.file_utils import validate_file, get_file_hash, ensure_directory, get_safe_filename

logger = structlog.get_logger(__name__)
router = APIRouter()
settings = get_settings()

@router.post("/upload/{project_id}", response_model=List[FileUploadResponse])
async def upload_files(
    project_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """上传文件到项目"""
    logger.info("开始文件上传", project_id=project_id, files_count=len(files))
    
    try:
        # 检查项目是否存在
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 检查项目状态
        if project.status == "processing":
            raise HTTPException(status_code=400, detail="项目正在处理中，无法上传文件")
        
        # 检查文件数量限制
        existing_files_count = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).count()
        if existing_files_count + len(files) > settings.MAX_FILES_PER_PROJECT:
            raise HTTPException(
                status_code=400, 
                detail=f"文件数量超过限制，最多允许 {settings.MAX_FILES_PER_PROJECT} 个文件"
            )
        
        uploaded_files = []
        
        # 创建项目上传目录
        project_upload_dir = settings.get_upload_path() / f"project_{project_id}"
        ensure_directory(project_upload_dir)
        
        for file in files:
            try:
                # 验证文件
                validation_result = await validate_file(file, settings)
                if not validation_result["valid"]:
                    logger.warning("文件验证失败", filename=file.filename, error=validation_result["error"])
                    uploaded_files.append(FileUploadResponse(
                        filename=file.filename,
                        success=False,
                        error=validation_result["error"]
                    ))
                    continue
                
                # 生成唯一文件名
                safe_original_filename = get_safe_filename(file.filename)
                file_extension = Path(safe_original_filename).suffix
                unique_filename = f"{uuid.uuid4()}{file_extension}"
                file_path = project_upload_dir / unique_filename
                
                # 保存文件
                async with aiofiles.open(file_path, 'wb') as f:
                    content = await file.read()
                    await f.write(content)
                
                # 计算文件哈希
                file_hash = get_file_hash(file_path)
                
                # 检查文件是否已存在（基于哈希）
                existing_file = db.query(ProjectFile).filter(
                    ProjectFile.project_id == project_id,
                    ProjectFile.file_path.contains(file_hash[:16])  # 使用哈希前16位作为标识
                ).first()
                
                if existing_file:
                    # 删除刚上传的重复文件
                    os.remove(file_path)
                    logger.warning("文件已存在", filename=file.filename, existing_id=existing_file.id)
                    uploaded_files.append(FileUploadResponse(
                        filename=file.filename,
                        success=False,
                        error="文件已存在"
                    ))
                    continue
                
                # 创建数据库记录
                db_file = ProjectFile(
                    project_id=project_id,
                    filename=unique_filename,
                    original_filename=safe_original_filename,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    file_type=file_extension.lower().replace('.', ''),
                    status="uploaded"
                )
                
                db.add(db_file)
                db.flush()  # 获取ID但不提交
                
                logger.info("文件上传成功", 
                        filename=safe_original_filename,
                           file_id=db_file.id,
                           file_size=db_file.file_size)
                
                uploaded_files.append(FileUploadResponse(
                    filename=file.filename,
                    success=True,
                    file_id=db_file.id,
                    file_size=db_file.file_size,
                    file_type=db_file.file_type
                ))
                
            except Exception as e:
                logger.error("单个文件上传失败", filename=file.filename, error=str(e))
                uploaded_files.append(FileUploadResponse(
                    filename=file.filename,
                    success=False,
                    error=f"上传失败: {str(e)}"
                ))
        
        # 更新项目文件统计
        successful_uploads = sum(1 for f in uploaded_files if f.success)
        if successful_uploads > 0:
            project.total_files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).count()
            project.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info("文件上传完成", 
                   project_id=project_id, 
                   total_files=len(files),
                   successful_uploads=successful_uploads)
        
        return uploaded_files
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("文件上传失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@router.get("/{project_id}", response_model=List[FileListResponse])
async def list_project_files(
    project_id: int,
    db: Session = Depends(get_db)
):
    """获取项目文件列表"""
    logger.info("获取项目文件列表", project_id=project_id)
    
    try:
        # 检查项目是否存在
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取文件列表
        files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
        
        logger.info("项目文件列表获取成功", project_id=project_id, files_count=len(files))
        return [FileListResponse.from_orm(file) for file in files]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取项目文件列表失败", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")

@router.get("/detail/{file_id}", response_model=FileDetailResponse)
async def get_file_detail(
    file_id: int,
    db: Session = Depends(get_db)
):
    """获取文件详情"""
    logger.info("获取文件详情", file_id=file_id)
    
    try:
        file = db.query(ProjectFile).filter(ProjectFile.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        logger.info("文件详情获取成功", file_id=file_id, filename=file.original_filename)
        return FileDetailResponse.from_orm(file)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取文件详情失败", file_id=file_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取文件详情失败: {str(e)}")

@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    db: Session = Depends(get_db)
):
    """删除文件"""
    logger.info("删除文件", file_id=file_id)
    
    try:
        file = db.query(ProjectFile).filter(ProjectFile.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 检查项目状态
        project = db.query(Project).filter(Project.id == file.project_id).first()
        if project and project.status == "processing":
            raise HTTPException(status_code=400, detail="项目正在处理中，无法删除文件")
        
        # 删除物理文件
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
            
            # 删除相关的处理结果文件
            for path_attr in ['converted_path', 'excel_path', 'translated_path']:
                path = getattr(file, path_attr)
                if path and os.path.exists(path):
                    os.remove(path)
                    
        except Exception as e:
            logger.warning("删除物理文件失败", file_id=file_id, error=str(e))
        
        # 删除数据库记录
        db.delete(file)
        
        # 更新项目文件统计
        if project:
            project.total_files = db.query(ProjectFile).filter(ProjectFile.project_id == project.id).count() - 1
            project.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info("文件删除成功", file_id=file_id, filename=file.original_filename)
        return {"message": "文件删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除文件失败", file_id=file_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除文件失败: {str(e)}")

@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    file_type: str = "original",  # original, converted, excel, translated
    db: Session = Depends(get_db)
):
    """下载文件"""
    logger.info("下载文件", file_id=file_id, file_type=file_type)
    
    try:
        file = db.query(ProjectFile).filter(ProjectFile.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 根据类型选择文件路径
        file_path = None
        download_filename = None
        
        if file_type == "original":
            file_path = file.file_path
            download_filename = get_safe_filename(file.original_filename)
        elif file_type == "converted" and file.converted_path:
            file_path = file.converted_path
            download_filename = f"converted_{get_safe_filename(file.original_filename)}"
        elif file_type == "excel" and file.excel_path:
            file_path = file.excel_path
            download_filename = f"{Path(get_safe_filename(file.original_filename)).stem}_texts.xlsx"
        elif file_type == "translated" and file.translated_path:
            file_path = file.translated_path
            download_filename = f"translated_{get_safe_filename(file.original_filename)}"
        else:
            raise HTTPException(status_code=404, detail=f"请求的文件类型不存在: {file_type}")
        
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        logger.info("文件下载开始", file_id=file_id, file_type=file_type, filename=download_filename)
        
        return FileResponse(
            path=file_path,
            filename=download_filename,
            media_type='application/octet-stream'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("文件下载失败", file_id=file_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"文件下载失败: {str(e)}")

@router.post("/batch-download/{project_id}")
async def create_batch_download(
    project_id: int,
    file_type: str = "all",  # all, original, converted, excel, translated
    db: Session = Depends(get_db)
):
    """创建批量下载包"""
    logger.info("创建批量下载包", project_id=project_id, file_type=file_type)
    
    try:
        # 检查项目是否存在
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取项目文件
        files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
        if not files:
            raise HTTPException(status_code=404, detail="项目中没有文件")
        
        # 创建临时打包目录
        import tempfile
        import zipfile
        
        temp_dir = Path(tempfile.mkdtemp())
        zip_path = temp_dir / f"project_{project_id}_{file_type}.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                # 根据类型添加文件到压缩包
                files_to_add = []
                
                if file_type == "all":
                    if os.path.exists(file.file_path):
                        files_to_add.append((file.file_path, f"original/{get_safe_filename(file.original_filename)}"))
                    if file.converted_path and os.path.exists(file.converted_path):
                        files_to_add.append((file.converted_path, f"converted/{Path(file.converted_path).name}"))
                    if file.excel_path and os.path.exists(file.excel_path):
                        files_to_add.append((file.excel_path, f"excel/{Path(file.excel_path).name}"))
                    if file.translated_path and os.path.exists(file.translated_path):
                        files_to_add.append((file.translated_path, f"translated/{Path(file.translated_path).name}"))
                elif file_type == "original" and os.path.exists(file.file_path):
                    files_to_add.append((file.file_path, get_safe_filename(file.original_filename)))
                elif file_type == "converted" and file.converted_path and os.path.exists(file.converted_path):
                    files_to_add.append((file.converted_path, Path(file.converted_path).name))
                elif file_type == "excel" and file.excel_path and os.path.exists(file.excel_path):
                    files_to_add.append((file.excel_path, Path(file.excel_path).name))
                elif file_type == "translated" and file.translated_path and os.path.exists(file.translated_path):
                    files_to_add.append((file.translated_path, Path(file.translated_path).name))
                
                for source_path, archive_name in files_to_add:
                    zipf.write(source_path, archive_name)
        
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            raise HTTPException(status_code=404, detail="没有找到可下载的文件")
        
        logger.info("批量下载包创建成功", project_id=project_id, zip_size=zip_path.stat().st_size)
        
        return FileResponse(
            path=str(zip_path),
            filename=f"project_{project_id}_{file_type}.zip",
            media_type='application/zip'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("创建批量下载包失败", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"创建下载包失败: {str(e)}")
