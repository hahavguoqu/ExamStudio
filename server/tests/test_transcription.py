import pytest

import model
import transcription
import wire
from PIL import Image
from schemas import Paper, Question


def test_long_screenshot_uses_overlapping_reading_windows_without_changing_source(tmp_path):
    path = tmp_path / 'long.png'
    Image.new('RGB', (100, 240), 'white').save(path)
    original = path.read_bytes()
    views = transcription.reading_views(path)
    assert len(views) == 3 and views[0] == path
    assert Image.open(views[1]).size == (100, 134)
    assert Image.open(views[2]).size == (100, 134)
    assert path.read_bytes() == original


def test_incomplete_review_cannot_silently_pass():
    with pytest.raises(ValueError):
        transcription.PageCheck(passed=False, issues=['漏了第二问'])
    with pytest.raises(ValueError):
        transcription.PageCheck(passed=True, issues=['漏了第二问'])


def test_corrected_page_rejects_broken_figure_reference_before_caching():
    corrected = wire.ReadPaper(questions=[wire.ReadQuestion(
        stem='如图求角度', figures=[{'page': 0, 'box': [.1, .1, .9, .9]}],
        visuals=[{'id': 'diagram', 'source_region': 1}])])
    with pytest.raises(ValueError, match='原图区域不存在'):
        transcription.PageCheck(passed=False, issues=['补图'], corrected=corrected)


@pytest.mark.asyncio
async def test_completeness_review_can_restore_missing_subquestion(monkeypatch, tmp_path):
    before = Paper(questions=[Question(stem='已知矩形。', parts=['（1）证明菱形。'])])
    after = Paper(questions=[Question(stem='已知矩形。', parts=['（1）证明菱形。', '（2）求线段长。'])])

    async def fake(prompt, data, schema, images):
        assert data['transcription']['questions'][0]['parts'] == ['（1）证明菱形。']
        assert 'solution' not in data['transcription']['questions'][0]
        return transcription.PageCheck(passed=False, issues=['原图有第二问'],
                                       corrected=wire.ReadPaper.model_validate(after.model_dump()))

    monkeypatch.setattr(model, 'ask', fake)
    result = await transcription.verify(before, {'page_index': 0}, tmp_path / 'page.png')
    assert result.questions[0].parts == after.questions[0].parts
