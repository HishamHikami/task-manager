import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../state.dart';
import '../ui.dart';
import 'dashboard.dart' show appBarActions;
import 'tasks.dart';

class WorkspacesScreen extends StatelessWidget {
  const WorkspacesScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final b = Theme.of(context).brightness;
    return Scaffold(
      appBar: AppBar(title: const Text('Workspaces'), actions: appBarActions(context)),
      body: Loader(
        load: () => app.api!.get('workspaces'),
        builder: (context, d, reload) {
          final list = (d['workspaces'] as List).cast<Json>();
          return RefreshList(onRefresh: reload, children: [
            for (final w in list)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Card(
                  margin: EdgeInsets.zero,
                  clipBehavior: Clip.antiAlias,
                  child: Pressable(
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => WorkspaceScreen(id: w['id'] as int))),
                    child: Container(
                      decoration: BoxDecoration(border: Border(left: BorderSide(color: workspaceColor(w['color'] as String?, b), width: 4))),
                      padding: const EdgeInsets.fromLTRB(16, 16, 12, 16),
                      child: Row(children: [
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(w['name'] as String, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                            const SizedBox(height: 4),
                            Meta(['${w['open_count']} open', '${w['holder_count']} departments & people', if (w['ai_enabled'] != true) 'AI off']),
                          ]),
                        ),
                        const Icon(Icons.chevron_right),
                      ]),
                    ),
                  ),
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class WorkspaceScreen extends StatelessWidget {
  const WorkspaceScreen({super.key, required this.id});
  final int id;
  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    return Loader(
      load: () => app.api!.get('workspaces/$id'),
      builder: (context, d, reload) {
        final w = d['workspace'] as Json;
        final holders = (d['holders'] as List).cast<Json>();
        return Scaffold(
          appBar: AppBar(title: Text(w['name'] as String)),
          floatingActionButton: FloatingActionButton.extended(
            icon: const Icon(Icons.person_add_alt_1_outlined),
            label: const Text('Add'),
            onPressed: () async {
              if (await openAddHolder(context, id) != null) reload();
            },
          ),
          body: RefreshList(onRefresh: reload, children: [
            if ((w['description'] as String).isNotEmpty)
              Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 8), child: Text(w['description'] as String, style: TextStyle(color: cs.onSurfaceVariant))),
            const SectionTitle('Departments & people'),
            if (holders.isEmpty)
              const Card(child: EmptyView('Nobody yet. Add the departments, committees or people you hand tasks to.', icon: Icons.groups_outlined))
            else
              ListCard(children: [
                for (final h in holders)
                  Pressable(
                    borderRadius: 0,
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => HolderScreen(id: h['id'] as int))),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
                      child: Row(children: [
                        CircleAvatar(
                          radius: 18,
                          backgroundColor: cs.secondaryContainer,
                          child: Icon(h['is_group'] == true ? Icons.groups_2_outlined : Icons.person_outline, size: 20, color: cs.onSecondaryContainer),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(h['name'] as String, style: TextStyle(fontWeight: FontWeight.w600, color: h['active'] == true ? null : cs.onSurfaceVariant)),
                            Meta([
                              h['kind_label'] as String,
                              if (h['is_group'] == true) '${h['people_count']} ${h['people_count'] == 1 ? 'person' : 'people'}',
                              if (h['main_contact'] != null) '★ ${(h['main_contact'] as Json)['name']}',
                            ]),
                          ]),
                        ),
                        if ((h['open_count'] as int) > 0) Pill('${h['open_count']} open'),
                        const SizedBox(width: 4),
                        const Icon(Icons.chevron_right, size: 20),
                      ]),
                    ),
                  ),
              ]),
          ]),
        );
      },
    );
  }
}

