import 'dart:async';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'secure_store.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';
import 'math_text.dart';
import 'question_table.dart';
import 'visual_group.dart';
import 'task_notice.dart';
import 'brief_authoring.dart';

const ink = Color(0xff252a33),
    muted = Color(0xff68717e),
    blue = Color(0xff3068dd);
const rail = Color(0xfff7f8fa), line = Color(0xffe8ebef);
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const StudioApp());
}

class StudioApp extends StatelessWidget {
  const StudioApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '试卷工作室',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: Platform.isWindows ? 'Microsoft YaHei UI' : null,
      scaffoldBackgroundColor: Colors.white,
      colorScheme: ColorScheme.fromSeed(
        seedColor: blue,
        primary: blue,
        surface: Colors.white,
      ),
      textTheme: const TextTheme(
        bodyMedium: TextStyle(color: ink, fontSize: 14),
      ),
      dividerTheme: const DividerThemeData(color: line, thickness: 1, space: 1),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 18),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.all(14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: line),
        ),
      ),
    ),
    home: const StudioHome(),
  );
}

class StudioHome extends StatefulWidget {
  const StudioHome({super.key});
  @override
  State<StudioHome> createState() => _StudioHomeState();
}

class _StudioHomeState extends State<StudioHome> {
  StudioApi api = StudioApi(
    Platform.isAndroid ? 'http://10.0.2.2:8765' : 'http://127.0.0.1:8765',
    '',
  );
  final secure = const SecureStore();
  final chatInput = TextEditingController(),
      requirements = TextEditingController();
  final scaffoldKey = GlobalKey<ScaffoldState>();
  List<dynamic> tasks = [];
  List<PlatformFile> files = [];
  final Map<PlatformFile, int?> fileSizes = {};
  bool picking = false;
  int filesRead = 0, filesToRead = 0;
  int? uploadSent, uploadTotal;
  Map<String, dynamic>? current, health;
  String page = 'convert',
      layout = 'clean',
      figureMode = 'both',
      difficulty = 'same',
      creativity = 'variation';
  String? questionId;
  final titleSearch = TextEditingController();
  String searchTitle = '';
  double sidebarWidth = 230;
  List<dynamic> get matchingTasks => tasks
      .where(
        (t) => t['title'].toString().toLowerCase().contains(
          searchTitle.trim().toLowerCase(),
        ),
      )
      .toList();
  bool busy = false,
      chatting = false,
      loading = true,
      connected = false,
      polling = false;
  bool showChat = false, showAnswers = false;
  bool loadingSource = false;
  bool freeAuthoring = true;
  Timer? poll;
  @override
  void initState() {
    super.initState();
    initialize();
    poll = Timer.periodic(const Duration(seconds: 3), (_) async {
      await pollTask();
      if (!polling &&
          tasks.any((t) => ['queued', 'running'].contains(t['status']))) {
        await refresh();
      }
    });
  }

  @override
  void dispose() {
    poll?.cancel();
    titleSearch.dispose();
    chatInput.dispose();
    requirements.dispose();
    super.dispose();
  }

