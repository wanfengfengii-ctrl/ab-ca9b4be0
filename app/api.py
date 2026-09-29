"""双应答机雷达脉冲联合判读业务 API。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .solver import interpret

app = FastAPI(
    title="双应答机脉冲联合判读 API",
    version="1.0.0",
    description="从混合雷达脉冲中联合还原两台固定整数周期的应答机。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MachineInput(BaseModel):
    period_min: int = Field(..., ge=10, le=200, description="重复周期下限（微秒）")
    period_max: int = Field(..., ge=10, le=200, description="重复周期上限（微秒）")
    tolerance: int = Field(..., ge=0, le=1000,
                           description="单周期计时误差（微秒）")
    max_missing: int = Field(..., ge=0, le=200, description="最多漏收数")

    @field_validator("period_max")
    @classmethod
    def _order(cls, v, info):
        lo = info.data.get("period_min")
        if lo is not None and v < lo:
            raise ValueError("period_max 不能小于 period_min")
        return v


class InterpretRequest(BaseModel):
    times: list[int] = Field(..., description="严格递增的到达时刻（微秒）")
    machine_a: MachineInput
    machine_b: MachineInput

    @field_validator("times")
    @classmethod
    def _count(cls, v):
        if not (8 <= len(v) <= 16):
            raise ValueError("需要 8 至 16 条到达时刻")
        return v


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/interpret")
def api_interpret(req: InterpretRequest):
    try:
        result = interpret(req.times,
                           req.machine_a.model_dump(),
                           req.machine_b.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not result.feasible:
        return {
            "feasible": False,
            "tied": False,
            "diagnosis": result.diagnosis,
            "solutions": [],
            "first_divergence": None,
        }
    return {
        "feasible": True,
        "tied": result.tied,
        "solutions": result.solutions,
        "first_divergence": result.first_divergence,
        "diagnosis": None,
    }
