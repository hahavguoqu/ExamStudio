from __future__ import annotations

import asyncio
import shutil
import re
import uuid
from xml.etree.ElementTree import ParseError
from pathlib import Path

from pydantic import BaseModel

import documents
import figure_location
import transcription
import model
import prompts
import store
import visuals
from schemas import Blueprint, Paper, Question, ReviewResult, SolveResult, SvgDrawings, FigureReview, SvgRepair

RUNNING: dict[str, asyncio.Task] = {}


def public_question(q: Question):
    value = q.model_dump(include={"stem", "options", "parts", "tables", "visual_groups", "kind", "points"})
    value["visuals"] = visuals.public_assets(q)
    if q.teacher_clarification:
        value["teacher_clarification"] = q.teacher_clarification
    return value


def generation_context(context):
    """Keep comparison material, but do not prime structural variants with solved templates."""
    if context["requirements"].get("creativity", "variation") == "parameters":
        return context
    return {k: v for k, v in context.items() if k != "source"} | {
        "reference_profile": [{k: v for k, v in q.items() if k in {"kind", "points", "difficulty"}}
                              for q in context["source"]]}


def images_for(folder, q):
    if q.visuals:
        return [visuals.safe_path(folder, visuals.choose_path(v)) for v in q.visuals]
    return [folder / path for path in (q.redrawn_images or q.original_images)]


def progress(task_id, stage, amount, **fields):
    store.update(task_id, stage=stage, progress=amount, **fields)


async def redraw(folder, q, on_saved=None):
    if q.visuals:
        for asset in q.visuals:
            if asset.redrawn_image and (folder / asset.redrawn_image).is_file():
                continue
            if asset.draft_redrawn_image and (folder / asset.draft_redrawn_image).is_file():
                asset.svg_file, asset.redrawn_image = asset.draft_svg_file, asset.draft_redrawn_image
                try:
                    await check_reference_redraw(folder, q, asset, on_saved)
                except Exception:
                    asset.draft_svg_file, asset.draft_redrawn_image = asset.svg_file, asset.redrawn_image
                    asset.svg_file = asset.redrawn_image = ""
                    visuals.sync_paths(q)
                    raise
                asset.draft_svg_file = asset.draft_redrawn_image = ""
                visuals.sync_paths(q)
                if on_saved:
                    on_saved()
                continue
            drawings = await model.ask(
                prompts.DRAW_SVG + "\n本次仅绘制 target_visual 指定的一张图，figures 必须恰好一项，不合并或调换其他图。"
                "\n有参考图时以该图实际点线关系为准；题干和description可能涉及其他构型，不要把其他小问的线段加入当前图。",
                {"question": public_question(q), "target_visual": asset.model_dump(include={"id", "caption", "description"})},
                SvgDrawings, [visuals.safe_path(folder, asset.original_image)] if asset.original_image else [])
            if len(drawings.figures) != 1:
                raise RuntimeError(f"配图 {asset.id} 返回数量不符，未将其错误关联到其他位置。")
            try:
                asset.svg_file, asset.redrawn_image = await asyncio.to_thread(
                    documents.render_svg, drawings.figures[0].svg, folder, f"{q.id}-{asset.id}-{uuid.uuid4().hex[:8]}")
            except (ParseError, ValueError) as exc:
                repaired = await model.ask(
                    prompts.DRAW_SVG + "\n修复这一张 SVG 的语法或不受支持的元素，保留几何关系。只返回一张图。",
                    {"question": public_question(q),
                     "target_visual": asset.model_dump(include={"id", "caption", "description"}),
                     "invalid_svg": drawings.figures[0].svg, "render_error": str(exc)},
                    SvgDrawings,
                    [visuals.safe_path(folder, asset.original_image)] if asset.original_image else [])
                if len(repaired.figures) != 1:
                    raise RuntimeError(f"配图 {asset.id} 修复后数量不符。")
                asset.svg_file, asset.redrawn_image = await asyncio.to_thread(
                    documents.render_svg, repaired.figures[0].svg, folder, f"{q.id}-{asset.id}")
            if asset.original_image:
                try:
                    await check_reference_redraw(folder, q, asset, on_saved)
                except Exception:
                    # Keep failed files for diagnosis, but never select them for export.
                    asset.draft_svg_file, asset.draft_redrawn_image = asset.svg_file, asset.redrawn_image
                    asset.svg_file = asset.redrawn_image = ""
                    visuals.sync_paths(q)
                    raise
            visuals.sync_paths(q)
            if on_saved:
                on_saved()
        visuals.sync_paths(q)
        return q
    if q.redrawn_images and all((folder / path).is_file() for path in q.redrawn_images):
        return q
    if not q.original_images:
        return q
    drawings = await model.ask(prompts.DRAW_SVG, public_question(q), SvgDrawings,
                               [folder / path for path in q.original_images])
    q.redrawn_images, q.svg_files = [], []
    for i, figure in enumerate(drawings.figures):
        svg, png = await asyncio.to_thread(documents.render_svg, figure.svg, folder, f"{q.id}-redraw-{i}")
        q.svg_files.append(svg)
        q.redrawn_images.append(png)
    return q


