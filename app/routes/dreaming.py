from fastapi import APIRouter, Request
from app import dreaming
from app.deps import manager
from app.routes.always_on import operator

router = APIRouter(prefix="/api/dreaming",tags=["dreaming"])


@router.post("/run")
def run(request: Request):
    operator(request)
    return dreaming.run_dreaming_pass(manager)


@router.get("/runs")
def runs(request: Request,limit: int=100):
    operator(request)
    return dreaming.list_runs(limit)
