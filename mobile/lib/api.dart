import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

typedef Json = Map<String, dynamic>;

class ApiException implements Exception {
  ApiException(this.message, {this.status = 0, this.fieldErrors = const {}});
  final String message;
  final int status;
  final Map<String, List<String>> fieldErrors;
  bool get unauthorized => status == 401;
  @override
  String toString() => message;
}

/// Talks to the Django server's /api/v1/ endpoints with a bearer token.
class ApiClient {
  ApiClient({required this.baseUrl, this.token});

  String baseUrl; // e.g. https://tasks.example.com
  String? token;
  final http.Client _http = http.Client();

  static String normalizeServer(String input) {
    var s = input.trim();
    if (s.isEmpty) return s;
    if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'https://$s';
    while (s.endsWith('/')) {
      s = s.substring(0, s.length - 1);
    }
    return s;
  }

  Uri _uri(String path, [Map<String, String>? query]) {
    final q = query == null ? null : (Map.of(query)..removeWhere((_, v) => v.isEmpty));
    return Uri.parse('$baseUrl/api/v1/$path').replace(queryParameters: (q == null || q.isEmpty) ? null : q);
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<Json> get(String path, {Map<String, String>? query}) =>
      _send(() => _http.get(_uri(path, query), headers: _headers));

  Future<Json> post(String path, [Json body = const {}, Duration timeout = const Duration(seconds: 25)]) =>
      _send(() => _http.post(_uri(path), headers: _headers, body: jsonEncode(body)), timeout);

  Future<Json> patch(String path, Json body) =>
      _send(() => _http.patch(_uri(path), headers: _headers, body: jsonEncode(body)));

  Future<Json> delete(String path) => _send(() => _http.delete(_uri(path), headers: _headers));

  Future<Json> _send(Future<http.Response> Function() call,
      [Duration timeout = const Duration(seconds: 25)]) async {
    http.Response r;
    try {
      r = await call().timeout(timeout);
    } on TimeoutException {
      throw ApiException('The server took too long to answer. Try again.');
    } on SocketException {
      throw ApiException('No connection to the server. Check your internet.');
    } on HandshakeException {
      throw ApiException('Secure connection failed. Check the server address.');
    } on http.ClientException {
      throw ApiException('Couldn\'t reach the server.');
    }
    Json data = {};
    if (r.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(utf8.decode(r.bodyBytes));
        if (decoded is Map<String, dynamic>) data = decoded;
      } catch (_) {
        if (r.statusCode >= 400) {
          throw ApiException('The server returned an error (${r.statusCode}).', status: r.statusCode);
        }
      }
    }
    if (r.statusCode >= 400) {
      final errors = <String, List<String>>{};
      final raw = data['errors'];
      if (raw is Map) {
        raw.forEach((k, v) => errors[k.toString()] = (v as List).map((e) => e.toString()).toList());
      }
      throw ApiException((data['error'] ?? 'Something went wrong (${r.statusCode}).').toString(),
          status: r.statusCode, fieldErrors: errors);
    }
    return data;
  }
}
