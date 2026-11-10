import asyncio
import zipfile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import brief_generation
import brief_prompts
import main
import model
import pipeline
import reference_search
import store
from schemas import BriefInput, BriefDraft, BriefConfirm, IdeaPlan, Options, Question, SolveResult, ReviewResult


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test')


def new_task():
    return store.create('单题', 'generate', Options(scope='single', figures='redraw').model_dump(),
        brief_input=BriefInput(grade='初三', purpose='考试训练', background='机器人').model_dump())


def test_empty_direction_rejected():
    with pytest.raises(ValidationError):
        BriefInput(grade='初三', purpose='日常练习', topic='   ')


@pytest.mark.asyncio
async def test_prepare_stops_for_confirmation_and_keeps_search_failure(monkeypatch):
    task = new_task()
    async def retrieve(inputs):
        return [], ['检索连接失败']
    async def ask(prompt, data, schema, *args):
        assert schema is BriefDraft
        return BriefDraft(title='机器人题', brief='用机器人背景考查比例。')
    monkeypatch.setattr(reference_search, 'retrieve', retrieve)
    monkeypatch.setattr(model, 'ask', ask)
    await pipeline.execute(task['id'])
    result = store.load(task['id'])
    assert result['status'] == 'awaiting_confirmation'
    assert result['paper'] is None and result['exports'] == []
    assert result['search_notes'] == ['检索连接失败']


@pytest.mark.asyncio
async def test_confirm_is_idempotent_and_requires_ready_draft(monkeypatch):
    task = new_task()
    with pytest.raises(HTTPException):
        await main.confirm_brief(task['id'], BriefConfirm(brief='机器人题'))
    store.update(task['id'], status='awaiting_confirmation', brief_draft={'brief': '草稿'})
    launches = []
    def launch(id):
        launches.append(id)
        store.update(id, status='queued')
    monkeypatch.setattr(pipeline, 'launch', launch)
    for _ in range(2):
        result = await main.confirm_brief(task['id'], BriefConfirm(brief='教师修改后的机器人题'))
    assert len(launches) == 1
    assert result['confirmed_brief'] == '教师修改后的机器人题'
    assert len(result['messages']) == 1


@pytest.mark.asyncio
async def test_full_chain_blind_solve_and_teacher_only_references(monkeypatch):
    task = new_task()
    store.update(task['id'], confirmed_brief='机器人比例题', references=[
        {'id': 'R1', 'title': '背景出处', 'category': '背景素材', 'url': 'https://example.org/robot', 'content': '机器人'}])
    async def ask(prompt, data, schema, *args):
        if schema is IdeaPlan:
            return IdeaPlan(ideas=[{'core': ['比例'], 'challenge': '建模', 'design': '运动'},
                                  {'core': ['比例'], 'challenge': '建模', 'design': '装配'}], selected=0, reason='合适')
        if schema is Question:
            return Question(stem='机器人每秒行走2米，3秒行走多少米？', kind='填空题',
                            answer='6米', solution='2×3=6', reference_ids=['R1'])
        if schema is SolveResult:
            assert 'answer' not in data and 'solution' not in data
            return SolveResult(answer='6米', solution='2×3=6', core=['比例'], method='乘法', difficulty='基础')
        assert schema is ReviewResult and prompt == brief_prompts.REVIEW
        return ReviewResult(passed=True, issues=[], core_alignment='符合', difficulty_alignment='符合',
                            auxiliary_impact='无', novelty='常见情境，可接受')
    monkeypatch.setattr(model, 'ask', ask)
    await pipeline.execute(task['id'])
    result = store.load(task['id'])
    assert result['status'] == 'completed', result.get('error')
    assert len(result['paper']['questions']) == 1
    assert len(result['brief_candidates']) == 1
    for name in result['exports']:
        if name.endswith('.docx'):
            with zipfile.ZipFile(store.task_dir(task['id']) / name) as z:
                xml = z.read('word/document.xml').decode()
            assert ('https://example.org/robot' in xml) == ('teacher' in name)


@pytest.mark.asyncio
async def test_pending_candidate_survives_interrupted_solve(monkeypatch):
    task = new_task()
    q = Question(id='saved', stem='保存过的题目')
    store.update(task['id'], confirmed_brief='要求', references=[],
        idea_plan={'ideas': [{'design': '方向'}], 'selected': 0}, brief_pending={'question': q.model_dump()})
    async def ask(prompt, data, schema, *args):
        assert schema is SolveResult  # No repeated generation charge.
        raise RuntimeError('network unavailable')
    monkeypatch.setattr(model, 'ask', ask)
    await pipeline.execute(task['id'])
    assert store.load(task['id'])['brief_pending']['question']['id'] == 'saved'


def test_invented_citation_rejected():
    with pytest.raises(ValueError):
        brief_generation.provenance(Question(reference_ids=['R99']), [])


@pytest.mark.asyncio
async def test_search_deduplicates_and_marks_summary(monkeypatch):
    async def search(query):
        return [{'title': '题目', 'url': 'https://example.org/q', 'summary': '摘要'},
                {'title': '危险链接', 'url': 'javascript:alert(1)', 'content': 'x'}]
    monkeypatch.setattr(reference_search, 'search', search)
    refs, notes = await reference_search.retrieve(BriefInput(grade='初三', purpose='练习', background='机器人').model_dump())
    assert len(refs) == 1 and refs[0]['summary_only'] is True
    assert refs[0]['id'] == 'R1'
