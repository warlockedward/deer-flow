import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.tools.builtins.bayesian_inference import update_priors
from src.tools.builtins.lead_scoring import (
    compute_lead_score,
    record_conversion_feedback,
)
from src.tools.builtins.lead_scoring import (
    load_industry_config as load_industry_cfg,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadScoreRequest(BaseModel):
    lead: dict[str, Any] = Field(..., description="Lead payload including signals and financial indicators")
    client: str = Field(default="action_education", description="Client identifier for feedback weighting")


@router.post(
    "/score",
    summary="Score Lead",
    description="Compute automated lead score with A/B/C classification and HITL trigger.",
)
async def score_lead(req: LeadScoreRequest) -> dict:
    try:
        return compute_lead_score(lead=req.lead, client=req.client).model_dump()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("Lead scoring failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Lead scoring failed") from e


class LeadFeedbackRequest(BaseModel):
    client: str = Field(default="action_education", description="Client identifier for feedback weighting")
    industry: str = Field(..., description="Industry key used for path weighting")
    outcome: str = Field(..., description="positive|negative|neutral feedback outcome")
    signal_names: list[str] | None = Field(default=None, description="Optional signal names to adjust (RLHF)")


@router.post(
    "/feedback",
    summary="Submit Feedback",
    description="Submit positive/negative feedback to update conversion path weights and optional signal weights.",
)
async def submit_feedback(req: LeadFeedbackRequest) -> dict[str, Any]:
    try:
        industry_config = load_industry_cfg(str(req.industry))
        known: set[str] = set()
        rels = industry_config.get("causal_relationships") if isinstance(industry_config.get("causal_relationships"), list) else []
        for r in rels:
            if isinstance(r, dict):
                eff = r.get("effect")
                if isinstance(eff, str) and eff.strip():
                    known.add(eff.strip())
        rules = industry_config.get("conflict_rules") if isinstance(industry_config.get("conflict_rules"), list) else []
        for rule in rules:
            if isinstance(rule, dict):
                ts = rule.get("trigger_signals")
                if isinstance(ts, list):
                    for t in ts:
                        if isinstance(t, str) and t.strip():
                            known.add(t.strip())

        if req.signal_names:
            invalid = [s for s in req.signal_names if not isinstance(s, str) or not s.strip() or s.strip() not in known]
            if invalid:
                raise HTTPException(status_code=422, detail=f"Unknown signal_names: {invalid}")

        new_weight = record_conversion_feedback(client=str(req.client), industry=str(req.industry), outcome=str(req.outcome))

        signal_updates: dict[str, float] = {}
        out = str(req.outcome).strip().lower()
        if req.signal_names and out in {"positive", "negative"}:
            delta = 0.05 if out == "positive" else -0.05
            for name in req.signal_names:
                n = str(name).strip()
                update_priors(signal_name=n, adjustment=delta, feedback_type="signal")
                signal_updates[n] = delta

        return {
            "success": True,
            "client": str(req.client),
            "industry": str(req.industry),
            "outcome": str(req.outcome).strip().lower(),
            "conversion_path_weight": float(new_weight),
            "signal_updates": signal_updates,
        }
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("Lead feedback failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Lead feedback failed") from e
