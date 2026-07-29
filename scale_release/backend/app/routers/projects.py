#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目管理API路由
Project Management API Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
import structlog
from datetime import datetime

from ..config import get_settings
from ..database import get_db, Project, ProjectFile, ProcessingTask
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, 
    ProjectListResponse, ProjectDetailResponse
)
from ..services.tasks.cad_tasks import process_project_batch_task
from ..services.cad_pipeline_service import cad_pipeline_service
from ..security import require_admin_access

logger = structlog.get_logger(__name__)
router = APIRouter()
settings = get_settings()

@router.get("/summary")
async def get_projects_summary(db: Session = Depends(get_db)):
    """Overview payload for dashboard and projects center."""
    try:
        status_rows = db.query(Project.status, func.count(Project.id)).group_by(Project.status).all()
        status_counts = {status: count for status, count in status_rows}

        recent_projects = (
            db.query(Project)
            .order_by(Project.updated_at.desc(), Project.created_at.desc())
            .limit(5)
            .all()
        )
        recent_task_rows = (
            db.query(ProcessingTask, Project.name)
            .join(Project, Project.id == ProcessingTask.project_id)
            .order_by(ProcessingTask.updated_at.desc(), ProcessingTask.created_at.desc())
            .limit(10)
            .all()
        )

        total_files = db.query(func.coalesce(func.sum(Project.total_files), 0)).scalar() or 0
        processed_files = db.query(func.coalesce(func.sum(Project.processed_files), 0)).scalar() or 0
        total_texts = db.query(func.coalesce(func.sum(Project.total_texts), 0)).scalar() or 0
        translated_texts = db.query(func.coalesce(func.sum(Project.translated_texts), 0)).scalar() or 0
        failed_tasks = (
            db.query(func.count(ProcessingTask.id))
            .filter(ProcessingTask.status.in_(["failed", "failure", "revoked"]))
            .scalar()
            or 0
        )
        recoverable_tasks = (
            db.query(func.count(ProcessingTask.id))
            .filter(ProcessingTask.status.in_(["failed", "failure"]))
            .scalar()
            or 0
        )

        release_path = settings.BASE_DIR.parent / "scale_release.zip"
        release_info = None
        if release_path.exists():
            stat = release_path.stat()
            release_info = {
                "filename": release_path.name,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size_bytes": stat.st_size,
            }

        counts = {
            "total_projects": status_counts.get("created", 0)
            + status_counts.get("processing", 0)
            + status_counts.get("completed", 0)
            + status_counts.get("failed", 0)
            + status_counts.get("cancelled", 0),
            "active_projects": status_counts.get("processing", 0),
            "completed_projects": status_counts.get("completed", 0),
            "failed_projects": status_counts.get("failed", 0) + status_counts.get("cancelled", 0),
            "total_files": int(total_files),
            "processed_files": int(processed_files),
            "total_texts": int(total_texts),
            "translated_texts": int(translated_texts),
        }

        recent_projects_payload = [
            {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "total_files": project.total_files,
                "processed_files": project.processed_files,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            }
            for project in recent_projects
        ]
        recent_tasks_payload = [
            {
                "task_id": task.task_id,
                "project_id": task.project_id,
                "project_name": project_name,
                "task_type": task.task_type,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
            for task, project_name in recent_task_rows
        ]

        # CAD Workspace currently persists most runtime task state on disk.
        # When the SQL tables are empty, derive dashboard/project summaries from task artifacts.
        if counts["total_projects"] == 0 and not recent_tasks_payload:
            artifact_tasks = cad_pipeline_service.list_tasks()
            counts["total_projects"] = len(artifact_tasks)
            counts["active_projects"] = sum(
                1 for task in artifact_tasks if not task.get("files", {}).get("translated_cad_file") and not task.get("extract_only")
            )
            counts["completed_projects"] = sum(
                1 for task in artifact_tasks if task.get("files", {}).get("translated_cad_file")
            )
            counts["failed_projects"] = 0
            counts["total_files"] = len(artifact_tasks)
            counts["processed_files"] = counts["completed_projects"]
            counts["total_texts"] = sum(int(task.get("text_count") or 0) for task in artifact_tasks)
            counts["translated_texts"] = sum(int(task.get("translation_count") or 0) for task in artifact_tasks)
            recent_tasks_payload = [
                {
                    "task_id": task.get("task_id"),
                    "project_id": None,
                    "project_name": task.get("original_filename"),
                    "task_type": "cad_pipeline",
                    "status": "completed" if task.get("files", {}).get("translated_cad_file") else "processing",
                    "progress": 100 if task.get("files", {}).get("translated_cad_file") else 68,
                    "message": f"{int(task.get('translation_count') or 0)} translated / {int(task.get('text_count') or 0)} extracted",
                    "updated_at": None,
                }
                for task in artifact_tasks[:10]
            ]

        return {
            "counts": counts,
            "status_breakdown": status_counts,
            "alerts": {
                "failed_tasks": int(failed_tasks),
                "recoverable_tasks": int(recoverable_tasks),
            },
            "recent_projects": recent_projects_payload,
            "recent_tasks": recent_tasks_payload,
            "last_release": release_info,
        }
    except Exception as e:
        logger.error("鑾峰彇椤圭洰姒傝澶辫触", error=str(e))
        raise HTTPException(status_code=500, detail=f"鑾峰彇椤圭洰姒傝澶辫触: {str(e)}")

@router.post("/", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db)
):
    """创建新项目"""
    logger.info("创建新项目", name=project.name)
    
    try:
        db_project = Project(
            name=project.name,
            description=project.description,
            source_language=project.source_language,
            target_language=project.target_language,
            font_name=project.font_name,
            font_size_reduction=project.font_size_reduction,
            translation_mode=project.translation_mode,
            status="created"
        )
        
        db.add(db_project)
        db.commit()
        db.refresh(db_project)
        
        logger.info("项目创建成功", project_id=db_project.id, name=project.name)
        return ProjectResponse.from_orm(db_project)
        
    except Exception as e:
        logger.error("创建项目失败", error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建项目失败: {str(e)}")

@router.get("/", response_model=List[ProjectListResponse])
async def list_projects(
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(20, ge=1, le=100, description="返回的记录数"),
    status: Optional[str] = Query(None, description="项目状态筛选"),
    db: Session = Depends(get_db)
):
    """获取项目列表"""
    logger.info("获取项目列表", skip=skip, limit=limit, status=status)
    
    try:
        query = db.query(Project)
        
        if status:
            query = query.filter(Project.status == status)
        
        projects = query.offset(skip).limit(limit).all()
        
        logger.info("项目列表获取成功", count=len(projects))
        return [ProjectListResponse.from_orm(project) for project in projects]
        
    except Exception as e:
        logger.error("获取项目列表失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取项目列表失败: {str(e)}")

@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    db: Session = Depends(get_db)
):
    """获取项目详情"""
    logger.info("获取项目详情", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取项目文件
        files = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
        
        # 获取处理任务
        tasks = db.query(ProcessingTask).filter(ProcessingTask.project_id == project_id).all()
        
        logger.info("项目详情获取成功", project_id=project_id, files_count=len(files), tasks_count=len(tasks))
        
        return ProjectDetailResponse(
            **project.__dict__,
            files=[file.__dict__ for file in files],
            tasks=[task.__dict__ for task in tasks]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取项目详情失败", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取项目详情失败: {str(e)}")

@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """更新项目信息"""
    logger.info("更新项目信息", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 更新项目字段
        update_data = project_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        
        project.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(project)
        
        logger.info("项目信息更新成功", project_id=project_id)
        return ProjectResponse.from_orm(project)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("更新项目信息失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新项目信息失败: {str(e)}")


@router.delete("/clear", dependencies=[Depends(require_admin_access)])
async def clear_all_data(db: Session = Depends(get_db)):
    """清空所有项目和任务数据 (供开发/测试系统清理使用)"""
    logger.info("清空所有系统数据")
    try:
        # 删除所有处理任务
        db.query(ProcessingTask).delete()
        # 删除所有项目文件
        db.query(ProjectFile).delete()
        # 删除所有项目
        db.query(Project).delete()
        
        db.commit()
        
        # 尝试清理旧的基于本地文件系统的缓存 (Artifact task 列表)
        try:
            cad_pipeline_service.clear_all_tasks()
        except AttributeError:
            pass
            
        return {"message": "所有项目和任务数据已清空"}
    except Exception as e:
        logger.error("清空数据失败", error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"清空数据失败: {str(e)}")


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db)
):
    """删除项目"""
    logger.info("删除项目", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 删除项目（级联删除相关文件和任务）
        db.delete(project)
        db.commit()
        
        logger.info("项目删除成功", project_id=project_id)
        return {"message": "项目删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除项目失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除项目失败: {str(e)}")

@router.post("/{project_id}/process")
async def start_project_processing(
    project_id: int,
    db: Session = Depends(get_db)
):
    """启动项目批量处理 - 一键处理功能"""
    logger.info("启动项目批量处理", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 检查项目状态
        if project.status == "processing":
            raise HTTPException(status_code=400, detail="项目正在处理中")
        
        # 检查是否有文件
        files_count = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).count()
        if files_count == 0:
            raise HTTPException(status_code=400, detail="项目中没有文件")
        
        # 准备处理配置
        config = {
            "font_name": project.font_name,
            "translation_mode": project.translation_mode,
            "font_size_reduction": project.font_size_reduction,
            "source_language": project.source_language,
            "target_language": project.target_language,
            "auto_translate": False  # 第一阶段暂不支持自动翻译
        }
        
        # 启动批量处理任务
        task = process_project_batch_task.delay(project_id, config)
        
        # 创建任务记录
        db_task = ProcessingTask(
            project_id=project_id,
            task_id=task.id,
            task_type="batch_process",
            status="pending",
            message="批量处理任务已启动"
        )
        db.add(db_task)
        
        # 更新项目状态
        project.status = "processing"
        project.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info("项目批量处理任务启动成功", project_id=project_id, task_id=task.id)
        
        return {
            "message": "批量处理任务已启动",
            "task_id": task.id,
            "project_status": "processing"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("启动项目批量处理失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"启动批量处理失败: {str(e)}")

@router.get("/{project_id}/status")
async def get_project_status(
    project_id: int,
    db: Session = Depends(get_db)
):
    """获取项目处理状态"""
    logger.info("获取项目处理状态", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取最新的处理任务
        latest_task = db.query(ProcessingTask).filter(
            ProcessingTask.project_id == project_id
        ).order_by(ProcessingTask.created_at.desc()).first()
        
        # 获取文件统计
        files_stats = db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
        
        status_counts = {}
        for file in files_stats:
            status = file.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        result = {
            "project_id": project_id,
            "project_status": project.status,
            "total_files": len(files_stats),
            "processed_files": project.processed_files,
            "file_status_counts": status_counts,
            "latest_task": None
        }
        
        if latest_task:
            result["latest_task"] = {
                "task_id": latest_task.task_id,
                "task_type": latest_task.task_type,
                "status": latest_task.status,
                "progress": latest_task.progress,
                "message": latest_task.message,
                "created_at": latest_task.created_at,
                "updated_at": latest_task.updated_at
            }
        
        logger.info("项目处理状态获取成功", project_id=project_id, status=project.status)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取项目处理状态失败", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"获取项目状态失败: {str(e)}")

@router.post("/{project_id}/cancel")
async def cancel_project_processing(
    project_id: int,
    db: Session = Depends(get_db)
):
    """取消项目处理"""
    logger.info("取消项目处理", project_id=project_id)
    
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        if project.status != "processing":
            raise HTTPException(status_code=400, detail="项目当前不在处理中")
        
        # 获取正在运行的任务
        running_tasks = db.query(ProcessingTask).filter(
            ProcessingTask.project_id == project_id,
            ProcessingTask.status.in_(["pending", "running"])
        ).all()
        
        # 取消Celery任务
        from ..services.celery_app import celery_app
        cancelled_count = 0
        
        for task in running_tasks:
            try:
                celery_app.control.revoke(task.task_id, terminate=True)
                task.status = "revoked"
                task.message = "任务已被用户取消"
                task.completed_at = datetime.utcnow()
                cancelled_count += 1
            except Exception as e:
                logger.warning("取消任务失败", task_id=task.task_id, error=str(e))
        
        # 更新项目状态
        project.status = "cancelled"
        project.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info("项目处理已取消", project_id=project_id, cancelled_tasks=cancelled_count)
        
        return {
            "message": "项目处理已取消",
            "cancelled_tasks": cancelled_count,
            "project_status": "cancelled"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("取消项目处理失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"取消项目处理失败: {str(e)}")
