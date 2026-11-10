import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import documents
import main
import model
import pipeline
import store
from schemas import Paper, Question, ReviewResult, SolveResult, Blueprint, Slot, SvgDrawings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def test_demo_docx_has_editable_math_and_images():
    with TestClient(main.app) as client:
        task = client.post("/demo").json()
        assert task["demo"] is True
        assert task["status"] == "completed"
        response = client.get(f"/tasks/{task['id']}/files/exports/paper.docx")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            xml = z.read("word/document.xml").decode()
            assert "<m:oMath" in xml
            assert "x^2" not in xml
            assert "如图" in xml
            assert any(name.startswith("word/media/") for name in z.namelist())


def test_auth_and_non_public_files(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "test-token-not-a-real-secret")
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 401
        headers = {"Authorization": "Bearer test-token-not-a-real-secret"}
        task = client.post("/demo", headers=headers).json()
        assert client.get(f"/tasks/{task['id']}/files/task.json", headers=headers).status_code == 404
        assert client.get(f"/tasks/{task['id']}/files/../task.json", headers=headers).status_code == 404


@pytest.mark.parametrize("svg", [
    '<svg><script>alert(1)</script></svg>',
    '<svg><image href="file:///etc/passwd"/></svg>',
    '<svg><path onclick="alert(1)"/></svg>',
    '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>',
    '<svg><path style="fill:url(https://example.com/a)"/></svg>',
])
def test_active_svg_rejected(tmp_path, svg):
    with pytest.raises(ValueError):
        documents.render_svg(svg, tmp_path, "unsafe")
    assert not (tmp_path / "media" / "unsafe.png").exists()


def test_upload_requires_real_key():
    with TestClient(main.app) as client:
        result = client.post("/tasks", files={"files": ("a.png", b"not-image", "image/png")})
        assert result.status_code == 409


def test_page_conversion_and_crop(tmp_path):
    (tmp_path / "uploads").mkdir()
    Image.new("RGB", (400, 600), "white").save(tmp_path / "uploads" / "a.png")
    pages, native = documents.prepare(tmp_path, [{"path": "uploads/a.png", "name": "a.png"}])
    paper = Paper(questions=[Question(id="q1", stem="题目", figures=[{"page": 0, "box": [0.1, 0.2, 0.9, 0.8]}])])
    documents.crop_figures(tmp_path, paper, pages)
    assert not native
    with Image.open(tmp_path / paper.questions[0].original_images[0]) as crop:
        assert crop.size == (320, 360)


def test_recovery_does_not_rebill():
    task = store.create("interrupted", "convert", {})
    store.update(task["id"], status="running")
    store.recover()
    assert store.load(task["id"])["status"] == "interrupted"
    assert task["id"] not in pipeline.RUNNING


@pytest.mark.asyncio
async def test_generation_blind_review_and_gate(monkeypatch):
    source = store.create("原卷", "convert", {})
    store.update(source["id"], paper=Paper(questions=[
        Question(id="source-q", stem="求 $2+2$", kind="填空题", points=4)]).model_dump())
    task = store.create("新卷", "generate", {"scope": "paper", "figures": "both"}, source_id=source["id"])
    blind_inputs = []
    calls = {"generate": 0}
    async def fake_ask(instruction, data, schema, images=(), history=()):
        if schema is SolveResult:
            blind_inputs.append(data)
            return SolveResult(answer="4", solution="完整解答", core=["运算"], method="运算", difficulty="基础")
        if schema is Blueprint:
            return Blueprint(title="新卷", explanation="测试", slots=[
                Slot(source_ids=["source-q"], kind="填空题", points=4, core=["运算"], method="运算", difficulty="基础")])
        if schema is Question:
            calls["generate"] += 1
            return Question(stem="求 $3+3$", answer="6", solution="解答")
        if schema is SvgDrawings:
            return SvgDrawings()
        if schema is ReviewResult:
            return ReviewResult(passed=False, issues=["两个答案矛盾"], core_alignment="符合",
                                difficulty_alignment="符合", auxiliary_impact="无", novelty="有变化")
        raise AssertionError(schema)
    monkeypatch.setattr(model, "ask", fake_ask)
    await pipeline.execute(task["id"])
    result = store.load(task["id"])
    assert result["status"] == "needs_review"
    assert len(result["exports"]) == 3
    assert calls["generate"] == 1
    assert all("answer" not in data and "solution" not in data for data in blind_inputs)


