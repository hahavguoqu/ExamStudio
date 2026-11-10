import 'dart:math' as math;
import 'package:flutter/material.dart';

/// Keeps task diagnostics from pushing the question list off screen.
class TaskNotice extends StatefulWidget {
  final String title;
  final String summary;
  final Widget details;
  final List<Widget> actions;
  const TaskNotice({
    super.key,
    required this.title,
    required this.summary,
    required this.details,
    required this.actions,
  });

  @override
  State<TaskNotice> createState() => _TaskNoticeState();
}

class _TaskNoticeState extends State<TaskNotice> {
  bool expanded = false;
  final scroll = ScrollController();

  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    color: const Color(0xfffff8ed),
    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                widget.title,
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  color: Color(0xff805d2c),
                ),
              ),
            ),
            TextButton.icon(
              onPressed: () => setState(() => expanded = !expanded),
              icon: Icon(
                expanded ? Icons.expand_less : Icons.expand_more,
                size: 18,
              ),
              label: Text(expanded ? '收起' : '展开'),
            ),
          ],
        ),
        Text(
          widget.summary,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(color: Color(0xff805d2c), height: 1.5),
        ),
        if (expanded)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: math.min(
                  180,
                  MediaQuery.sizeOf(context).height * .22,
                ),
              ),
              child: Scrollbar(
                controller: scroll,
                thumbVisibility: true,
                child: SingleChildScrollView(
                  controller: scroll,
                  primary: false,
                  padding: const EdgeInsets.only(right: 12),
                  child: widget.details,
                ),
              ),
            ),
          ),
        Wrap(spacing: 8, children: widget.actions),
      ],
    ),
  );
}

String taskNoticeSummary(Map<String, dynamic> task) {
  if (task['source_blocker'] != null) {
    return '原题 ${task['source_blocker']['number']} 的题意需要确认，已完成的分析已保存。';
  }
  if (task['status'] == 'completed') {
    return '部分配图暂未通过核对，已保留原图。具体原因见对应题目下方。';
  }
  final error = (task['error'] ?? '').toString();
  if (error.contains('超时')) return 'AI 请求超时，已保留当前结果，可从失败步骤继续。';
  if (error.contains('输出') && (error.contains('上限') || error.contains('预算'))) {
    return 'AI 输出达到上限，已保留当前结果，可从失败步骤继续。';
  }
  if (error.contains('审核') || error.contains('复核')) {
    return '题目已生成，可直接导出。审核建议供你决定是否修改。';
  }
  return '本次处理尚未完成，已保留当前结果。展开查看原因后可继续。';
}
