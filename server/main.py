from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Environment must be loaded before model concurrency/configuration is initialized.
import store
import demo
import documents
import model
import pipeline
import drafts
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from schemas import ChatRequest, GenerateRequest, Options, BriefInput, BriefConfirm


@asynccontextmanager
async def lifespan(app):
    store.recover()
    yield
    active = list(pipeline.RUNNING.values())
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)


app = FastAPI(title="试卷工作室", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


class KeySettings(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


@app.post("/settings/key")
async def save_key(body: KeySettings, request: Request):
    # Desktop-only; even authenticated remote clients cannot change credentials.
    host = request.client.host if request.client else ""
    if not os.getenv("SHIJUAN_PROFILE") or host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "请在 Windows 桌面软件中配置 API Key。")
    key = body.api_key.strip()
    if not key or any(c.isspace() for c in key):
        raise HTTPException(422, "API Key 不能为空或包含空格。")
    import desktop_settings
    desktop_settings.save(key)
    return {"model_configured": True}


@app.middleware("http")
async def authenticate(request: Request, call_next):
    token = os.getenv("SERVICE_TOKEN", "")
    host = request.client.host if request.client else ""
    if token:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(token, supplied):
            return JSONResponse({"detail": "服务连接口令不正确，请在设置中检查。"}, 401)
    else:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "testclient"
        if not local:
            return JSONResponse({"detail": "远程连接需先在服务端配置 SERVICE_TOKEN。"}, 403)
    return await call_next(request)


def get_task(task_id):
    try:
        task = store.load(task_id)
        if task.get("deleted_at"):
            raise HTTPException(404, "任务已删除")
        snapshot = drafts.current(task)
        if snapshot.get('questions'):
            task['paper'] = snapshot
        task['draft_versions'] = [f'候选版本 {i+1}' for i, _ in enumerate(drafts.versions(task))]
        if task.get("source_id"):
            try:
                source = store.load(task["source_id"])
                if not source.get("deleted_at"):
                    task["source_summary"] = {"id": source["id"], "title": source["title"],
                                              "files": [f["name"] for f in source.get("files", [])]}
            except (ValueError, FileNotFoundError):
                pass
        return task
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "任务不存在")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "model_configured": model.configured(),
            "legacy_doc_supported": bool(documents.office_binary()),
            "vision_model": os.getenv("VISION_MODEL", "deepseek-flash")}


@app.get("/tasks")
async def tasks():
    return [{k: t.get(k) for k in ("id", "title", "mode", "status", "stage", "progress", "created_at", "demo")}
            for t in store.all_tasks()]


@app.get("/tasks/{task_id}")
async def task_detail(task_id: str):
    return get_task(task_id)


class TaskRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.patch("/tasks/{task_id}")
async def rename_task(task_id: str, body: TaskRename):
    task = get_task(task_id)
    if task_id in pipeline.RUNNING or task["status"] in ("running", "queued"):
        raise HTTPException(409, "请先停止处理，再修改名称。")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "名称不能为空。")
    return store.update(task_id, title=title)


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    task = get_task(task_id)
    if task_id in pipeline.RUNNING or task["status"] in ("running", "queued"):
        raise HTTPException(409, "请先停止处理，再删除任务。")
    # Keep source data available to existing derived tasks and their retry operations.
    store.update(task_id, deleted_at=store.now())
    return {"deleted": True}


@app.post("/tasks")
async def upload(files: list[UploadFile] = File(...), options: str = Form("{}")):
    if not model.configured():
        raise HTTPException(409, "请先在软件设置中填写 DeepSeek API Key。也可先打开演示材料体验。")
    try:
        settings = Options.model_validate_json(options)
    except ValidationError:
        raise HTTPException(422, "任务设置无效")
    if not files or len(files) > 30:
        raise HTTPException(422, "请选择 1—30 个文件")
    allowed = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".webp"}
    if any(Path(f.filename or "").suffix.lower() not in allowed for f in files):
        raise HTTPException(422, "支持 PDF、DOCX、DOC、PNG、JPG 和 WebP")
    task = store.create(Path(files[0].filename).stem, "convert", settings.model_dump())
    folder = store.task_dir(task["id"])
    (folder / "uploads").mkdir()
    info = []
    total = 0
    try:
        for file in files:
            suffix = Path(file.filename).suffix.lower()
            target = folder / "uploads" / (uuid.uuid4().hex + suffix)
            size = 0
            with target.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > 30 * 1024 * 1024 or total > 100 * 1024 * 1024:
                        raise HTTPException(413, "单文件最多 30 MB，单次总计最多 100 MB")
                    stream.write(chunk)
            if not size:
                raise HTTPException(422, "不能上传空文件")
            info.append({"name": Path(file.filename).name,
                         "path": target.relative_to(folder).as_posix(), "size": size})
    except Exception:
        store.update(task["id"], status="failed", stage="上传未完成", error="文件上传失败，请重新选择文件。")
        raise
    store.update(task["id"], files=info)
    pipeline.launch(task["id"])
    return store.load(task["id"])


