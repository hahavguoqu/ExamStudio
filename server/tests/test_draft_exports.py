import zipfile

import pytest

import main
import model
import pipeline
import revision
import store
from schemas import Paper, Question, ReviewResult, SolveResult, SvgRepair


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['running', 'needs_review', 'failed', 'cancelled'])
async def test_unreviewed_pending_export_is_read_only(status):
    task = store.create('草稿', 'generate', {'figures': 'redraw'})
    q = Question(id='q', stem='正在生成的题目', answer='尚待核对')
    store.update(task['id'], status=status, brief_pending={'question': q.model_dump()})
    result = await main.export_current(task['id'], main.ExportRequest())
    with zipfile.ZipFile(store.task_dir(task['id']) / result['path']) as z:
        assert '正在生成的题目' in z.read('word/document.xml').decode()
    saved = store.load(task['id'])
    assert saved['status'] == status and saved['paper'] is None
    assert main.get_task(task['id'])['paper']['questions'][0]['id'] == 'q'


@pytest.mark.asyncio
async def test_historical_candidate_export():
    task = store.create('草稿', 'generate', {})
    store.update(task['id'], paper=Paper(questions=[Question(stem='新版')]).model_dump(),
                 brief_candidates=[Question(stem='旧候选').model_dump()])
    result = await main.export_current(task['id'], main.ExportRequest(version=0))
    with zipfile.ZipFile(store.task_dir(task['id']) / result['path']) as z:
        xml = z.read('word/document.xml').decode()
    assert '旧候选' in xml and '新版' not in xml


@pytest.mark.asyncio
async def test_teacher_revision_preserves_source_and_remains_exportable(monkeypatch):
    old = Question(id='q', number='1', stem='原题', answer='原答案', provenance='原出处')
    source = store.create('原版', 'generate', {})
    store.update(source['id'], paper=Paper(questions=[old]).model_dump(),
                 messages=[{'role': 'assistant', 'content': '改为证明', 'question_id': 'q'}])
    source = store.load(source['id'])
    revised = revision.create(source, source['paper'], old.model_dump(), '保留构型，增加证明')
    async def ask(prompt, data, schema, *args):
        if schema is Question:
            assert data['teacher_advice'] == '保留构型，增加证明'
            assert data['discussion'][0]['content'] == '改为证明'
            return Question(stem='修改题', answer='新答案', solution='完整证明')
        if schema is SolveResult:
            assert 'answer' not in data
            return SolveResult(answer='新答案', solution='证明', core=['证明'], method='推导', difficulty='中等')
        return ReviewResult(passed=False, issues=['难度仍可提高'], core_alignment='符合',
                            difficulty_alignment='略低', auxiliary_impact='无', novelty='常见')
    monkeypatch.setattr(model, 'ask', ask)
    await pipeline.execute(revised['id'])
    saved = store.load(revised['id'])
    assert saved['status'] == 'needs_review' and saved['exports']
    assert store.load(source['id'])['paper']['questions'][0]['stem'] == '原题'
    assert saved['paper']['questions'][0]['stem'] == '修改题'
    assert len(saved['candidate_history']) == 2
    # Export retry after a completed edit must not repeat paid generation.
    await pipeline.execute(revised['id'])
    assert len(store.load(revised['id'])['candidate_history']) == 2


@pytest.mark.asyncio
async def test_redraw_keeps_previous_image_and_exposes_new_draft(monkeypatch):
    task = store.create('图题', 'generate', {'figures': 'redraw'})
    folder = store.task_dir(task['id'])
    (folder/'media').mkdir()
    (folder/'media/old.svg').write_text('<svg/>')
    (folder/'media/old.png').write_bytes(b'old')
    q = Question(id='q', stem='题目', visuals=[{'id': 'v', 'svg_file': 'media/old.svg', 'redrawn_image': 'media/old.png'}])
    paper = Paper(questions=[q])
    store.update(task['id'], paper=paper.model_dump(), status='needs_review')
    async def ask(*args):
        return SvgRepair(figures=[{'caption': '图', 'svg': '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="450"><circle cx="300" cy="200" r="50"/></svg>'}])
    monkeypatch.setattr(model, 'ask', ask)
    await pipeline.repair_figure(task['id'], paper, q, q.visuals[0], 'media/old.svg', '标签放大', store.load(task['id']))
    asset = store.load(task['id'])['paper']['questions'][0]['visuals'][0]
    assert asset['redrawn_image'] == 'media/old.png'
    assert asset['draft_redrawn_image'] and len(asset['review_history']) == 2
    response = await main.download(task['id'], asset['draft_redrawn_image'])
    assert response.path.is_file()
