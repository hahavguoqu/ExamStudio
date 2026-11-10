import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shijuan_studio/math_text.dart';

void main() {
  testWidgets('Chinese text with inline fractions and geometry renders', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 360,
            child: MathText(
              r'求 $\frac{1}{2}+\frac{1}{3}$，已知 $\angle A=90^\circ$。',
            ),
          ),
        ),
      ),
    );
    expect(tester.takeException(), isNull);
    expect(find.byType(MathText), findsOneWidget);
  });
}