class HolderScreen extends StatelessWidget {
  const HolderScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    return Loader(
      load: () => app.api!.get('holders/$id'),
      builder: (context, d, reload) {
        final h = d['holder'] as Json;
        final people = (h['people'] as List).cast<Json>();
        final tasks = (h['open_tasks'] as List).cast<Json>();
        return Scaffold(
          appBar: AppBar(title: Text(h['name'] as String)),
          floatingActionButton: h['is_group'] == true
              ? FloatingActionButton.extended(
                  icon: const Icon(Icons.person_add_alt_1_outlined),
                  label: const Text('Add person'),
                  onPressed: () async {
                    if (await openAddPerson(context, h) != null) reload();
                  },
                )
              : null,
          body: RefreshList(onRefresh: reload, children: [
            Text(h['kind_label'] as String, style: TextStyle(color: cs.onSurfaceVariant)),
            const SizedBox(height: 4),
            ContactActions(phone: h['phone'] as String?, email: h['email'] as String?),
            if (h['is_group'] == true) ...[
              SectionTitle('People (${people.length})'),
              if (people.isEmpty)
                const Card(child: EmptyView('No people yet. Add the manager and anyone else you deal with.', icon: Icons.person_add_alt_outlined))
              else
                ListCard(children: [
                  for (final p in people)
                    Opacity(
                      opacity: p['active'] == true ? 1 : .55,
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 4, 8),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            Text(p['name'] as String, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
                            if (p['is_primary'] == true) ...[const SizedBox(width: 8), const Pill('★ Main', tone: 'green')],
                            const Spacer(),
                            IconButton(
                              tooltip: 'Edit',
                              visualDensity: VisualDensity.compact,
                              icon: const Icon(Icons.edit_outlined, size: 20),
                              onPressed: () async {
                                if (await openAddPerson(context, h, person: p) != null) reload();
                              },
                            ),
                          ]),
                          if ((p['role'] as String).isNotEmpty) Text(p['role'] as String, style: TextStyle(color: cs.onSurfaceVariant)),
                          ContactActions(phone: p['phone'] as String?, email: p['email'] as String?),
                        ]),
                      ),
                    ),
                ]),
            ],
            SectionTitle('Open tasks on this desk (${tasks.length})'),
            if (tasks.isEmpty)
              const Card(child: EmptyView('Nothing open here.', icon: Icons.task_alt))
            else
              ListCard(children: [
                for (final t in tasks)
                  TaskTile(t, onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TaskDetailScreen(id: t['id'] as int)))),
              ]),
          ]),
        );
      },
    );
  }
}

/// Add a department/committee/person to a workspace. Returns the new desk value (e.g. "h12" or "c5").
Future<String?> openAddHolder(BuildContext context, int workspaceId) async {
  final app = AppScope.read(context);
  final name = TextEditingController();
  final role = TextEditingController();
  final phone = TextEditingController();
  final email = TextEditingController();
  String kind = 'department';
  int? department;
  List<Json> groups = [];
  try {
    final r = await app.api!.get('workspaces/$workspaceId');
    groups = (r['holders'] as List).cast<Json>().where((h) => h['is_group'] == true && h['active'] == true).toList();
  } catch (_) {}
  if (!context.mounted) return null;
  ApiException? err;
  return showSheet<String>(context, title: 'Add department or person', builder: (ctx) => StatefulBuilder(builder: (ctx, set) {
        final isPerson = kind == 'person';
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final k in app.option('holder_kinds'))
              ChoiceChip(label: Text(k['label'] as String), selected: kind == k['value'], showCheckmark: false, onSelected: (_) => set(() => kind = k['value'] as String)),
          ]),
          const SizedBox(height: 14),
          TextField(controller: name, autofocus: true, textCapitalization: TextCapitalization.words, decoration: InputDecoration(labelText: 'Name', errorText: fieldError(err, 'name'))),
          if (isPerson && groups.isNotEmpty) ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<int?>(
              initialValue: department,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Department (optional)'),
              items: [
                const DropdownMenuItem(value: null, child: Text('— Works on their own')),
                for (final g in groups) DropdownMenuItem(value: g['id'] as int, child: Text(g['name'] as String)),
              ],
              onChanged: (v) => set(() => department = v),
            ),
            if (department != null) ...[
              const SizedBox(height: 12),
              TextField(controller: role, decoration: const InputDecoration(labelText: 'Role (e.g. Manager)')),
            ],
          ],
          const SizedBox(height: 12),
          TextField(controller: phone, keyboardType: TextInputType.phone, decoration: InputDecoration(labelText: 'Phone (optional)', errorText: fieldError(err, 'phone'))),
          const SizedBox(height: 12),
          TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: 'Email (optional)', errorText: fieldError(err, 'email'))),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: () async {
              try {
                final r = await app.api!.post('workspaces/$workspaceId/holders', {
                  'name': name.text.trim(), 'kind': kind, 'phone': phone.text.trim(), 'email': email.text.trim(),
                  if (isPerson && department != null) ...{'department': department, 'role': role.text.trim()},
                });
                app.changed();
                HapticFeedback.mediumImpact();
                if (ctx.mounted) Navigator.pop(ctx, r['desk'] as String);
              } on ApiException catch (e) {
                set(() => err = e);
                if (ctx.mounted) toast(ctx, e.message, error: true);
              }
            },
            child: const Text('Add'),
          ),
        ]);
      }));
}