@app.post("/demo")
async def demo_task():
    return await asyncio.to_thread(demo.create_demo)


@app.post("/tasks/{task_id}/generate")
async def generate(task_id: str, request: GenerateRequest):
    source = get_task(task_id)
    if not source.get("paper"):
        raise HTTPException(409, "原题尚未整理完成")
    candidates = source["paper"].get("questions", [])
    if request.options.scope == "single":
        candidates = [q for q in candidates if q.get("id") == request.options.question_id]
    if candidates and not any(q.get("content_role", "problem") == "problem" for q in candidates):
        raise HTTPException(409, "这些内容是参考答案或评分标准，可导出 Word；出题需要上传对应的完整题目。")
    if not model.configured():
        raise HTTPException(409, "请在软件设置中填写 DeepSeek API Key 后再出题")
    task = store.create(source["title"] + " · 新卷", "generate",
                        request.options.model_dump(), source_id=task_id)
    pipeline.launch(task["id"])
    return task


@app.post("/brief-tasks")
async def create_brief(request: BriefInput):
    if not model.configured():
        raise HTTPException(409, "请在设置中配置 DeepSeek API Key")
    task = store.create('按要求出题 · 准备中', 'generate',
        Options(scope='single', figures='redraw').model_dump(), brief_input=request.model_dump())
    pipeline.launch(task['id'])
    return store.load(task['id'])


@app.post("/tasks/{task_id}/confirm-brief")
async def confirm_brief(task_id: str, request: BriefConfirm):
    task = get_task(task_id)
    text = request.brief.strip()
    if not text:
        raise HTTPException(422, '命题要求不能为空')
    if task.get('confirmed_brief') == text:
        return task  # Safe to retry a confirmation after a lost network response.
    if task_id in pipeline.RUNNING or task['status'] != 'awaiting_confirmation' or not task.get('brief_input'):
        raise HTTPException(409, '此任务当前不能确认命题要求')
    if not model.configured():
        raise HTTPException(409, '请先配置 API Key')
    store.update(task_id, confirmed_brief=text)
    store.add_message(task_id, 'user', '确认命题要求：\n' + text)
    pipeline.launch(task_id)
    return store.load(task_id)


@app.post("/tasks/{task_id}/retry")
async def retry(task_id: str, body: dict | None = None):
    task = get_task(task_id)
    if task_id in pipeline.RUNNING:
        raise HTTPException(409, "任务仍在运行")
    if task["demo"]:
        raise HTTPException(409, "演示任务无需重试")
    if not model.configured():
        raise HTTPException(409, "请先配置 API Key")
    if task["status"] == "completed" and not task.get("redraw_errors"):
        raise HTTPException(409, "任务已完成，无需重复处理。")
    advice = str((body or {}).get("advice", "")).strip()
    blocker = task.get("source_blocker")
    if advice:
        if not blocker:
            raise HTTPException(409, "当前没有可补充建议的原题检查步骤")
        advice_map = dict(task.get("source_advice", {}))
        advice_map[blocker["question_id"]] = advice
        store.update(task_id, source_advice=advice_map)
        store.add_message(task_id, "user", "原题补充说明：" + advice, blocker["question_id"])
    pipeline.launch(task_id)
    return store.load(task_id)


@app.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str):
    get_task(task_id)
    active = pipeline.RUNNING.get(task_id)
    if active:
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
    return get_task(task_id)


@app.post("/tasks/{task_id}/chat")
async def chat(task_id: str, body: ChatRequest):
    get_task(task_id)
    try:
        reply = await pipeline.chat(task_id, body.message, body.question_id)
        return {"reply": reply}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


class RevisionRequest(BaseModel):
    advice: str = Field(min_length=1, max_length=6000)
    question_id: str | None = None


@app.post('/tasks/{task_id}/revise')
async def revise(task_id: str, body: RevisionRequest):
    task = get_task(task_id)
    advice = body.advice.strip()
    if not advice:
        raise HTTPException(422, '请填写修改意见')
    if not model.configured():
        raise HTTPException(409, '请先配置 API Key')
    paper = task.get('paper') or {}
    questions = paper.get('questions', [])
    selected = [q for q in questions if q['id'] == body.question_id] if body.question_id else questions
    if len(selected) != 1:
        raise HTTPException(422, '请选择一道需要修改的题目')
    import revision
    new = revision.create(task, paper, selected[0], advice)
    pipeline.launch(new['id'])
    return store.load(new['id'])


class FigureChoice(BaseModel):
    question_id: str
    mode: str = Field(pattern="^(original|redraw)$")


class FigureAction(BaseModel):
    question_id: str
    asset_id: str
    action: str = Field(pattern="^(accept|original|repair)$")
    advice: str = ""
    history_index: int | None = Field(default=None, ge=0)


