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
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from ..config import get_settings
from ..database import (
    get_db, Project, ProjectFile, ProcessingTask, TextExtraction,
    TranslationCache,
)
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, 
    ProjectListResponse, ProjectDetailResponse
)
from ..services.tasks.cad_tasks import process_project_batch_task
from ..services.cad_pipeline_service import cad_pipeline_service
from ..security import require_admin_access
from ..utils.file_utils import resolve_within_directory

logger = structlog.get_logger(__name__)
router = APIRouter()
settings = get_settings()


def _remove_project_artifacts(project_id: int, files: list[ProjectFile]) -> list[str]:
    """Remove only paths contained by configured upload/output roots."""
    roots = [settings.get_upload_path(), settings.get_output_path()]
    failures: list[str] = []
    candidates = {
        str(value)
        for file in files
        for value in (
            file.file_path,
            file.converted_path,
            file.excel_path,
            file.translated_path,
        )
        if value
    }
    for raw_path in candidates:
        allowed = None
        for root in roots:
            try:
                allowed = resolve_within_directory(root, raw_path)
                break
            except ValueError:
                continue
        if allowed is None:
            failures.append(f"拒绝删除允许目录之外的文件: {raw_path}")
            continue
        try:
            allowed.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"删除文件失败 {allowed}: {exc}")
    project_upload = resolve_within_directory(
        settings.get_upload_path(), f"project_{project_id}"
    )
    try:
        if project_upload.exists():
            shutil.rmtree(project_upload)
    except OSError as exc:
        failures.append(f"删除项目上传目录失败 {project_upload}: {exc}")
    return failures

@router.get("/summary", dependencies=[Depends(require_admin_access)])
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

        total_projects = db.query(func.count(Project.id)).scalar() or 0
        total_files = db.query(func.count(ProjectFile.id)).scalar() or 0
        processed_files = (
            db.query(func.count(ProjectFile.id))
            .filter(ProjectFile.status.notin_(["uploaded", "failed"]))
            .scalar()
            or 0
        )
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
            "total_projects": int(total_projects),
            "active_projects": status_counts.get("processing", 0),
            "completed_projects": status_counts.get("completed", 0)
            + status_counts.get("partially_completed", 0),
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

        # SQL projects and canonical filesystem tasks are independent live
        # stores. Include both on every request and report their persisted
        # status instead of hiding one whenever the other is non-empty.
        artifact_tasks = cad_pipeline_service.list_tasks()
        artifact_status_counts: dict[str, int] = {}
        artifact_payload = []
        for task in artifact_tasks:
            status = str(task.get("status") or "queued").lower()
            artifact_status_counts[status] = artifact_status_counts.get(status, 0) + 1
            total_chunks = int(task.get("total_chunks") or 0)
            completed_chunks = int(task.get("completed_chunks") or 0)
            progress = (
                min(100.0, completed_chunks * 100.0 / total_chunks)
                if total_chunks
                else (100.0 if status in {"done", "partial"} else 0.0)
            )
            updated_timestamp = task.get("last_activity_at") or task.get("created_at")
            artifact_payload.append(
                {
                    "task_id": task.get("task_id"),
                    "project_id": None,
                    "project_name": task.get("original_filename"),
                    "task_type": "cad_pipeline",
                    "status": status,
                    "progress": progress,
                    "message": (
                        f"stage={task.get('stage') or 'queued'}; "
                        f"{int(task.get('translation_count') or 0)} translated / "
                        f"{int(task.get('text_count') or 0)} extracted"
                    ),
                    "updated_at": (
                        datetime.fromtimestamp(float(updated_timestamp)).isoformat()
                        if updated_timestamp
                        else None
                    ),
                }
            )

        active_artifacts = sum(
            artifact_status_counts.get(status, 0)
            for status in ("queued", "processing")
        )
        completed_artifacts = sum(
            artifact_status_counts.get(status, 0) for status in ("done", "partial")
        )
        failed_artifacts = sum(
            artifact_status_counts.get(status, 0) for status in ("error", "cancelled")
        )
        counts["total_projects"] += len(artifact_tasks)
        counts["active_projects"] += active_artifacts
        counts["completed_projects"] += completed_artifacts
        counts["failed_projects"] += failed_artifacts
        counts["total_files"] += len(artifact_tasks)
        counts["processed_files"] += completed_artifacts
        counts["total_texts"] += sum(
            int(task.get("text_count") or 0) for task in artifact_tasks
        )
        counts["translated_texts"] += sum(
            int(task.get("translation_count") or 0) for task in artifact_tasks
        )
        recent_tasks_payload = sorted(
            [*recent_tasks_payload, *artifact_payload],
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )[:10]

        return {
            "counts": counts,
            "status_breakdown": status_counts,
            "alerts": {
                "failed_tasks": int(failed_tasks) + failed_artifacts,
                "recoverable_tasks": int(recoverable_tasks)
                + artifact_status_counts.get("error", 0)
                + artifact_status_counts.get("partial", 0),
            },
            "artifact_status_breakdown": artifact_status_counts,
            "recent_projects": recent_projects_payload,
            "recent_tasks": recent_tasks_payload,
            "last_release": release_info,
        }
    except Exception as e:
        logger.error("鑾峰彇椤圭洰姒傝澶辫触", error=str(e))
        raise HTTPException(status_code=500, detail=f"鑾峰彇椤圭洰姒傝澶辫触: {str(e)}")

