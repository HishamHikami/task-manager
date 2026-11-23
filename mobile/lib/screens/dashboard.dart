import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../state.dart';
import '../ui.dart';
import 'events.dart';
import 'settings.dart';
import 'tasks.dart';

/// AppBar action that opens Settings (inside the current tab, with a back arrow).
List<Widget> appBarActions(BuildContext context) => [
  IconButton(
    tooltip: 'Settings',
    icon: const Icon(Icons.settings_outlined),
    onPressed: () =>
        Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
  ),
  const SizedBox(width: 4),
];

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final ws = app.workspaceFilter;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Home'),
        actions: appBarActions(context),
      ),
      floatingActionButton: FloatingActionButton(
        tooltip: 'New task',
        onPressed: () => openNewTask(context),
        child: const Icon(Icons.add),
      ),
      body: Column(
        children: [
          const WorkspaceFilter(),
          Expanded(
            child: Loader(
              key: ValueKey('dash-$ws'),
              load: () => app.api!.get(
                'dashboard',
                query: {'ws': ws?.toString() ?? ''},
              ),
              builder: (context, d, reload) =>
                  _DashboardBody(d: d, reload: reload),
            ),
          ),
        ],
      ),
    );
  }
}

class _DashboardBody extends StatelessWidget {
  const _DashboardBody({required this.d, required this.reload});
  final Json d;
  final Future<void> Function() reload;

  @override
  Widget build(BuildContext context) {
    final stats = d['stats'] as Json;
    final attention = (d['attention'] as List).cast<Json>();
    final events = (d['upcoming_events'] as List).cast<Json>();
    final groups = (d['groups'] as List).cast<Json>();
    final cs = Theme.of(context).colorScheme;
    final b = Theme.of(context).brightness;
    void openTask(Json t) => Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => TaskDetailScreen(id: t['id'] as int)),
    );

    return RefreshList(
      onRefresh: reload,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 4, 14),
          child: Text(
            DateFormat('EEEE, d MMMM')
                .format(DateTime.parse(d['today'] as String)),
            style: TextStyle(color: cs.onSurfaceVariant),
          ),
        ),
        Row(
          children: [
            _Stat(
              '${stats['attention']}',
              'Attention',
              warn: (stats['attention'] as int) > 0,
            ),
            const SizedBox(width: 10),
            _Stat('${stats['open']}', 'Open'),
            const SizedBox(width: 10),
            _Stat('${stats['events']}', 'Events'),
            if ((stats['invites'] as int) > 0) ...[
              const SizedBox(width: 10),
              _Stat('${stats['invites']}', 'Invites', warn: true),
            ],
          ],
        ),
        if (attention.isNotEmpty) ...[
          const SectionTitle('Needs attention'),
          ListCard(
            children: [
              for (final t in attention)
                TaskTile(t, showNote: true, onTap: () => openTask(t)),
            ],
          ),
        ],
        if (events.isNotEmpty) ...[
          const SectionTitle('Coming up'),
          ListCard(
            children: [
              for (final e in events)
                EventTile(
                  e,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => EventDetailScreen(id: e['id'] as int),
                    ),
                  ),
                ),
            ],
          ),
        ],
        const SectionTitle('On whose desk'),
        if (groups.isEmpty)
          Card(
            child: EmptyView(
              'No open tasks.',
              icon: Icons.task_alt,
              action: FilledButton.tonal(
                onPressed: () => openNewTask(context),
                child: const Text('New task'),
              ),
            ),
          )
        else
          Card(
            margin: EdgeInsets.zero,
            clipBehavior: Clip.antiAlias,
            child: Column(
              children: [
                for (var i = 0; i < groups.length; i++) ...[
                  if (i > 0)
                    Divider(
                      height: 1,
                      color: cs.outlineVariant.withValues(alpha: .6),
                    ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 2),
                    child: Row(
                      children: [
                        Flexible(
                          child: Text(
                            groups[i]['title'] as String,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (groups[i]['workspace'] != null &&
                            AppScope.of(context).workspaceFilter == null) ...[
                          const SizedBox(width: 8),
                          Dot(
                            workspaceColor(
                              (groups[i]['workspace'] as Json)['color']
                                  as String?,
                              b,
                            ),
                          ),
                          const SizedBox(width: 5),
                          Text(
                            (groups[i]['workspace'] as Json)['name'] as String,
                            style: TextStyle(
                              fontSize: 12.5,
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ],
                        const Spacer(),
                        Pill('${(groups[i]['tasks'] as List).length}'),
                      ],
                    ),
                  ),
                  for (final t in (groups[i]['tasks'] as List).cast<Json>())
                    TaskTile(t, hideDesk: true, onTap: () => openTask(t)),
                  const SizedBox(height: 4),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.value, this.label, {this.warn = false});
  final String value;
  final String label;
  final bool warn;
  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: double.tryParse(value) ?? 0),
                duration: const Duration(milliseconds: 500),
                curve: Curves.easeOutCubic,
                builder: (_, v, _) => Text(
                  '${v.round()}',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    height: 1.1,
                    color: warn ? Tones.amber(context) : null,
                  ),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12.5,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
