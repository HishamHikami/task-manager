package org.taskmanager.tasks_app

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/** Receives text shared from other apps ("Share → Tasks") and hands it to Flutter. */
class MainActivity : FlutterActivity() {
    private val channelName = "org.taskmanager/share"
    private var channel: MethodChannel? = null
    private var pending: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        pending = sharedText(intent)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).also {
            it.setMethodCallHandler { call, result ->
                if (call.method == "initial") {
                    result.success(pending)
                    pending = null
                } else {
                    result.notImplemented()
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        sharedText(intent)?.let { channel?.invokeMethod("shared", it) }
    }

    private fun sharedText(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND || intent.type?.startsWith("text/") != true) return null
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
        return listOfNotNull(subject, text).filter { it.isNotBlank() }.distinct().joinToString("\n").ifBlank { null }
    }
}
