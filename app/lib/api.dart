import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;

String formatFileSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
}

class ProgressMultipartRequest extends http.MultipartRequest {
  final void Function(int sent, int total)? onProgress;
  ProgressMultipartRequest(super.method, super.url, this.onProgress);
  @override
  http.ByteStream finalize() {
    final stream = super.finalize();
    final total = contentLength;
    var sent = 0;
    return http.ByteStream(
      stream.map((chunk) {
        sent += chunk.length;
        onProgress?.call(sent, total);
        return chunk;
      }),
    );
  }
}

class StudioApi {
  String baseUrl;
  String token;
  StudioApi(this.baseUrl, this.token);
  Map<String, String> get headers => {
    if (token.isNotEmpty) 'Authorization': 'Bearer $token',
  };
  Uri uri(String path) =>
      Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path');
  dynamic decode(http.Response response) {
    dynamic value;
    try {
      value = jsonDecode(utf8.decode(response.bodyBytes));
    } catch (_) {
      throw Exception('服务返回了无法读取的响应，请检查服务地址。');
    }
    if (response.statusCode >= 400) {
      throw Exception(value is Map ? value['detail'].toString() : '请求失败');
    }
    return value;
  }

  Future<dynamic> get(String path) async => decode(
    await http
        .get(uri(path), headers: headers)
        .timeout(const Duration(seconds: 15)),
  );
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async =>
      decode(
        await http
            .post(
              uri(path),
              headers: {...headers, 'Content-Type': 'application/json'},
              body: jsonEncode(body ?? {}),
            )
            .timeout(const Duration(minutes: 5)),
      );
  Future<Map<String, dynamic>> upload(
    List<PlatformFile> files,
    Map<String, dynamic> options, {
    void Function(int sent, int total)? onProgress,
  }) async {
    final request = ProgressMultipartRequest('POST', uri('/tasks'), onProgress);
    request.headers.addAll(headers);
    request.fields['options'] = jsonEncode(options);
    for (final file in files) {
      final length = await file.length();
      if (length == null || length == 0) {
        throw Exception('无法读取 ${file.name}，请重新选择。');
      }
      if (length > 30 * 1024 * 1024) {
        throw Exception('${file.name} 超过 30 MB。');
      }
      request.files.add(
        http.MultipartFile(
          'files',
          file.readAsByteStream(),
          length,
          filename: file.name,
        ),
      );
    }
    final response = await http.Response.fromStream(
      await request.send().timeout(const Duration(minutes: 3)),
    );
    return Map<String, dynamic>.from(decode(response));
  }

  Future<dynamic> renameTask(String id, String title) async => decode(
    await http
        .patch(
          uri('/tasks/$id'),
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'title': title}),
        )
        .timeout(const Duration(seconds: 15)),
  );
  Future<void> deleteTask(String id) async {
    decode(
      await http
          .delete(uri('/tasks/$id'), headers: headers)
          .timeout(const Duration(seconds: 15)),
    );
  }

  Future<http.Response> download(String id, String path) async {
    final response = await http
        .get(uri('/tasks/$id/files/$path'), headers: headers)
        .timeout(const Duration(minutes: 2));
    if (response.statusCode != 200) {
      decode(response);
      throw Exception('下载失败');
    }
    return response;
  }
}
