import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shijuan_studio/api.dart';
import 'package:shijuan_studio/brief_authoring.dart';

class BriefApi extends StudioApi {
  Map<String, dynamic>? body;
  String? path;
  Completer<dynamic>? pending;
  bool fail = false;
  BriefApi() : super('http://localhost', '');
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    this.path = path;
    this.body = body;
    if (fail) throw Exception('连接暂时不可用');
    return pending == null
        ? {'id': 'new', 'status': 'queued'}
        : pending!.future;
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  for (final width in [390.0, 1280.0]) {
    testWidgets(
      'brief form allows background only and shows submitting at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        if (const bool.fromEnvironment('BRIEF_SCREENSHOT')) {
          await tester.runAsync(() async {
            final loader = FontLoader('Microsoft YaHei UI');
            loader.addFont(
              File(
                'C:/Windows/Fonts/msyh.ttc',
              ).readAsBytes().then((v) => ByteData.sublistView(v)),
            );
            await loader.load();
            final icons = FontLoader('MaterialIcons');
            icons.addFont(
              File(
                'C:/flutter/bin/cache/artifacts/material_fonts/materialicons-regular.otf',
              ).readAsBytes().then((v) => ByteData.sublistView(v)),
            );
            await icons.load();
          });
        }
        final api = BriefApi()..pending = Completer();
        dynamic created;
        final boundaryKey = GlobalKey();
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(
              fontFamily: 'Microsoft YaHei UI',
              colorScheme: ColorScheme.fromSeed(
                seedColor: const Color(0xff3068dd),
              ),
              inputDecorationTheme: const InputDecorationTheme(
                border: OutlineInputBorder(),
              ),
            ),
            home: Scaffold(
              body: RepaintBoundary(
                key: boundaryKey,
                child: ColoredBox(
                  color: Colors.white,
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(24),
                    child: BriefAuthoring(
                      api: api,
                      onCreated: (v) => created = v,
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField).at(2), '机器人巡检');
        await tester.pumpAndSettle();
        if (const bool.fromEnvironment('BRIEF_SCREENSHOT')) {
          final boundary =
              boundaryKey.currentContext!.findRenderObject()
                  as RenderRepaintBoundary;
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final data = await image.toByteData(format: ui.ImageByteFormat.png);
            final file = File('../work/ui-preview/brief-$width.png');
            await file.parent.create(recursive: true);
            await file.writeAsBytes(data!.buffer.asUint8List());
          });
        }
        await tester.ensureVisible(find.text('整理命题要求'));
        await tester.tap(find.text('整理命题要求'));
        await tester.pump();
        expect(find.text('正在提交…'), findsOneWidget);
        expect(api.body!['background'], '机器人巡检');
        expect(api.body!['topic'], '');
        expect(api.path, '/brief-tasks');
        api.pending!.complete({'id': 'new', 'status': 'queued'});
        await tester.pumpAndSettle();
        expect(created['id'], 'new');
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('confirmation preserves edited text after failure at $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = BriefApi()..fail = true;
      dynamic confirmed;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: BriefConfirmation(
                api: api,
                task: {
                  'id': 'draft',
                  'brief_draft': {
                    'brief': '原要求',
                    'notes': ['请核对难度'],
                  },
                  'search_notes': [],
                  'references': [],
                },
                onConfirmed: (v) => confirmed = v,
              ),
            ),
          ),
        ),
      );
      await tester.enterText(find.byType(TextField), '改为机器人巡检的填空题');
      await tester.ensureVisible(find.text('确认并出题'));
      await tester.tap(find.text('确认并出题'));
      await tester.pumpAndSettle();
      expect(find.text('连接暂时不可用'), findsOneWidget);
      expect(find.text('改为机器人巡检的填空题'), findsOneWidget);
      api.fail = false;
      await tester.ensureVisible(find.text('确认并出题'));
      await tester.tap(find.text('确认并出题'));
      await tester.pumpAndSettle();
      expect(api.body!['brief'], '改为机器人巡检的填空题');
      expect(confirmed['status'], 'queued');
      expect(tester.takeException(), isNull);
    });
  }
}
