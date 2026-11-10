import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shijuan_studio/visual_group.dart';
import 'package:shijuan_studio/question_table.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('panels and table images preserve labels at $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Widget figure(String id) => SizedBox(height: 80, child: Text('图片$id'));
      final panels = [
        {'title': '作图方法一', 'figure_id': 'f1', 'text': '作垂线'},
        {'title': '作图方法二', 'figure_id': 'f2', 'text': '作圆弧'},
        {'title': '备用图', 'figure_id': 'f3', 'text': ''},
      ];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Column(
                children: [
                  VisualGroupView({
                    'columns': 2,
                    'panels': panels,
                  }, figureBuilder: figure),
                  QuestionTableView({
                    'rows': 1,
                    'columns': 1,
                    'cells': [
                      {
                        'row': 0,
                        'column': 0,
                        'text': '表内说明',
                        'panels': [panels[0]],
                      },
                    ],
                  }, figureBuilder: figure),
                ],
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('图片f1'), findsNWidgets(2));
      expect(find.text('图片f2'), findsOneWidget);
      expect(find.text('备用图'), findsOneWidget);
      expect(tester.takeException(), isNull);
      final first = tester.getTopLeft(find.text('作图方法一').first);
      final second = tester.getTopLeft(find.text('作图方法二'));
      if (width < 600) {
        expect(second.dy, greaterThan(first.dy));
      } else {
        expect(second.dy, first.dy);
        expect(second.dx, greaterThan(first.dx));
      }
      await tester.pumpWidget(const SizedBox());
    });
  }
}