@pytest.mark.asyncio
async def test_conversion_pipeline_with_fake_vision(monkeypatch):
    task = store.create("输入", "convert", {"figures": "original", "layout": "clean"})
    folder = store.task_dir(task["id"])
    (folder / "uploads").mkdir()
    Image.new("RGB", (200, 300), "white").save(folder / "uploads" / "a.png")
    store.update(task["id"], files=[{"name": "a.png", "path": "uploads/a.png"}])
    async def fake_ask(*args, **kwargs):
        if args[2] is pipeline.transcription.PageCheck:
            return pipeline.transcription.PageCheck(passed=True)
        return Paper(title="测试", questions=[Question(stem="求 $\\frac{1}{2}+\\frac{1}{3}$。")])
    monkeypatch.setattr(model, "ask", fake_ask)
    await pipeline.execute(task["id"])
    result = store.load(task["id"])
    assert result["status"] == "completed"
    assert len(result["exports"]) == 2


@pytest.mark.asyncio
async def test_successful_generation_includes_whole_paper_review(monkeypatch):
    source = store.create("原卷", "convert", {})
    store.update(source["id"], paper=Paper(questions=[
        Question(id="q1", stem="求 $2+2$", kind="填空题", points=4)]).model_dump())
    task = store.create("新卷", "generate", {"scope": "paper", "figures": "both"}, source_id=source["id"])
    reviews = []
    async def fake_ask(instruction, data, schema, images=(), history=()):
        if schema is SolveResult:
            return SolveResult(answer="6", solution="完整解答", core=["加法"], method="运算", difficulty="基础")
        if schema is Blueprint:
            return Blueprint(title="新卷", explanation="测试", slots=[
                Slot(source_ids=["q1"], kind="填空题", points=4, core=["加法"], method="运算", difficulty="基础")])
        if schema is Question:
            return Question(stem="求 $3+3$", answer="$6$", solution="$3+3=6$", core=["加法"])
        if schema is SvgDrawings:
            return SvgDrawings()
        if schema is ReviewResult:
            reviews.append(instruction)
            return ReviewResult(passed=True, issues=[], core_alignment="对齐",
                                difficulty_alignment="对齐", auxiliary_impact="无", novelty="数据变化")
        raise AssertionError(schema)
    monkeypatch.setattr(model, "ask", fake_ask)
    await pipeline.execute(task["id"])
    result = store.load(task["id"])
    assert result["status"] == "completed"
    assert result["full_review"]["passed"]
    assert len(reviews) == 2
    assert len(result["exports"]) == 3


def test_rename_and_delete_task_persist_without_breaking_source_data():
    with TestClient(main.app) as client:
        task = client.post('/demo').json()
        path = f"/tasks/{task['id']}"
        assert client.patch(path, json={'title': '  几何专项  '}).json()['title'] == '几何专项'
        assert client.get('/tasks').json()[0]['title'] == '几何专项'
        assert client.patch(path, json={'title': '   '}).status_code == 422
        assert client.delete(path).json() == {'deleted': True}
        assert client.get('/tasks').json() == []
        assert client.get(path).status_code == 404
        assert client.get(path + '/files/exports/paper.docx').status_code == 404
        # Derived tasks can still read the source for retrying generation.
        assert store.load(task['id'])['paper']
        assert store.load(task['id'])['deleted_at']


def test_task_mutations_reject_running_work():
    with TestClient(main.app) as client:
        task = store.create('正在处理', 'convert', {})
        path = f"/tasks/{task['id']}"
        assert client.patch(path, json={'title': '新名字'}).status_code == 409
        assert client.delete(path).status_code == 409
        assert not store.load(task['id']).get('deleted_at')
