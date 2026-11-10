import asyncio
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
import model
import pipeline
import store
from schemas import Paper, Question, SolveResult, FigureReview, SvgRepair


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture')
    monkeypatch.delenv('SERVICE_TOKEN', raising=False)


@pytest.mark.asyncio
async def test_retry_returns_queued_before_background_execution(monkeypatch):
    task = store.create('原题', 'generate', {}, source_blocker={'question_id': 'q1'})
    store.update(task['id'], status='failed', error='原题错误')
    event = asyncio.Event()
    async def execute(task_id):
        await event.wait()
    monkeypatch.setattr(pipeline, 'execute', execute)
    result = await main.retry(task['id'], {'advice': 'y表示水深'})
    assert result['status'] == 'queued' and result['error'] is None
    assert result['source_advice'] == {'q1': 'y表示水深'}
    worker = pipeline.RUNNING.pop(task['id'])
    event.set()
    await worker


@pytest.mark.asyncio
async def test_source_advice_reaches_failed_question_and_keeps_completed_analysis(monkeypatch):
    done = Question(id='done', stem='已解答', answer='1', solution='证明', core=['加法'])
    blocked = Question(id='blocked', stem='y离桌面高度')
    paper = Paper(questions=[done, blocked])
    source = store.create('原卷', 'convert', {})
    store.update(source['id'], paper=paper.model_dump())
    task = store.create('新卷', 'generate', {}, source_id=source['id'],
                        analysis=paper.model_dump(), source_advice={'blocked': '应为杯底以上水深'})
    calls = []
    async def ask(instruction, data, schema, *args):
        calls.append((schema, data))
        if schema is SolveResult:
            assert data['teacher_clarification'] == '应为杯底以上水深'
            return SolveResult(answer='3', solution='根据更正解答', core=['函数'], method='计算', difficulty='基础')
        raise RuntimeError('stop after source analysis')
    monkeypatch.setattr(model, 'ask', ask)
    with pytest.raises(RuntimeError, match='stop after'):
        await pipeline.generate(task['id'])
    assert sum(s is SolveResult for s, _ in calls) == 1
    analysis = store.load(task['id'])['analysis']['questions']
    assert analysis[0]['solution'] == '证明'
    assert analysis[1]['teacher_clarification'] == '应为杯底以上水深'


def test_human_accept_draft_preserves_review_and_exports_selected_image(tmp_path):
    q = Question(id='q1', number='1', stem='看图', visuals=[{
        'id': 'a', 'original_image': 'media/original.png',
        'draft_redrawn_image': 'media/draft.png', 'draft_svg_file': 'media/draft.svg',
        'review_issues': ['相切关系待确认'],
        'review_history': [{'image': 'media/draft.png', 'svg': 'media/draft.svg',
                            'passed': False, 'issues': ['相切关系待确认']}]}])
    task = store.create('试卷', 'convert', {'figures': 'both'})
    folder = store.task_dir(task['id'])
    (folder / 'media').mkdir()
    Image.new('RGB', (40, 40), 'red').save(folder / 'media/original.png')
    Image.new('RGB', (40, 40), 'blue').save(folder / 'media/draft.png')
    (folder / 'media/draft.svg').write_text('<svg/>')
    store.update(task['id'], paper=Paper(questions=[q]).model_dump(), status='completed',
                 error='第 1 题重绘未完成：待确认', redraw_errors=['第 1 题重绘未完成：待确认'])
    client = TestClient(main.app)
    response = client.post(f"/tasks/{task['id']}/figure-review", json={
        'question_id': 'q1', 'asset_id': 'a', 'action': 'accept', 'history_index': 0})
    assert response.status_code == 200
    result = response.json()
    asset = result['paper']['questions'][0]['visuals'][0]
    assert asset['human_accepted'] and asset['review_issues'] == ['相切关系待确认']
    assert asset['draft_redrawn_image'] == asset['redrawn_image']
    assert result['error'] is None
    export = client.post(f"/tasks/{task['id']}/export", json={'teacher': False})
    assert export.status_code == 200
    with zipfile.ZipFile(folder / export.json()['path']) as archive:
        images = [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
    assert (folder / 'media/draft.png').read_bytes() in images
    assert (folder / 'media/original.png').read_bytes() not in images


@pytest.mark.asyncio
async def test_review_saves_each_draft_and_does_not_overwrite_previous(tmp_path, monkeypatch):
    task = store.create('试卷', 'convert', {})
    folder = store.task_dir(task['id'])
    (folder / 'media').mkdir()
    Image.new('RGB', (40, 40)).save(folder / 'media/original.png')
    Image.new('RGB', (40, 40), 'blue').save(folder / 'media/first.png')
    (folder / 'media/first.svg').write_text('<svg/>')
    q = Question(stem='圆', visuals=[{'id': 'a', 'original_image': 'media/original.png',
                                   'redrawn_image': 'media/first.png', 'svg_file': 'media/first.svg'}])
    asset = q.visuals[0]
    async def ask(instruction, data, schema, *args):
        if schema is FigureReview:
            return FigureReview(passed=False, issues=['圆不相切'])
        assert schema is SvgRepair
        return SvgRepair(figures=[{'svg': '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><circle cx="20" cy="20" r="10"/></svg>'}])
    monkeypatch.setattr(model, 'ask', ask)
    saves = []
    with pytest.raises(RuntimeError, match='未通过'):
        await pipeline.check_reference_redraw(folder, q, asset, lambda: saves.append(asset.model_dump()))
    assert len(asset.review_history) == 2
    assert asset.review_history[0]['svg'] != asset.review_history[1]['svg']
    assert all((folder / h['image']).is_file() for h in asset.review_history)
    assert saves[0]['draft_svg_file'] == 'media/first.svg'
    assert all(not s['redrawn_image'] and not s['svg_file'] for s in saves)
