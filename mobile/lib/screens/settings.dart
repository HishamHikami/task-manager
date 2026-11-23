import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state.dart';
import '../ui.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Settings'),
      ), // back arrow appears automatically
      body: Loader(
        load: () => app.api!.get('settings'),
        builder: (context, s, reload) {
          final usage = s['usage'] as Map<String, dynamic>;
          final devices = (s['devices'] as List).cast<Map<String, dynamic>>();
          return RefreshList(
            onRefresh: reload,
            children: [
              const SectionTitle('Account'),
              Card(
                margin: EdgeInsets.zero,
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.person_outline),
                      title: Text(s['username'] as String),
                      subtitle: Text(
                        app.api!.baseUrl.replaceFirst('https://', ''),
                      ),
                    ),
                    const Divider(height: 1),
                    ListTile(
                      leading: const Icon(Icons.open_in_browser),
                      title: const Text('Open the website'),
                      subtitle: const Text(
                        'Manage stages, the AI key and more',
                      ),
                      onTap: () => launchUrl(
                        Uri.parse('${app.api!.baseUrl}/settings/'),
                        mode: LaunchMode.externalApplication,
                      ),
                    ),
                  ],
                ),
              ),
              const SectionTitle('AI summaries'),
              Card(
                margin: EdgeInsets.zero,
                child: Column(
                  children: [
                    ListTile(
                      leading: Icon(
                        s['ai_ready'] == true
                            ? Icons.auto_awesome
                            : Icons.auto_awesome_outlined,
                        color: s['ai_ready'] == true
                            ? Tones.green(context)
                            : cs.outline,
                      ),
                      title: Text(
                        s['ai_ready'] == true
                            ? 'Ready (${s['key_hint']})'
                            : 'Not set up',
                      ),
                      subtitle: Text(
                        s['ai_ready'] == true
                            ? (s['ai_model'] as String)
                                  .replaceAll('claude-', 'Claude ')
                                  .replaceAll('-', ' ')
                            : 'Add your Anthropic key on the website’s Settings page',
                      ),
                    ),
                    const Divider(height: 1),
                    ListTile(
                      leading: const Icon(Icons.bar_chart_outlined),
                      title: Text(
                        '${usage['calls']} request${usage['calls'] == 1 ? '' : 's'} this month',
                      ),
                      subtitle: Text(
                        'About \$${(usage['cost'] as num).toStringAsFixed(4)}'
                        '${(usage['errors'] as int) > 0 ? ' · ${usage['errors']} failed' : ''}',
                      ),
                    ),
                  ],
                ),
              ),
              const SectionTitle('Signed-in devices'),
              Card(
                margin: EdgeInsets.zero,
                child: Column(
                  children: [
                    for (final d in devices)
                      ListTile(
                        leading: Icon(
                          d['current'] == true
                              ? Icons.smartphone
                              : Icons.devices_other_outlined,
                        ),
                        title: Text(
                          '${d['device']}${d['current'] == true ? ' (this one)' : ''}',
                        ),
                        subtitle: Text(
                          'Since ${fmtDateTime(d['created_at'] as String?)}',
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                icon: const Icon(Icons.logout),
                label: const Text('Log out'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Tones.red(context),
                ),
                onPressed: () async {
                  final ok = await showDialog<bool>(
                    context: context,
                    builder: (c) => AlertDialog(
                      title: const Text('Log out?'),
                      content: const Text(
                        'You’ll need your password to log in again.',
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(c, false),
                          child: const Text('Cancel'),
                        ),
                        FilledButton(
                          onPressed: () => Navigator.pop(c, true),
                          child: const Text('Log out'),
                        ),
                      ],
                    ),
                  );
                  if (ok == true) await app.logout();
                },
              ),
            ],
          );
        },
      ),
    );
  }
}