def save_draft_checkpoint(q, asset, on_saved):
    """Persist an unapproved image only as a draft, including on cancellation."""
    if not on_saved:
        return
    svg, image = asset.svg_file, asset.redrawn_image
    asset.svg_file = asset.redrawn_image = ""
    visuals.sync_paths(q)
    try:
        on_saved()
    finally:
        asset.svg_file, asset.redrawn_image = svg, image
        visuals.sync_paths(q)


async def check_reference_redraw(folder, q, asset, on_saved=None):
    data = {"stem": q.stem, "caption": asset.caption}

    async def review():
        asset.draft_svg_file, asset.draft_redrawn_image = asset.svg_file, asset.redrawn_image
        save_draft_checkpoint(q, asset, on_saved)
        # Read on every review so a repair is checked against its new code.
        review_data = {**data, "svg_source":
                       visuals.safe_path(folder, asset.svg_file).read_text("utf-8")}
        verdict = await model.ask(
                               prompts.REVIEW_FIGURE +
                               "\n同时提供当前渲染图的SVG代码。报告缺线或虚实线错误前，"
                               "核对代码中的端点、路径与样式；已存在且覆盖目标线段的线不能判缺失。"
                               "涉及代码的问题给出可核对的元素或坐标证据。原图仍是核对依据。",
                               review_data, FigureReview,
                               [visuals.safe_path(folder, asset.original_image),
                                visuals.safe_path(folder, asset.redrawn_image)])
        asset.review_issues = verdict.issues
        asset.review_history.append({"time": store.now(), "svg": asset.svg_file,
                                    "image": asset.redrawn_image, "passed": verdict.passed,
                                    "issues": verdict.issues})
        save_draft_checkpoint(q, asset, on_saved)
        return verdict

    verdict = await review()
    if verdict.passed and not verdict.issues:
        return
    repaired = await model.ask(
        prompts.REPAIR_SVG,
        {**data, "issues": verdict.issues,
         "existing_svg": visuals.safe_path(folder, asset.svg_file).read_text("utf-8")}, SvgRepair,
        [visuals.safe_path(folder, asset.original_image),
         visuals.safe_path(folder, asset.redrawn_image)])
    if len(repaired.figures) != 1:
        raise RuntimeError("重绘返修返回数量不符，暂保留原图。")
    asset.svg_file, asset.redrawn_image = await asyncio.to_thread(
        documents.render_svg, repaired.figures[0].svg, folder, f"{q.id}-{asset.id}-repair-{uuid.uuid4().hex[:8]}")
    verdict = await review()
    if not verdict.passed or verdict.issues:
        raise RuntimeError("重绘图与原图对照未通过：" + "；".join(verdict.issues or ["存在无法确认的图形关系"]))


