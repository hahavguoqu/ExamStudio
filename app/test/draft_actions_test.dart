import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shijuan_studio/main.dart';
import 'package:shijuan_studio/api.dart';

class DraftApi extends StudioApi {
  Map<String, dynamic> task;
  String? posted;
  Map<String, dynamic>? body;
  DraftApi(this.task) : super('http://localhost', '');
  @override
  Future<dynamic> get(String path) async => path == '/health'
      ? {}
      : path == '/tasks'
      ? [task]
      : task;
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posted = path;
    this.body = body;
    return task;
  }
}

Map<String, dynamic> draftTask(String status) => {
  'id': 'draft',
  'title': '未审核题目',
  'mode': 'generate',
  'status': status,
  'stage': '正在审核',
  'progress': 80,
  'exports': [],
  'error': null,
  'demo': false,
  'messages': [
    {'role': 'assistant', 'content': '放大字母，拉开标签间距，保留几何关系。', 'question_id': 'q'},
  ],
  'paper': {
    'title': '试题',
    'instructions': [],
    'questions': [
      {
        'id': 'q',
        'number': '1',
        'stem': '证明线段相等',
        'kind': '解答题',
        'points': 10,
        'options': [],
        'parts': [],
        'tables': [],
        'visual_groups': [],
        'warnings': [],
        'review': {
          'passed': false,
          'issues': ['难度可提高'],
        },
        'visuals': [
          {
            'id': 'v',
            'caption': '题图',
            'redrawn_image': 'media/a.png',
            'svg_file': 'media/a.svg',
          },
        ],
        'original_images': [],
        'redrawn_images': ['media/a.png'],
      },
    ],
  },
  'draft_versions': ['候选版本 1'],
};

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('cn.shijuan/secure'),
          (_) async => null,
        );
  });
  for (final status in ['running', 'needs_review']) {
    testWidgets('export available without automatic exports: $status', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1280, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const StudioApp());
      await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(StudioHome));
      final task = draftTask(status);
      state.api = DraftApi(task);
      state.openResult(task);
      await tester.pump();
      await tester.tap(find.text('导出').first);
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('当前题目 DOCX（含未审核草稿）'), findsOneWidget);
      expect(find.text('候选版本 1 · 题目'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('chat suggestion goes to editable redraw confirmation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const StudioApp());
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(StudioHome));
    final task = draftTask('needs_review');
    final api = DraftApi(task);
    state.api = api;
    state.openResult(task);
    state.questionId = 'q';
    state.showChat = true;
    await tester.pumpAndSettle();
    await tester.tap(find.text('按对话重画配图'));
    await tester.pumpAndSettle();
    expect(find.text('重绘草稿与审核意见'), findsOneWidget);
    expect(api.posted, isNull);
    final field = find.descendant(
      of: find.byType(AlertDialog),
      matching: find.byType(TextField),
    );
    expect(tester.widget<TextField>(field).controller!.text, contains('放大字母'));
    await tester.enterText(field, '仅放大字母，保留线段连接');
    await tester.tap(find.text('按建议重新绘图'));
    await tester.pumpAndSettle();
    expect(api.posted, '/tasks/draft/figure-review');
    expect(api.body!['advice'], '仅放大字母，保留线段连接');
    expect(api.body!['action'], 'repair');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