@app.post("/tasks/{task_id}/figure-review")
async def figure_review(task_id: str, body: FigureAction):
    from schemas import Paper
    import visuals
    task = get_task(task_id)
    if task_id in pipeline.RUNNING or task["status"] in ("running", "queued"):
        raise HTTPException(409, "请等待当前处理结束")
    paper = Paper.model_validate(task.get("paper") or {})
    q = next((q for q in paper.questions if q.id == body.question_id), None)
    asset = next((a for a in q.visuals if a.id == body.asset_id), None) if q else None
    if asset is None:
        raise HTTPException(404, "配图不存在")
    image, svg = asset.draft_redrawn_image or asset.redrawn_image, asset.draft_svg_file or asset.svg_file
    if body.history_index is not None:
        if body.history_index >= len(asset.review_history):
            raise HTTPException(404, "草稿版本不存在")
        version = asset.review_history[body.history_index]
        image, svg = version["image"], version["svg"]
    modes = dict(task.get("figure_modes", {}))
    if body.action == "original":
        modes[q.id] = "original"
    else:
        if not image or not svg:
            raise HTTPException(409, "尚无可用草稿")
        visuals.safe_path(store.task_dir(task_id), image)
        visuals.safe_path(store.task_dir(task_id), svg)
        if body.action == "accept":
            asset.redrawn_image, asset.svg_file = image, svg
            asset.human_accepted = True
            modes[q.id] = "redraw"
            visuals.sync_paths(q)
        else:
            if not body.advice.strip():
                raise HTTPException(422, "请填写修改建议")
            if not model.configured():
                raise HTTPException(409, "请先配置 API Key")
            store.add_message(task_id, "user", "配图修改建议：" + body.advice, q.id)
            store.update(task_id, status="queued", stage="已收到配图修改建议，准备重新绘图", error=None)
            pipeline.RUNNING[task_id] = asyncio.create_task(
                pipeline.repair_figure(task_id, paper, q, asset, svg, body.advice, task))
            return store.load(task_id)
    resolved = pipeline.figure_resolution(task, q) if body.action == "accept" else {}
    return store.update(task_id, paper=paper.model_dump(), figure_modes=modes, **resolved)


@app.post("/tasks/{task_id}/figures")
async def choose_figures(task_id: str, body: FigureChoice):
    task = get_task(task_id)
    question = next((q for q in (task.get("paper") or {}).get("questions", []) if q["id"] == body.question_id), None)
    if question is None:
        raise HTTPException(404, "题目不存在")
    if body.mode == "redraw" and not question.get("redrawn_images"):
        raise HTTPException(409, "该题尚无重绘图")
    modes = dict(task.get("figure_modes", {}))
    modes[body.question_id] = body.mode
    return store.update(task_id, figure_modes=modes)


class ExportRequest(BaseModel):
    teacher: bool = False
    version: int | None = Field(default=None, ge=0)


@app.post("/tasks/{task_id}/export")
async def export_current(task_id: str, body: ExportRequest):
    task = get_task(task_id)
    paper = task.get('paper')
    if body.version is not None:
        versions = drafts.versions(task)
        if body.version >= len(versions):
            raise HTTPException(404, '草稿版本不存在')
        paper = versions[body.version]
    if not paper or not paper.get('questions'):
        raise HTTPException(409, "尚未生成题目，暂时没有可导出的内容")
    from schemas import Paper
    name = ("teacher-" if body.teacher else "paper-") + uuid.uuid4().hex[:12] + ".docx"
    path = await asyncio.to_thread(documents.export_docx, store.task_dir(task_id),
        Paper.model_validate(paper), {**task["options"], "figure_modes": task.get("figure_modes", {})}, body.teacher, name)
    latest = store.load(task_id)
    store.update(task_id, generated_exports=[*latest.get("generated_exports", []), path])
    return {"path": path}


@app.get("/tasks/{task_id}/files/{file_path:path}")
async def download(task_id: str, file_path: str):
    task = get_task(task_id)
    folder = store.task_dir(task_id).resolve()
    target = (folder / file_path).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    allowed = set(task.get("exports", []))
    allowed.update(task.get("generated_exports", []))
    allowed.update(p["path"] for p in task.get("pages", []))
    for q in (task.get("paper") or {}).get("questions", []):
        for field in ("original_images", "redrawn_images", "svg_files"):
            allowed.update(q.get(field, []))
        for asset in q.get('visuals', []):
            allowed.update(asset.get(k) for k in ('original_image', 'redrawn_image', 'svg_file', 'draft_redrawn_image', 'draft_svg_file') if asset.get(k))
            for version in asset.get('review_history', []):
                allowed.update(version.get(k) for k in ('image', 'svg') if version.get(k))
    if file_path not in allowed:
        raise HTTPException(404, "文件不可访问")
    return FileResponse(target, filename=target.name)
