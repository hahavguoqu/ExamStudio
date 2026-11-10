"""Separate page-level illustration localization from mathematical transcription."""
from pathlib import Path
from collections import deque
import asyncio

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
from pydantic import BaseModel, Field, model_validator

import model


class LocatedFigure(BaseModel):
    key: str
    box: list[int] = Field(min_length=4, max_length=4)
    caption: str = ""
    component: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_box(self):
        left, top, right, bottom = self.box
        if not (0 <= left < right <= 1000 and 0 <= top < bottom <= 1000):
            raise ValueError("配图坐标必须在0至1000之间，且左上小于右下")
        return self


class FigureLocations(BaseModel):
    figures: list[LocatedFigure]


PROMPT = """只定位试卷中的独立配图，不解题、不重画、不重抄题干。
第一张是原图，第二张为同尺寸坐标辅助网格；蓝色x/y数字是坐标刻度，不属于题目。
整页左上(0,0)，右下(1000,1000)，细网格间隔50，数字标注间隔100。box=[左,上,右,下]。
必须读取x/y刻度，不能把图片像素坐标混入0至1000的刻度坐标。
按网格定位，包含整个图形、所有字母、虚线及端点；排除题干、设问、邻图和水印。
caption只抄该图正下方实际印刷图号，没有则空字符串，不从邻图复制。
每个指定key必须恰好返回一次；同题多图按原页面阅读顺序对应，不合并、不调换。
逐个检查最左、最右、最上、最下的字母标注，不能只框主要实线轮廓。"""

COMPONENT_PROMPT = """
如有第三张图，它用红框及编号标出程序检测的候选图形（不是原稿内容）。
优先为每个key选择对应的候选编号component，程序会使用其精确边界；
不要把题号、选项字母或图号误当候选编号。相邻选项必须分别匹配，不能共用一个候选。
候选可能包含纸边、正文或漏掉图形，不是每个候选都要选择。
只有确实对应且包含主要图形时才选component，否则为null并使用box。
box仍返回大致0至1000坐标；选择component时它不会覆盖程序边界。"""


def component_overview(source, target, components):
    with Image.open(source) as im:
        image = im.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", max(14, image.width // 50)) \
        if Path("C:/Windows/Fonts/arial.ttf").exists() else ImageFont.load_default(size=18)
    for i, (l, t, r, b) in enumerate(components):
        x, y = l * image.width, t * image.height
        draw.rectangle((x, y, r*image.width, b*image.height), outline="#e02828", width=2)
        label = f"#{i}"
        bounds = draw.textbbox((x, y), label, font=font)
        draw.rectangle(bounds, fill="white")
        draw.text((x, y), label, fill="#c00000", font=font)
    image.save(target)


