import json
import zipfile
import hashlib
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import documents
import main
import model
import pipeline
import store
import wire
from schemas import Paper, Question, SolveResult, ReviewResult, Blueprint, Slot, SvgDrawings, FigureReview


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.delenv('SERVICE_TOKEN', raising=False)


def test_wire_schema_excludes_internal_fields_and_preserves_layout():
    schema = wire.compact_schema(Paper)
    props = schema['$defs']['ReadQuestion']['properties']
    assert 'tables' in props and 'visual_groups' in props
    assert not {'review', 'original_images', 'solution', 'provenance', 'id'} & props.keys()
    visual = schema['$defs']['ReadVisual']['properties']
    assert 'source_region' in visual and 'original_image' not in visual
    assert len(json.dumps(schema)) < len(json.dumps(Paper.model_json_schema())) * .6


def test_question_may_have_subquestions_without_shared_stem():
    q = Question(stem='', parts=['求整数解。', '证明不等式。'])
    assert len(q.parts) == 2
    with pytest.raises(ValueError, match='题目必须包含'):
        Question(stem='', parts=['  '])
    duplicated = Question(stem='求整数解。', parts=['求整数解。', '证明不等式。'])
    assert duplicated.stem == '' and len(duplicated.parts) == 2


@pytest.mark.asyncio
async def test_resume_reuses_candidate_and_blind_solution(monkeypatch):
    source = store.create('source', 'convert', {})
    store.update(source['id'], paper=Paper(questions=[Question(id='a', stem='2+2?', kind='填空题', points=4)]).model_dump())
    task = store.create('new', 'generate', {'scope':'paper', 'figures':'both'}, source_id=source['id'])
    calls = Counter()
    async def fake(instruction, data, schema, images=(), history=()):
        calls[schema.__name__] += 1
        if schema is SolveResult:
            assert 'answer' not in data
            return SolveResult(answer='6', solution='计算', core=['加法'], method='计算', difficulty='基础')
        if schema is Blueprint:
            assert 'solution' not in data['source'][0]
            return Blueprint(title='new', explanation='', slots=[Slot(source_ids=['a'],kind='填空题',points=4,core=['加法'],method='计算',difficulty='基础')])
        if schema is Question:
            return Question(stem='3+3?', answer='6',solution='计算')
        if schema is ReviewResult:
            if 'new_paper' in data:
                assert all('points' in q and 'kind' in q for q in data['new_paper'])
                assert all('description' not in v for q in data['new_paper'] for v in q['visuals'])
            if calls['ReviewResult'] == 1:
                raise RuntimeError('模拟审核输出上限')
            return ReviewResult(passed=True,issues=[],core_alignment='',difficulty_alignment='',auxiliary_impact='',novelty='')
        raise AssertionError('无图题不应调用绘图')
    monkeypatch.setattr(model,'ask',fake)
    await pipeline.execute(task['id'])
    failed = store.load(task['id'])
    assert failed['status'] == 'failed' and failed['pending']['blind']
    candidate_id = failed['pending']['question']['id']
    before = calls.copy()
    await pipeline.execute(task['id'])
    result = store.load(task['id'])
    assert result['status'] == 'completed'
    assert result['paper']['questions'][0]['id'] == candidate_id
    assert calls['SolveResult'] == before['SolveResult'] == 2
    assert calls['Question'] == calls['Blueprint'] == 1
    assert calls['ReviewResult'] == 3