  Future<void> initialize() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      api = StudioApi(
        Platform.environment['SHIJUAN_SERVICE_URL'] ??
            prefs.getString('service_url') ??
            api.baseUrl,
        Platform.environment['SERVICE_TOKEN'] ??
            await secure.read(key: 'service_token') ??
            '',
      );
    } catch (_) {
      /* Settings remain available if credential storage fails. */
    }
    await refresh();
  }

  void notice(String text) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(text.replaceFirst('Exception: ', '')),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<void> refresh() async {
    try {
      final result = await api.get('/health'), list = await api.get('/tasks');
      if (mounted) {
        setState(() {
          health = Map<String, dynamic>.from(result);
          tasks = list;
          connected = true;
          loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          connected = false;
          loading = false;
        });
      }
    }
  }

  Future<void> pollTask() async {
    if (polling ||
        current == null ||
        !['queued', 'running'].contains(current!['status'])) {
      return;
    }
    polling = true;
    final id = current!['id'];
    try {
      final value = await api.get('/tasks/$id');
      if (mounted && current?['id'] == id) {
        setState(() => current = Map<String, dynamic>.from(value));
      }
      if (!['queued', 'running'].contains(value['status'])) await refresh();
    } catch (_) {
      if (mounted) setState(() => connected = false);
    } finally {
      polling = false;
    }
  }

  Future<void> run(Future<void> Function() action) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await action();
    } catch (e) {
      notice(e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Map<String, dynamic> options() => {
    'layout': layout,
    'figures': figureMode,
    'difficulty': difficulty,
    'creativity': creativity,
    'requirements': requirements.text,
    'scope': questionId == null ? 'paper' : 'single',
    'question_id': questionId,
  };
  void navigate(String value) {
    setState(() {
      page = value;
      current = null;
      questionId = null;
      showChat = false;
    });
    scaffoldKey.currentState?.closeDrawer();
  }

  void openResult(dynamic value) {
    if (mounted) {
      setState(() {
        current = Map<String, dynamic>.from(value);
        page = 'workspace';
        questionId = null;
        showAnswers = false;
      });
    }
  }

  Future<void> selectTask(String id) async {
    await run(() async => openResult(await api.get('/tasks/$id')));
    scaffoldKey.currentState?.closeDrawer();
  }

  Future<void> pick() async {
    if (picking || busy) return;
    setState(() {
      picking = true;
      filesRead = 0;
      filesToRead = 0;
    });
    try {
      final result = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg', 'webp'],
      );
      if (!mounted) return;
      setState(() {
        files.addAll(result);
        filesToRead = result.length;
      });
      for (final file in result) {
        int? size;
        try {
          size = await file.length();
        } catch (_) {
          /* Show an explicit read failure. */
        }
        if (!mounted) return;
        setState(() {
          fileSizes[file] = size;
          filesRead++;
        });
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('读取文件失败：$error')));
      }
    } finally {
      if (mounted) setState(() => picking = false);
    }
  }

  Future<void> startUpload() => run(() async {
    if (files.isEmpty || picking) return;
    final selected = List<PlatformFile>.of(files);
    setState(() {
      uploadSent = 0;
      uploadTotal = null;
    });
    try {
      openResult(
        await api.upload(
          selected,
          options(),
          onProgress: (sent, total) {
            if (mounted) {
              setState(() {
                uploadSent = sent;
                uploadTotal = total;
              });
            }
          },
        ),
      );
      await refresh();
    } finally {
      if (mounted) {
        setState(() {
          uploadSent = null;
          uploadTotal = null;
        });
      }
    }
  });
  Future<void> openDemo() => run(() async {
    openResult(await api.post('/demo'));
    await refresh();
  });
  Future<void> download(String path) => run(() async {
    final task = Map<String, dynamic>.from(current!);
    int? version;
    if (path.startsWith('version:')) {
      final parts = path.split(':');
      version = int.parse(parts[1]);
      path = parts[2];
    }
    if (path.endsWith('.docx')) {
      final result = await api.post('/tasks/${task['id']}/export', {
        'teacher': path.contains('teacher'),
        'version': version,
      });
      path = result['path'];
    }
    final response = await api.download(task['id'], path),
        suffix = path.split('.').last;
    final label = path.contains('teacher')
        ? '答案与解析'
        : path.contains('figures')
        ? '配图资源'
        : '试卷';
    final title = task['title'].toString().replaceAll(
      RegExp(r'[<>:"/\\|?*]'),
      '_',
    );
    final name =
        '$title-${version == null ? "" : "候选${version + 1}-"}$label.$suffix';
    if (Platform.isWindows) {
      final target = await FilePicker.saveFile(
        dialogTitle: '保存$label',
        fileName: name,
        bytes: response.bodyBytes,
        type: FileType.custom,
        allowedExtensions: [suffix],
      );
      if (target != null) {
        notice('已保存$label');
      }
    } else {
      final directory = await getTemporaryDirectory();
      final file = File('${directory.path}/$name');
      await file.writeAsBytes(response.bodyBytes);
      await SharePlus.instance.share(
        ShareParams(files: [XFile(file.path)], text: label),
      );
    }
  });

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 1000;
    return Scaffold(
      key: scaffoldKey,
      drawer: wide ? null : Drawer(child: sidebar()),
      appBar: wide
          ? null
          : AppBar(
              title: const Text('试卷工作室', style: TextStyle(fontSize: 18)),
              actions: [
                IconButton(
                  onPressed: settings,
                  tooltip: '连接设置',
                  icon: const Icon(Icons.settings_outlined),
                ),
              ],
            ),
      body: Row(
        children: [
          if (wide) SizedBox(width: sidebarWidth, child: sidebar()),
          if (wide)
            MouseRegion(
              cursor: SystemMouseCursors.resizeColumn,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onHorizontalDragUpdate: (details) => setState(() {
                  sidebarWidth = (sidebarWidth + details.delta.dx).clamp(
                    210.0,
                    MediaQuery.sizeOf(context).width * .4,
                  );
                }),
                child: Tooltip(
                  message: '左右拖动调整侧栏宽度',
                  child: Container(width: 6, color: line),
                ),
              ),
            ),
          Expanded(
            child: Column(
              children: [
                toolbar(wide),
                Expanded(child: body(wide)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget sidebar() => Container(
    decoration: const BoxDecoration(
      color: rail,
      border: Border(right: BorderSide(color: line)),
    ),
    child: SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 30, 16, 18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(left: 12),
              child: Row(
                children: [
                  Icon(Icons.auto_stories_outlined, color: blue, size: 27),
                  SizedBox(width: 10),
                  Text(
                    '试卷工作室',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 9),

            const SizedBox(height: 35),
            nav('convert', '转成 Word', Icons.description_outlined),
            nav('generate', '出题', Icons.edit_note_outlined),
            nav('history', '历史任务', Icons.history_outlined),
            const SizedBox(height: 20),
            TextField(
              controller: titleSearch,
              style: const TextStyle(fontSize: 12),
              onChanged: (value) => setState(() => searchTitle = value),
              decoration: InputDecoration(
                hintText: '搜索任务标题',
                hintStyle: const TextStyle(fontSize: 12, color: muted),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 8,
                ),
                prefixIconConstraints: const BoxConstraints(
                  minWidth: 30,
                  minHeight: 32,
                ),
                suffixIconConstraints: const BoxConstraints(
                  minWidth: 30,
                  minHeight: 32,
                ),
                prefixIcon: const Icon(Icons.search, size: 16),
                suffixIcon: searchTitle.isEmpty
                    ? null
                    : IconButton(
                        tooltip: '清除搜索',
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () {
                          titleSearch.clear();
                          setState(() => searchTitle = '');
                        },
                      ),
                isDense: true,
              ),
            ),
            const SizedBox(height: 18),
            const Padding(
              padding: EdgeInsets.only(left: 12),
              child: Text('最近使用', style: TextStyle(color: muted, fontSize: 12)),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: ListView(
                children: matchingTasks.isEmpty && searchTitle.isNotEmpty
                    ? [
                        const Padding(
                          padding: EdgeInsets.all(12),
                          child: Text('没有匹配的任务'),
                        ),
                      ]
                    : matchingTasks
                          .take(
                            searchTitle.trim().isEmpty
                                ? 7
                                : matchingTasks.length,
                          )
                          .map<Widget>(
                            (t) => ListTile(
                              dense: true,
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 12,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                              selected: current?['id'] == t['id'],
                              selectedTileColor: const Color(0xffeaf0fd),
                              title: Text(
                                t['title'],
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 13),
                              ),
                              subtitle: Text(
                                t['demo'] == true
                                    ? '演示材料'
                                    : statusName(t['status']),
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: muted,
                                ),
                              ),
                              trailing: taskActions(t),
                              onTap: () => selectTask(t['id']),
                            ),
                          )
                          .toList(),
              ),
            ),
            const Divider(),
            const SizedBox(height: 10),
            ListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 12),
              leading: const Icon(Icons.tune, size: 20),
              title: const Text('设置'),
              onTap: settings,
            ),
          ],
        ),
      ),
    ),
  );
  Widget nav(String id, String name, IconData icon) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: ListTile(
      dense: true,
      selected: page == id,
      selectedColor: blue,
      selectedTileColor: const Color(0xffeaf0fd),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      leading: Icon(icon, size: 21),
      title: Text(name, style: const TextStyle(fontSize: 14)),
      onTap: () => navigate(id),
    ),
  );
  Widget toolbar(bool wide) => Container(
    height: 64,
    padding: EdgeInsets.symmetric(horizontal: wide ? 30 : 16),
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: line)),
    ),
    child: Row(
      children: [
        Expanded(
          child: Text(
            current == null
                ? (page == 'generate'
                      ? '出题 / 新的练习'
                      : page == 'history'
                      ? '我的任务'
                      : '文档 / 转成 Word')
                : current!['title'],
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: muted, fontSize: 13),
          ),
        ),
        if (busy)
          const Padding(
            padding: EdgeInsets.only(right: 12),
            child: SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        Icon(
          Icons.circle,
          size: 7,
          color: connected ? const Color(0xff3f906d) : const Color(0xffb08a45),
        ),
        const SizedBox(width: 7),
        Text(
          connected ? '已就绪' : '正在连接',
          style: const TextStyle(fontSize: 12, color: muted),
        ),
        IconButton(
          onPressed: busy ? null : refresh,
          tooltip: '刷新连接',
          icon: const Icon(Icons.refresh, size: 18),
        ),
      ],
    ),
  );
  Widget body(bool wide) {
    if (loading) return const Center(child: CircularProgressIndicator());
    if (current != null) return workspace(wide);
    if (page == 'history') return history();
    if (page == 'generate') return generateHome();
    return convertHome();
  }

  Widget pageContent(List<Widget> children) => SingleChildScrollView(
    padding: const EdgeInsets.all(28),
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 970),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: children,
        ),
      ),
    ),
  );
  Widget connectionBanner() => Container(
    margin: const EdgeInsets.only(bottom: 20),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xfff6f8fc),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.info_outline, color: muted, size: 19),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            !connected
                ? '处理组件未连接，请重新打开软件。'
                : '请在设置中填写 DeepSeek API Key，即可开始识别和出题。也可以先体验演示材料。',
            style: const TextStyle(fontSize: 13, color: muted, height: 1.6),
          ),
        ),
        TextButton(onPressed: settings, child: const Text('设置')),
      ],
    ),
  );
  Widget convertHome() => pageContent([
    const SizedBox(height: 18),
    const Text(
      '把试卷整理成可编辑 Word',
      style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600, height: 1.4),
    ),
    const SizedBox(height: 12),
    const Text(
      '照片、扫描件和电子文档，整理为文字、公式与配图。\n导出后，在 Word 或 WPS 中继续修改。',
      style: TextStyle(color: muted, fontSize: 14, height: 1.9),
    ),
    const SizedBox(height: 28),
    if (!connected || health?['model_configured'] != true) connectionBanner(),
    InkWell(
      onTap: busy || picking ? null : pick,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 38, horizontal: 20),
        decoration: BoxDecoration(
          color: const Color(0xfff9fbff),
          border: Border.all(color: const Color(0xffd8e3f7)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.all(13),
              decoration: BoxDecoration(
                color: const Color(0xffeaf0fd),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.note_add_outlined, color: blue, size: 30),
            ),
            const SizedBox(height: 16),
            const Text(
              '选择试卷或题目文件',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 9),
            const Text(
              'PDF · Word · JPG · PNG · WebP',
              style: TextStyle(color: muted, fontSize: 12),
            ),
            const SizedBox(height: 5),
            const Text(
              '支持多文件，按选择顺序整理',
              style: TextStyle(color: muted, fontSize: 12),
            ),
          ],
        ),
      ),
    ),
    if (picking) ...[
      const SizedBox(height: 14),
      LinearProgressIndicator(
        value: filesToRead == 0 ? null : filesRead / filesToRead,
      ),
      Text(filesToRead == 0 ? '等待选择文件…' : '正在读取文件 $filesRead / $filesToRead'),
    ],
    if (uploadSent != null) ...[
      const SizedBox(height: 14),
      LinearProgressIndicator(
        value: uploadTotal == null || uploadTotal == 0
            ? null
            : uploadSent! / uploadTotal!,
      ),
      const SizedBox(height: 8),
      Text(
        uploadTotal == null
            ? '正在准备上传…'
            : uploadSent! >= uploadTotal!
            ? '文件已发送，等待服务确认…'
            : '正在上传 ${(100 * uploadSent! / uploadTotal!).toStringAsFixed(0)}% · ${formatFileSize(uploadSent!)} / ${formatFileSize(uploadTotal!)}',
      ),
    ],
    ...files.asMap().entries.map(
      (entry) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.insert_drive_file_outlined, color: muted),
        title: Text(entry.value.name, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          !fileSizes.containsKey(entry.value)
              ? '正在读取文件大小…'
              : fileSizes[entry.value] == null
              ? '无法读取大小，请移除后重新选择'
              : formatFileSize(fileSizes[entry.value]!),
        ),
        trailing: IconButton(
          onPressed: busy || picking
              ? null
              : () => setState(() {
                  fileSizes.remove(entry.value);
                  files.removeAt(entry.key);
                }),
          tooltip: '移除文件',
          icon: const Icon(Icons.close, size: 18),
        ),
      ),
    ),
    const SizedBox(height: 26),
    const Text(
      '整理方式',
      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 14),
    LayoutBuilder(
      builder: (context, box) {
        final items = [
          choice(
            '连续排题',
            '题目连续排列，Word 按内容自动换页；适合重新编排试卷。',
            layout == 'clean',
            () => setState(() => layout = 'clean'),
          ),
          choice(
            '按原页分组',
            '原稿下一页开始的题目，另起一页；组内仍由 Word 自动排版。',
            layout == 'original',
            () => setState(() => layout = 'original'),
          ),
        ];
        return box.maxWidth > 600
            ? Row(
                children: [
                  Expanded(child: items[0]),
                  const SizedBox(width: 14),
                  Expanded(child: items[1]),
                ],
              )
            : Column(
                children: [items[0], const SizedBox(height: 10), items[1]],
              );
      },
    ),
    const SizedBox(height: 22),
    const Text(
      '例如：原第 2 页从第 6 题开始，“按原页分组”会在第 6 题前换页。两者都保留题序，使用相同字体与表格样式；跨页题合并，均不复刻原稿布局。DOCX 不提供原页分组信息。',
      style: TextStyle(color: muted, fontSize: 12),
    ),
    const SizedBox(height: 16),
    dropdown('几何配图', figureMode, {
      'both': '保留原图 + AI 重绘 SVG',
      'original': '仅保留原图',
      'redraw': '重绘 SVG 并用于试卷（仍保留原图）',
    }, (v) => setState(() => figureMode = v)),
    const SizedBox(height: 24),
    Wrap(
      spacing: 14,
      runSpacing: 10,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        FilledButton.icon(
          onPressed: busy || picking || files.isEmpty ? null : startUpload,
          icon: const Icon(Icons.auto_awesome_outlined, size: 18),
          label: const Text('开始整理'),
        ),
        TextButton(
          onPressed: busy || !connected ? null : openDemo,
          child: const Text('打开演示材料'),
        ),
        const Text(
          '识别与重绘通过云端 API 完成',
          style: TextStyle(color: muted, fontSize: 12),
        ),
      ],
    ),
  ]);
  Widget choice(String title, String desc, bool selected, VoidCallback onTap) =>
      InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            border: Border.all(color: selected ? blue : line),
            borderRadius: BorderRadius.circular(8),
            color: selected ? const Color(0xfff7faff) : Colors.white,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                selected ? Icons.radio_button_checked : Icons.radio_button_off,
                color: selected ? blue : muted,
                size: 19,
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      desc,
                      style: const TextStyle(
                        fontSize: 12,
                        color: muted,
                        height: 1.7,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
  Widget dropdown(
    String label,
    String value,
    Map<String, String> entries,
    ValueChanged<String> onChanged,
  ) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
      ),
      const SizedBox(height: 8),
      DropdownButtonFormField<String>(
        initialValue: value,
        isExpanded: true,
        items: entries.entries
            .map(
              (e) => DropdownMenuItem(
                value: e.key,
                child: Text(
                  e.value,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            )
            .toList(),
        onChanged: (v) {
          if (v != null) onChanged(v);
        },
      ),
    ],
  );
  Widget generateHome() => pageContent([
    const SizedBox(height: 18),
    const Text(
      '设计一道适合学生的题',
      style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 12),
    const Text(
      '按教学要求设计单题，或从已有试卷生成变式。',
      style: TextStyle(color: muted, height: 1.9),
    ),
    const SizedBox(height: 28),
    if (!connected || health?['model_configured'] != true) connectionBanner(),
    Wrap(
      spacing: 12,
      runSpacing: 8,
      children: [
        ChoiceChip(
          label: const Text('按要求出题'),
          selected: freeAuthoring,
          onSelected: (_) => setState(() => freeAuthoring = true),
        ),
        ChoiceChip(
          label: const Text('参考题出题'),
          selected: !freeAuthoring,
          onSelected: (_) => setState(() => freeAuthoring = false),
        ),
      ],
    ),
    const SizedBox(height: 28),
    if (freeAuthoring)
      BriefAuthoring(
        api: api,
        onCreated: (value) {
          openResult(value);
          refresh();
        },
      ),
    if (!freeAuthoring) ...[
      Row(
        children: [
          const Expanded(
            child: Text(
              '选择参考试卷',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
          ),
          TextButton.icon(
            onPressed: () => navigate('convert'),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('导入新试卷'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      if (tasks.where((t) => t['status'] == 'completed').isEmpty)
        empty('还没有整理好的试卷', '先导入一份试卷，或打开演示材料体验界面。'),
      ...tasks.where((t) => t['status'] == 'completed').map<Widget>(taskRow),
      const SizedBox(height: 26),
      const Text(
        '参考题模式使用上传材料进行改编；按要求出题可联网查找参考资料。',
        style: TextStyle(color: muted, height: 1.8, fontSize: 12),
      ),
    ],
  ]);
  Widget history() => pageContent([
    const Text(
      '历史任务',
      style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 12),
    const Text('原稿、生成结果与对话记录会自动保存。', style: TextStyle(color: muted)),
    const SizedBox(height: 26),
    if (tasks.isEmpty) empty('还没有任务', '导入文件后，处理记录会保存在这里。'),
    if (tasks.isNotEmpty && matchingTasks.isEmpty)
      empty('没有匹配的任务', '请修改左侧标题搜索条件。'),
    if (searchTitle.isNotEmpty)
      Text('搜索：$searchTitle', style: const TextStyle(color: muted)),
    ...matchingTasks.map<Widget>(taskRow),
  ]);
  Widget taskActions(dynamic task) => PopupMenuButton<String>(
    tooltip: '任务操作',
    enabled: !busy,
    onSelected: (action) =>
        action == 'rename' ? renameTask(task) : deleteTask(task),
    itemBuilder: (_) => const [
      PopupMenuItem(value: 'rename', child: Text('重命名')),
      PopupMenuItem(
        value: 'delete',
        child: Text('删除', style: TextStyle(color: Colors.red)),
      ),
    ],
  );

  Future<void> renameTask(dynamic task) async {
    var draft = task['title'].toString();
    final title = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('重命名任务'),
        content: TextFormField(
          initialValue: draft,
          onChanged: (value) => draft = value,
          autofocus: true,
          maxLength: 120,
          decoration: const InputDecoration(labelText: '任务名称'),
          onFieldSubmitted: (value) {
            if (value.trim().isNotEmpty) Navigator.pop(ctx, value.trim());
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () {
              if (draft.trim().isNotEmpty) Navigator.pop(ctx, draft.trim());
            },
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (title == null || !mounted) return;
    await run(() async {
      final updated = await api.renameTask(task['id'], title);
      if (mounted && current?['id'] == task['id']) {
        setState(() => current = Map<String, dynamic>.from(updated));
      }
      await refresh();
    });
  }

  Future<void> deleteTask(dynamic task) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除任务？'),
        content: Text(
          '“${task['title']}”将从历史任务和最近使用中移除。本机文件仍保留，以供关联出题任务使用；已下载的文件不受影响。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('删除', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await run(() async {
      await api.deleteTask(task['id']);
      if (mounted && current?['id'] == task['id']) navigate('history');
      await refresh();
    });
  }

  Widget taskRow(dynamic t) => Container(
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: line)),
    ),
    child: ListTile(
      contentPadding: const EdgeInsets.symmetric(vertical: 10),
      leading: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: rail,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(
          t['mode'] == 'generate'
              ? Icons.auto_awesome_outlined
              : Icons.description_outlined,
          color: blue,
          size: 22,
        ),
      ),
      title: Text(t['title'], maxLines: 2),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 7),
        child: Text(
          '${t['demo'] == true
              ? '人工演示材料'
              : t['mode'] == 'generate'
              ? '出题'
              : '文档整理'}  ·  ${statusName(t['status'])}',
          style: const TextStyle(color: muted, fontSize: 12),
        ),
      ),
      trailing: taskActions(t),
      onTap: () => selectTask(t['id']),
    ),
  );
  Widget empty(String title, String subtitle) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 48),
    child: Center(
      child: Column(
        children: [
          const Icon(Icons.folder_open_outlined, size: 40, color: muted),
          const SizedBox(height: 16),
          Text(title, style: const TextStyle(fontSize: 17)),
          const SizedBox(height: 8),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(color: muted),
          ),
        ],
      ),
    ),
  );
  String statusName(String? status) =>
      {
        'queued': '等待处理',
        'running': '处理中',
        'completed': '已完成',
        'failed': '处理失败',
        'needs_review': '有审核建议',
        'cancelled': '已停止',
        'interrupted': '已中断',
        'awaiting_confirmation': '待确认要求',
      }[status] ??
      '未知状态';

  Widget workspace(bool wide) {
    if (current!['status'] == 'awaiting_confirmation') {
      return pageContent([
        BriefConfirmation(
          key: ValueKey(current!['id']),
          api: api,
          task: current!,
          onConfirmed: (value) {
            openResult(value);
            refresh();
          },
        ),
      ]);
    }
    final paper = current!['paper'] as Map?,
        questions = (current!['paper']?['questions'] as List?) ?? [];
    final active = ['queued', 'running'].contains(current!['status']);
    final document = Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: line)),
          ),
          child: Wrap(
            spacing: 10,
            runSpacing: 10,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              TextButton.icon(
                onPressed: questions.isEmpty
                    ? (current!['source_id'] != null && !busy
                          ? () => sourcePreview()
                          : null)
                    : () => setState(() => showAnswers = !showAnswers),
                icon: Icon(
                  showAnswers ? Icons.menu_book : Icons.description_outlined,
                  size: 18,
                ),
                label: Text(
                  questions.isEmpty
                      ? (loadingSource ? '正在加载参考试卷…' : '查看参考试卷')
                      : (showAnswers ? '隐藏解析' : '显示解析'),
                ),
              ),
              if (questions.isNotEmpty)
                TextButton.icon(
                  onPressed: busy ? null : revisionDialog,
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: const Text('按意见修改题目'),
                ),
              if (questions.isNotEmpty)
                TextButton.icon(
                  onPressed: busy || active ? null : generationDialog,
                  icon: const Icon(Icons.auto_awesome_outlined, size: 18),
                  label: Text(questionId == null ? '根据整卷出题' : '根据选中题出题'),
                ),
              TextButton.icon(
                onPressed: () => openChat(wide),
                icon: const Icon(Icons.chat_bubble_outline, size: 18),
                label: const Text('与 AI 讨论'),
              ),
              if (questions.isNotEmpty)
                PopupMenuButton<String>(
                  tooltip: '导出文件',
                  onSelected: download,
                  itemBuilder: (_) => [
                    const PopupMenuItem(
                      value: 'paper.docx',
                      child: Text('当前题目 DOCX（含未审核草稿）'),
                    ),
                    const PopupMenuItem(
                      value: 'teacher.docx',
                      child: Text('当前答案与解析 DOCX'),
                    ),
                    for (final f in current!['exports'] as List)
                      if (f.toString().endsWith('.zip'))
                        PopupMenuItem(value: f, child: const Text('配图资源包')),
                    for (
                      var i = 0;
                      i < (current!['draft_versions'] as List? ?? []).length;
                      i++
                    ) ...[
                      PopupMenuItem(
                        value: 'version:$i:paper.docx',
                        child: Text('候选版本 ${i + 1} · 题目'),
                      ),
                      PopupMenuItem(
                        value: 'version:$i:teacher.docx',
                        child: Text('候选版本 ${i + 1} · 答案与解析'),
                      ),
                    ],
                  ],
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 17,
                      vertical: 10,
                    ),
                    decoration: BoxDecoration(
                      color: blue,
                      borderRadius: BorderRadius.circular(7),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.file_download_outlined,
                          color: Colors.white,
                          size: 18,
                        ),
                        SizedBox(width: 6),
                        Text('导出', style: TextStyle(color: Colors.white)),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
        if (active)
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                Row(
                  children: [
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        current!['stage'],
                        style: const TextStyle(color: muted),
                      ),
                    ),
                    TextButton(
                      onPressed: () => run(
                        () async => openResult(
                          await api.post('/tasks/${current!['id']}/cancel'),
                        ),
                      ),
                      child: const Text('停止'),
                    ),
                  ],
                ),
                LinearProgressIndicator(
                  value: (current!['progress'] as num).toDouble() / 100,
                  minHeight: 3,
                ),
              ],
            ),
          ),
        if (current!['error'] != null && !active)
          TaskNotice(
            key: ValueKey('notice-${current!['id']}'),
            title: current!['status'] == 'completed'
                ? '题目已整理，部分配图待确认'
                : current!['status'] == 'needs_review'
                ? '审核建议（不影响导出）'
                : '处理需要确认',
            summary: taskNoticeSummary(Map<String, dynamic>.from(current!)),
            details: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (current!['source_id'] != null) ...[
                  Text(
                    '参考试卷：${current!['source_summary']?['title'] ?? current!['title']}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if ((current!['source_summary']?['files'] as List? ?? [])
                      .isNotEmpty)
                    SelectableText(
                      '来源文件：${(current!['source_summary']['files'] as List).join('、')}',
                    ),
                ],
                MathText(
                  current!['error'],
                  style: const TextStyle(color: Color(0xff805d2c), height: 1.6),
                ),
              ],
            ),
            actions: [
              if (questions.isNotEmpty)
                TextButton(
                  onPressed: busy ? null : revisionDialog,
                  child: const Text('按我的意见修改'),
                ),
              TextButton(
                onPressed: busy ? null : () => continueTask(),
                child: Text(busy ? '正在提交…' : '从失败步骤继续'),
              ),
              if (current!['source_blocker'] != null) ...[
                TextButton.icon(
                  onPressed: busy ? null : () => sourcePreview(focused: true),
                  icon: const Icon(Icons.description_outlined, size: 18),
                  label: Text(loadingSource ? '正在加载原题…' : '查看受阻原题与原稿'),
                ),
                TextButton.icon(
                  onPressed: busy ? null : () => sourceAdvice(),
                  icon: const Icon(Icons.edit_note),
                  label: const Text('补充题目更正或解题建议后继续'),
                ),
              ],
            ],
          ),
        if (current!['demo'] == true)
          Container(
            width: double.infinity,
            color: const Color(0xfff0f5ff),
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 10),
            child: const Text(
              '人工编写的演示材料 · 用于体验预览、原图 / SVG 和导出，未调用 AI。',
              style: TextStyle(color: blue, fontSize: 12, height: 1.6),
            ),
          ),
        Expanded(
          child: questions.isEmpty
              ? empty(
                  active
                      ? '正在处理'
                      : current!['source_blocker'] != null
                      ? '新题尚未生成，请先确认原题'
                      : '暂无题目结果',
                  active ? '可以切换页面，处理仍会继续；请保持软件打开。' : '请查看任务状态或重试。',
                )
              : Container(
                  color: const Color(0xfff5f6f8),
                  child: ListView(
                    padding: EdgeInsets.all(wide ? 30 : 14),
                    children: [
                      if (current!['confirmed_brief'] != null)
                        ExpansionTile(
                          title: const Text('本题命题要求与参考资料'),
                          children: [
                            SelectableText(current!['confirmed_brief']),
                            ReferenceMaterials(task: current!),
                          ],
                        ),
                      if ((current!['pages'] as List? ?? []).isNotEmpty)
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton.icon(
                            onPressed: originalPages,
                            icon: const Icon(Icons.image_outlined, size: 17),
                            label: const Text('查看上传原稿'),
                          ),
                        ),
                      Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 820),
                          child: Container(
                            padding: EdgeInsets.all(wide ? 40 : 22),
                            decoration: BoxDecoration(
                              color: Colors.white,
                              border: Border.all(color: line),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Center(
                                  child: Text(
                                    paper?['title'] ?? '',
                                    textAlign: TextAlign.center,
                                    style: const TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.w600,
                                      height: 1.7,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 14),
                                ...((paper?['instructions'] as List?) ?? [])
                                    .map(
                                      (x) => Padding(
                                        padding: const EdgeInsets.only(
                                          bottom: 8,
                                        ),
                                        child: MathText(
                                          x,
                                          style: const TextStyle(
                                            fontSize: 13,
                                            height: 1.7,
                                          ),
                                        ),
                                      ),
                                    ),
                                const SizedBox(height: 20),
                                const Divider(),
                                ...questions.asMap().entries.map(
                                  (entry) => question(entry.value, entry.key),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
        ),
      ],
    );
    return Row(
      children: [
        Expanded(child: document),
        if (wide && showChat)
          Container(
            width: 330,
            decoration: const BoxDecoration(
              border: Border(left: BorderSide(color: line)),
            ),
            child: chatPanel(),
          ),
      ],
    );
  }

  bool usesRedraw(dynamic q) =>
      (current?['figure_modes']?[q['id']] ?? current?['options']?['figures']) ==
      'redraw';

  Future<void> continueTask([String? advice]) => run(() async {
    final id = current!['id'];
    final result = await api.post('/tasks/$id/retry', {'advice': ?advice});
    openResult(result);
    notice('已提交，正在继续处理；下方会更新当前步骤。');
    await refresh();
    await pollTask();
  });

  Future<T?> completedDialog<T>({
    required BuildContext context,
    required WidgetBuilder builder,
  }) async {
    final route = DialogRoute<T>(context: context, builder: builder);
    final result = await Navigator.of(context).push(route);
    await route.completed;
    return result;
  }

  Future<void> sourcePreview({bool focused = false}) => run(() async {
    final task = Map<String, dynamic>.from(current!);
    final sourceId = task['source_id'] as String?;
    if (sourceId == null) return;
    dynamic source;
    setState(() => loadingSource = true);
    try {
      source = await api.get('/tasks/$sourceId');
    } finally {
      if (mounted) setState(() => loadingSource = false);
    }
    if (!mounted) return;
    final paper = task['analysis'] ?? source['paper'];
    final all = paper?['questions'] as List? ?? [];
    final blocker = task['source_blocker'];
    final selected = focused && blocker != null
        ? all.where((q) => q['id'] == blocker['question_id']).toList()
        : all;
    if (selected.isEmpty) throw Exception('暂未找到对应原题，请打开参考试卷检查。');
    Widget sourceImage(String path) => InteractiveViewer(
      minScale: 0.5,
      maxScale: 5,
      child: Image.network(
        api.uri('/tasks/$sourceId/files/$path').toString(),
        headers: api.headers,
        fit: BoxFit.contain,
        errorBuilder: (_, _, _) => const Text('原稿图片加载失败，请检查连接'),
      ),
    );
    await completedDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          focused
              ? '${source['title']} · 原题 ${blocker['number']}'
              : '${source['title']} · 参考试卷',
        ),
        content: SizedBox(
          width: 820,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                SelectableText(
                  '来源文件：${(source['files'] as List? ?? []).map((f) => f['name']).join('、')}',
                ),
                const SizedBox(height: 16),
                for (final q in selected) ...[
                  Text(
                    '原题 ${q['number'] ?? ''}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  MathText(q['stem'] ?? ''),
                  ...tableViews(q, 'stem', 0, ownerId: sourceId),
                  for (final entry
                      in (q['options'] as List? ?? []).asMap().entries) ...[
                    MathText(
                      '${String.fromCharCode(65 + entry.key)}. ${entry.value}',
                    ),
                    ...tableViews(q, 'option', entry.key, ownerId: sourceId),
                  ],
                  for (final entry
                      in (q['parts'] as List? ?? []).asMap().entries) ...[
                    MathText(entry.value),
                    ...tableViews(q, 'part', entry.key, ownerId: sourceId),
                  ],
                  for (final asset in q['visuals'] as List? ?? [])
                    if (!referencedVisuals(q).contains(asset['id']))
                      visualAsset(q, asset['id'], ownerId: sourceId),
                  if ((q['visuals'] as List? ?? []).isEmpty)
                    for (final path in q['original_images'] as List? ?? [])
                      sourceImage(path),
                  const Divider(),
                ],
                for (final entry
                    in (source['pages'] as List? ?? []).asMap().entries)
                  ExpansionTile(
                    title: Text(
                      '上传原稿 · 第 ${entry.key + 1} 页${focused && entry.key == selected.first['source_page'] ? ' · 本题所在页' : ''}（可缩放）',
                    ),
                    children: [sourceImage(entry.value['path'])],
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭预览'),
          ),
        ],
      ),
    );
  });

  Future<void> sourceAdvice() async {
    final blocker = current!['source_blocker'];
    final controller = TextEditingController(
      text: (current!['source_advice'] ?? {})[blocker['question_id']] ?? '',
    );
    final value = await completedDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('原题 ${blocker['number']} · 补充说明'),
        content: SizedBox(
          width: 650,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                MathText(blocker['stem'] ?? ''),
                const SizedBox(height: 12),
                MathText((blocker['issues'] as List? ?? []).join('；')),
                const SizedBox(height: 16),
                TextField(
                  controller: controller,
                  minLines: 4,
                  maxLines: 10,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: '你的更正或解题建议',
                    hintText: '例如：y 表示离杯底的水深。请按此定义重新解题。',
                  ),
                ),
                const SizedBox(height: 8),
                const Text('建议将用于这道原题的重新解答；已完成的其他题目会保留。'),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              if (controller.text.trim().isNotEmpty) {
                Navigator.pop(context, controller.text.trim());
              }
            },
            child: const Text('提交并继续'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (value != null && mounted) await continueTask(value);
  }

  Future<void> reviewFigure(
    dynamic q,
    dynamic asset, {
    String? initialAdvice,
  }) async {
    final taskId = current!['id'];
    final history = asset['review_history'] as List? ?? [];
    int? selected;
    final controller = TextEditingController(
      text:
          initialAdvice ??
          ((asset['review_issues'] as List? ?? []).isNotEmpty
                  ? asset['review_issues'] as List
                  : q['warnings'] as List? ?? [])
              .join('；'),
    );
    final action = await completedDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) {
          final version = selected == null ? null : history[selected!];
          final imagePath =
              version?['image'] ??
              ((asset['draft_redrawn_image'] ?? '').toString().isNotEmpty
                  ? asset['draft_redrawn_image']
                  : asset['redrawn_image']);
          Widget picture(String path) => Image.network(
            api.uri('/tasks/$taskId/files/$path').toString(),
            headers: api.headers,
            height: 240,
            fit: BoxFit.contain,
            errorBuilder: (_, _, _) => const Text('图片加载失败'),
          );
          return AlertDialog(
            title: const Text('重绘草稿与审核意见'),
            content: SizedBox(
              width: 760,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if ((asset['original_image'] ?? '')
                        .toString()
                        .isNotEmpty) ...[
                      const Text('原图'),
                      picture(asset['original_image']),
                      const SizedBox(height: 12),
                    ],
                    const Text('重绘草稿（可人工决定是否采用）'),
                    if (imagePath != null && imagePath.toString().isNotEmpty)
                      picture(imagePath),
                    if (history.isNotEmpty)
                      DropdownButton<int>(
                        isExpanded: true,
                        value: selected,
                        hint: const Text('当前草稿 · 可切换历史版本'),
                        items: [
                          for (var i = 0; i < history.length; i++)
                            DropdownMenuItem(
                              value: i,
                              child: Text(
                                '版本 ${i + 1} · ${history[i]['passed'] == true ? '审核通过' : '审核待确认'}',
                              ),
                            ),
                        ],
                        onChanged: (i) => update(() {
                          selected = i;
                          controller.text =
                              (history[i!]['issues'] as List? ?? []).join('；');
                        }),
                      ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: controller,
                      minLines: 4,
                      maxLines: 12,
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        labelText: 'AI 审核意见 / 你的修改要求',
                        hintText: '可以修改审核意见，再让 AI 按你的要求绘图。',
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text('采用草稿是你的人工决定，不代表 AI 审核通过。原图和历史草稿会保留。'),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('关闭'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, {'action': 'original'}),
                child: const Text('使用原图'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, {
                  'action': 'accept',
                  'history_index': selected,
                }),
                child: const Text('采用这张草稿'),
              ),
              FilledButton(
                onPressed: () {
                  if (controller.text.trim().isNotEmpty) {
                    Navigator.pop(context, {
                      'action': 'repair',
                      'advice': controller.text.trim(),
                      'history_index': selected,
                    });
                  }
                },
                child: const Text('按建议重新绘图'),
              ),
            ],
          );
        },
      ),
    );
    controller.dispose();
    if (action != null && mounted) {
      await run(() async {
        final result = await api.post('/tasks/$taskId/figure-review', {
          ...action,
          'question_id': q['id'],
          'asset_id': asset['id'],
        });
        if (current?['id'] == taskId) openResult(result);
        notice(
          action['action'] == 'repair' ? '已提交修改，正在重新绘图。' : '配图选择已保存，导出时生效。',
        );
        await refresh();
      });
    }
  }

  Future<void> toggleFigure(dynamic q) => run(() async {
    final result = await api.post('/tasks/${current!['id']}/figures', {
      'question_id': q['id'],
      'mode': usesRedraw(q) ? 'original' : 'redraw',
    });
    if (mounted) setState(() => current = Map<String, dynamic>.from(result));
  });

  Widget visualAsset(dynamic q, String id, {String? ownerId}) {
    final matches = ((q['visuals'] as List?) ?? []).where((v) => v['id'] == id);
    if (matches.isEmpty) return const Text('配图引用无效');
    final asset = matches.first;
    final original = asset['original_image'] as String? ?? '';
    final redraw = asset['redrawn_image'] as String? ?? '';
    final path = ownerId == null && usesRedraw(q) && redraw.isNotEmpty
        ? redraw
        : original.isNotEmpty
        ? original
        : redraw;
    return Column(
      children: [
        if (path.isNotEmpty)
          Image.network(
            api
                .uri('/tasks/${ownerId ?? current!['id']}/files/$path')
                .toString(),
            headers: api.headers,
            height: 220,
            fit: BoxFit.contain,
            errorBuilder: (_, _, _) => const Text('配图暂不可用，请检查连接'),
          )
        else
          const Text('配图尚未生成'),
        if ((asset['caption'] ?? '').toString().isNotEmpty)
          MathText(asset['caption']),
      ],
    );
  }

  Set<String> referencedVisuals(dynamic q) {
    final ids = <String>{};
    void add(dynamic panels) {
      for (final p in (panels as List? ?? [])) {
        if (p['figure_id'] != null) ids.add(p['figure_id'] as String);
      }
    }

    for (final g in (q['visual_groups'] as List? ?? [])) {
      add(g['panels']);
    }
    for (final t in (q['tables'] as List? ?? [])) {
      for (final c in (t['cells'] as List)) {
        add(c['panels']);
      }
    }
    return ids;
  }

  List<Widget> tableViews(
    dynamic q,
    String after,
    int index, {
    String? ownerId,
  }) {
    final items = <Map<String, dynamic>>[
      for (final t in (q['tables'] as List? ?? []))
        {'kind': 'table', 'value': t},
      for (final g in (q['visual_groups'] as List? ?? []))
        {'kind': 'group', 'value': g},
    ];
    for (var i = 0; i < items.length; i++) {
      items[i]['sequence'] = i;
    }
    items.sort((a, b) {
      final order = ((a['value']['order'] ?? 0) as int).compareTo(
        (b['value']['order'] ?? 0) as int,
      );
      return order != 0
          ? order
          : (a['sequence'] as int).compareTo(b['sequence'] as int);
    });
    return items
        .where(
          (item) =>
              (item['value']['after'] ?? 'stem') == after &&
              (item['value']['after_index'] ?? 0) == index,
        )
        .map<Widget>((item) {
          final value = Map<String, dynamic>.from(item['value']);
          return item['kind'] == 'table'
              ? QuestionTableView(
                  value,
                  figureBuilder: (id) => visualAsset(q, id, ownerId: ownerId),
                )
              : VisualGroupView(
                  value,
                  figureBuilder: (id) => visualAsset(q, id, ownerId: ownerId),
                );
        })
        .toList();
  }

  Widget question(dynamic q, int index) {
    final selected = questionId == q['id'],
        originals = q['original_images'] as List? ?? [],
        redraws = q['redrawn_images'] as List? ?? [];
    final images = usesRedraw(q) && redraws.isNotEmpty
        ? redraws
        : originals.isNotEmpty
        ? originals
        : redraws;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 22),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '第 ${q['number']?.toString().isNotEmpty == true ? q['number'] : index + 1} 题${q['points'] != null ? '  /  ${q['points']} 分' : ''}',
                  style: const TextStyle(fontSize: 12, color: muted),
                ),
              ),
              TextButton(
                onPressed: () =>
                    setState(() => questionId = selected ? null : q['id']),
                child: Text(
                  selected ? '已选中 · 取消' : '选择本题',
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
          if ((q['visuals'] as List? ?? []).isNotEmpty &&
              originals.isNotEmpty &&
              redraws.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: busy ? null : () => toggleFigure(q),
                child: Text(usesRedraw(q) ? '重绘图 · 切换原图' : '原图 · 切换重绘图'),
              ),
            ),
          for (final asset in (q['visuals'] as List? ?? []))
            if ((asset['draft_redrawn_image'] ?? asset['redrawn_image'] ?? '')
                    .toString()
                    .isNotEmpty ||
                (asset['review_history'] as List? ?? []).isNotEmpty ||
                (asset['redrawn_image'] ?? '').toString().isNotEmpty)
              TextButton.icon(
                onPressed:
                    busy || ['queued', 'running'].contains(current!['status'])
                    ? null
                    : () => reviewFigure(q, asset),
                icon: const Icon(Icons.rate_review_outlined, size: 18),
                label: Text(
                  '${asset['caption']?.toString().isNotEmpty == true ? asset['caption'] : asset['id']} · 查看草稿与审核意见',
                ),
              ),
          MathText(q['stem'] ?? ''),
          ...tableViews(q, 'stem', 0),
          for (final entry
              in ((q['options'] as List?) ?? []).asMap().entries) ...[
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: MathText(
                RegExp(
                      r'^\s*[A-Z](?:[.．、)）:：]|$)',
                    ).hasMatch(entry.value.toString())
                    ? entry.value
                    : '${String.fromCharCode(65 + entry.key)}. ${entry.value}',
              ),
            ),
            ...tableViews(q, 'option', entry.key),
          ],
          for (final entry
              in ((q['parts'] as List?) ?? []).asMap().entries) ...[
            Padding(
              padding: const EdgeInsets.only(top: 9),
              child: MathText(entry.value),
            ),
            ...tableViews(q, 'part', entry.key),
          ],
          for (final asset in (q['visuals'] as List? ?? []))
            if (!referencedVisuals(q).contains(asset['id']))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: visualAsset(q, asset['id']),
              ),
          if ((q['visuals'] as List? ?? []).isEmpty && images.isNotEmpty) ...[
            const SizedBox(height: 14),
            if (originals.isNotEmpty && redraws.isNotEmpty)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: busy ? null : () => toggleFigure(q),
                  child: Text(
                    usesRedraw(q) ? '重绘图 · 切换原图' : '原图 · 切换重绘图',
                    style: const TextStyle(fontSize: 12),
                  ),
                ),
              ),
            ...images.map<Widget>(
              (path) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Center(
                  child: Image.network(
                    api.uri('/tasks/${current!['id']}/files/$path').toString(),
                    headers: api.headers,
                    height: 250,
                    fit: BoxFit.contain,
                    errorBuilder: (_, _, _) => const Text(
                      '配图暂不可用，请检查连接',
                      style: TextStyle(color: muted),
                    ),
                  ),
                ),
              ),
            ),
          ],
          ...((q['warnings'] as List?) ?? []).map(
            (s) => Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                '需注意：$s',
                style: const TextStyle(
                  color: Color(0xff946629),
                  fontSize: 12,
                  height: 1.6,
                ),
              ),
            ),
          ),
          if ((q['review'] as Map? ?? {}).isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                q['review']['passed'] == true
                    ? 'AI 独立解答与审核已通过'
                    : '审核建议：${(q['review']['issues'] as List).join('；')}',
                style: TextStyle(
                  color: q['review']['passed'] == true
                      ? const Color(0xff3f8064)
                      : const Color(0xff946629),
                  fontSize: 12,
                ),
              ),
            ),
          if (showAnswers) ...[
            if ((q['provenance'] ?? '').toString().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: SelectableText(
                  '来源说明：${q['provenance']}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: muted,
                    height: 1.6,
                  ),
                ),
              ),
            const SizedBox(height: 18),
            for (final field in {
              'answer': '答案',
              'solution': '详细解答',
              'knowledge': '知识点介绍',
            }.entries)
              if ((q[field.key] ?? '').toString().isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 12, bottom: 5),
                  child: Text(
                    field.value,
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ),
                MathText(
                  q[field.key],
                  style: const TextStyle(fontSize: 14, height: 1.9, color: ink),
                ),
              ],
            if ((q['answer'] ?? '').isEmpty)
              const Text(
                '文档转换不自动解题，可在对话中询问。',
                style: TextStyle(color: muted, fontSize: 12),
              ),
          ],
        ],
      ),
    );
  }

  void openChat(bool wide) {
    if (wide) {
      setState(() => showChat = !showChat);
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => Scaffold(
          appBar: AppBar(title: const Text('讨论试卷')),
          body: StatefulBuilder(
            builder: (context, update) => chatPanel(
              onUpdate: () {
                if (context.mounted) update(() {});
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget chatPanel({VoidCallback? onUpdate}) {
    final messages = (current?['messages'] as List? ?? [])
        .where((m) => m['question_id'] == questionId)
        .toList();
    return SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(18),
            child: Row(
              children: [
                const Icon(Icons.chat_bubble_outline, size: 18, color: blue),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    questionId == null ? '讨论整张试卷' : '讨论选中题目',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
          const Divider(),
          Expanded(
            child: messages.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(22),
                    child: Text(
                      '可以讨论题目、审核意见或配图。\n\n讨论不会自动改变文件；下方按钮可将建议用于修改题目或重画配图，执行前可以编辑意见。',
                      style: TextStyle(color: muted, fontSize: 13, height: 1.9),
                    ),
                  )
                : ListView(
                    padding: const EdgeInsets.all(18),
                    children: messages
                        .map<Widget>(
                          (m) => Padding(
                            padding: const EdgeInsets.only(bottom: 22),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  m['role'] == 'user' ? '你' : '数学助手',
                                  style: const TextStyle(
                                    color: muted,
                                    fontSize: 11,
                                  ),
                                ),
                                const SizedBox(height: 7),
                                MathText(
                                  m['content'],
                                  style: const TextStyle(
                                    fontSize: 13,
                                    height: 1.8,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                        .toList(),
                  ),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              children: [
                if (messages.isNotEmpty)
                  Wrap(
                    spacing: 8,
                    children: [
                      TextButton(
                        onPressed: busy
                            ? null
                            : () => revisionDialog(fromChat: true),
                        child: const Text('按对话修改题目'),
                      ),
                      TextButton(
                        onPressed: busy ? null : redrawFromChat,
                        child: const Text('按对话重画配图'),
                      ),
                    ],
                  ),
                TextField(
                  controller: chatInput,
                  minLines: 2,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    hintText: '询问思路、解答或知识点…',
                    hintStyle: TextStyle(fontSize: 13),
                  ),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '讨论记录会保存',
                        style: TextStyle(color: muted, fontSize: 11),
                      ),
                    ),
                    FilledButton(
                      onPressed: chatting ? null : () => sendChat(onUpdate),
                      child: Text(chatting ? '思考中…' : '发送'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> sendChat(VoidCallback? onUpdate) async {
    final message = chatInput.text.trim();
    if (message.isEmpty || current == null) return;
    final id = current!['id'];
    setState(() => chatting = true);
    onUpdate?.call();
    try {
      await api.post('/tasks/$id/chat', {
        'message': message,
        'question_id': questionId,
      });
      final updated = await api.get('/tasks/$id');
      if (mounted && current?['id'] == id) {
        setState(() {
          current = Map<String, dynamic>.from(updated);
          chatInput.clear();
        });
      }
    } catch (e) {
      notice(e.toString());
    } finally {
      if (mounted) setState(() => chatting = false);
      onUpdate?.call();
    }
  }

  Future<void> originalPages() async {
    final pages = current!['pages'] as List;
    await showDialog(
      context: context,
      builder: (context) => Dialog(
        child: SizedBox(
          width: 900,
          height: 800,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text('上传原稿', style: TextStyle(fontSize: 17)),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: pages
                      .map<Widget>(
                        (p) => Padding(
                          padding: const EdgeInsets.only(bottom: 20),
                          child: Image.network(
                            api
                                .uri(
                                  '/tasks/${current!['id']}/files/${p['path']}',
                                )
                                .toString(),
                            headers: api.headers,
                            errorBuilder: (_, _, _) => const Text('原稿加载失败'),
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String recentAdvice() {
    final messages = (current?['messages'] as List? ?? [])
        .where((m) => m['question_id'] == questionId)
        .toList();
    return messages.reversed
        .take(2)
        .toList()
        .reversed
        .map((m) => '${m['role'] == 'user' ? '教师' : 'AI建议'}：${m['content']}')
        .join('\n\n');
  }

  Future<void> revisionDialog({bool fromChat = false}) async {
    final taskId = current!['id'];
    final questions = (current!['paper']?['questions'] as List?) ?? [];
    if (questions.isEmpty) {
      notice('尚未生成题目');
      return;
    }
    String selected = questionId ?? questions.first['id'];
    final controller = TextEditingController(
      text: fromChat ? recentAdvice() : '',
    );
    final result = await completedDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const Text('按意见修改题目'),
          content: SizedBox(
            width: 620,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('将创建修改版任务，保留当前版本。审核意见供你参考，不会强制采用。'),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    initialValue: selected,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: '修改哪一道题'),
                    items: questions
                        .map(
                          (q) => DropdownMenuItem<String>(
                            value: q['id'],
                            child: Text(
                              '第 ${q['number']} 题 · ${q['stem']}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: (v) => update(() => selected = v!),
                  ),
                  TextButton(
                    onPressed: () {
                      final q = questions.firstWhere(
                        (q) => q['id'] == selected,
                      );
                      controller.text =
                          ((q['review']?['issues'] as List?) ?? []).join('\n');
                    },
                    child: const Text('填入审核建议后再编辑'),
                  ),
                  TextField(
                    controller: controller,
                    minLines: 5,
                    maxLines: 12,
                    maxLength: 6000,
                    decoration: const InputDecoration(
                      labelText: '你的修改意见',
                      hintText: '例如：保留构型，增加一个更有挑战的设问；不要照搬审核建议。',
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                if (controller.text.trim().isNotEmpty) {
                  Navigator.pop(context, {
                    'question_id': selected,
                    'advice': controller.text.trim(),
                  });
                }
              },
              child: const Text('生成修改版'),
            ),
          ],
        ),
      ),
    );
    controller.dispose();
    if (result != null && mounted) {
      await run(() async {
        openResult(await api.post('/tasks/$taskId/revise', result));
        await refresh();
      });
    }
  }

  Future<void> redrawFromChat() async {
    final choices = <Map<String, dynamic>>[];
    for (final q in current!['paper']?['questions'] as List? ?? []) {
      if (questionId != null && q['id'] != questionId) continue;
      for (final a in q['visuals'] as List? ?? []) {
        if ((a['svg_file'] ?? '').toString().isNotEmpty ||
            (a['draft_svg_file'] ?? '').toString().isNotEmpty) {
          choices.add({'question': q, 'asset': a});
        }
      }
    }
    if (choices.isEmpty) {
      notice('当前题目还没有可修改的重绘图；可以先生成配图或选中有图的题目。');
      return;
    }
    final selected = choices.length == 1
        ? choices.first
        : await completedDialog<Map<String, dynamic>>(
            context: context,
            builder: (context) => SimpleDialog(
              title: const Text('选择要重画的配图'),
              children: [
                for (final choice in choices)
                  SimpleDialogOption(
                    onPressed: () => Navigator.pop(context, choice),
                    child: Text(
                      '第 ${choice['question']['number']} 题 · ${choice['asset']['caption'] ?? choice['asset']['id']}',
                    ),
                  ),
              ],
            ),
          );
    if (selected != null && mounted) {
      await reviewFigure(
        selected['question'],
        selected['asset'],
        initialAdvice: recentAdvice(),
      );
    }
  }

  Future<void> generationDialog() async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: Text(questionId == null ? '根据整卷出题' : '生成单题变式'),
          content: SizedBox(
            width: 480,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '核心知识与主要思路对齐，允许辅助方法变化。\n每道新题独立解答，并审核难度与命题质量。',
                    style: TextStyle(color: muted, fontSize: 13, height: 1.8),
                  ),
                  const SizedBox(height: 22),
                  dropdown('目标难度', difficulty, {
                    'easier': '略简单',
                    'same': '接近原卷',
                    'harder': '略难',
                  }, (v) => update(() => difficulty = v)),
                  const SizedBox(height: 18),
                  dropdown('变化程度', creativity, {
                    'parameters': '参数变式',
                    'variation': '思路变式',
                    'creative': '综合创新',
                  }, (v) => update(() => creativity = v)),
                  const SizedBox(height: 18),
                  TextField(
                    controller: requirements,
                    minLines: 3,
                    maxLines: 6,
                    decoration: const InputDecoration(
                      labelText: '补充要求',
                      hintText: '例如：保留四点共圆与轨迹最值，允许二次函数计算；面向初三实验班。',
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    '生成新版本，原试卷保留。使用云端 API，产生实际调用费用。',
                    style: TextStyle(color: muted, fontSize: 12, height: 1.7),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('开始出题'),
            ),
          ],
        ),
      ),
    );
    if (accepted == true) {
      await run(() async {
        openResult(
          await api.post('/tasks/${current!['id']}/generate', {
            'options': options(),
          }),
        );
        await refresh();
      });
    }
  }

  Future<void> settings() async {
    final keyInput = TextEditingController();
    final url = TextEditingController(text: api.baseUrl);
    final token = TextEditingController(text: api.token);
    final desktop = Platform.environment.containsKey('SHIJUAN_SERVICE_URL');
    bool saving = false, visible = false;
    String? error;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const Text('设置'),
          content: SizedBox(
            width: 480,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (desktop) ...[
                    const Text(
                      'DeepSeek API Key',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: keyInput,
                      obscureText: !visible,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: InputDecoration(
                        hintText: health?['model_configured'] == true
                            ? '已保存密钥；输入新密钥可替换'
                            : '粘贴你的 API Key',
                        suffixIcon: IconButton(
                          onPressed: () => update(() => visible = !visible),
                          icon: Icon(
                            visible
                                ? Icons.visibility_off_outlined
                                : Icons.visibility_outlined,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      '密钥加密保存在本机，保存后立即生效。留空可保留已有密钥。',
                      style: TextStyle(color: muted, height: 1.7),
                    ),
                  ] else ...[
                    TextField(
                      controller: url,
                      decoration: const InputDecoration(labelText: '电脑或服务器地址'),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: token,
                      obscureText: true,
                      decoration: const InputDecoration(labelText: '连接口令'),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      '此客户端连接远程处理服务。API Key 请在处理端配置。',
                      style: TextStyle(color: muted),
                    ),
                  ],
                  const SizedBox(height: 20),
                  Text(
                    'API Key：${health?['model_configured'] == true ? '已配置' : '未配置'}',
                    style: const TextStyle(color: muted),
                  ),
                  if (error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(
                        error!,
                        style: const TextStyle(color: Colors.red),
                      ),
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: saving ? null : () => Navigator.pop(dialogContext),
              child: const Text('关闭'),
            ),
            FilledButton(
              onPressed: saving
                  ? null
                  : () async {
                      update(() {
                        saving = true;
                        error = null;
                      });
                      try {
                        if (desktop) {
                          if (keyInput.text.trim().isNotEmpty) {
                            await api.post('/settings/key', {
                              'api_key': keyInput.text.trim(),
                            });
                          }
                        } else {
                          final parsed = Uri.tryParse(url.text.trim());
                          if (parsed == null ||
                              !['http', 'https'].contains(parsed.scheme) ||
                              parsed.host.isEmpty ||
                              parsed.userInfo.isNotEmpty ||
                              parsed.hasQuery ||
                              parsed.hasFragment) {
                            throw Exception('请输入有效的 HTTP 或 HTTPS 地址');
                          }
                          final prefs = await SharedPreferences.getInstance();
                          await prefs.setString('service_url', url.text.trim());
                          await secure.write(
                            key: 'service_token',
                            value: token.text.trim(),
                          );
                          api = StudioApi(url.text.trim(), token.text.trim());
                        }
                        await refresh();
                        if (dialogContext.mounted) Navigator.pop(dialogContext);
                        notice('设置已保存');
                      } catch (e) {
                        update(() {
                          saving = false;
                          error = e.toString().replaceFirst('Exception: ', '');
                        });
                      }
                    },
              child: Text(saving ? '保存中…' : '保存'),
            ),
          ],
        ),
      ),
    );
    Future.delayed(const Duration(seconds: 1), () {
      keyInput.dispose();
      url.dispose();
      token.dispose();
    });
  }
}
