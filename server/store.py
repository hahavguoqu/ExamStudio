import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
ROOT = Path(os.getenv("DATA_DIR", Path(__file__).with_name("data"))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
_lock = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def task_dir(task_id: str):
    if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
        raise ValueError("无效任务编号")
    return ROOT / task_id


def load(task_id: str):
    with _lock:
        return json.loads((task_dir(task_id) / "task.json").read_text("utf-8"))


def save(task):
    with _lock:
        folder = task_dir(task["id"])
        folder.mkdir(parents=True, exist_ok=True)
        task["updated_at"] = now()
        target = folder / "task.json"
        temp = folder / f"{uuid.uuid4().hex}.tmp"
        temp.write_text(json.dumps(task, ensure_ascii=False, indent=2), "utf-8")
        temp.replace(target)


def update(task_id: str, **fields):
    with _lock:
        task = load(task_id)
        task.update(fields)
        save(task)
        return task


def create(title: str, mode: str, options: dict, **extra):
    task = dict(id=uuid.uuid4().hex, title=title, mode=mode,
                options=options, status="queued", stage="等待处理", progress=0,
                created_at=now(), updated_at=now(), files=[], pages=[],
                paper=None, messages=[], exports=[], error=None, demo=False,
                **extra)
    save(task)
    return task


def all_tasks():
    result = []
    with _lock:
        for file in ROOT.glob("*/task.json"):
            try:
                task = json.loads(file.read_text("utf-8"))
                if not task.get("deleted_at"):
                    result.append(task)
            except (ValueError, OSError):
                continue
    return sorted(result, key=lambda t: t["created_at"], reverse=True)


def add_message(task_id, role, content, question_id=None):
    with _lock:
        task = load(task_id)
        task["messages"].append(dict(role=role, content=content,
                                     question_id=question_id, time=now()))
        save(task)


def recover():
    for task in all_tasks():
        if task["status"] in ("queued", "running"):
            update(task["id"], status="interrupted", stage="服务重启，任务中断",
                   error="已经保存当前结果。可点击重试重新运行；不会自动重复产生 API 费用。")
