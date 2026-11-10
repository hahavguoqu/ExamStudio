from __future__ import annotations

from typing import Literal
import math
import re
from pydantic import BaseModel, Field, model_validator


class FigureRegion(BaseModel):
    page: int = Field(ge=0)
    box: list[float] = Field(min_length=4, max_length=4)
    caption: str = ""

    @model_validator(mode="after")
    def valid_box(self):
        x1, y1, x2, y2 = self.box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("图形边界必须为 0—1 范围内的有效矩形")
        return self


class VisualAsset(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    caption: str = ""
    description: str = ""
    source_region: int | None = Field(default=None, ge=0)
    original_image: str = ""
    redrawn_image: str = ""
    svg_file: str = ""
    draft_svg_file: str = ""
    draft_redrawn_image: str = ""
    review_issues: list[str] = Field(default_factory=list)
    review_history: list[dict] = Field(default_factory=list)
    human_accepted: bool = False


class VisualPanel(BaseModel):
    title: str = ""
    figure_id: str | None = None
    text: str = ""


class VisualGroup(BaseModel):
    caption: str = ""
    columns: int = Field(default=2, ge=1, le=4)
    panels: list[VisualPanel] = Field(min_length=1, max_length=20)
    after: Literal["stem", "option", "part"] = "stem"
    after_index: int = Field(default=0, ge=0)
    order: int = Field(default=0, ge=0)


class TableCell(BaseModel):
    row: int = Field(ge=0, lt=100)
    column: int = Field(ge=0, lt=30)
    row_span: int = Field(default=1, ge=1, le=100)
    column_span: int = Field(default=1, ge=1, le=30)
    text: str = ""
    panels: list[VisualPanel] = Field(default_factory=list, max_length=20)


class QuestionTable(BaseModel):
    caption: str = ""
    rows: int = Field(ge=1, le=100)
    columns: int = Field(ge=1, le=30)
    column_widths: list[float] = Field(default_factory=list, max_length=30)
    cells: list[TableCell] = Field(max_length=3000)
    # Zero-based index; stem has only index 0.
    after: Literal["stem", "option", "part"] = "stem"
    after_index: int = Field(default=0, ge=0)
    order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_grid(self):
        if self.column_widths and (
            len(self.column_widths) != self.columns or
            any(not math.isfinite(w) or w <= 0 for w in self.column_widths) or
            not math.isfinite(sum(self.column_widths))
        ):
            raise ValueError("表格列宽需为每列一个有限正数")
        occupied = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.rows or cell.column + cell.column_span > self.columns:
                raise ValueError("表格合并单元格超出边界")
            for row in range(cell.row, cell.row + cell.row_span):
                for col in range(cell.column, cell.column + cell.column_span):
                    if (row, col) in occupied:
                        raise ValueError("表格单元格重叠")
                    occupied.add((row, col))
        if len(occupied) != self.rows * self.columns:
            raise ValueError("表格必须覆盖所有单元格，空白格也需显式保留")
        return self


class Question(BaseModel):
    teacher_clarification: str = ""
    id: str = ""
    content_role: Literal["problem", "reference_answer"] = "problem"
    number: str = ""
    source_page: int = 0
    # Some original exercises consist solely of numbered subquestions.
    stem: str
    kind: str = "解答题"
    points: float | None = Field(default=None, ge=0)
    options: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    tables: list[QuestionTable] = Field(default_factory=list, max_length=30)
    visuals: list[VisualAsset] = Field(default_factory=list, max_length=40)
    visual_groups: list[VisualGroup] = Field(default_factory=list, max_length=40)
    figures: list[FigureRegion] = Field(default_factory=list)
    original_images: list[str] = Field(default_factory=list)
    redrawn_images: list[str] = Field(default_factory=list)
    svg_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    core: list[str] = Field(default_factory=list)
    supporting: list[str] = Field(default_factory=list)
    method: str = ""
    difficulty: str = ""
    answer: str = ""
    solution: str = ""
    knowledge: str = ""
    review: dict = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    provenance: str = "用户上传材料"
    reference_ids: list[str] = Field(default_factory=list, max_length=8)
    continued: bool = False

    @model_validator(mode="after")
    def validate_table_positions(self):
        if self.content_role == "reference_answer" and self.number:
            self.stem = re.sub(
                rf"^\s*{re.escape(self.number)}[.．、](?:\s+|$)", "", self.stem, count=1)
        if (self.parts and self.stem.strip() == self.parts[0].strip()
                and not self.tables and not self.visual_groups and not self.visuals):
            # A shared stem is optional; do not duplicate the first subquestion.
            self.stem = ""
        if not self.stem.strip() and not any(p.strip() for p in self.parts) and not self.tables:
            raise ValueError("题目必须包含题干、小问或题目表格")
        for table in [*self.tables, *self.visual_groups]:
            length = {"stem": 1, "option": len(self.options), "part": len(self.parts)}[table.after]
            if table.after_index >= length:
                raise ValueError("表格插入位置不存在")
        ids = [v.id for v in self.visuals]
        if len(ids) != len(set(ids)):
            raise ValueError("配图ID不能重复")
        for visual in self.visuals:
            if visual.source_region is not None and visual.source_region >= len(self.figures):
                raise ValueError("配图引用的原图区域不存在")
        panels = [p for g in self.visual_groups for p in g.panels]
        panels += [p for t in self.tables for c in t.cells for p in c.panels]
        if any(p.figure_id is not None and p.figure_id not in ids for p in panels):
            raise ValueError("图文组合引用了不存在的配图ID")
        return self


class Paper(BaseModel):
    title: str = "数学试卷"
    instructions: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list, max_length=120)
    warnings: list[str] = Field(default_factory=list)


