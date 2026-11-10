import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shijuan_studio/api.dart';

void main() {
  test('small files retain a meaningful size', () {
    expect(formatFileSize(24576), '24.0 KB');
    expect(formatFileSize(512), '512 B');
    expect(formatFileSize(1572864), '1.5 MB');
  });
  test(
    'multipart progress includes boundaries and reaches the real total',
    () async {
      final progress = <int>[];
      var total = 0;
      final request = ProgressMultipartRequest(
        'POST',
        Uri.parse('http://localhost/tasks'),
        (sent, size) {
          progress.add(sent);
          total = size;
        },
      );
      request.fields['options'] = '{}';
      request.files.add(
        http.MultipartFile.fromBytes(
          'files',
          utf8.encode('sample content'),
          filename: 'sample.txt',
        ),
      );
      final bytes = await request.finalize().toBytes();
      expect(total, bytes.length);
      expect(progress.last, total);
      expect(progress, orderedEquals([...progress]..sort()));
      expect(utf8.decode(bytes), contains('sample content'));
    },
  );
}