async def extract(task_id):
    task = store.load(task_id)
    folder = store.task_dir(task_id)
    if task.get("paper") and task.get("pages"):
        paper = Paper.model_validate(task["paper"])
        pages = task["pages"]
    elif task.get("extracted_paper") and task.get("pages"):
        paper = Paper.model_validate(task["extracted_paper"])
        pages = task["pages"]
        progress(task_id, "核对配图位置", 56)
        await figure_location.locate(folder, paper, pages)
        await asyncio.to_thread(documents.crop_figures, folder, paper, pages)
        progress(task_id, "已完成题目整理", 58, paper=paper.model_dump(), title=paper.title)
    else:
        progress(task_id, "整理原始文件", 5)
        pages, native = await asyncio.to_thread(documents.prepare, folder, task["files"])
        progress(task_id, "识别题目与公式", 12, pages=pages)
        paper = Paper(title=task["title"])
        if native:
            paper = await model.ask(
                prompts.EXTRACT + "\n输入含 DOCX 原生 XML，保留 OMML 公式语义，按关系文件关联嵌入图。图片序号从0开始。",
                {"documents": native, "images": pages}, Paper,
                [folder / p["path"] for p in pages])
        else:
            for index, page in enumerate(pages):
                result = await model.ask(prompts.EXTRACT,
                                         {"page_index": index, "text_hint": page.get("text_hint", ""),
                                          "previous_question": paper.questions[-1].stem if paper.questions else ""},
                                         Paper, [folder / page["path"]])
                progress(task_id, f"核对第 {index+1}/{len(pages)} 页题目完整性",
                         12 + int(43 * index / len(pages)))
                result = await transcription.verify(result, {
                    "page_index": index,
                    "previous_question": paper.questions[-1].stem if paper.questions else ""
                }, folder / page["path"])
                if index == 0:
                    paper.title, paper.instructions = result.title, result.instructions
                for q in result.questions:
                    q.source_page = index
                    if (q.continued and paper.questions
                            and q.content_role == paper.questions[-1].content_role):
                        prior = paper.questions[-1]
                        visuals.merge_continuation(prior, q)
                        continuation_index = len(prior.parts)
                        prior.parts.append(q.stem)
                        part_offset, option_offset = len(prior.parts), len(prior.options)
                        for table in [*q.tables, *q.visual_groups]:
                            if table.after == "stem":
                                table.after = "part"
                                table.after_index = continuation_index
                            elif table.after == "part":
                                table.after_index += part_offset
                            elif table.after == "option":
                                table.after_index += option_offset
                        prior.tables.extend(q.tables)
                        prior.visual_groups.extend(q.visual_groups)
                        prior.parts.extend(q.parts)
                        prior.options.extend(q.options)
                        prior.figures.extend(q.figures)
                        prior.warnings.extend(q.warnings)
                    else:
                        paper.questions.append(q)
                paper.warnings.extend(result.warnings)
                progress(task_id, f"已识别 {index+1}/{len(pages)} 页", 12 + int(43*(index+1)/len(pages)))
        if not paper.questions:
            store.update(task_id, extraction_warnings=paper.warnings)
            detail = "；".join(paper.warnings)
            raise RuntimeError("未识别到可整理的题目。" + (detail or "请检查上传材料是否包含完整题干。"))
        for q in paper.questions:
            q.id = uuid.uuid4().hex[:12]
            # Ignore model-provided filesystem paths and evaluation claims.
            q.original_images, q.redrawn_images, q.svg_files = [], [], []
            for asset in q.visuals:
                asset.original_image = asset.redrawn_image = asset.svg_file = ""
                asset.draft_svg_file = asset.draft_redrawn_image = ""
            q.review = {}
            q.provenance = "用户上传材料；识别整理，未改编"
        # Keep transcription even if the independent localization step fails.
        progress(task_id, "核对配图位置", 56, extracted_paper=paper.model_dump())
        await figure_location.locate(folder, paper, pages)
        await asyncio.to_thread(documents.crop_figures, folder, paper, pages)
        progress(task_id, "已完成题目整理", 58, paper=paper.model_dump(), title=paper.title)
    redraw_errors = []
    if task["options"]["figures"] != "original":
        for index, q in enumerate(paper.questions):
            if q.original_images:
                progress(task_id, f"重绘第 {index+1} 题配图", 60+int(25*index/len(paper.questions)))
                try:
                    await redraw(folder, q, lambda: store.update(task_id, paper=paper.model_dump()))
                    q.warnings = [w for w in q.warnings if not w.startswith(f"第 {q.number or index+1} 题重绘未完成：")]
                except Exception as exc:
                    message = f"第 {q.number or index+1} 题重绘未完成：{exc}；暂保留原图，可继续补绘。"
                    redraw_errors.append(message)
                    if message not in q.warnings:
                        q.warnings.append(message)
                if q.redrawn_images and "重绘图由 AI 生成，请与原图对照确认。" not in q.warnings:
                    q.warnings.append("重绘图由 AI 生成，请与原图对照确认。")
                progress(task_id, f"重绘配图 {index+1}/{len(paper.questions)}", 60+int(25*(index+1)/len(paper.questions)),
                         paper=paper.model_dump())
    store.update(task_id, paper=paper.model_dump(), redraw_errors=redraw_errors)
    return paper


