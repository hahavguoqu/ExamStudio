import copy
import pipeline


def test_variation_uses_abstract_target_not_original_problem_or_solution():
    context = {'target': {'core': ['几何关系建立函数模型']},
               'requirements': {'creativity': 'variation'},
               'source': [{'stem': '图形题', 'parts': ['求函数关系'],
                           'teacher_clarification': '沿对角线移动', 'difficulty': '中等',
                           'answer': '2', 'solution': '原题的逐步解法',
                           'core': ['具体菱形性质'], 'supporting': ['等边三角形'],
                           'method': '固定步骤', 'knowledge': '详细知识讲解'}]}
    before = copy.deepcopy(context)
    result = pipeline.generation_context(context)
    assert 'source' not in result
    assert result['reference_profile'] == [{'difficulty': '中等'}]
    assert result['target'] == context['target']
    assert context == before  # Full source still available for independent review.


def test_parameter_variant_retains_reference_solution():
    context = {'requirements': {'creativity': 'parameters'}, 'source': [{'solution': '原方法'}]}
    assert pipeline.generation_context(context)['source'][0]['solution'] == '原方法'
