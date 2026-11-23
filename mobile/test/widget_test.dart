import 'package:flutter_test/flutter_test.dart';
import 'package:tasks_app/api.dart';

void main() {
  test('server addresses are normalized', () {
    expect(ApiClient.normalizeServer('tasks.example.com/'), 'https://tasks.example.com');
    expect(ApiClient.normalizeServer(' https://x.org// '), 'https://x.org');
    expect(ApiClient.normalizeServer('http://10.0.2.2:8000'), 'http://10.0.2.2:8000');
  });
}
