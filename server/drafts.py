"""Read-only snapshots for preview, discussion and export, including in-flight candidates."""
from copy import deepcopy


def current(task):
    paper = deepcopy(task.get('paper') or {'title': task['title'], 'questions': []})
    pending = task.get('revision_pending') or task.get('brief_pending') or task.get('pending')
    if pending and pending.get('question'):
        index = pending.get('slot', 0)
        questions = paper.setdefault('questions', [])
        if index < len(questions):
            questions[index] = deepcopy(pending['question'])
        else:
            questions.append(deepcopy(pending['question']))
    return paper


def versions(task):
    papers = list(task.get('candidate_history', []))
    for q in task.get('brief_candidates', []):
        papers.append({'title': task['title'], 'questions': [q]})
    return papers