/// Add or edit a person inside a department. Returns the desk value on success.
Future<String?> openAddPerson(BuildContext context, Json holder, {Json? person}) {
  final app = AppScope.read(context);
  final name = TextEditingController(text: person?['name'] as String? ?? '');
  final role = TextEditingController(text: person?['role'] as String? ?? '');
  final phone = TextEditingController(text: person?['phone'] as String? ?? '');
  final email = TextEditingController(text: person?['email'] as String? ?? '');
  bool primary = person?['is_primary'] == true || (person == null && (holder['people'] as List).isEmpty);
  bool active = person == null ? true : person['active'] == true;
  ApiException? err;
  return showSheet<String>(context, title: person == null ? 'Add person to ${holder['name']}' : 'Edit ${person['name']}', builder: (ctx) => StatefulBuilder(builder: (ctx, set) {
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(controller: name, autofocus: person == null, textCapitalization: TextCapitalization.words, decoration: InputDecoration(labelText: 'Name', errorText: fieldError(err, 'name'))),
          const SizedBox(height: 12),
          TextField(controller: role, decoration: const InputDecoration(labelText: 'Role (e.g. Manager, Accountant)')),
          const SizedBox(height: 12),
          TextField(controller: phone, keyboardType: TextInputType.phone, decoration: InputDecoration(labelText: 'Phone', errorText: fieldError(err, 'phone'))),
          const SizedBox(height: 12),
          TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: 'Email', errorText: fieldError(err, 'email'))),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Main contact'), value: primary, onChanged: (v) => set(() => primary = v)),
          if (person != null) SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Still works here'), value: active, onChanged: (v) => set(() => active = v)),
          const SizedBox(height: 8),
          Row(children: [
            if (person != null)
              TextButton(
                style: TextButton.styleFrom(foregroundColor: Tones.red(ctx)),
                onPressed: () async {
                  try {
                    await app.api!.delete('people/${person['id']}');
                    app.changed();
                    if (ctx.mounted) Navigator.pop(ctx, 'deleted');
                  } catch (e) {
                    if (ctx.mounted) showApiError(ctx, e);
                  }
                },
                child: const Text('Remove'),
              ),
            const Spacer(),
            FilledButton(
              onPressed: () async {
                final data = {'name': name.text.trim(), 'role': role.text.trim(), 'phone': phone.text.trim(), 'email': email.text.trim(), 'is_primary': primary, 'active': active, 'notes': person?['notes'] ?? ''};
                try {
                  final r = person == null ? await app.api!.post('holders/${holder['id']}/people', data) : await app.api!.patch('people/${person['id']}', data);
                  app.changed();
                  HapticFeedback.mediumImpact();
                  if (ctx.mounted) Navigator.pop(ctx, (r['desk'] as String?) ?? 'saved');
                } on ApiException catch (e) {
                  set(() => err = e);
                  if (ctx.mounted) toast(ctx, e.message, error: true);
                }
              },
              child: Text(person == null ? 'Add' : 'Save'),
            ),
          ]),
        ]);
      }));
}