async def generate(task_id):
    task = store.load(task_id)
    folder = store.task_dir(task_id)
    source_task = store.load(task["source_id"])
    source_folder = store.task_dir(source_task["id"])
    source = Paper.model_validate(task.get("analysis") or source_task["paper"])
    if task["options"].get("scope") == "single":
        source.questions = [q for q in source.questions if q.id == task["options"].get("question_id")]
        if not source.questions:
            raise RuntimeError("请选择需要仿照的题目。")
    source.questions = [q for q in source.questions if q.content_role == "problem"]
    if not source.questions:
        raise RuntimeError("这些内容是参考答案或评分标准，可导出 Word；出题需要上传对应的完整题目。")
    progress(task_id, "独立解答原题，分析核心考点", 8)
    for i, q in enumerate(source.questions):
        if task.get("analysis") and q.solution and q.answer and q.core:
            continue
        progress(task_id, f"解答原题 {i+1}/{len(source.questions)}", 8+int(22*i/len(source.questions)))
        solve_data = public_question(q)
        advice = (task.get("source_advice") or {}).get(q.id)
        if advice:
            q.teacher_clarification = advice
            solve_data["teacher_clarification"] = advice
        solved = await model.ask(prompts.SOLVE + "\n若有 teacher_clarification，它是教师对题意的补充或更正；据此重新解题，并在解答中说明采用的更正。仍需检查数学正确性，不可直接跳过检查。",
                                 solve_data, SolveResult, images_for(source_folder, q))
        if solved.issues:
            store.update(task_id, source_blocker={"question_id": q.id, "number": q.number or str(i+1),
                         "stem": q.stem, "issues": solved.issues}, analysis=source.model_dump())
            raise RuntimeError(f"尚未开始出题：原题 {i+1} 的解答检查未通过。请核对原题文字和配图。模型报告：" + "；".join(solved.issues))
        store.update(task_id, source_blocker=None)
        q.warnings.extend(note for note in solved.notes if note not in q.warnings)
        for field in ("answer", "solution", "core", "supporting", "method", "difficulty", "knowledge"):
            setattr(q, field, getattr(solved, field))
        progress(task_id, f"原题分析 {i+1}/{len(source.questions)}", 8+int(22*(i+1)/len(source.questions)),
                 analysis=source.model_dump())
    plan = Blueprint.model_validate(task["blueprint"]) if task.get("blueprint") else await model.ask(
        prompts.PLAN, {"source": [{k: getattr(q, k) for k in ("id", "kind", "points", "core", "supporting", "method", "difficulty")} for q in source.questions],
                       "requirements": task["options"]}, Blueprint)
    lookup = {q.id: q for q in source.questions}
    covered = [sid for slot in plan.slots for sid in slot.source_ids]
    if sorted(covered) != sorted(lookup):
        raise RuntimeError("命题规划没有完整且唯一地覆盖原题，已停止以避免知识点遗漏。请重试。")
    if len(plan.slots) != len(source.questions):
        raise RuntimeError("命题规划改变了题数，请重试。")
    from collections import Counter
    if Counter(s.kind for s in plan.slots) != Counter(q.kind for q in source.questions):
        raise RuntimeError("命题规划改变了题型分布，请重试。")
    if all(q.points is not None for q in source.questions):
        if any(s.points is None for s in plan.slots) or abs(sum(s.points for s in plan.slots) - sum(q.points for q in source.questions)) > 0.001:
            raise RuntimeError("命题规划改变了总分，请重试。")
    single = task["options"].get("scope") == "single"
    paper = Paper.model_validate(task["paper"]) if task.get("paper") else Paper(
        title=source.title + (" · 新题" if single else " · 新卷"),
        instructions=[] if single else source.instructions)
    progress(task_id, "命题蓝图已建立", 32, blueprint=plan.model_dump())
    for i, slot in enumerate(plan.slots):
        if i < len(paper.questions) and paper.questions[i].review.get("passed"):
            continue
        targets = [lookup[sid] for sid in slot.source_ids]
        context = {"target": slot.model_dump(), "requirements": task["options"],
                   "source": [{**public_question(q), **{k: getattr(q, k) for k in ("answer", "solution", "core", "supporting", "method", "difficulty")}} for q in targets]}
        feedback = paper.questions[i].review.get("issues", []) if i < len(paper.questions) else []
        q = None
        resume = task.get("pending") or {}
        first_attempt = resume.get("attempt", 0) if resume.get("slot") == i else 0
        for attempt in range(first_attempt, first_attempt + 1):
            pending = store.load(task_id).get("pending") or {}
            restoring = pending.get("slot") == i and pending.get("attempt") == attempt
            progress(task_id, (f"复用第 {i+1} 题已保存候选题" if restoring else
                     f"生成第 {i+1}/{len(plan.slots)} 题" + (" · 根据审核重新生成" if attempt else "")),
                     34+int(50*i/len(plan.slots)))
            if pending.get("slot") == i and pending.get("attempt") == attempt:
                q = Question.model_validate(pending["question"])
            else:
                q = await model.ask(prompts.GENERATE, {**generation_context(context), "previous_issues": feedback}, Question,
                                    [path for ref in targets for path in images_for(source_folder, ref)]
                                    if task["options"].get("creativity", "variation") == "parameters" else [])
                if len(q.parts) > 1 and not any(re.match(r"^\s*(?:[（(]\d+[)）]|\d+[.．、]|[①-⑳])", p) for p in q.parts):
                    q.parts = [f"（{j+1}）{part}" for j, part in enumerate(q.parts)]
                q.id, q.number = uuid.uuid4().hex[:12], str(i+1)
                q.source_ids, q.provenance = slot.source_ids, "AI 根据用户原题改编；未使用网页检索，不声明全网原创"
                q.figures, q.original_images, q.redrawn_images, q.svg_files = [], [], [], []
                for asset in q.visuals:
                    asset.original_image = asset.redrawn_image = asset.svg_file = ""
                    asset.draft_svg_file = asset.draft_redrawn_image = ""
                    asset.source_region = None
                q.kind, q.points = slot.kind, slot.points
                pending = {"slot": i, "attempt": attempt, "question": q.model_dump()}
                store.update(task_id, pending=pending)
            def save_pending():
                pending["question"] = q.model_dump()
                store.update(task_id, pending=pending)
            progress(task_id, f"绘制新题 {i+1} 配图", 35+int(50*i/len(plan.slots)))
            await redraw(folder, q, save_pending)
            save_pending()
            progress(task_id, f"复用第 {i+1} 题独立解答" if pending.get("blind") else f"独立解答第 {i+1} 题", 36+int(50*i/len(plan.slots)))
            blind = SolveResult.model_validate(pending["blind"]) if pending.get("blind") else await model.ask(
                prompts.SOLVE, public_question(q), SolveResult, images_for(folder, q))
            pending["blind"] = blind.model_dump()
            save_pending()
            progress(task_id, f"审核第 {i+1} 题", 37+int(50*i/len(plan.slots)))
            review = await model.ask(prompts.REVIEW, {
                **context, "candidate": {**public_question(q), **{k: getattr(q, k) for k in ("answer", "solution", "core", "supporting", "method", "difficulty")}},
                "independent_solution": blind.model_dump()}, ReviewResult, images_for(folder, q))
            if blind.issues:
                review.passed = False
                review.issues.extend(blind.issues)
            if any(public_question(q) == public_question(ref) for ref in targets):
                review.passed = False
                review.issues.append("新题题干与原题相同。")
            q.review = review.model_dump()
            if review.passed:
                break
            feedback = review.issues
        if i < len(paper.questions):
            paper.questions[i] = q
        else:
            paper.questions.append(q)
        store.update(task_id, paper=paper.model_dump(), pending=None)
        store.update(task_id, candidate_history=[*store.load(task_id).get('candidate_history', []), paper.model_dump()])
        progress(task_id, f"已处理 {i+1}/{len(plan.slots)} 题", 38+int(48*(i+1)/len(plan.slots)), paper=paper.model_dump())
    if all(q.review.get("passed") for q in paper.questions):
        progress(task_id, "整卷复核：核心知识覆盖、难度顺序与重复题", 88)
        full_review = await model.ask(
            "复核整卷命题质量，不重新逐题求解。检查核心知识及思维目标的覆盖和权重、题型与分值、"
            "整卷难度顺序、题目间重复与相互泄露答案。辅助知识可以变化，题序可以调整。"
            "不要因为辅助知识不同就否决。实质缺陷 passed=false，并列出具体题号和原因。"
            "以plan提炼后的主要考点为对齐依据；source中的具体数值、构型及分步解法仅供背景理解，不得要求新题逐项继承。"
            "原卷 points 为 null 表示原稿未给分值；对应新题也未给分值不能作为否决理由，不得要求编造分数。"
            "visuals 的 id 只在本题内唯一，不同题重复 id 合法，不会覆盖图片。"
            "逐题数学与图题一致性已由独立审核检查；本轮聚焦整卷覆盖、题序、重复与泄题。"
            "不要将不影响结论的非严重提醒判为失败。",
            {"source": [{"id": q.id, "core": q.core, "method": q.method, "difficulty": q.difficulty,
                          "kind": q.kind, "points": q.points} for q in source.questions],
             "plan": plan.model_dump(), "requirements": task["options"],
             "new_paper": [{"number": q.number, "kind": q.kind, "points": q.points, "stem": q.stem, "parts": q.parts,
                            "options": q.options, "tables": [t.model_dump() for t in q.tables],
                            "visuals": [{"id": v.id, "caption": v.caption} for v in q.visuals], "visual_groups": [g.model_dump() for g in q.visual_groups],
                            "core": q.core, "supporting": q.supporting, "method": q.method,
                            "difficulty": q.difficulty, "review": q.review} for q in paper.questions]},
            ReviewResult)
        store.update(task_id, full_review=full_review.model_dump())
    store.update(task_id, paper=paper.model_dump())
    return paper