@pytest.mark.asyncio
async def test_conversion_redraw_failure_still_exports_and_can_resume(monkeypatch):
    task = store.create('source','convert', {'figures':'both'})
    folder = store.task_dir(task['id'])
    (folder/'media').mkdir()
    Image.new('RGB',(50,50),'white').save(folder/'media/a.png')
    q=Question(id='a',stem='一个圆', original_images=['media/a.png'], visuals=[{'id':'circle','original_image':'media/a.png'}])
    store.update(task['id'],paper=Paper(questions=[q]).model_dump(),pages=[{'path':'media/a.png'}])
    calls=0
    async def fake(*args,**kwargs):
        nonlocal calls
        if args[2] is FigureReview:
            return FigureReview(passed=True)
        calls+=1
        if calls==1: raise RuntimeError('模拟输出上限')
        return SvgDrawings(figures=[{'svg':'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 450"><circle cx="300" cy="225" r="100"/></svg>'}])
    monkeypatch.setattr(model,'ask',fake)
    await pipeline.execute(task['id'])
    failed_draw=store.load(task['id'])
    assert failed_draw['status']=='completed' and failed_draw['redraw_errors']
    assert (folder/'exports/paper.docx').exists()
    await pipeline.execute(task['id'])
    assert not store.load(task['id'])['redraw_errors']
    assert calls==2
    await pipeline.execute(task['id'])
    assert calls==2


def test_export_uses_persisted_per_question_selection_without_ai(monkeypatch):
    with TestClient(main.app) as client:
        task=store.create('source','convert',{'figures':'both'})
        folder=store.task_dir(task['id']);(folder/'media').mkdir()
        for name,color in [('original','red'),('redraw','blue')]:
            Image.new('RGB',(50,50),color).save(folder/f'media/{name}.png')
        q=Question(id='a',stem='图',original_images=['media/original.png'],redrawn_images=['media/redraw.png'],
            visuals=[{'id':'f','original_image':'media/original.png','redrawn_image':'media/redraw.png'}],visual_groups=[{'panels':[{'figure_id':'f'}]}])
        store.update(task['id'],status='completed',paper=Paper(questions=[q,q.model_copy(update={'id':'b'})]).model_dump())
        path=f"/tasks/{task['id']}"
        assert client.post(path+'/figures',json={'question_id':'a','mode':'redraw'}).status_code==200
        response=client.post(path+'/export',json={})
        assert response.status_code==200
        with zipfile.ZipFile(folder/response.json()['path']) as archive:
            media=[archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
            assert (folder/'media/original.png').read_bytes() in media
            assert (folder/'media/redraw.png').read_bytes() in media
        assert client.get(path).json()['figure_modes']=={'a':'redraw'}
        assert not (folder/'api_usage.jsonl').exists()


@pytest.mark.asyncio
async def test_local_model_cache_and_usage(monkeypatch,tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture')
    calls=[]
    real=httpx.AsyncClient
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"figures":[]}'}}],
                                       'usage':{'prompt_tokens':100,'completion_tokens':5}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler)))
    token=model.TASK_FOLDER.set(tmp_path)
    try:
        await model.ask('输出JSON',{},SvgDrawings)
        await model.ask('输出JSON',{},SvgDrawings)
    finally:model.TASK_FOLDER.reset(token)
    assert len(calls)==1
    assert calls[0]['thinking']['type']=='enabled'
    assert calls[0]['reasoning_effort']=='low'
    text=calls[0]['messages'][-1]['content']
    assert text.index('输出 JSON Schema') < text.index('输入资料')
    logs=[json.loads(s) for s in (tmp_path/'api_usage.jsonl').read_text('utf-8').splitlines()]
    assert logs[0]['usage']['completion_tokens']==5 and logs[1]['local_cache_hit']

@pytest.mark.asyncio
async def test_provider_length_preserves_results_without_app_budget(monkeypatch,tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture')
    real=httpx.AsyncClient
    calls=[]
    result=SolveResult(answer='4',solution='2+2=4',core=['加法'],method='加法',difficulty='基础')
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if len(calls)==1 else 'stop',
            'message':{'content':result.model_dump_json()}}], 'usage':{'completion_tokens':32768 if len(calls)==1 else 100}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler)))
    token=model.TASK_FOLDER.set(tmp_path)
    try:
        with pytest.raises(RuntimeError,match='上限'):
            await model.ask('解题',{'stem':'2+2'},SolveResult)
        assert len(calls)==1
        assert not list((tmp_path/'model-cache').glob('*.json'))
        answer=await model.ask('解题',{'stem':'2+2'},SolveResult)
        assert answer.answer=='4'
        assert all('max_tokens' not in c for c in calls)
    finally:model.TASK_FOLDER.reset(token)


