import zipfile
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

import documents
import pipeline
import store
from schemas import Paper, Question, QuestionTable


def sample_table():
    return {
        "rows": 2, "columns": 3, "after": "part", "after_index": 0,
        "cells": [
            {"row": 0, "column": 0, "row_span": 2, "text": "$A_1=$"},
            {"row": 0, "column": 1, "text": "$1$"},
            {"row": 0, "column": 2, "text": "$-1$"},
            {"row": 1, "column": 1, "text": "$-1$"},
            {"row": 1, "column": 2, "text": "$1$"},
        ],
    }


def test_editable_table_order_spans_and_blind_context(tmp_path):
    q = Question(number="16", stem="设数阵具有性质P。",
                 parts=["（1）判断下表。", "（2）求最多个数。"], tables=[sample_table()])
    assert pipeline.public_question(q)["tables"][0]["cells"][0]["text"] == "$A_1=$"
    assert "answer" not in pipeline.public_question(q)
    relative = documents.export_docx(tmp_path, Paper(questions=[q]), {})
    with zipfile.ZipFile(tmp_path / relative) as archive:
        xml = archive.read("word/document.xml").decode()
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
    root = ET.fromstring(xml)
    assert len(root.findall(".//w:tbl", ns)) == 1
    assert root.find(".//w:vMerge", ns) is not None
    assert root.find(".//w:tbl//m:oMath", ns) is not None
    assert xml.index("判断下表") < xml.index("<w:tbl>") < xml.index("求最多个数")
    assert "16. " in xml
    assert "pmatrix" not in xml


def test_horizontal_merge_blank_and_long_text(tmp_path):
    table = QuestionTable(rows=2, columns=2, cells=[
        {"row": 0, "column": 0, "column_span": 2, "text": "项目背景：价格为 $x$ 元。\n回答下列问题。"},
        {"row": 1, "column": 0, "text": "（1）利润"},
        {"row": 1, "column": 1, "text": ""},
    ])
    q = Question(stem="项目式学习", tables=[table])
    path = documents.export_docx(tmp_path, Paper(questions=[q]), {}, True)
    with zipfile.ZipFile(tmp_path / path) as archive:
        xml = archive.read("word/document.xml").decode()
        assert 'w:gridSpan w:val="2"' in xml
        assert "项目背景" in xml and "（1）利润" in xml


def test_grid_rejects_missing_overlapping_and_out_of_bounds_cells():
    table = sample_table()
    for cells in [table["cells"][:-1], table["cells"] + [table["cells"][0]],
                  [{"row": 0, "column": 0, "row_span": 3, "column_span": 3}]]:
        with pytest.raises(ValidationError):
            QuestionTable(**{**table, "cells": cells})
    with pytest.raises(ValidationError):
        Question(stem="题目", tables=[sample_table()])


def test_old_tasks_without_tables_remain_valid():
    assert Question.model_validate({"stem": "旧题目"}).tables == []


@pytest.mark.asyncio
async def test_continued_page_keeps_tables_next_to_their_text(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    task = store.create("跨页试卷", "convert", {"figures": "original"})
    pages = [{"path": "page1.png"}, {"path": "page2.png"}]
    monkeypatch.setattr(documents, "prepare", lambda *args: (pages, []))
    monkeypatch.setattr(documents, "crop_figures", lambda *args: None)
    first = Question(stem="原始题干", parts=["（1）第一问"], tables=[
        {**sample_table(), "after": "stem", "after_index": 0}])
    continuation = Question(stem="第二页续接条件", continued=True,
                            parts=["（2）第二问"], tables=[
                                {**sample_table(), "after": "stem", "after_index": 0},
                                sample_table()])
    responses = iter([Paper(questions=[first]), Paper(questions=[continuation])])

    async def ask(*args, **kwargs):
        if args[2] is pipeline.transcription.PageCheck:
            return pipeline.transcription.PageCheck(passed=True)
        return next(responses)

    monkeypatch.setattr(pipeline.model, "ask", ask)
    result = await pipeline.extract(task["id"])
    q = result.questions[0]
    assert q.parts == ["（1）第一问", "第二页续接条件", "（2）第二问"]
    assert [(t.after, t.after_index) for t in q.tables] == [
        ("stem", 0), ("part", 1), ("part", 2)]
    Question.model_validate(q.model_dump())