async def execute(task_id):
    context_token = model.TASK_FOLDER.set(store.task_dir(task_id))
    try:
        task = store.load(task_id)
        store.update(task_id, status="running", error=None, exports=[])
        if task.get('revision_of'):
            import revision
            paper = await revision.generate(task_id)
        elif task.get("brief_input"):
            import brief_generation
            if not task.get("confirmed_brief"):
                await brief_generation.prepare(task_id)
                return
            paper = await brief_generation.generate(task_id)
        else:
            paper = await (generate(task_id) if task["mode"] == "generate" else extract(task_id))
        failed = [q for q in paper.questions if task["mode"] == "generate" and not q.review.get("passed")]
        if failed:
            store.update(task_id, error="审核有建议，当前题目仍可导出，也可填写修改意见生成新版本。")
        full_review = store.load(task_id).get("full_review")
        review_pending = bool(failed or (full_review and not full_review['passed']))
        progress(task_id, "生成可编辑 Word 与配图资源", 92)
        folder = store.task_dir(task_id)
        exports = [await asyncio.to_thread(documents.export_docx, folder, paper, task["options"])]
        if task["mode"] == "generate":
            exports.append(await asyncio.to_thread(documents.export_docx, folder, paper, task["options"], True))
        exports.append(await asyncio.to_thread(documents.export_resources, folder, paper))
        store.update(task_id, status="needs_review" if review_pending else "completed",
                     stage="题目已生成，审核建议可供参考" if review_pending else "处理完成", progress=100,
                     exports=exports, paper=paper.model_dump(),
                     error=("审核有建议，当前题目可直接导出；也可讨论后填写修改意见。" if review_pending else
                            "；".join(store.load(task_id).get("redraw_errors", [])) or None))
    except asyncio.CancelledError:
        store.update(task_id, status="cancelled", stage="已停止", error=None)
        raise
    except Exception as exc:
        # Exception strings here contain no request headers or credentials.
        store.update(task_id, status="failed", stage="处理未完成", error=f"{store.load(task_id).get('stage', '')}：{exc}"[:1000])
    finally:
        model.TASK_FOLDER.reset(context_token)
        RUNNING.pop(task_id, None)


