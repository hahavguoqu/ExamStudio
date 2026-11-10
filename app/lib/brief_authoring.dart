import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';

class BriefAuthoring extends StatefulWidget {
  final StudioApi api;
  final ValueChanged<dynamic> onCreated;
  const BriefAuthoring({super.key, required this.api, required this.onCreated});
  @override
  State<BriefAuthoring> createState() => _BriefAuthoringState();
}

class _BriefAuthoringState extends State<BriefAuthoring> {
  final topic = TextEditingController(),
      model = TextEditingController(),
      background = TextEditingController(),
      extra = TextEditingController();
  String grade = '初三', purpose = '日常练习', kind = '自动选择';
  bool search = true, busy = false, touched = false;
  String? error;
  static const grades = ['初一', '初二', '初三', '高一', '高二', '高三'];
  static const purposes = ['初学巩固', '日常练习', '考试训练', '竞赛训练'];
  @override
  void initState() {
    super.initState();
    restore();
  }

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted || touched) return;
    setState(() {
      final g = prefs.getString('brief_grade'),
          p = prefs.getString('brief_purpose');
      if (grades.contains(g)) grade = g!;
      if (purposes.contains(p)) purpose = p!;
    });
  }

  @override
  void dispose() {
    for (final c in [topic, model, background, extra]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> submit() async {
    if (busy) return;
    if ([topic, model, background, extra].every((c) => c.text.trim().isEmpty)) {
      setState(() => error = '至少填写一个方向：考查内容、模型、背景或补充要求。');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.post('/brief-tasks', {
        'grade': grade,
        'purpose': purpose,
        'kind': kind,
        'topic': topic.text.trim(),
        'model_name': model.text.trim(),
        'background': background.text.trim(),
        'extra': extra.text.trim(),
        'search': search,
      });
      // Preference persistence must not hide a successfully created task.
      try {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('brief_grade', grade);
        await prefs.setString('brief_purpose', purpose);
      } catch (_) {}
      if (mounted) widget.onCreated(result);
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget select(
    String label,
    String value,
    List<String> choices,
    ValueChanged<String> change,
  ) => SizedBox(
    width: 210,
    child: DropdownButtonFormField<String>(
      key: ValueKey('$label:$value'),
      initialValue: value,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      items: choices
          .map((v) => DropdownMenuItem(value: v, child: Text(v)))
          .toList(),
      onChanged: busy
          ? null
          : (v) {
              touched = true;
              setState(() => change(v!));
            },
    ),
  );
  Widget field(
    String label,
    String hint,
    TextEditingController controller, {
    int lines = 1,
  }) => Padding(
    padding: const EdgeInsets.only(top: 18),
    child: TextField(
      controller: controller,
      enabled: !busy,
      minLines: lines,
      maxLines: lines + 2,
      maxLength: controller == extra ? 2000 : 300,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        counterText: '',
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '先说想考什么，具体要求由 AI 帮你整理。',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 8),
      const Text(
        '不需要参考题，也不用填写所有内容。确认要求之后才会开始出题。',
        style: TextStyle(color: Color(0xff68717e), height: 1.6),
      ),
      const SizedBox(height: 24),
      Wrap(
        spacing: 14,
        runSpacing: 16,
        children: [
          select('年级', grade, grades, (v) => grade = v),
          select('用途与难度', purpose, purposes, (v) => purpose = v),
          select('题型', kind, ['自动选择', '选择题', '填空题', '解答题'], (v) => kind = v),
        ],
      ),
      field('考查内容（选填）', '例如：导角、线段证明、二次函数最值', topic),
      field('指定模型（选填，填写后必须满足）', '例如：婆罗摩笈多模型', model),
      field('指定背景（选填，填写后必须满足）', '例如：机器人运动；也可以要求近期真实事件', background),
      field('补充要求（选填）', '例如：中考压轴难度、不用三角函数、两个小问', extra, lines: 2),
      const SizedBox(height: 12),
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        value: search,
        onChanged: busy ? null : (v) => setState(() => search = v!),
        title: const Text('联网寻找参考题与背景素材'),
        subtitle: const Text('允许合理借鉴；实际使用的资料会注明来源。'),
      ),
      if (error != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(error!, style: const TextStyle(color: Colors.red)),
        ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: busy ? null : submit,
        icon: busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.edit_note),
        label: Text(busy ? '正在提交…' : '整理命题要求'),
      ),
    ],
  );
}

class BriefConfirmation extends StatefulWidget {
  final StudioApi api;
  final Map<String, dynamic> task;
  final ValueChanged<dynamic> onConfirmed;
  const BriefConfirmation({
    super.key,
    required this.api,
    required this.task,
    required this.onConfirmed,
  });
  @override
  State<BriefConfirmation> createState() => _BriefConfirmationState();
}

class _BriefConfirmationState extends State<BriefConfirmation> {
  late final TextEditingController text;
  bool busy = false;
  String? error;
  @override
  void initState() {
    super.initState();
    text = TextEditingController(text: widget.task['brief_draft']['brief']);
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  Future<void> confirm() async {
    if (busy) return;
    if (text.text.trim().isEmpty) {
      setState(() => error = '请保留命题要求。');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final task = await widget.api.post(
        '/tasks/${widget.task['id']}/confirm-brief',
        {'brief': text.text.trim()},
      );
      if (mounted) widget.onConfirmed(task);
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        '确认这道题怎么出',
        style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 12),
      const Text('下面是 AI 整理的命题要求。可以直接修改；确认后按这份要求生成一道题。'),
      const SizedBox(height: 22),
      TextField(
        controller: text,
        enabled: !busy,
        minLines: 8,
        maxLines: 20,
        maxLength: 6000,
        decoration: const InputDecoration(
          labelText: '命题要求',
          alignLabelWithHint: true,
        ),
      ),
      for (final note in [
        ...?widget.task['brief_draft']['notes'],
        ...?widget.task['search_notes'],
      ])
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Text(
            note.toString(),
            style: const TextStyle(color: Color(0xff946629)),
          ),
        ),
      const SizedBox(height: 16),
      ReferenceMaterials(task: widget.task),
      if (error != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(error!, style: const TextStyle(color: Colors.red)),
        ),
      const SizedBox(height: 22),
      FilledButton.icon(
        onPressed: busy ? null : confirm,
        icon: busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.auto_awesome_outlined),
        label: Text(busy ? '正在开始出题…' : '确认并出题'),
      ),
    ],
  );
}

class ReferenceMaterials extends StatelessWidget {
  final Map<String, dynamic> task;
  const ReferenceMaterials({super.key, required this.task});
  @override
  Widget build(BuildContext context) {
    final refs = (task['references'] as List?) ?? [];
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text('参考资料（${refs.length}）'),
      subtitle: const Text('检索到的资料不一定全部采用；实际引用见题目解析。'),
      children: [
        if (refs.isEmpty)
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('没有可用的联网参考资料。'),
          ),
        for (final r in refs)
          Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SelectableText(
                  '[${r['id']}] ${r['category']} · ${r['title']}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                if (r['date'] != null) Text('资料日期：${r['date']}'),
                SelectableText(
                  r['url'],
                  style: const TextStyle(color: Color(0xff3068dd)),
                ),
                if (r['summary_only'] == true) const Text('仅获得搜索摘要，未获取完整正文。'),
                const SizedBox(height: 6),
                Text(
                  (r['content'] as String).length > 500
                      ? '${(r['content'] as String).substring(0, 500)}…'
                      : r['content'],
                ),
              ],
            ),
          ),
      ],
    );
  }
}
