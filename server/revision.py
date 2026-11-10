"""Teacher-directed edits create a new task; no original question is overwritten."""
import shutil
import uuid

import brief_prompts
import model
import pipeline
import prompts
import store
from schemas import Paper, Question, ReviewResult, SolveResult


def create(task, paper, question, advice):
    new = store.create(task['title'] + ' · 修改版', 'generate', task['options'],
        revision_of=task['id'], revision_question_id=question['id'], revision_original=question,
        revision_advice=advice, revision_context=task.get('confirmed_brief', task['options'].get('requirements', '')),
        references=task.get('references', []), discussion=[m for m in task.get('messages', [])
            if m.get('question_id') in (None, question['id'])][-12:])
    source = store.task_dir(task['id']).resolve()
    target = store.task_dir(new['id']).resolve()
    media = source / 'media'
    if media.exists():
        shutil.copytree(media, target / 'media')
    store.update(new['id'], paper=paper, candidate_history=[paper])
    store.add_message(new['id'], 'user', '修改意见：' + advice, question['id'])
    return store.load(new['id'])


async def generate(task_id):
    task = store.load(task_id)
    folder = store.task_dir(task_id)
    paper = Paper.model_validate(task['paper'])
    if task.get('revision_done'):
        return paper
    old = Question.model_validate(task['revision_original'])
    index = next(i for i, q in enumerate(paper.questions) if q.id == task['revision_question_id'])
    context = {'original_question': old.model_dump(), 'previous_requirements': task['revision_context'],
               'teacher_advice': task['revision_advice'], 'discussion': task['discussion'],
               'references': task['references']}
    pending = task.get('revision_pending')
    if not pending:
        pipeline.progress(task_id, '正在按教师意见修改题目，保留原版', 35)
        q = await model.ask(brief_prompts.GENERATE + '\n这是修改现有题目。以teacher_advice为本轮最高要求；只改需要改的内容，未要求改变的核心目标保留。讨论记录与审核仅供参考，不强制服从审核。返回完整修改题、答案及解析。',
                            context, Question, pipeline.images_for(folder, old))
        q.id, q.number = uuid.uuid4().hex[:12], old.number
        q.provenance = old.provenance + '\n本版由 AI 根据教师修改意见调整。'
        q.figures, q.original_images, q.redrawn_images, q.svg_files = [], [], [], []
        for asset in q.visuals:
            asset.source_region = None
            asset.original_image = asset.redrawn_image = asset.svg_file = ''
            asset.draft_svg_file = asset.draft_redrawn_image = ''
        pending = {'slot': index, 'question': q.model_dump()}
        store.update(task_id, revision_pending=pending)
    q = Question.model_validate(pending['question'])
    def save():
        pending['question'] = q.model_dump()
        store.update(task_id, revision_pending=pending)
    pipeline.progress(task_id, '正在更新修改题的配图', 50)
    await pipeline.redraw(folder, q, save)
    save()
    pipeline.progress(task_id, '正在独立解答修改后的题目', 65)
    blind = SolveResult.model_validate(pending['blind']) if pending.get('blind') else await model.ask(
        prompts.SOLVE, pipeline.public_question(q), SolveResult, pipeline.images_for(folder, q))
    pending['blind'] = blind.model_dump()
    save()
    pipeline.progress(task_id, '正在提供修改版的审核建议', 80)
    review = await model.ask(brief_prompts.REVIEW + '\n本轮teacher_advice优先于previous_requirements；审核只给建议，不决定是否允许导出。',
        {**context, 'candidate': q.model_dump(), 'independent_solution': blind.model_dump()},
        ReviewResult, pipeline.images_for(folder, q))
    if blind.issues:
        review.passed = False
        review.issues.extend(blind.issues)
    q.review = review.model_dump()
    paper.questions[index] = q
    store.update(task_id, paper=paper.model_dump(), revision_pending=None, revision_done=True,
                 candidate_history=[*task.get('candidate_history', []), paper.model_dump()])
    return paper