def launch(task_id):
    if task_id in RUNNING:
        raise ValueError("该任务正在处理")
    store.update(task_id, status="queued", stage="已收到继续处理请求，正在准备", error=None)
    RUNNING[task_id] = asyncio.create_task(execute(task_id))


def figure_resolution(task, q):
    """Clear only this question's stale redraw warning when all its drafts are resolved."""
    if any(a.draft_redrawn_image and not a.redrawn_image for a in q.visuals):
        return {}
    prefix = f"第 {q.number or ''} 题重绘未完成："
    q.warnings = [w for w in q.warnings if not w.startswith(prefix)]
    errors = [e for e in task.get("redraw_errors", []) if not e.startswith(prefix)]
    fields = {"redraw_errors": errors}
    if task["status"] == "completed":
        fields.update(error="；".join(errors) or None, stage="配图选择已保存")
    return fields


class ChatAnswer(BaseModel):
    reply: str


async def repair_figure(task_id, paper, q, asset, svg, advice, prior_task):
    """User-requested targeted edit; never redo OCR or unrelated questions."""
    folder = store.task_dir(task_id)
    token = model.TASK_FOLDER.set(folder)
    old_image, old_svg = asset.redrawn_image, asset.svg_file
    if old_image and old_svg and not any(h.get('svg') == old_svg for h in asset.review_history):
        asset.review_history.append({'time': store.now(), 'svg': old_svg, 'image': old_image,
                                     'passed': None, 'issues': ['修改前的版本']})
    try:
        progress(task_id, "正在按你的建议修改配图", prior_task.get("progress", 0), status="running")
        result = await model.ask(prompts.REPAIR_SVG,
            {"stem": q.stem, "issues": [advice], "existing_svg": visuals.safe_path(folder, svg).read_text("utf-8")},
            SvgRepair, [visuals.safe_path(folder, asset.original_image)] if asset.original_image else [])
        if len(result.figures) != 1:
            raise RuntimeError("应返回一张配图")
        asset.svg_file, asset.redrawn_image = await asyncio.to_thread(
            documents.render_svg, result.figures[0].svg, folder, f"{q.id}-{asset.id}-manual-{uuid.uuid4().hex[:8]}")
        asset.draft_svg_file, asset.draft_redrawn_image = asset.svg_file, asset.redrawn_image
        asset.human_accepted = False
        save = lambda: store.update(task_id, paper=paper.model_dump())
        save_draft_checkpoint(q, asset, save)
        if asset.original_image:
            progress(task_id, "新草稿已保存，正在审核", prior_task.get("progress", 0))
            await check_reference_redraw(folder, q, asset, save)
        else:
            asset.review_history.append({'time': store.now(), 'svg': asset.draft_svg_file,
                'image': asset.draft_redrawn_image, 'passed': None, 'issues': ['按教师建议重画，等待人工选择']})
            asset.redrawn_image, asset.svg_file = old_image, old_svg
        visuals.sync_paths(q)
        fields = figure_resolution(prior_task, q)
        fields.setdefault("error", prior_task.get("error"))
        fields["stage"] = "配图修改完成，可查看草稿与审核意见"
        store.update(task_id, paper=paper.model_dump(), status=prior_task["status"], **fields)
    except asyncio.CancelledError:
        asset.redrawn_image, asset.svg_file = old_image, old_svg
        visuals.sync_paths(q)
        store.update(task_id, paper=paper.model_dump(), status="cancelled", stage="配图修改已停止", error=None)
        raise
    except Exception as exc:
        asset.redrawn_image, asset.svg_file = old_image, old_svg
        visuals.sync_paths(q)
        store.update(task_id, paper=paper.model_dump(), status=prior_task["status"],
                     stage="配图草稿待确认", error=f"配图修改未通过：{exc}")
    finally:
        model.TASK_FOLDER.reset(token)
        RUNNING.pop(task_id, None)


