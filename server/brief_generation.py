"""Single-question authoring without a source paper, with an explicit confirmation gate."""
import uuid

import brief_prompts
import model
import reference_search
import store
from schemas import BriefDraft, IdeaPlan, Paper, Question, ReviewResult, SolveResult


async def prepare(task_id):
    task = store.load(task_id)
    if 'references' not in task:
        store.update(task_id, stage='正在查找参考题与背景素材', progress=10)
        refs, notes = await reference_search.retrieve(task['brief_input'])
        task = store.update(task_id, references=refs, search_notes=notes)
    store.update(task_id, stage='正在整理命题要求，随后请你确认', progress=25)
    draft = await model.ask(brief_prompts.PREPARE,
        {'input': task['brief_input'], 'references': task['references'],
         'retrieval_notes': task.get('search_notes', [])}, BriefDraft)
    store.update(task_id, title=draft.title[:120], brief_draft=draft.model_dump(),
                 status='awaiting_confirmation', stage='请确认或修改命题要求', progress=30, error=None)


def provenance(q, references):
    lookup = {r['id']: r for r in references}
    if any(rid not in lookup for rid in q.reference_ids):
        raise ValueError('候选题引用了不存在的资料编号')
    used = [lookup[rid] for rid in dict.fromkeys(q.reference_ids)]
    q.provenance = 'AI 按教师确认要求生成；不声明全网原创。'
    if used:
        q.provenance += '\n参考资料（参考题或背景借鉴，不代表原作者撰写本题）：\n' + '\n'.join(
            f'[{r["id"]}] {r["category"]}：{r["title"]}\n{r["url"]}' for r in used)
    else:
        q.provenance += ' 本题未标注具体参考借鉴。'


async def generate(task_id):
    import pipeline  # Existing drawing, persistence and export behavior stays shared.
    task = store.load(task_id)
    folder = store.task_dir(task_id)
    context = {'confirmed_requirements': task['confirmed_brief'], 'original_input': task['brief_input'],
               'references': task.get('references', []), 'retrieval_notes': task.get('search_notes', [])}
    if not task.get('idea_plan'):
        pipeline.progress(task_id, '正在比较命题方向', 35)
        plan = await model.ask(brief_prompts.DESIGN, context, IdeaPlan)
        if plan.selected >= len(plan.ideas):
            raise ValueError('命题方向选择无效，请从当前步骤继续')
        task = store.update(task_id, idea_plan=plan.model_dump())
    context['selected_design'] = task['idea_plan']['ideas'][task['idea_plan']['selected']]
    paper = Paper.model_validate(task['paper']) if task.get('paper') else Paper(title=task['title'])
    if paper.questions and paper.questions[0].review.get('passed'):
        return paper
    feedback = paper.questions[0].review.get('issues', []) if paper.questions else []
    for attempt in range(1):
        pending = store.load(task_id).get('brief_pending')
        if pending:
            q = Question.model_validate(pending['question'])
        else:
            pipeline.progress(task_id, '正在生成单题' if not feedback else '正在根据审核修正单题', 45)
            q = await model.ask(brief_prompts.GENERATE, {**context, 'previous_issues': feedback}, Question)
            q.id, q.number = uuid.uuid4().hex[:12], '1'
            q.source_ids = []
            # Only generated geometry is allowed; LLM paths cannot enter storage.
            q.figures, q.original_images, q.redrawn_images, q.svg_files = [], [], [], []
            for a in q.visuals:
                a.source_region = None
                a.original_image = a.redrawn_image = a.svg_file = ''
                a.draft_redrawn_image = a.draft_svg_file = ''
            pending = {'question': q.model_dump()}
            store.update(task_id, brief_pending=pending)
        def save():
            pending['question'] = q.model_dump()
            store.update(task_id, brief_pending=pending)
        pipeline.progress(task_id, '正在绘制题目配图', 55)
        await pipeline.redraw(folder, q, save)
        save()
        pipeline.progress(task_id, '正在独立解答，核对题目是否成立', 68)
        blind = SolveResult.model_validate(pending['blind']) if pending.get('blind') else await model.ask(
            __import__('prompts').SOLVE, pipeline.public_question(q), SolveResult, pipeline.images_for(folder, q))
        pending['blind'] = blind.model_dump()
        save()
        pipeline.progress(task_id, '正在审核要求、难度与引用', 80)
        review = await model.ask(brief_prompts.REVIEW,
            {**context, 'candidate': q.model_dump(), 'independent_solution': blind.model_dump()},
            ReviewResult, pipeline.images_for(folder, q))
        if blind.issues:
            review.passed = False
            review.issues.extend(blind.issues)
        try:
            provenance(q, task.get('references', []))
        except ValueError as exc:
            review.passed = False
            review.issues.append(str(exc))
            q.provenance = 'AI 按要求生成；引用待核实。'
        q.review = review.model_dump()
        paper.questions = [q]
        latest = store.load(task_id)
        history = latest.get('brief_candidates', []) + [q.model_dump()]
        store.update(task_id, paper=paper.model_dump(), brief_pending=None, brief_candidates=history)
        if review.passed:
            break
        feedback = review.issues
    return paper
