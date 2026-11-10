import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shijuan_studio/main.dart';
import 'package:shijuan_studio/api.dart';

class RecoveryApi extends StudioApi {
  Map<String, dynamic> task;
  Map<String, dynamic>? submitted;
  RecoveryApi(this.task) : super('http://localhost', '');
  @override
  Future<dynamic> get(String path) async {
    if (path == '/health') return <String, dynamic>{};
    if (path == '/tasks') return [task];
    return task;
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    submitted = body;
    task = {...task, 'status': 'queued', 'stage': '已收到建议，正在准备', 'error': null};
    return task;
  }
}

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
  for (final width in [390.0, 1280.0]) {
    testWidgets(
      'teacher clarification resumes with visible progress at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(const StudioApp());
        await tester.pumpAndSettle();
        final dynamic state = tester.state(find.byType(StudioHome));
        final task = <String, dynamic>{
          'id': 'test',
          'title': '待更正题目',
          'mode': 'generate',
          'status': 'failed',
          'error': '原题高度定义不一致',
          'progress': 20,
          'exports': [],
          'paper': null,
          'options': {},
          'source_blocker': {
            'question_id': 'q',
            'number': '13',
            'stem': '水深函数题',
            'issues': ['请确认水深定义'],
          },
        };
        final api = RecoveryApi(task);
        state.api = api;
        state.openResult(task);
        await tester.pumpAndSettle();
        await tester.tap(find.text('补充题目更正或解题建议后继续'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField).last, 'y应为离杯底的水深');
        await tester.tap(find.text('提交并继续'));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        await tester.pump();
        expect(api.submitted?['advice'], 'y应为离杯底的水深');
        expect(find.text('已收到建议，正在准备'), findsOneWidget);
        expect(find.text('处理需要确认'), findsNothing);
        expect(find.byType(CircularProgressIndicator), findsWidgets);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
  testWidgets('draft review edits AI advice and submits targeted repair', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const StudioApp());
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(StudioHome));
    final task = <String, dynamic>{
      'id': 'test',
      'title': '配图待确认',
      'mode': 'convert',
      'status': 'completed',
      'error': null,
      'progress': 100,
      'exports': [],
      'paper': {'questions': []},
      'options': {},
    };
    final api = RecoveryApi(task);
    state.api = api;
    state.openResult(task);
    await tester.pumpAndSettle();
    state.reviewFigure(
      {'id': 'q', 'warnings': []},
      {
        'id': 'a',
        'caption': '图1',
        'draft_redrawn_image': 'media/draft.png',
        'review_issues': ['缺少线段DM'],
        'review_history': [
          {
            'image': 'media/draft.png',
            'svg': 'media/draft.svg',
            'passed': false,
            'issues': ['缺少线段DM'],
          },
        ],
      },
    );
    await tester.pumpAndSettle();
    expect(find.text('重绘草稿与审核意见'), findsOneWidget);
    expect(find.text('缺少线段DM'), findsOneWidget);
    await tester.enterText(find.byType(TextField).last, 'DM已存在，请保留，只调整圆的位置');
    await tester.tap(find.text('按建议重新绘图'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(api.submitted?['action'], 'repair');
    expect(api.submitted?['asset_id'], 'a');
    expect(api.submitted?['advice'], 'DM已存在，请保留，只调整圆的位置');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
    'blocked question preview opens source content, not answer toggle',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const StudioApp());
      await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(StudioHome));
      final source = <String, dynamic>{
        'id': 'source',
        'title': '函数练习卷',
        'files': [
          {'name': '暗光拍照.jpg'},
        ],
        'pages': [],
        'paper': {
          'questions': [
            {
              'id': 'q13',
              'number': '13',
              'stem': '水杯高度定义',
              'parts': ['求水位相同的时间'],
              'options': [],
              'visuals': [],
              'tables': [],
              'visual_groups': [],
            },
          ],
        },
      };
      state.api = RecoveryApi(source);
      state.openResult({
        'id': 'new',
        'source_id': 'source',
        'title': '新卷',
        'mode': 'generate',
        'status': 'failed',
        'error': '需要更正定义',
        'exports': [],
        'paper': null,
        'options': {},
        'source_summary': {
          'title': '函数练习卷',
          'files': ['暗光拍照.jpg'],
        },
        'source_blocker': {
          'question_id': 'q13',
          'number': '13',
          'stem': '水杯高度定义',
          'issues': [],
        },
      });
      await tester.pumpAndSettle();
      expect(find.text('参考试卷：函数练习卷'), findsNothing);
      await tester.tap(find.text('展开'));
      await tester.pumpAndSettle();
      expect(find.text('参考试卷：函数练习卷'), findsOneWidget);
      expect(find.text('查看参考试卷'), findsOneWidget);
      await tester.tap(find.text('查看受阻原题与原稿'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('函数练习卷 · 原题 13'), findsOneWidget);
      expect(find.textContaining('水杯高度定义', findRichText: true), findsWidgets);
      expect(find.textContaining('求水位相同的时间', findRichText: true), findsWidgets);
      await tester.tap(find.text('关闭预览'));
      await tester.pumpAndSettle();
      expect(state.current['id'], 'new');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