async def chat(task_id, message, question_id=None):
    task = store.load(task_id)
    import drafts
    snapshot = drafts.current(task)
    if not snapshot.get("questions"):
        raise ValueError("请等待题目识别完成后再提问。")
    paper = Paper.model_validate(snapshot)
    selected = [q for q in paper.questions if not question_id or q.id == question_id]
    if not selected:
        raise ValueError("没有找到指定题目。")
    # Persist all conversation; send only scoped recent exchanges.
    history = [{"role": m["role"], "content": m["content"]} for m in task["messages"]
               if m.get("question_id") == question_id][-12:]
    store.add_message(task_id, "user", message, question_id)
    answer = await model.ask(
        "回答教师对当前题目或试卷的提问，帮助分析审核建议并拟定具体修改意见。只讨论，不声称已修改文件。需要实际修改时，通过“按对话修改题目”提交；重画图片时给出可执行的布局、标注等建议，提醒可点“按对话重画配图”确认执行；审核是建议，不能宣称它禁止导出。",
        {"message": message, "paper_title": paper.title, "questions": [q.model_dump() for q in selected]},
        ChatAnswer, [path for q in selected for path in images_for(store.task_dir(task_id), q)][:8],
        history=history)
    store.add_message(task_id, "assistant", answer.reply, question_id)
    return answer.reply