def test_choice_labels_added_without_duplication(tmp_path):
    q=Question(stem='选择',options=['$1$', 'B. $2$', 'C、$3$'])
    path=documents.export_docx(tmp_path,Paper(questions=[q]),{})
    with zipfile.ZipFile(tmp_path/path) as z:
        xml=z.read('word/document.xml').decode()
    assert 'A. ' in xml and 'B. B.' not in xml and 'C. C' not in xml


def test_graphic_choice_labels_are_not_exported_again_as_empty_options(tmp_path):
    from lxml import etree
    (tmp_path / 'media').mkdir()
    Image.new('RGB', (40, 40), 'white').save(tmp_path / 'media/figure.png')
    q = Question(stem='选择图象', options=['A.', 'B. 有实际文字'],
                 visuals=[{'id': 'a', 'original_image': 'media/figure.png'},
                          {'id': 'b', 'original_image': 'media/figure.png'}],
                 visual_groups=[{'columns': 2, 'panels': [
                     {'figure_id': 'a', 'text': 'A.'},
                     {'figure_id': 'b', 'text': 'B.'}]}])
    path = documents.export_docx(tmp_path, Paper(questions=[q]), {})
    with zipfile.ZipFile(tmp_path / path) as archive:
        tree = etree.fromstring(archive.read('word/document.xml'))
        texts = tree.xpath('//w:t/text()', namespaces={
            'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
    assert texts.count('A.') == 1
    assert 'B. 有实际文字' in texts


def test_section_headers_follow_question_types_without_moving_exam_instructions(tmp_path):
    from docx import Document
    paper = Paper(instructions=['考试时间120分钟', '一. 选择题（40 分）', '二. 填空题（48 分）'],
                  questions=[Question(stem='选择内容', kind='选择题'),
                             Question(stem='填空内容', kind='填空题')])
    path = documents.export_docx(tmp_path, paper, {})
    text = '\n'.join(p.text for p in Document(tmp_path / path).paragraphs)
    assert text.index('考试时间') < text.index('一. 选择题') < text.index('选择内容')
    assert text.index('选择内容') < text.index('二. 填空题') < text.index('填空内容')


def test_choice_diagram_and_options_keep_together_without_linking_next_question(tmp_path):
    from docx import Document
    (tmp_path / "media").mkdir()
    Image.new("RGB", (80, 80), "white").save(tmp_path / "media/choice.png")
    q = Question(stem="看图选择", options=["甲", "乙", "丙", "丁"],
                 visuals=[{"id": "fig", "original_image": "media/choice.png"}],
                 visual_groups=[{"after": "stem", "panels": [{"figure_id": "fig"}]}])
    path = documents.export_docx(tmp_path, Paper(questions=[q, Question(stem="下一题")]), {})
    doc = Document(tmp_path / path)
    choices = [p for p in doc.paragraphs if p.text.startswith(("A.", "B.", "C.", "D."))]
    assert len(choices) == 4
    assert all(p.paragraph_format.keep_with_next for p in choices[:-1])
    assert choices[-1].paragraph_format.keep_with_next is False
    assert all(p.paragraph_format.keep_with_next for row in doc.tables[0].rows
               for cell in row.cells for p in cell.paragraphs)


@pytest.mark.asyncio
async def test_repeated_length_stops_at_cap_without_caching_partial_json(monkeypatch, tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture')
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'length', 'message': {'content': '{"answer":"尚未完成'}
        }], 'usage': {'completion_tokens': 65536}})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler)))
    token = model.TASK_FOLDER.set(tmp_path)
    try:
        for attempt in range(3):
            with pytest.raises(RuntimeError, match='上限') as error:
                await model.ask('解题', {'stem': '长题目'}, SolveResult)
            assert len(calls) == attempt + 1  # No automatic paid retry.
            if attempt:
                assert '模型服务的输出上限' in str(error.value)
        assert all('max_tokens' not in c for c in calls)
        assert not list((tmp_path / 'model-cache').glob('*.json'))
        diagnostics = list((tmp_path / 'model-cache').glob('*.length.txt'))
        assert len(diagnostics) == 1
        for path in diagnostics:
            saved = json.loads(path.read_text('utf-8'))
            assert saved['choices'][0]['finish_reason'] == 'length'
            assert saved['choices'][0]['message']['content'] == '{"answer":"尚未完成'
    finally:
        model.TASK_FOLDER.reset(token)


