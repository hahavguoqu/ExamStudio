import zipfile
import xml.etree.ElementTree as ET

from PIL import Image
from pydantic import ValidationError
import pytest

import documents
import pipeline
import visuals
from schemas import Paper, Question, SvgDrawings, FigureReview


def question():
    return Question(
        stem="选择符合条件的图，再完成作图。",
        options=["A.", "B."], parts=["（1）比较两种方法。", "（2）请在备用图中作图。"],
        visuals=[
            {"id": "f1", "caption": "图1", "description": "直角三角形"},
            {"id": "f2", "caption": "图2", "description": "圆"},
            {"id": "spare", "caption": "备用图", "description": "坐标轴"},
        ],
        visual_groups=[
            {"after": "option", "after_index": 0, "columns": 1, "panels": [{"figure_id": "f1"}]},
            {"after": "option", "after_index": 1, "columns": 1, "panels": [{"figure_id": "f2"}]},
            {"after": "part", "after_index": 1, "columns": 1, "panels": [{"figure_id": "spare"}]},
        ],
        tables=[{"rows": 1, "columns": 2, "after": "part", "cells": [
            {"row": 0, "column": 0, "panels": [{"title": "方法一", "figure_id": "f1", "text": "作垂线。"}]},
            {"row": 0, "column": 1, "panels": [{"title": "方法二", "figure_id": "f2", "text": "作圆弧。"}]},
        ]}],
    )


def attach_images(q, folder):
    (folder / "media").mkdir(exist_ok=True)
    for i, asset in enumerate(q.visuals):
        path = f"media/f{i}.png"
        Image.new("RGB", (100 + i * 10, 80), ["red", "green", "blue"][i]).save(folder / path)
        asset.original_image = path
    visuals.sync_paths(q)


def test_docx_keeps_option_group_cell_and_spare_locations(tmp_path):
    q = question()
    attach_images(q, tmp_path)
    path = documents.export_docx(tmp_path, Paper(questions=[q]), {})
    with zipfile.ZipFile(tmp_path / path) as archive:
        xml = archive.read("word/document.xml").decode()
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml)
    assert len(root.findall(".//w:drawing", ns)) == 5  # explicit reuse, no extra copies at end
    assert xml.index("A.") < xml.index("图1") < xml.index("B.") < xml.index("图2")
    assert xml.index("比较两种方法") < xml.index("方法一") < xml.index("请在备用图") < xml.index("备用图</w:t>")
    assert "作垂线" in xml and "作圆弧" in xml
    assert root.find(".//w:tbl/w:tblPr/w:tblBorders", ns) is not None
    context = pipeline.public_question(q)
    assert context["visual_groups"][0]["panels"][0]["figure_id"] == "f1"
    assert "original_image" not in context["visuals"][0]
    assert len(pipeline.images_for(tmp_path, q)) == 3


def test_invalid_references_and_anchors_rejected():
    data = question().model_dump()
    data["visual_groups"][0]["panels"][0]["figure_id"] = "missing"
    with pytest.raises(ValidationError):
        Question.model_validate(data)
    data = question().model_dump()
    data["visuals"].append(data["visuals"][0])
    with pytest.raises(ValidationError):
        Question.model_validate(data)
    data = question().model_dump()
    data["visual_groups"][0]["after_index"] = 9
    with pytest.raises(ValidationError):
        Question.model_validate(data)


def test_continuation_rebases_ids_and_crop_regions():
    a = Question(stem="前页", figures=[{"page": 0, "box": [0, 0, 1, 1]}],
                 visuals=[{"id": "f1", "source_region": 0}])
    b = Question(stem="续页", figures=[{"page": 1, "box": [0, 0, 1, 1]}],
                 visuals=[{"id": "f1", "source_region": 0}],
                 visual_groups=[{"panels": [{"figure_id": "f1"}]}])
    visuals.merge_continuation(a, b)
    assert a.visuals[-1].id == "f1_next"
    assert a.visuals[-1].source_region == 1
    assert b.visual_groups[0].panels[0].figure_id == "f1_next"


@pytest.mark.asyncio
async def test_each_redraw_targets_one_asset_and_does_not_swap(tmp_path, monkeypatch):
    q = question()
    q.id = "q1"
    attach_images(q, tmp_path)
    seen = []

    async def ask(prompt, data, schema, images):
        if schema is FigureReview:
            return FigureReview(passed=True)
        seen.append((data["target_visual"]["id"], images[0].name))
        return SvgDrawings(figures=[{"caption": "", "svg":
            '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="20"/></svg>'}])

    monkeypatch.setattr(pipeline.model, "ask", ask)
    await pipeline.redraw(tmp_path, q)
    assert seen == [("f1", "f0.png"), ("f2", "f1.png"), ("spare", "f2.png")]
    assert len(q.redrawn_images) == 3
    assert "q1-f1" in q.visuals[0].redrawn_image
    assert "q1-f2" in q.visuals[1].redrawn_image
    assert visuals.choose_path(q.visuals[0]) == "media/f0.png"
    assert visuals.choose_path(q.visuals[0], True) == q.visuals[0].redrawn_image


def test_missing_asset_blocks_export_instead_of_dropping_option(tmp_path):
    with pytest.raises(RuntimeError, match="配图资源缺失"):
        documents.export_docx(tmp_path, Paper(questions=[question()]), {})


def test_crop_maps_by_region_not_asset_list_order(tmp_path):
    (tmp_path / "media").mkdir()
    Image.new("RGB", (100, 100), "white").save(tmp_path / "media/page.png")
    q = Question(id="q", stem="题目", figures=[
        {"page": 0, "box": [0, 0, .5, 1]}, {"page": 0, "box": [.5, 0, 1, 1]}],
        visuals=[{"id": "right", "source_region": 1}, {"id": "left", "source_region": 0}])
    documents.crop_figures(tmp_path, Paper(questions=[q]), [{"path": "media/page.png"}])
    assert q.visuals[0].original_image.endswith("original-1.png")
    assert q.visuals[1].original_image.endswith("original-0.png")
