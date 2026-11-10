"""A separate completeness check of the printed source, not a math solution."""
from pydantic import BaseModel, Field, model_validator
from PIL import Image
from pathlib import Path

import model
import wire
from schemas import Paper


class PageCheck(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list, max_length=6)
    corrected: wire.ReadPaper | None = None

    @model_validator(mode="after")
    def correction_required(self):
        if not self.passed and self.corrected is None:
            raise ValueError("发现转录遗漏时必须返回完整修正页面")
        if self.passed and self.corrected is not None:
            raise ValueError("转录通过时不应同时返回另一份修正稿")
        if self.passed and self.issues:
            raise ValueError("转录通过时不能仍有待修正问题")
        if self.corrected is not None:
            # Wire schemas are intentionally small and do not inherit domain
            # validators. Reject broken references before model.ask caches them.
            Paper.model_validate(self.corrected.model_dump())
        return self


PROMPT = """独立核对图片与已转录页面，检查题目文字的完整性与忠实性，不解题、不改题。
逐项核对所有印刷题号、条件、选项、小问（包括①②、深入探究）、末尾设问以及表格内文字。
不能遗漏小问后面的“求…”“则…为____”；手写答案不应混入条件，印刷设问不能跟着手写答案被删除。
仅有若干小问的题目允许stem为空，小问不应重复放在stem中。
instructions只能包含整卷考试说明，不能重复题干和选项。各题的来源题注放在对应stem。
平行四边形的符号转写成“平行四边形”，不能误写成正方形。
不审核数学真伪，不求解、不修正原稿疑似错题；无法辨认的原文保留明确warnings，不能猜造。
重点检查图像边界是否截掉分母、根号内项或上下标。不能把可见字符的上半部当作完整公式，
也不能按熟悉题型补齐；不可辨认处在正文标“[原图截断，待补]”，warnings指出具体缺失位置。
候选转录不是证据：若候选已填写原图不可见的分母等内容，必须删除该猜测并在该位置使用
$\\text{待补}$ 或正文占位；不能保留完整猜测公式、只在句末追加“原图截断”。
不要因为页眉、广告、水印、手写演算和批改未转录而认为遗漏。
逐张清点原页实际配图，包括官方答案中的证明图、尺规作图步骤和不同作法。
不能用“证明用图”“作法1”等文字代替真实图；有图的panel必须引用figure_id，
在visuals和figures补齐漏图，source_region引用figures索引，提供大致归一化边界及page_index。
不用精修图形裁剪坐标（另有定位步骤）；但必须核对每张配图的题目归属：
对照题号、题干点名及上下文，不能把照片上方上一题的残留图并入下方新题。
不能仅凭配图在题干上方就删除：图下注明本题题号、或点名与关系明确对应本题时必须保留。
属于本题但被照片边界截断的图仍须建立figures、visuals并保留可见区域，在warnings说明缺失，不补造。
孤立残图没有对应题干时删除错误关联的figures、visuals和panel，不倒推缺失题干；
删除后同步重排source_region索引及组图引用，保留实际属于本题的所有配图和表格。
已有的正确配图、组图、表格关联及位置保持不变。
检查正确且完整时passed=true，corrected=null，issues=[]。
发现实质遗漏、重复或错字时passed=false，issues最多列6条简要证据，
corrected必须是完整修正页面，包含原本正确的所有题目与结构，不只返回差异。
官方印刷参考答案、评分细则应保留为content_role="reference_answer"的独立条目，
kind="参考答案"，原文按顺序放stem、parts、tables及配图；不得倒推缺失题干或标为problem。
核对每个评分分值与步骤的对应：分值紧跟原稿对应步骤，不能全部集中在答案末尾。
如把stem中的解答拆到parts，必须同步调整配图组和表格的after/after_index，
确保配图仍跟随原稿对应的小问或步骤，不能留在空stem前而脱离对应解答。
纯官方答案页不应清空内容；学生手写解答与教师批改仍排除。
不要因原稿年份与当前年份不同而报警。"""


def reading_views(image):
    image = Path(image)
    views = [image]
    if image.is_file():
        with Image.open(image) as source:
            if source.height / source.width >= 1.8:
                # Supplemental reading windows, not enhanced/replaced source pixels.
                for name, start, end in (("top", 0, .56), ("bottom", .44, 1)):
                    target = image.with_name(f"{image.stem}-read-{name}.png")
                    source.crop((0, round(start * source.height), source.width,
                                 round(end * source.height))).save(target)
                    views.append(target)
    return views


async def verify(paper, context, image):
    result = await model.ask(PROMPT, {
        "context": context,
        "image_order": "第一张为完整原页；如有后续图片，依次为同页上、下局部阅读窗口，存在重叠，不是新页或新题，禁止重复录入。",
        "transcription": wire.ReadPaper.model_validate(paper.model_dump()).model_dump(exclude_defaults=True)
    }, PageCheck, reading_views(image))
    return paper if result.passed else Paper.model_validate(result.corrected.model_dump())
