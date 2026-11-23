import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../state.dart';
import '../ui.dart';
import 'dashboard.dart' show appBarActions;
import 'workspaces.dart';

void openNewTask(BuildContext context, {int? workspaceId}) {
  Navigator.of(context).push(
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => TaskFormScreen(workspaceId: workspaceId),
    ),
  );
}

// ======================================================================= list

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});
  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  String _status = 'open';
  String _q = '';
  Timer? _debounce;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final ws = app.workspaceFilter;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Tasks'),
        actions: appBarActions(context),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => openNewTask(context),
        tooltip: 'New task',
        child: const Icon(Icons.add),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 6),
            child: SearchBar(
              hintText: 'Search tasks and messages',
              leading: const Icon(Icons.search),
              elevation: const WidgetStatePropertyAll(0),
              onChanged: (v) {
                _debounce?.cancel();
                _debounce = Timer(
                  const Duration(milliseconds: 350),
                  () => setState(() => _q = v.trim()),
                );
              },
            ),
          ),
          const WorkspaceFilter(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                showSelectedIcon: false,
                segments: const [
                  ButtonSegment(value: 'open', label: Text('Open')),
                  ButtonSegment(value: 'closed', label: Text('Finished')),
                  ButtonSegment(value: 'all', label: Text('All')),
                ],
                selected: {_status},
                onSelectionChanged: (s) {
                  HapticFeedback.selectionClick();
                  setState(() => _status = s.first);
                },
              ),
            ),
          ),
          Expanded(
            child: Loader(
              key: ValueKey('tasks-$ws-$_status-$_q'),
              load: () => app.api!.get(
                'tasks',
                query: {'ws': ws?.toString() ?? '', 'status': _status, 'q': _q},
              ),
              builder: (context, d, reload) {
                final tasks = (d['tasks'] as List).cast<Json>();
                return RefreshList(
                  onRefresh: reload,
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 120),
                  children: [
                    if (tasks.isEmpty)
                      EmptyView(
                        _q.isEmpty
                            ? 'No tasks here.'
                            : 'Nothing matches “$_q”.',
                        icon: Icons.task_alt,
                      )
                    else
                      ListCard(
                        children: [
                          for (final t in tasks)
                            TaskTile(
                              t,
                              onTap: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) =>
                                      TaskDetailScreen(id: t['id'] as int),
                                ),
                              ),
                            ),
                        ],
                      ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// ======================================================================= detail

class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({super.key, required this.id});
  final int id;
  @override
  State<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<TaskDetailScreen> {
  Json? _task;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await AppScope.read(context).api!.get('tasks/${widget.id}');
      if (mounted) setState(() => _task = r['task'] as Json);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  /// Runs an action, shows its message, refreshes this page and the lists behind it.
  Future<bool> _act(
    Future<Json> Function(ApiClient api) call, {
    String? done,
  }) async {
    final app = AppScope.read(context);
    try {
      final r = await call(app.api!);
      if (!mounted) return true;
      if (r['task'] != null) setState(() => _task = r['task'] as Json);
      HapticFeedback.mediumImpact();
      toast(context, (r['message'] as String?) ?? done ?? 'Saved');
      app.changed();
      return true;
    } catch (e) {
      if (mounted) showApiError(context, e);
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = _task;
    return Scaffold(
      appBar: AppBar(
        title: Text(
          t == null ? '' : (t['workspace'] as Json)['name'] as String,
        ),
        actions: [
          if (t != null)
            IconButton(
              tooltip: 'More',
              icon: const Icon(Icons.more_vert),
              onPressed: () async {
                final v = await showActions(
                  context,
                  title: t['title'] as String,
                  actions: const [
                    PickOption(
                      'edit',
                      'Edit task',
                      subtitle: 'Title, dates, priority, role',
                      icon: Icons.edit_outlined,
                    ),
                    PickOption(
                      'delete',
                      'Delete task',
                      subtitle: 'Removes its whole timeline',
                      icon: Icons.delete_outline,
                      danger: true,
                    ),
                  ],
                );
                if (v == 'edit') _edit(t);
                if (v == 'delete') _delete(t);
              },
            ),
        ],
      ),
      body: AnimatedSwitcher(
        duration: const Duration(milliseconds: 220),
        child: t == null
            ? (_error != null
                  ? ErrorView(
                      _error!,
                      onRetry: () {
                        setState(() => _error = null);
                        _load();
                      },
                    )
                  : const Center(
                      child: CircularProgressIndicator(strokeWidth: 2.5),
                    ))
            : RefreshIndicator(onRefresh: _load, child: _body(context, t)),
      ),
    );
  }

  Widget _body(BuildContext context, Json t) {
    final cs = Theme.of(context).colorScheme;
    final b = Theme.of(context).brightness;
    final ws = t['workspace'] as Json;
    final person = t['person'] as Json?;
    final contact = t['contact'] as Json?;
    final people = (t['people'] as List).cast<Json>();
    final timeline = (t['timeline'] as List).cast<Json>();
    final pri = t['priority'] as int;

    Widget fact(String label, Widget value) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(fontSize: 12.5, color: cs.onSurfaceVariant),
          ),
          const SizedBox(height: 3),
          value,
        ],
      ),
    );

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(
        parent: BouncingScrollPhysics(),
      ),
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 40),
      children: [
        Row(
          children: [
            Dot(workspaceColor(ws['color'] as String?, b)),
            const SizedBox(width: 8),
            Flexible(
              child: Meta([
                (t['stage'] as Json)['name'] as String,
                t['my_role_label'] as String,
              ]),
            ),
            if (pri >= 3) ...[
              const SizedBox(width: 8),
              Pill(
                t['priority_label'] as String,
                tone: pri >= 4 ? 'red' : 'amber',
              ),
            ],
          ],
        ),
        const SizedBox(height: 8),
        Text(
          t['title'] as String,
          style: Theme.of(context).textTheme.headlineSmall
              ?.copyWith(fontWeight: FontWeight.w800, height: 1.2),
        ),
        if ((t['description'] as String).isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            t['description'] as String,
            style: TextStyle(color: cs.onSurfaceVariant),
          ),
        ],
        const SizedBox(height: 16),
        Card(
          margin: EdgeInsets.zero,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                fact(
                  'With',
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text.rich(
                        TextSpan(
                          children: [
                            TextSpan(
                              text: (t['desk'] as String).isEmpty
                                  ? 'Nobody yet'
                                  : t['desk'] as String,
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                                fontSize: 16,
                              ),
                            ),
                            if (t['days_with_holder'] != null)
                              TextSpan(
                                text:
                                    '  ·  ${t['days_with_holder']} day${t['days_with_holder'] == 1 ? '' : 's'}',
                                style: TextStyle(color: cs.onSurfaceVariant),
                              ),
                          ],
                        ),
                      ),
                      if (person != null &&
                          (person['role'] as String).isNotEmpty)
                        Text(
                          '${person['name']} · ${person['role']}',
                          style: TextStyle(color: cs.onSurfaceVariant),
                        ),
                      if (contact != null) ...[
                        if (contact['is_department'] == true && person != null)
                          Text(
                            'Department contact:',
                            style: TextStyle(
                              fontSize: 12.5,
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ContactActions(
                          phone: contact['phone'] as String?,
                          email: contact['email'] as String?,
                        ),
                      ],
                      if (people.length > 1)
                        TextButton.icon(
                          style: TextButton.styleFrom(
                            padding: EdgeInsets.zero,
                            visualDensity: VisualDensity.compact,
                          ),
                          icon: const Icon(Icons.groups_outlined, size: 18),
                          label: Text(
                            'People at ${(t['holder'] as Json)['name']} (${people.length})',
                          ),
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => HolderScreen(
                                id: (t['holder'] as Json)['id'] as int,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                const Divider(height: 1),
                Row(
                  children: [
                    Expanded(
                      child: fact(
                        'Due',
                        Text(
                          fmtDate(t['due_date'] as String?),
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: t['is_overdue'] == true
                                ? Tones.red(context)
                                : null,
                          ),
                        ),
                      ),
                    ),
                    Expanded(
                      child: fact(
                        'Follow up',
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              fmtDate(t['follow_up_date'] as String?),
                              style: TextStyle(
                                fontWeight: FontWeight.w600,
                                color: t['follow_up_due'] == true
                                    ? Tones.amber(context)
                                    : null,
                              ),
                            ),
                            if ((t['follow_up_note'] as String).isNotEmpty)
                              Text(
                                t['follow_up_note'] as String,
                                style: TextStyle(
                                  fontSize: 13,
                                  color: cs.onSurfaceVariant,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                if ((t['reference'] as String).isNotEmpty) ...[
                  const Divider(height: 1),
                  fact('Reference', Text(t['reference'] as String)),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          childAspectRatio: 3.6,
          children: [
            FilledButton.icon(
              onPressed: () => _handoff(t),
              icon: const Icon(Icons.forward_rounded),
              label: const Text('Hand off'),
            ),
            FilledButton.tonalIcon(
              onPressed: () => _addUpdate(t),
              icon: const Icon(Icons.edit_note_rounded),
              label: const Text('Add update'),
            ),
            OutlinedButton.icon(
              onPressed: () => _stage(t),
              icon: const Icon(Icons.swap_vert_rounded),
              label: const Text('Stage'),
            ),
            OutlinedButton.icon(
              onPressed: () => _followUp(t),
              icon: const Icon(Icons.notifications_none_rounded),
              label: const Text('Follow-up'),
            ),
          ],
        ),
        const SectionTitle('Timeline'),
        for (var i = 0; i < timeline.length; i++)
          _TimelineEntry(
            timeline[i],
            last: i == timeline.length - 1,
            canAi: t['can_use_ai'] == true,
            onSummarize: (id) => _act(
              (api) => api.post(
                'updates/$id/summarize',
                {},
                const Duration(seconds: 75),
              ),
              done: 'Summary added',
            ),
          ),
        if (timeline.isEmpty) const EmptyView('No history yet.'),
      ],
    );
  }

  // ---------------------------------------------------------------- actions

  Future<void> _handoff(Json t) async {
    String? desk;
    final note = TextEditingController();
    DateTime? follow;
    await showSheet(
      context,
      title: 'Hand off',
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DeskPicker(
                groups: (t['handoff_options'] as List).cast<Json>(),
                value: desk,
                allowNone: false,
                label: 'Hand to',
                onChanged: (v) => set(() => desk = v),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  icon: const Icon(Icons.person_add_alt_1_outlined, size: 18),
                  label: const Text('Add someone new'),
                  onPressed: () async {
                    final newDesk = await openAddHolder(
                      ctx,
                      (t['workspace'] as Json)['id'] as int,
                    );
                    if (newDesk != null) {
                      await _load();
                      set(() => desk = newDesk);
                    }
                  },
                ),
              ),
              const SizedBox(height: 4),
              TextField(
                controller: note,
                maxLines: 3,
                minLines: 1,
                decoration: const InputDecoration(labelText: 'Note (optional)'),
              ),
              const SizedBox(height: 12),
              DateField(
                label: 'Follow up on (optional)',
                value: follow,
                onChanged: (v) => set(() => follow = v),
              ),
              const SizedBox(height: 18),
              FilledButton(
                onPressed: desk == null
                    ? null
                    : () async {
                        final ok = await _act(
                          (api) => api.post('tasks/${t['id']}/handoff', {
                            'to_holder': desk,
                            'note': note.text,
                            if (follow != null)
                              'follow_up_date': isoDate(follow!),
                          }),
                        );
                        if (ok && ctx.mounted) Navigator.pop(ctx);
                      },
                child: const Text('Record hand-off'),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _addUpdate(Json t) async {
    final app = AppScope.read(context);
    String kind = 'note';
    final body = TextEditingController();
    final source = TextEditingController();
    await showSheet(
      context,
      title: 'Add update',
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final k in app.option('update_kinds'))
                    ChoiceChip(
                      label: Text(k['label'] as String),
                      selected: kind == k['value'],
                      showCheckmark: false,
                      onSelected: (_) => set(() => kind = k['value'] as String),
                    ),
                ],
              ),
              const SizedBox(height: 14),
              TextField(
                controller: body,
                autofocus: true,
                maxLines: 8,
                minLines: 3,
                decoration: const InputDecoration(
                  labelText: 'What happened / paste the message',
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: source,
                decoration: const InputDecoration(labelText: 'From (optional)'),
              ),
              const SizedBox(height: 18),
              FilledButton(
                onPressed: () async {
                  if (body.text.trim().isEmpty) {
                    return toast(ctx, 'Write something first.', error: true);
                  }
                  final ok = await _act(
                    (api) => api.post('tasks/${t['id']}/updates', {
                      'kind': kind,
                      'body': body.text,
                      'source': source.text,
                    }),
                  );
                  if (ok && ctx.mounted) Navigator.pop(ctx);
                },
                child: const Text('Add to timeline'),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _stage(Json t) async {
    final current = (t['stage'] as Json)['id'];
    final note = TextEditingController();
    await showSheet(
      context,
      title: 'Move to stage',
      builder: (ctx) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final s in (t['stages'] as List).cast<Json>())
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  s['id'] == current
                      ? Icons.radio_button_checked
                      : (s['closed'] == true
                            ? Icons.check_circle_outline
                            : Icons.radio_button_unchecked),
                  color: s['id'] == current
                      ? Theme.of(ctx).colorScheme.primary
                      : null,
                ),
                title: Text(s['name'] as String),
                subtitle: s['closed'] == true
                    ? const Text('Closes the task')
                    : null,
                enabled: s['id'] != current,
                onTap: () async {
                  final ok = await _act(
                    (api) => api.post('tasks/${t['id']}/stage', {
                      'stage': s['id'],
                      'note': note.text,
                    }),
                  );
                  if (ok && ctx.mounted) Navigator.pop(ctx);
                },
              ),
            const SizedBox(height: 8),
            TextField(
              controller: note,
              decoration: const InputDecoration(labelText: 'Note (optional)'),
            ),
          ],
        );
      },
    );
  }

  Future<void> _followUp(Json t) async {
    DateTime? date = t['follow_up_date'] == null
        ? null
        : DateTime.parse(t['follow_up_date'] as String);
    final note = TextEditingController(text: t['follow_up_note'] as String);
    await showSheet(
      context,
      title: 'Follow-up',
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 8,
                children: [
                  for (final p in const [
                    ('Tomorrow', 1),
                    ('In 3 days', 3),
                    ('Next week', 7),
                  ])
                    ActionChip(
                      label: Text(p.$1),
                      onPressed: () => set(
                        () => date = DateTime.now().add(Duration(days: p.$2)),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              DateField(
                label: 'Follow up on',
                value: date,
                onChanged: (v) => set(() => date = v),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: note,
                decoration: const InputDecoration(labelText: 'What to check'),
              ),
              const SizedBox(height: 18),
              FilledButton(
                onPressed: () async {
                  final ok = await _act(
                    (api) => api.post('tasks/${t['id']}/follow-up', {
                      'follow_up_date': date == null ? '' : isoDate(date!),
                      'follow_up_note': note.text,
                    }),
                  );
                  if (ok && ctx.mounted) Navigator.pop(ctx);
                },
                child: Text(
                  date == null ? 'Clear follow-up' : 'Save follow-up',
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _edit(Json t) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => TaskFormScreen(task: t),
      ),
    );
    if (changed == true) _load();
  }

  Future<void> _delete(Json t) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete this task?'),
        content: const Text(
          'Its whole timeline is removed too. This can’t be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Tones.red(context)),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final app = AppScope.read(context);
    try {
      await app.api!.delete('tasks/${t['id']}');
      app.changed();
      if (mounted) {
        Navigator.of(context).pop();
        toast(context, 'Task deleted');
      }
    } catch (e) {
      if (mounted) showApiError(context, e);
    }
  }
}

class _TimelineEntry extends StatelessWidget {
  const _TimelineEntry(
    this.u, {
    required this.last,
    required this.canAi,
    required this.onSummarize,
  });
  final Json u;
  final bool last;
  final bool canAi;
  final ValueChanged<int> onSummarize;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final kind = u['kind'] as String;
    final color = switch (kind) {
      'handoff' => cs.primary,
      'stage' => Tones.green(context),
      'followup' => Tones.amber(context),
      'created' => cs.outline,
      _ => const Color(0xFF6B46C1),
    };
    final move = u['move'] as Json?;
    String? moveText;
    if (move != null) {
      moveText = kind == 'created'
          ? 'Registered in ${move['stage']}${(move['with'] as String).isNotEmpty ? ', with ${move['with']}' : ''}'
          : '${move['from']}  →  ${move['to']}';
    }
    final summary = u['summary'] as String;
    final body = u['body'] as String;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 22,
            child: Column(
              children: [
                const SizedBox(height: 5),
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: kind == 'handoff' ? color : Colors.transparent,
                    border: Border.all(color: color, width: 2),
                  ),
                ),
                if (!last)
                  Expanded(
                    child: Container(width: 2, color: cs.outlineVariant),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        u['kind_label'] as String,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        fmtDateTime(u['occurred_at'] as String?),
                        style: TextStyle(
                          fontSize: 12,
                          color: cs.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  if (moveText != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 3),
                      child: Text(moveText),
                    ),
                  if ((u['source'] as String).isNotEmpty)
                    Text(
                      'From: ${u['source']}',
                      style: TextStyle(
                        fontSize: 13,
                        color: cs.onSurfaceVariant,
                      ),
                    ),
                  if (summary.isNotEmpty)
                    Container(
                      margin: const EdgeInsets.only(top: 6),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: Theme.of(context).cardTheme.color,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: cs.outlineVariant),
                      ),
                      child: Text(summary),
                    ),
                  if (body.isNotEmpty)
                    summary.isNotEmpty || body.length > 300
                        ? Theme(
                            data: Theme.of(context)
                                .copyWith(dividerColor: Colors.transparent),
                            child: ExpansionTile(
                              tilePadding: EdgeInsets.zero,
                              dense: true,
                              visualDensity: VisualDensity.compact,
                              title: Text(
                                summary.isNotEmpty
                                    ? 'Original text'
                                    : 'Show full text',
                                style: TextStyle(
                                  color: cs.primary,
                                  fontSize: 13.5,
                                ),
                              ),
                              children: [
                                Align(
                                  alignment: Alignment.centerLeft,
                                  child: SelectableText(body),
                                ),
                              ],
                            ),
                          )
                        : Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: SelectableText(body),
                          ),
                  if (canAi && u['can_summarize'] == true)
                    TextButton.icon(
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        visualDensity: VisualDensity.compact,
                      ),
                      icon: const Icon(Icons.auto_awesome, size: 16),
                      label: const Text('Summarize'),
                      onPressed: () => onSummarize(u['id'] as int),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ======================================================================= create / edit

class TaskFormScreen extends StatefulWidget {
  const TaskFormScreen({super.key, this.task, this.workspaceId});
  final Json? task; // edit when set
  final int? workspaceId;
  @override
  State<TaskFormScreen> createState() => _TaskFormScreenState();
}

class _TaskFormScreenState extends State<TaskFormScreen> {
  late int? _ws;
  final _title = TextEditingController();
  final _desc = TextEditingController();
  final _ref = TextEditingController();
  final _note = TextEditingController();
  final _fuNote = TextEditingController();
  String _role = 'following';
  int _priority = 2;
  String? _desk;
  DateTime? _due;
  DateTime? _follow;
  List<Json> _desks = [];
  bool _busy = false;
  ApiException? _err;

  bool get _editing => widget.task != null;

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    final t = widget.task;
    if (t != null) {
      _ws = (t['workspace'] as Json)['id'] as int;
      _title.text = t['title'] as String;
      _desc.text = t['description'] as String;
      _ref.text = t['reference'] as String;
      _fuNote.text = t['follow_up_note'] as String;
      _role = t['my_role'] as String;
      _priority = t['priority'] as int;
      _due = t['due_date'] == null
          ? null
          : DateTime.parse(t['due_date'] as String);
      _follow = t['follow_up_date'] == null
          ? null
          : DateTime.parse(t['follow_up_date'] as String);
    } else {
      _ws =
          widget.workspaceId ??
          app.workspaceFilter ??
          (app.workspaces.isNotEmpty
              ? app.workspaces.first['id'] as int
              : null);
      _loadDesks();
    }
  }

  Future<void> _loadDesks() async {
    if (_ws == null) return;
    try {
      final r = await AppScope.read(context).api!.get('workspaces/$_ws/desks');
      if (mounted) setState(() => _desks = (r['desks'] as List).cast<Json>());
    } catch (_) {}
  }

  Future<void> _save() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _err = null;
    });
    final app = AppScope.read(context);
    final data = <String, dynamic>{
      'title': _title.text.trim(),
      'description': _desc.text.trim(),
      'my_role': _role,
      'priority': _priority,
      'due_date': _due == null ? '' : isoDate(_due!),
      'follow_up_date': _follow == null ? '' : isoDate(_follow!),
      'follow_up_note': _fuNote.text.trim(),
      'reference': _ref.text.trim(),
    };
    try {
      if (_editing) {
        await app.api!.patch('tasks/${widget.task!['id']}', data);
      } else {
        data['workspace'] = _ws;
        data['current_holder'] = _role == 'executing' ? '' : (_desk ?? '');
        data['first_note'] = _note.text.trim();
        final r = await app.api!.post('tasks', data);
        app.changed();
        if (!mounted) return;
        HapticFeedback.mediumImpact();
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) =>
                TaskDetailScreen(id: (r['task'] as Json)['id'] as int),
          ),
        );
        return;
      }
      app.changed();
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      setState(() => _err = e);
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final b = Theme.of(context).brightness;
    const gap = SizedBox(height: 14);
    return Scaffold(
      appBar: AppBar(
        title: Text(_editing ? 'Edit task' : 'New task'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_editing ? 'Save' : 'Create'),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
        children: [
          if (!_editing && app.workspaces.length > 1) ...[
            Wrap(
              spacing: 8,
              children: [
                for (final w in app.workspaces)
                  ChoiceChip(
                    showCheckmark: false,
                    selected: _ws == w['id'],
                    label: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Dot(workspaceColor(w['color'] as String?, b)),
                        const SizedBox(width: 6),
                        Text(w['name'] as String),
                      ],
                    ),
                    onSelected: (_) => setState(() {
                      _ws = w['id'] as int;
                      _desk = null;
                      _loadDesks();
                    }),
                  ),
              ],
            ),
            gap,
          ],
          TextField(
            controller: _title,
            autofocus: !_editing,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(
              labelText: 'Title',
              errorText: fieldError(_err, 'title'),
            ),
          ),
          gap,
          TextField(
            controller: _desc,
            maxLines: 4,
            minLines: 1,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(
              labelText: 'Description (optional)',
            ),
          ),
          gap,
          Text(
            'My role',
            style: TextStyle(
              fontSize: 13,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 6),
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: 'assigned', label: Text('Assigned')),
              ButtonSegment(value: 'following', label: Text('Following')),
              ButtonSegment(value: 'executing', label: Text('Doing it')),
            ],
            selected: {_role},
            onSelectionChanged: (s) => setState(() => _role = s.first),
          ),
          gap,
          if (!_editing)
            AnimatedSize(
              duration: const Duration(milliseconds: 200),
              child: _role == 'executing'
                  ? const SizedBox(width: double.infinity)
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        DeskPicker(
                          groups: _desks,
                          value: _desk,
                          label: 'Currently with',
                          onChanged: (v) => setState(() => _desk = v),
                        ),
                        TextButton.icon(
                          icon: const Icon(
                            Icons.person_add_alt_1_outlined,
                            size: 18,
                          ),
                          label: const Text('Add someone new'),
                          onPressed: _ws == null
                              ? null
                              : () async {
                                  final d = await openAddHolder(context, _ws!);
                                  if (d != null) {
                                    await _loadDesks();
                                    setState(() => _desk = d);
                                  }
                                },
                        ),
                        const SizedBox(height: 6),
                      ],
                    ),
            ),
          PickerField<int>(
            label: 'Priority',
            value: _priority,
            groups: [
              PickGroup([
                for (final p in app.option('priorities'))
                  PickOption(
                    p['value'] as int,
                    p['label'] as String,
                    icon: const [
                      Icons.south_rounded,
                      Icons.remove_rounded,
                      Icons.north_rounded,
                      Icons.priority_high_rounded,
                    ][(p['value'] as int) - 1],
                  ),
              ]),
            ],
            onChanged: (v) => setState(() => _priority = v ?? 2),
          ),
          gap,
          DateField(
            label: 'Due date',
            value: _due,
            onChanged: (v) => setState(() => _due = v),
          ),
          gap,
          DateField(
            label: 'Follow up on',
            value: _follow,
            onChanged: (v) => setState(() => _follow = v),
          ),
          if (_follow != null) ...[
            gap,
            TextField(
              controller: _fuNote,
              decoration: const InputDecoration(labelText: 'What to check'),
            ),
          ],
          gap,
          TextField(
            controller: _ref,
            decoration: const InputDecoration(
              labelText: 'Reference no. (optional)',
            ),
          ),
          if (!_editing) ...[
            gap,
            TextField(
              controller: _note,
              maxLines: 4,
              minLines: 2,
              decoration: const InputDecoration(
                labelText: 'Background / first note (optional)',
                alignLabelWithHint: true,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
