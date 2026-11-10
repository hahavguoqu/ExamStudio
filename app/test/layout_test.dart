import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shijuan_studio/main.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('cn.shijuan/secure'),
          (_) async => null,
        );
  });
  for (final size in [const Size(1280, 900), const Size(390, 844)]) {
    testWidgets('navigation and conversion layout at $size', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const StudioApp());
      await tester.pumpAndSettle();
      expect(find.text('把试卷整理成可编辑 Word'), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (size.width < 1000) {
        await tester.tap(find.byTooltip('Open navigation menu'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('出题').first);
      await tester.pumpAndSettle();
      expect(find.text('先说想考什么，具体要求由 AI 帮你整理。'), findsOneWidget);
      await tester.ensureVisible(find.text('参考题出题'));
      await tester.tap(find.text('参考题出题'));
      await tester.pumpAndSettle();
      expect(find.text('选择参考试卷'), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (Platform.environment.containsKey('SHIJUAN_SERVICE_URL')) {
        if (size.width < 1000) {
          await tester.tap(find.byTooltip('Open navigation menu'));
          await tester.pumpAndSettle();
        }
        await tester.tap(find.text('设置').hitTestable().first);
        await tester.pumpAndSettle();
        expect(find.text('DeepSeek API Key'), findsOneWidget);
        expect(find.text('处理服务地址'), findsNothing);
        expect(find.text('服务连接口令（SERVICE_TOKEN）'), findsNothing);
        expect(tester.takeException(), isNull);
        await tester.tap(find.text('关闭'));
        await tester.pump(const Duration(seconds: 2));
        await tester.pumpAndSettle();
      }
      await tester.pumpWidget(const SizedBox());
    });
  }
}
