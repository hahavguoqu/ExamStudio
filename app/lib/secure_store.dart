import 'package:flutter/services.dart';

/// Windows Credential Manager / Android Keystore. No model key is stored here.
class SecureStore {
  const SecureStore();
  static const _channel = MethodChannel('cn.shijuan/secure');
  Future<String?> read({required String key}) =>
      _channel.invokeMethod<String>('read');
  Future<void> write({required String key, required String value}) =>
      _channel.invokeMethod<void>('write', value);
}
