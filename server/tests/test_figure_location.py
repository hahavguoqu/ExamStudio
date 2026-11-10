import pytest
from PIL import Image, ImageDraw

import figure_location
import model
import pipeline
import store
from schemas import Paper, Question


def test_component_snap_requires_unique_strong_match():
    component = [.2, .3, .5, .6]
    assert figure_location.snap_boxes([[.18, .28, .52, .62]], [component]) == [component]
    ambiguous = [[.18, .28, .52, .62], [.19, .29, .51, .61]]
    assert figure_location.snap_boxes(ambiguous, [component]) == ambiguous
    remote = [[.7, .7, .9, .9]]
    assert figure_location.snap_boxes(remote, [component]) == remote


def test_label_margin_does_not_pull_neighboring_prose_into_crop():
    core = [.2, .3, .5, .6]
    letter = [.21, .293, .225, .299]
    prose_glyph = [.25, .282, .27, .29]
    result = figure_location.label_bounds(core, [letter, prose_glyph], [[.1, .28, .8, .29]])
    # The actual point label sits below the prose row; isolated prose is omitted.
    assert result == [.2, .293, .5, .6]


def test_prose_fragments_separated_by_formula_exclude_intervening_glyph():
    core = [.25, .754, .486, .87]
    glyph = [.326, .731, .340, .744]
    rows = figure_location.merge_text_rows([
        [.117, .729, .322, .746], [.420, .728, .767, .745]])
    assert len(rows) == 1
    assert figure_location.label_bounds(core, [glyph], rows) == core


def test_prose_touching_drawing_is_detached_only_with_text_evidence():
    core = [.25, .754, .486, .87]
    finer = [.251, .771, .485, .869]
    assert figure_location.detach_prose(core, [finer], []) == core
    result = figure_location.detach_prose(core, [finer], [[.1, .752, .5, .773]])
    assert result == [.25, .771, .486, .87]


@pytest.mark.asyncio
async def test_shadowed_page_component_overrides_inaccurate_model_coordinates(tmp_path, monkeypatch):
    (tmp_path / 'media').mkdir()
    source = tmp_path / 'media/page.png'
    image = Image.new('L', (600, 800))
    draw = ImageDraw.Draw(image)
    for x in range(600):
        draw.line((x, 0, x, 800), fill=80 + x // 5)
    draw.rectangle((180, 280, 330, 430), outline=10, width=3)
    image.save(source)
    original = source.read_bytes()
    components, _, _ = figure_location.ink_components(source)
    matching = [i for i, box in enumerate(components)
                if box[0] <= .3 and box[2] >= .55 and box[1] <= .35 and box[3] >= .5375]
    assert len(matching) == 1
    paper = Paper(questions=[Question(stem='如图',
        figures=[{'page': 0, 'box': [.6, .2, .9, .5]}])])

    async def fake(instruction, data, schema, images):
        assert len(images) == 3 and data['components']
        return schema(figures=[{'key': 'q0_f0', 'box': [600, 200, 900, 500],
                                'component': matching[0]}])

    monkeypatch.setattr(model, 'ask', fake)
    await figure_location.locate(tmp_path, paper, [{'path': 'media/page.png'}])
    box = paper.questions[0].figures[0].box
    assert box[0] < .3 < box[2] and box[0] < .55 < box[2] < .6
    assert source.read_bytes() == original


@pytest.mark.asyncio
async def test_location_keeps_pixels_and_updates_only_matching_caption(tmp_path, monkeypatch):
    (tmp_path / 'media').mkdir()
    source = tmp_path / 'media/page.png'
    Image.new('RGB', (1000, 1000), 'white').save(source)
    original = source.read_bytes()
    paper = Paper(questions=[Question(stem='题目',
        figures=[{'page': 0, 'box': [.1, .1, .3, .3], 'caption': '图(1)'}],
        visuals=[{'id': 'f', 'source_region': 0, 'caption': '图(1)'}],
        visual_groups=[{'panels': [{'figure_id': 'f', 'text': '图(1)'}]}])])

    async def fake(instruction, data, schema, images):
        assert len(images) == 2
        return figure_location.FigureLocations(figures=[
            figure_location.LocatedFigure(key='q0_f0', box=[200, 300, 500, 600], caption='')])

    monkeypatch.setattr(model, 'ask', fake)
    await figure_location.locate(tmp_path, paper, [{'path': 'media/page.png'}])
    q = paper.questions[0]
    assert q.figures[0].box == pytest.approx([.185, .285, .515, .615])
    assert q.visuals[0].caption == q.visual_groups[0].panels[0].text == ''
    assert source.read_bytes() == original


def test_snap_does_not_expand_into_separately_located_neighbor():
    boxes = [[.255, .55, .465, .705], [.535, .574, .689, .684]]
    bridged = [.239, .557, .657, .702]
    right = [.51, .58, .68, .70]
    snapped = figure_location.snap_boxes(boxes, [bridged, right])
    assert snapped[0] == boxes[0]
    assert snapped[1] == right


def test_axis_tick_row_is_not_trimmed_as_neighboring_prose():
    core = [.28, .09, .63, .321]
    finer = [.28, .09, .63, .31]
    ticks = [.35, .307, .59, .321]
    assert figure_location.detach_prose(core, [finer], [ticks]) == core


def test_horizontal_axis_units_follow_arrow_without_vertical_prose():
    core = [.28, .09, .63, .321]
    labels = [[.633, .298, .65, .31], [.657, .298, .71, .311],
              [.30, .34, .38, .36]]
    result = figure_location.label_bounds(core, labels)
    assert result[2] == .71
    assert result[3] == core[3]


@pytest.mark.asyncio
async def test_location_rejects_missing_targets(tmp_path, monkeypatch):
    (tmp_path / 'media').mkdir()
    Image.new('RGB', (100, 100), 'white').save(tmp_path / 'media/page.png')
    paper = Paper(questions=[Question(stem='题目',
        figures=[{'page': 0, 'box': [.1, .1, .3, .3]}])])

    async def fake(*args):
        return figure_location.FigureLocations(figures=[])

    monkeypatch.setattr(model, 'ask', fake)
    with pytest.raises(RuntimeError, match='数量或编号不一致'):
        await figure_location.locate(tmp_path, paper, [{'path': 'media/page.png'}])


@pytest.mark.asyncio
async def test_resume_localization_uses_saved_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    task = store.create('题目', 'convert', {'figures': 'original'})
    folder = store.task_dir(task['id'])
    (folder / 'media').mkdir()
    Image.new('RGB', (100, 100), 'white').save(folder / 'media/page.png')
    paper = Paper(questions=[Question(id='q', stem='题目',
        figures=[{'page': 0, 'box': [.1, .1, .3, .3]}])])
    store.update(task['id'], extracted_paper=paper.model_dump(),
                 pages=[{'path': 'media/page.png'}])
    calls = []

    async def fake(instruction, data, schema, images):
        calls.append(schema)
        assert schema is figure_location.FigureLocations
        return schema(figures=[{'key': 'q0_f0', 'box': [100, 100, 300, 300]}])

    monkeypatch.setattr(model, 'ask', fake)
    await pipeline.execute(task['id'])
    assert store.load(task['id'])['status'] == 'completed'
    assert calls == [figure_location.FigureLocations]