@router.post("/", response_model=ProjectResponse, dependencies=[Depends(require_admin_access)])
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
        return ProjectResponse.model_validate(db_project)
        
    except Exception as e:
        logger.error("创建项目失败", error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建项目失败: {str(e)}")

@router.get("/", response_model=List[ProjectListResponse], dependencies=[Depends(require_admin_access)])
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
        return [ProjectListResponse.model_validate(project) for project in projects]
        
    except Exception as e:
        logger.error("获取项目列表失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"获取项目列表失败: {str(e)}")

@router.get("/{project_id}", response_model=ProjectDetailResponse, dependencies=[Depends(require_admin_access)])
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

@router.put("/{project_id}", response_model=ProjectResponse, dependencies=[Depends(require_admin_access)])
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
        update_data = project_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        
        project.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(project)
        
        logger.info("项目信息更新成功", project_id=project_id)
        return ProjectResponse.model_validate(project)
        
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
        db.query(TextExtraction).delete()
        db.query(TranslationCache).delete()
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


@router.delete("/{project_id}", dependencies=[Depends(require_admin_access)])
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
        
        project_files = list(project.files)
        # 先提交级联数据库删除，再受控清理本项目拥有的文件。
        db.query(TextExtraction).filter(
            TextExtraction.project_id == project_id
        ).delete(synchronize_session=False)
        db.delete(project)
        db.commit()
        cleanup_failures = _remove_project_artifacts(project_id, project_files)
        for failure in cleanup_failures:
            logger.warning("project_artifact_cleanup_failed", detail=failure)
        
        logger.info("项目删除成功", project_id=project_id)
        return {
            "message": "项目删除成功",
            "cleanup_complete": not cleanup_failures,
            "cleanup_errors": cleanup_failures,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除项目失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除项目失败: {str(e)}")

@router.post("/{project_id}/process", dependencies=[Depends(require_admin_access)])
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
        
        task_id = uuid.uuid4().hex
        # Claim the project in the database before dispatch. The conditional
        # update serializes concurrent start requests across API workers.
        claimed = (
            db.query(Project)
            .filter(Project.id == project_id, Project.status != "processing")
            .update(
                {
                    Project.status: "processing",
                    Project.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="项目已有正在执行的任务")

        # Persist the durable task row before eager or remote workers can emit
        # lifecycle signals for this exact task id.
        db_task = ProcessingTask(
            project_id=project_id,
            task_id=task_id,
            task_type="batch_process",
            status="pending",
            message="批量处理任务等待执行"
        )
        db.add(db_task)
        db.commit()

        try:
            process_project_batch_task.apply_async(
                args=(project_id, config), task_id=task_id
            )
        except Exception as exc:
            db.rollback()
            failed_task = db.query(ProcessingTask).filter(
                ProcessingTask.task_id == task_id
            ).first()
            failed_project = db.query(Project).filter(Project.id == project_id).first()
            if failed_task:
                failed_task.status = "failure"
                failed_task.message = "任务派发失败"
                failed_task.error_message = str(exc)
                failed_task.completed_at = datetime.now(timezone.utc)
            if failed_project:
                failed_project.status = "failed"
            db.commit()
            raise HTTPException(status_code=503, detail=f"任务派发失败: {exc}") from exc

        db.expire_all()
        effective_project = db.query(Project).filter(Project.id == project_id).first()
        effective_task = db.query(ProcessingTask).filter(
            ProcessingTask.task_id == task_id
        ).first()
        project_status = effective_project.status if effective_project else "failed"
        task_status = effective_task.status if effective_task else "failure"
        logger.info("项目批量处理任务启动成功", project_id=project_id, task_id=task_id)

        return {
            "message": "批量处理任务已提交",
            "task_id": task_id,
            "task_status": task_status,
            "project_status": project_status,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("启动项目批量处理失败", project_id=project_id, error=str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"启动批量处理失败: {str(e)}")

@router.get("/{project_id}/status", dependencies=[Depends(require_admin_access)])
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

@router.post("/{project_id}/cancel", dependencies=[Depends(require_admin_access)])
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
                task.completed_at = datetime.now(timezone.utc)
                cancelled_count += 1
            except Exception as e:
                logger.warning("取消任务失败", task_id=task.task_id, error=str(e))
        
        # 更新项目状态
        project.status = "cancelled"
        project.updated_at = datetime.now(timezone.utc)
        
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