@pytest.mark.asyncio
async def test_length_without_task_does_not_promise_budget_increase(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture')
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'length', 'message': {'content': ''}
        }]})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler)))
    token = model.TASK_FOLDER.set(None)
    try:
        with pytest.raises(RuntimeError, match='上限') as error:
            await model.ask('解题', {}, SolveResult)
        assert '下次继续仅对这一步提高预算' not in str(error.value)
        assert len(calls) == 1
    finally:
        model.TASK_FOLDER.reset(token)


@pytest.mark.asyncio
async def test_empty_extraction_retains_reason_and_produces_no_exam(monkeypatch):
    task = store.create('答案页', 'convert', {'figures': 'both'})
    folder = store.task_dir(task['id'])
    image = folder / 'answer.png'
    Image.new('RGB', (50, 50), 'white').save(image)
    store.update(task['id'], files=[{'name': image.name, 'path': image.name}])

    async def fake(*args, **kwargs):
        if args[2] is pipeline.transcription.PageCheck:
            return pipeline.transcription.PageCheck(passed=True)
        return Paper(questions=[], warnings=['本页只有参考答案和评分细则，无法还原题干。'])

    monkeypatch.setattr(model, 'ask', fake)
    await pipeline.execute(task['id'])
    result = store.load(task['id'])
    assert result['status'] == 'failed'
    assert '只有参考答案' in result['error']
    assert result['extraction_warnings'] == ['本页只有参考答案和评分细则，无法还原题干。']
    assert not result['exports']


@pytest.mark.asyncio
async def test_official_answers_convert_but_never_become_generation_sources(monkeypatch):
    task = store.create('参考答案', 'convert', {'figures': 'original'})
    folder = store.task_dir(task['id'])
    image = folder / 'answers.png'
    Image.new('RGB', (50, 50), 'white').save(image)
    store.update(task['id'], files=[{'name': image.name, 'path': image.name}])
    answer = Question(number='12', content_role='reference_answer', kind='参考答案',
                      stem='解：$x=2$。', parts=['代入检验成立，得 3 分。'])

    async def fake(instruction, data, schema, *args, **kwargs):
        if schema is pipeline.transcription.PageCheck:
            return pipeline.transcription.PageCheck(passed=True)
        assert schema is Paper
        return Paper(title='参考答案', questions=[answer])

    monkeypatch.setattr(model, 'ask', fake)
    await pipeline.execute(task['id'])
    result = store.load(task['id'])
    assert result['status'] == 'completed'
    assert result['paper']['questions'][0]['content_role'] == 'reference_answer'
    with zipfile.ZipFile(folder / 'exports/paper.docx') as archive:
        xml = archive.read('word/document.xml').decode()
        assert '得 3 分' in xml and '<m:oMath' in xml and '姓名：' not in xml
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture')
    with TestClient(main.app) as client:
        response = client.post(f"/tasks/{task['id']}/generate", json={'options': {}})
        assert response.status_code == 409 and '参考答案' in response.json()['detail']
    generated = store.create('不能从答案出题', 'generate', {}, source_id=task['id'])
    with pytest.raises(RuntimeError, match='完整题目'):
        await pipeline.generate(generated['id'])


