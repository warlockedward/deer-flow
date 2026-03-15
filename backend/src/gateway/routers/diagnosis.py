import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.subagents.semantic_diagnosis_pipeline import (
    claim_hitl_task,
    get_hitl_task,
    list_hitl_tasks,
    resolve_hitl_task,
    run_semantic_diagnosis_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnosis", tags=["diagnosis"])


class DiagnosisRunRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID used for audit and sandboxed paths")
    company_name: str = Field(..., description="Company name to diagnose")
    industry: str = Field(..., description="Industry map name (e.g. high_tech)")
    model_name: str | None = Field(None, description="Optional model override")
    hitl_approved: bool = Field(False, description="Whether human-in-the-loop approval was granted")
    reviewer: str | None = Field(None, description="Optional reviewer identifier for audit")
    hitl_task_id: str | None = Field(None, description="Optional HITL task id for sealing logic")


@router.post(
    "/run",
    summary="Run Semantic Diagnosis",
    description="Run deterministic semantic diagnosis pipeline with hard gates and audit logging.",
)
async def run_diagnosis(req: DiagnosisRunRequest) -> dict:
    try:
        return run_semantic_diagnosis_pipeline(
            thread_id=req.thread_id,
            company_name=req.company_name,
            industry=req.industry,
            model_name=req.model_name,
            hitl_approved=req.hitl_approved,
            reviewer=req.reviewer,
            hitl_task_id=req.hitl_task_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("Diagnosis run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Diagnosis run failed") from e


@router.get(
    "/hitl/tasks",
    summary="List HITL Tasks",
    description="List diagnosis HITL tasks stored on disk, optionally filtered by status.",
)
async def list_tasks(status: str | None = Query(default=None, description="pending|claimed|resolved")) -> dict:
    try:
        return {"tasks": list_hitl_tasks(status=status)}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("List HITL tasks failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="List HITL tasks failed") from e


@router.get(
    "/hitl/tasks/{task_id}",
    summary="Get HITL Task",
    description="Get a single HITL task by id.",
)
async def get_task(task_id: str) -> dict:
    t = get_hitl_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")
    return t


class HitlTaskClaimRequest(BaseModel):
    reviewer: str = Field(..., description="Reviewer identifier claiming the task")


@router.post(
    "/hitl/tasks/{task_id}/claim",
    summary="Claim HITL Task",
    description="Claim a pending HITL task for a reviewer.",
)
async def claim_task(task_id: str, req: HitlTaskClaimRequest) -> dict:
    try:
        return claim_hitl_task(task_id=task_id, reviewer=req.reviewer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("Claim HITL task failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Claim HITL task failed") from e


class HitlTaskResolveRequest(BaseModel):
    reviewer: str = Field(..., description="Reviewer identifier resolving the task")
    decision: str = Field(..., description="approve|reject|modify")
    review_notes: str = Field(default="", description="Reviewer notes")
    seal_logical_gap: bool = Field(default=True, description="Whether to seal logical gaps and allow briefing")
    patch: dict | None = Field(default=None, description="Optional patch payload attached to consultant seal")


@router.post(
    "/hitl/tasks/{task_id}/resolve",
    summary="Resolve HITL Task",
    description="Resolve an HITL task with decision and optional logical sealing patch.",
)
async def resolve_task(task_id: str, req: HitlTaskResolveRequest) -> dict:
    try:
        return resolve_hitl_task(
            task_id=task_id,
            reviewer=req.reviewer,
            decision=req.decision,
            review_notes=req.review_notes,
            seal_logical_gap=req.seal_logical_gap,
            patch=req.patch,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("Resolve HITL task failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Resolve HITL task failed") from e
