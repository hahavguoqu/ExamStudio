import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shijuan_studio/task_notice.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('long diagnostics stay bounded and collapse at $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var resumed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                TaskNotice(
                  title: '题目已整理，部分配图待确认',
                  summary: taskNoticeSummary({'status': 'completed'}),
                  details: Text(
                    List.filled(100, '第2题：圆与正方形的位置需要确认。').join('\n'),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => resumed = true,
                      child: const Text('从失败步骤继续'),
                    ),
                  ],
                ),
                const Expanded(child: Center(child: Text('题目预览'))),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final notice = find.byType(TaskNotice);
      final collapsed = tester.getSize(notice).height;
      expect(collapsed, lessThan(200));
      expect(find.textContaining('第2题：'), findsNothing);
      await tester.tap(find.text('展开'));
      await tester.pumpAndSettle();
      expect(find.text('收起'), findsOneWidget);
      expect(tester.getSize(notice).height, lessThan(collapsed + 200));
      expect(tester.getRect(find.text('题目预览')).bottom, lessThan(844));
      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -300),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('收起'));
      await tester.pumpAndSettle();
      expect(tester.getSize(notice).height, collapsed);
      await tester.tap(find.text('从失败步骤继续'));
      expect(resumed, isTrue);
      expect(tester.takeException(), isNull);
    });
  }
}
