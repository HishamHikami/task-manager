import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:material_ui/material_ui.dart';

import 'api.dart';

/// App-wide state: who is logged in, the workspaces, the selected filter,
/// and a "something changed" signal so open screens can refresh.
class AppState extends ChangeNotifier {
  static const _storage = FlutterSecureStorage();
  static const _shareChannel = MethodChannel('org.taskmanager/share');

  ApiClient? api;
  Json? boot;
  int? workspaceFilter; // null = all
  bool loading = true;
  int dataVersion = 0; // bumps after any change, screens reload on it
  String? sharedText; // text shared into the app from another app
  int requestedTab = -1;

  List<Json> get workspaces =>
      ((boot?['workspaces'] as List?) ?? []).cast<Json>();
  bool get aiReady => boot?['ai_ready'] == true;
  List<Json> option(String key) => ((boot?[key] as List?) ?? []).cast<Json>();

  Future<void> init() async {
    final server = await _storage.read(key: 'server');
    final token = await _storage.read(key: 'token');
    final ws = await _storage.read(key: 'ws');
    workspaceFilter = int.tryParse(ws ?? '');
    if (server != null && token != null) {
      api = ApiClient(baseUrl: server, token: token);
      try {
        boot = await api!.get('bootstrap');
      } on ApiException catch (e) {
        if (e.unauthorized) {
          api = null;
          await _storage.delete(key: 'token');
        }
        // offline: keep the token, screens will show the error and retry
      }
    }
    loading = false;
    notifyListeners();
    _listenForShares();
  }

  Future<void> login(String server, String username, String password) async {
    final base = ApiClient.normalizeServer(server);
    final client = ApiClient(baseUrl: base);
    final r = await client.post('auth/login', {
      'username': username,
      'password': password,
      'device': 'Android app',
    });
    client.token = r['token'] as String;
    boot = await client.get('bootstrap');
    api = client;
    await _storage.write(key: 'server', value: base);
    await _storage.write(key: 'token', value: client.token);
    notifyListeners();
  }

  Future<String?> savedServer() => _storage.read(key: 'server');

  Future<void> logout() async {
    try {
      await api?.post('auth/logout');
    } catch (_) {}
    api = null;
    boot = null;
    await _storage.delete(key: 'token');
    notifyListeners();
  }

  Future<void> refreshBoot() async {
    if (api == null) return;
    try {
      boot = await api!.get('bootstrap');
      notifyListeners();
    } catch (_) {}
  }

  void setWorkspaceFilter(int? id) {
    workspaceFilter = id;
    _storage.write(key: 'ws', value: id?.toString() ?? '');
    notifyListeners();
  }

  void changed() {
    dataVersion++;
    notifyListeners();
  }

  void handleSessionExpired(BuildContext context) {
    api = null;
    _storage.delete(key: 'token');
    notifyListeners();
  }

  // --- Android "Share → Tasks" -------------------------------------------------
  void _listenForShares() {
    _shareChannel.setMethodCallHandler((call) async {
      if (call.method == 'shared' && call.arguments is String) {
        _receiveShare(call.arguments as String);
      }
    });
    _shareChannel
        .invokeMethod<String>('initial')
        .then((t) {
          if (t != null && t.isNotEmpty) _receiveShare(t);
        })
        .catchError((_) {});
  }

  void _receiveShare(String text) {
    sharedText = text;
    requestedTab = 2; // Capture
    notifyListeners();
  }

  String? takeSharedText() {
    final t = sharedText;
    sharedText = null;
    return t;
  }
}

/// Makes AppState available to the widget tree.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
    : super(notifier: state);

  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;
  static AppState read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<AppScope>()!.widget
              as AppScope)
          .notifier!;
}