class Options(BaseModel):
    layout: Literal["clean", "original"] = "clean"
    figures: Literal["both", "original", "redraw"] = "both"
    difficulty: Literal["easier", "same", "harder"] = "same"
    creativity: Literal["parameters", "variation", "creative"] = "variation"
    scope: Literal["paper", "single"] = "paper"
    question_id: str | None = None
    requirements: str = Field(default="", max_length=6000)


class GenerateRequest(BaseModel):
    options: Options = Field(default_factory=Options)


class BriefInput(BaseModel):
    grade: str = Field(min_length=1, max_length=40)
    purpose: str = Field(min_length=1, max_length=60)
    topic: str = Field(default="", max_length=500)
    model_name: str = Field(default="", max_length=300)
    background: str = Field(default="", max_length=500)
    kind: Literal["自动选择", "选择题", "填空题", "解答题"] = "自动选择"
    extra: str = Field(default="", max_length=2000)
    search: bool = True

    @model_validator(mode="after")
    def meaningful(self):
        if not any(s.strip() for s in (self.topic, self.model_name, self.background, self.extra)):
            raise ValueError("请至少填写考查内容、指定模型、背景或补充要求中的一项")
        return self


class BriefDraft(BaseModel):
    title: str
    brief: str = Field(min_length=1, max_length=6000)
    notes: list[str] = Field(default_factory=list)


class BriefConfirm(BaseModel):
    brief: str = Field(min_length=1, max_length=6000)


class Idea(BaseModel):
    core: list[str]
    challenge: str
    design: str


class IdeaPlan(BaseModel):
    ideas: list[Idea] = Field(min_length=2, max_length=3)
    selected: int = Field(ge=0, le=2)
    reason: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    question_id: str | None = None


class SolveResult(BaseModel):
    answer: str
    solution: str
    core: list[str]
    supporting: list[str] = Field(default_factory=list)
    method: str
    difficulty: str
    knowledge: str = ""
    issues: list[str] = Field(default_factory=list, description="仅列出尚未解决、会导致答案或论证不可靠的阻断问题；已排除的退化情形和不影响结论的说明放notes")
    notes: list[str] = Field(default_factory=list, description="不阻断解题的说明：图中可确认的位置关系、已排除的退化情形、不影响答案的多解构型等")


class ReviewResult(BaseModel):
    passed: bool
    issues: list[str]
    core_alignment: str
    difficulty_alignment: str
    auxiliary_impact: str
    novelty: str


class Slot(BaseModel):
    source_ids: list[str] = Field(min_length=1)
    kind: str
    points: float | None = None
    core: list[str]
    method: str
    difficulty: str


class Blueprint(BaseModel):
    title: str
    explanation: str
    slots: list[Slot] = Field(min_length=1, max_length=120)


class Primitive(BaseModel):
    type: Literal["line", "polyline", "circle", "ellipse", "text"]
    points: list[list[float]] = Field(default_factory=list, max_length=100)
    x: float = Field(default=0, ge=-2000, le=2000)
    y: float = Field(default=0, ge=-2000, le=2000)
    r: float = Field(default=0, ge=0, le=1000)
    rx: float = Field(default=0, ge=0, le=1000)
    ry: float = Field(default=0, ge=0, le=1000)
    text: str = Field(default="", max_length=100)
    dashed: bool = False

    @model_validator(mode="after")
    def validate_points(self):
        if any(len(p) != 2 or any(abs(v) > 2000 for v in p) for p in self.points):
            raise ValueError("无效绘图坐标")
        if self.type in ("line", "polyline") and len(self.points) < 2:
            raise ValueError("线条至少需要两个点")
        return self


class Diagram(BaseModel):
    caption: str = ""
    primitives: list[Primitive] = Field(min_length=1, max_length=300)


class Drawings(BaseModel):
    figures: list[Diagram] = Field(default_factory=list, max_length=8)


class SvgFigure(BaseModel):
    caption: str = ""
    svg: str = Field(min_length=20, max_length=120000)


class SvgDrawings(BaseModel):
    figures: list[SvgFigure] = Field(default_factory=list, max_length=8)


class SvgRepair(SvgDrawings):
    """A bounded reasoning pass for a figure with concrete review feedback."""


class FigureReview(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list, max_length=12)
