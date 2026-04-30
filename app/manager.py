"""Worker Manager — spawn, track, and control multiple workers."""

import logging
from pathlib import Path
from typing import Optional

from app.worker import Worker, WorkerStatus

logger = logging.getLogger(__name__)

WORKER_MD_PATH = Path.home() / ".claude" / "agents" / "worker.md"


class WorkerManager:
    def __init__(self):
        self.workers: dict[str, Worker] = {}

    def _load_worker_md(self) -> str:
        if WORKER_MD_PATH.exists():
            return WORKER_MD_PATH.read_text()
        return ""

    async def spawn(self, name: str, task: str, repo_path: str,
                    model: str = "claude-sonnet-4-6") -> Worker:
        if name in self.workers:
            existing = self.workers[name]
            if existing.status in (WorkerStatus.WORKING, WorkerStatus.SPAWNING):
                raise ValueError(f"Worker '{name}' already running")
            await existing.kill()

        worker_md = self._load_worker_md()
        worker = Worker(
            name=name,
            task=task,
            repo_path=repo_path,
            model=model,
            system_prompt=worker_md,
        )
        self.workers[name] = worker
        await worker.spawn()
        logger.info(f"Spawned worker '{name}' on {repo_path}")
        return worker

    async def inject(self, name: str, message: str) -> bool:
        worker = self.workers.get(name)
        if not worker:
            return False
        return await worker.inject(message)

    async def interrupt(self, name: str):
        worker = self.workers.get(name)
        if worker:
            await worker.interrupt()

    async def kill(self, name: str):
        worker = self.workers.get(name)
        if worker:
            await worker.kill()
            logger.info(f"Killed worker '{name}'")

    async def kill_all(self):
        for name in list(self.workers.keys()):
            await self.kill(name)

    def get(self, name: str) -> Optional[Worker]:
        return self.workers.get(name)

    def list_all(self) -> list[dict]:
        return [w.to_dict() for w in self.workers.values()]

    def active_count(self) -> int:
        return sum(1 for w in self.workers.values()
                   if w.status in (WorkerStatus.WORKING, WorkerStatus.SPAWNING))


manager = WorkerManager()
