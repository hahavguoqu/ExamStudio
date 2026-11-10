import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shijuan_studio/question_table.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('merged table and math fit at $width', (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: QuestionTableView({
                'rows': 3,
                'columns': 3,
                'caption': '数表',
                'cells': [
                  {'row': 0, 'column': 0, 'column_span': 3, 'text': '根据下表回答问题'},
                  {'row': 1, 'column': 0, 'row_span': 2, 'text': r'$A_1=$'},
                  {'row': 1, 'column': 1, 'text': r'$\frac{1}{2}$'},
                  {'row': 1, 'column': 2, 'text': '-1'},
                  {'row': 2, 'column': 1, 'text': '较长的项目背景文字。' * 8},
                  {'row': 2, 'column': 2, 'text': ''},
                ],
              }),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('根据下表回答问题'), findsOneWidget);
      expect(find.text('-1'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