def test_crop_recovers_only_unambiguous_missing_reference(tmp_path):
    (tmp_path / 'media').mkdir()
    Image.new('RGB', (100, 100), 'white').save(tmp_path / 'media/page.png')
    q = Question(stem='图', figures=[{'page': 0, 'box': [.1, .1, .9, .9], 'caption': '图1'}],
                 visuals=[{'id': 'f', 'caption': '图1'}])
    documents.crop_figures(tmp_path, Paper(questions=[q]), [{'path': 'media/page.png'}])
    assert q.visuals[0].source_region == 0 and q.visuals[0].original_image
    q2 = Question(stem='图', figures=[{'page': 0, 'box': [.1, .1, .4, .4]},
                                   {'page': 0, 'box': [.5, .5, .9, .9]}],
                  visuals=[{'id': 'f'}])
    with pytest.raises(RuntimeError, match='缺少有效原图区域'):
        documents.crop_figures(tmp_path, Paper(questions=[q2]), [{'path': 'media/page.png'}])


@pytest.mark.asyncio
async def test_invalid_svg_gets_one_targeted_repair(monkeypatch):
    task = store.create('source', 'convert', {'figures': 'both'})
    folder = store.task_dir(task['id'])
    (folder / 'media').mkdir()
    Image.new('RGB', (50, 50), 'white').save(folder / 'media/a.png')
    q = Question(id='a', stem='圆', visuals=[{'id': 'circle', 'original_image': 'media/a.png'}])
    calls = []

    async def fake(instruction, data, *args, **kwargs):
        if args[0] is FigureReview:
            return FigureReview(passed=True)
        calls.append(data)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1" width="2"/>'
               if len(calls) == 1 else
               '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="100" cy="100" r="50"/></svg>')
        return SvgDrawings(figures=[{'svg': svg}])

    monkeypatch.setattr(model, 'ask', fake)
    await pipeline.redraw(folder, q)
    assert len(calls) == 2 and 'render_error' in calls[1]
    assert (folder / q.visuals[0].redrawn_image).exists()
    await pipeline.redraw(folder, q)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_failed_reference_review_cannot_leave_wrong_redraw_selected(monkeypatch):
    task = store.create('source', 'convert', {'figures': 'both'})
    folder = store.task_dir(task['id'])
    (folder / 'media').mkdir()
    Image.new('RGB', (50, 50), 'white').save(folder / 'media/a.png')
    q = Question(id='a', stem='圆', visuals=[{'id': 'circle', 'original_image': 'media/a.png'}])
    calls = Counter()
    allow_pass = False

    async def fake(instruction, data, schema, *args, **kwargs):
        calls[schema.__name__] += 1
        if schema is FigureReview:
            return FigureReview(passed=allow_pass, issues=[] if allow_pass else ['连接关系错误'])
        return SvgDrawings(figures=[{'svg':
            '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="100" cy="100" r="50"/></svg>'}])

    monkeypatch.setattr(model, 'ask', fake)
    with pytest.raises(RuntimeError, match='对照未通过'):
        await pipeline.redraw(folder, q)
    assert calls['FigureReview'] == 2
    assert calls['SvgDrawings'] == calls['SvgRepair'] == 1
    assert q.visuals[0].redrawn_image == q.visuals[0].svg_file == ''
    assert not q.redrawn_images and q.original_images == ['media/a.png']
    draft = q.visuals[0].draft_redrawn_image
    assert draft and (folder / draft).exists()
    allow_pass = True
    await pipeline.redraw(folder, q)
    assert q.visuals[0].redrawn_image == draft
    assert q.visuals[0].draft_redrawn_image == ''
    assert calls['SvgDrawings'] == calls['SvgRepair'] == 1