def coordinate_grid(source: Path, target: Path):
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", max(9, min(20, image.width // 45)))
    except OSError:
        font = ImageFont.load_default(size=max(9, min(20, image.width // 45)))
    for n in range(50, 1000, 50):
        x, y = n * image.width / 1000, n * image.height / 1000
        draw.line((x, 0, x, image.height), fill="#78b5dc", width=1)
        draw.line((0, y, image.width, y), fill="#78b5dc", width=1)
        if n % 100:
            continue
        labels = [(1, y, f"y{n}"), (image.width // 2, y, f"y{n}")]
        # Repeat x labels down the page: distant top-only labels are difficult
        # to associate with a diagram near the bottom of a tall photograph.
        labels += [(x, row * image.height / 1000 + 1, f"x{n}")
                   for row in range(0, 1000, 200)]
        for xx, yy, label in labels:
            draw.text((xx, yy), label, fill="#0050c0", font=font,
                      stroke_width=1, stroke_fill="white")
    image.save(target)


def ink_components(source: Path, *, adaptive=None, dilation=5):
    """Find connected line drawings; this mask is never used as export imagery."""
    with Image.open(source) as source_image:
        image = source_image.convert("L")
        image.thumbnail((1200, 1800))
    if adaptive is None:
        # Only the internal detection mask changes; source/crop pixels stay intact.
        adaptive = sum(image.histogram()[:155]) > .25 * image.width * image.height
    if adaptive:
        contrast = ImageChops.subtract(image.filter(ImageFilter.GaussianBlur(12)), image)
        mask = contrast.point(lambda x: 255 if x > 12 else 0)
    else:
        mask = image.point(lambda x: 255 if x < 155 else 0)
    mask = mask.filter(ImageFilter.MaxFilter(dilation))
    width, height = mask.size
    pixels = bytearray(mask.tobytes())
    regions, labels, text_rows = [], [], []
    for seed in range(len(pixels)):
        if not pixels[seed]:
            continue
        pixels[seed] = 0
        queue = deque([seed])
        left = right = seed % width
        top = bottom = seed // width
        count = 0
        while queue:
            p = queue.popleft()
            x, y = p % width, p // width
            left, right, top, bottom = min(left, x), max(right, x), min(top, y), max(bottom, y)
            count += 1
            for n in ((p - 1 if x else -1), (p + 1 if x + 1 < width else -1),
                      p - width, p + width):
                if 0 <= n < len(pixels) and pixels[n]:
                    pixels[n] = 0
                    queue.append(n)
        if (.06 * width < right - left < .7 * width
                and .04 * height < bottom - top < .5 * height and count > 150):
            regions.append([left / width, top / height, (right + 1) / width, (bottom + 1) / height])
        elif (2 < right - left <= .08 * width and 2 < bottom - top < .025 * height and count > 5):
            labels.append([left / width, top / height, (right + 1) / width, (bottom + 1) / height])
        elif right - left > .08 * width and bottom - top < .025 * height and count > 30:
            text_rows.append([left / width, top / height, (right + 1) / width, (bottom + 1) / height])
    # Prose may consist of many disconnected glyphs rather than one wide component.
    lines = []
    for label in sorted(labels, key=lambda b: (b[1] + b[3]) / 2):
        cy = (label[1] + label[3]) / 2
        if not lines or abs(cy - lines[-1][0]) > .004:
            lines.append((cy, []))
        lines[-1][1].append(label)
    for _, line in lines:
        chains = []
        for label in sorted(line, key=lambda b: b[0]):
            if not chains or label[0] - chains[-1][-1][2] > .025:
                chains.append([])
            chains[-1].append(label)
        for chain in chains:
            if len(chain) >= 5 and chain[-1][2] - chain[0][0] > .1:
                text_rows.append([chain[0][0], min(b[1] for b in chain),
                                  chain[-1][2], max(b[3] for b in chain)])
    return regions, labels, merge_text_rows(text_rows)


def merge_text_rows(rows):
    """Treat prose fragments separated by formulas/spaces as the same line."""
    merged = []
    for row in sorted(rows, key=lambda b: ((b[1]+b[3])/2, b[0])):
        matching = [i for i, other in enumerate(merged)
                    if abs((row[1]+row[3]-other[1]-other[3])/2) <= .006
                    and max(row[0], other[0]) - min(row[2], other[2]) <= .12]
        if not matching:
            merged.append(list(row))
            continue
        combined = [row, *(merged[i] for i in matching)]
        bound = [min(b[0] for b in combined), min(b[1] for b in combined),
                 max(b[2] for b in combined), max(b[3] for b in combined)]
        for i in reversed(matching):
            merged.pop(i)
        merged.append(bound)
    return merged


def ink_regions(source: Path):
    return ink_components(source)[0]


def label_bounds(core, labels, text_rows=()):
    """Include nearby isolated labels, not a full extra band of surrounding prose."""
    left, top, right, bottom = core
    for label in labels:
        cx, cy = (label[0] + label[2]) / 2, (label[1] + label[3]) / 2
        if (cy < core[1] or cy > core[3]) and any(
            row[1] - .002 <= cy <= row[3] + .002
            and min(row[2], core[2]) - max(row[0], core[0]) > .5 * (core[2] - core[0])
            for row in text_rows
        ):
            continue
        if core[0] - .018 <= cx <= core[2] + .018 and core[1] - .018 <= cy <= core[3] + .018:
            left, top = min(left, label[0]), min(top, label[1])
            right, bottom = max(right, label[2]), max(bottom, label[3])
    # Axis units can be several disconnected glyphs beyond the arrow. Extend
    # along a short horizontal label chain, never vertically into prose rows.
    for _ in range(4):
        for label in labels:
            cy = (label[1] + label[3]) / 2
            if not core[1] <= cy <= core[3]:
                continue
            if (0 <= label[0] - right <= .012 and label[2] <= core[2] + .1):
                right = label[2]
                top, bottom = min(top, label[1]), max(bottom, label[3])
            elif (0 <= left - label[2] <= .012 and label[0] >= core[0] - .1):
                left = label[0]
                top, bottom = min(top, label[1]), max(bottom, label[3])
    return [left, top, right, bottom]


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0


def detach_prose(core, finer_components, text_rows):
    """Undo a mask bridge to prose only when a finer mask and text row agree."""
    matches = sorted(((overlap(core, b), b) for b in finer_components), key=lambda x: x[0], reverse=True)
    if not matches or matches[0][0] < .7 or (len(matches) > 1 and matches[0][0]-matches[1][0] < .15):
        return core
    finer = matches[0][1]
    result = list(core)
    for index in (1, 3):
        lower, upper = sorted((core[index], finer[index]))
        inward = finer[index] > core[index] if index == 1 else finer[index] < core[index]
        if not inward or upper-lower < .004:
            continue
        if any(row[1] <= lower+.004 and row[3] >= upper-.004
               and row[2]-row[0] > .9*(core[2]-core[0])
               and min(row[2], core[2])-max(row[0], core[0]) > .5*(core[2]-core[0])
               for row in text_rows):
            result[index] = finer[index]
    return result


def snap_boxes(boxes, components):
    matches = []
    for position, box in enumerate(boxes):
        def includes_neighbor(region):
            for other_position, other in enumerate(boxes):
                if position == other_position or overlap(box, other) > .1:
                    continue
                intersection = (max(0, min(region[2], other[2]) - max(region[0], other[0]))
                                * max(0, min(region[3], other[3]) - max(region[1], other[1])))
                if intersection > .5 * (other[2]-other[0]) * (other[3]-other[1]):
                    return True
            return False

        # A text/dilation bridge may connect adjacent drawings. Do not expand a
        # separately located target into a component that contains its neighbor.
        scores = sorted(((overlap(box, region), i) for i, region in enumerate(components)
                         if not includes_neighbor(region)), reverse=True)
        matches.append(scores[0][1] if scores and scores[0][0] >= .35
                       and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .15) else None)
    # A connected region shared by two targets is not evidence for either crop.
    return [components[i] if i is not None and matches.count(i) == 1 else box
            for box, i in zip(boxes, matches)]


async def locate(folder, paper, pages):
    for question in paper.questions:
        assigned = {v.source_region for v in question.visuals if v.source_region is not None}
        for asset in question.visuals:
            if asset.source_region is not None:
                continue
            candidates = [i for i, region in enumerate(question.figures)
                          if i not in assigned and asset.caption and region.caption == asset.caption]
            if len(candidates) == 1:
                asset.source_region = candidates[0]
            elif len(question.figures) == len(question.visuals) == 1:
                asset.source_region = 0
            if asset.source_region is not None:
                assigned.add(asset.source_region)
    for page_index, page in enumerate(pages):
        if page.get("embedded_media"):
            continue
        targets, references = [], {}
        for qi, question in enumerate(paper.questions):
            for ri, region in enumerate(question.figures):
                if region.page != page_index:
                    continue
                key = f"q{qi}_f{ri}"
                references[key] = (question, ri, region)
                targets.append({"key": key, "number": question.number,
                                "stem": question.stem, "figure_order": ri,
                                "options": question.options,
                                "description": [a.description for a in question.visuals
                                                if a.source_region == ri]})
        if not targets:
            continue
        source = folder / page["path"]
        grid = folder / "media" / f"page-{page_index + 1}-coordinate-grid.png"
        await asyncio.to_thread(coordinate_grid, source, grid)
        components, labels, text_rows = await asyncio.to_thread(ink_components, source)
        images = [source, grid]
        if components:
            overview = folder / "media" / f"page-{page_index + 1}-components.png"
            await asyncio.to_thread(component_overview, source, overview, components)
            images.append(overview)
        result = await model.ask(PROMPT + COMPONENT_PROMPT, {"targets": targets,
            "components": [{"id": i, "box": [round(n*1000) for n in box]}
                           for i, box in enumerate(components)]}, FigureLocations, images)
        keys = [figure.key for figure in result.figures]
        if len(keys) != len(set(keys)) or set(keys) != set(references):
            raise RuntimeError(f"第{page_index + 1}页配图定位数量或编号不一致，未使用不确定裁剪结果。")
        selected = [f.component for f in result.figures if f.component is not None]
        if any(i >= len(components) for i in selected) or len(selected) != len(set(selected)):
            raise RuntimeError("配图候选编号无效或重复，未采用不确定的图片匹配。")
        boxes = snap_boxes([[n / 1000 for n in figure.box] for figure in result.figures], components)
        finer, fine_labels, fine_rows = await asyncio.to_thread(ink_components, source, dilation=3)
        fine_boxes = snap_boxes([[n / 1000 for n in figure.box] for figure in result.figures], finer)
        text_rows = merge_text_rows([*text_rows, *fine_rows])
        for figure, box, fine_box in zip(result.figures, boxes, fine_boxes):
            boundary_labels = labels
            if figure.component is not None:
                box = components[figure.component]
            elif box not in components and fine_box in finer:
                # A smaller dilation can separate drawings joined by text or
                # scanning noise. The same uniqueness/neighbor checks apply.
                box = fine_box
                boundary_labels = fine_labels
            question, ri, region = references[figure.key]
            # Small margin retains letter strokes at estimated box edges.
            snapped = box in components or box in finer
            if snapped:
                box = detach_prose(box, finer, text_rows)
            l, t, r, b = label_bounds(box, boundary_labels, text_rows) if snapped else box
            margin = .003 if snapped else .015
            region.box = [max(0, l - margin), max(0, t - margin),
                          min(1, r + margin), min(1, b + margin)]
            previous_caption = region.caption
            region.caption = figure.caption
            for asset in question.visuals:
                if asset.source_region == ri:
                    asset.caption = figure.caption
                    # Remove only duplicate captions, never arbitrary panel text.
                    panels = [p for g in question.visual_groups for p in g.panels]
                    panels += [p for table in question.tables for cell in table.cells for p in cell.panels]
                    for panel in panels:
                        if panel.figure_id == asset.id:
                            if panel.text == previous_caption:
                                panel.text = figure.caption
                            if panel.title == previous_caption:
                                panel.title = figure.caption
    return paper
