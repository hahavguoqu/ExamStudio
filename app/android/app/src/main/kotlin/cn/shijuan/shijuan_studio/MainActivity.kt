package cn.shijuan.shijuan_studio

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class MainActivity : FlutterActivity() {
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val alias = "shijuan-service-token"
        if (!store.containsAlias(alias)) {
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
                generateKey()
            }
        }
        return store.getKey(alias, null) as SecretKey
    }
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "cn.shijuan/secure")
            .setMethodCallHandler { call, result ->
                val prefs = getSharedPreferences("studio-secure", MODE_PRIVATE)
                try {
                    when (call.method) {
                        "read" -> {
                            val encoded = prefs.getString("token", null)
                            if (encoded == null) result.success("")
                            else {
                                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                                val iv = Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)
                                cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
                                result.success(String(cipher.doFinal(Base64.decode(encoded, Base64.NO_WRAP)), Charsets.UTF_8))
                            }
                        }
                        "write" -> {
                            val value = call.arguments as? String ?: error("Invalid credential")
                            if (value.isEmpty()) {
                                check(prefs.edit().clear().commit())
                            } else {
                                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                                cipher.init(Cipher.ENCRYPT_MODE, key())
                                val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
                                check(prefs.edit().putString("token", Base64.encodeToString(encrypted, Base64.NO_WRAP))
                                    .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).commit())
                            }
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (_: Exception) { result.error("storage", "Unable to access service credential.", null) }
            }
    }
}
