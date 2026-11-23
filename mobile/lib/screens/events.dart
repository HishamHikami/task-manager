import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../state.dart';
import '../ui.dart';
import 'dashboard.dart' show appBarActions;

class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key});
  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  String _show = 'upcoming';

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final ws = app.workspaceFilter;
    return Scaffold(
      appBar: AppBar(title: const Text('Events'), actions: appBarActions(context)),
      floatingActionButton: FloatingActionButton(
        tooltip: 'New event',
        onPressed: () => Navigator.of(context).push(MaterialPageRoute(fullscreenDialog: true, builder: (_) => const EventFormScreen())),
        child: const Icon(Icons.add),
      ),
      body: Column(children: [
        const WorkspaceFilter(),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: 'upcoming', label: Text('Upcoming')),
              ButtonSegment(value: 'invites', label: Text('To answer')),
              ButtonSegment(value: 'past', label: Text('Past')),
            ],
            selected: {_show},
            onSelectionChanged: (s) {
              HapticFeedback.selectionClick();
              setState(() => _show = s.first);
            },
          ),
        ),
        Expanded(
          child: Loader(
            key: ValueKey('events-$ws-$_show'),
            load: () => app.api!.get('events', query: {'ws': ws?.toString() ?? '', 'show': _show}),
            builder: (context, d, reload) {
              final events = (d['events'] as List).cast<Json>();
              return RefreshList(onRefresh: reload, padding: const EdgeInsets.fromLTRB(16, 0, 16, 120), children: [
                if (events.isEmpty)
                  EmptyView(switch (_show) { 'past' => 'No past events.', 'invites' => 'No invitations waiting.', _ => 'Nothing coming up.' }, icon: Icons.event_available_outlined)
                else
                  ListCard(children: [
                    for (final e in events)
                      EventTile(e, onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EventDetailScreen(id: e['id'] as int)))),
                  ]),
              ]);
            },
          ),
        ),
      ]),
    );
  }
}

class EventDetailScreen extends StatefulWidget {
  const EventDetailScreen({super.key, required this.id});
  final int id;
  @override
  State<EventDetailScreen> createState() => _EventDetailScreenState();
}

class _EventDetailScreenState extends State<EventDetailScreen> {
  Json? _e;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await AppScope.read(context).api!.get('events/${widget.id}');
      if (mounted) setState(() => _e = r['event'] as Json);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _setStatus(String s) async {
    final app = AppScope.read(context);
    HapticFeedback.selectionClick();
    try {
      final r = await app.api!.patch('events/${widget.id}', {'status': s});
      setState(() => _e = r['event'] as Json);
      app.changed();
    } catch (e) {
      if (mounted) showApiError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final e = _e;
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(e == null ? '' : (e['workspace'] as Json)['name'] as String),
        actions: [
          if (e != null)
            IconButton(
              tooltip: 'Edit',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () async {
                final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => EventFormScreen(event: e)));
                if (ok == true) _load();
              },
            ),
        ],
      ),
      body: e == null
          ? (_error != null ? ErrorView(_error!, onRetry: _load) : const Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 40), children: [
                Row(children: [
                  Pill(e['status_short'] as String, tone: statusTone(e['status'] as String)),
                  const SizedBox(width: 8),
                  Expanded(child: Meta([e['kind_label'] as String])),
                ]),
                const SizedBox(height: 8),
                Text(e['title'] as String, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, height: 1.2)),
                const SizedBox(height: 6),
                Text.rich(TextSpan(children: [
                  TextSpan(text: 'My role: ', style: TextStyle(color: cs.onSurfaceVariant)),
                  TextSpan(text: e['my_role_label'] as String, style: const TextStyle(fontWeight: FontWeight.w700)),
                ])),
                const SizedBox(height: 16),
                Card(
                  margin: EdgeInsets.zero,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 4, 8, 4),
                    child: Column(children: [
                      _row(context, Icons.schedule, 'When', '${fmtDateTime(e['start'] as String?)}${e['end'] != null ? '  →  ${fmtTime(e['end'] as String?)}' : ''}'),
                      if ((e['location'] as String).isNotEmpty) _row(context, Icons.place_outlined, 'Where', e['location'] as String),
                      if ((e['online_link'] as String).isNotEmpty)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.videocam_outlined),
                          title: const Text('Join online'),
                          onTap: () => launchUrl(Uri.parse(e['online_link'] as String), mode: LaunchMode.externalApplication),
                        ),
                      if ((e['organizer'] as String).isNotEmpty) ...[
                        _row(context, Icons.badge_outlined, 'Invited by', e['organizer'] as String),
                        if (e['organizer_contact'] != null)
                          Padding(
                            padding: const EdgeInsets.only(left: 40, bottom: 6),
                            child: ContactActions(phone: (e['organizer_contact'] as Json)['phone'] as String?, email: (e['organizer_contact'] as Json)['email'] as String?),
                          ),
                      ],
                      if ((e['my_topic'] as String).isNotEmpty)
                        _row(context, Icons.mic_none, 'My topic', '${e['my_topic']}${e['duration_minutes'] != null ? '  ·  ${e['duration_minutes']} min' : ''}'),
                      if ((e['audience'] as String).isNotEmpty) _row(context, Icons.groups_outlined, 'Audience', e['audience'] as String),
                    ]),
                  ),
                ),
                const SectionTitle('Mark as'),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final s in const [('invited', 'Invited'), ('tentative', 'Maybe'), ('confirmed', 'Going'), ('declined', 'Declined'), ('done', 'Attended'), ('cancelled', 'Cancelled')])
                    ChoiceChip(label: Text(s.$2), selected: e['status'] == s.$1, showCheckmark: false, onSelected: (_) => _setStatus(s.$1)),
                ]),
                if ((e['description'] as String).isNotEmpty) ...[
                  const SectionTitle('Details'),
                  Card(margin: EdgeInsets.zero, child: Padding(padding: const EdgeInsets.all(16), child: SelectableText(e['description'] as String))),
                ],
                if ((e['preparation'] as String).isNotEmpty) ...[
                  const SectionTitle('Preparation'),
                  Card(margin: EdgeInsets.zero, child: Padding(padding: const EdgeInsets.all(16), child: SelectableText(e['preparation'] as String))),
                ],
              ]),
            ),
    );
  }

  Widget _row(BuildContext context, IconData icon, String label, String value) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, size: 22, color: cs.onSurfaceVariant),
        const SizedBox(width: 16),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: TextStyle(fontSize: 12.5, color: cs.onSurfaceVariant)),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
          ]),
        ),
      ]),
    );
  }
}

class EventFormScreen extends StatefulWidget {
  const EventFormScreen({super.key, this.event});
  final Json? event;
  @override
  State<EventFormScreen> createState() => _EventFormScreenState();
}

class _EventFormScreenState extends State<EventFormScreen> {
  int? _ws;
  final _title = TextEditingController();
  final _location = TextEditingController();
  final _link = TextEditingController();
  final _topic = TextEditingController();
  final _minutes = TextEditingController();
  final _organizerOther = TextEditingController();
  final _desc = TextEditingController();
  final _prep = TextEditingController();
  String _kind = 'meeting';
  String _role = 'participant';
  String _status = 'confirmed';
  DateTime? _start;
  DateTime? _end;
  String? _organizer;
  List<Json> _desks = [];
  bool _busy = false;
  ApiException? _err;

  static const _presenting = {'host', 'speaker', 'panelist', 'moderator', 'trainer'};

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    final e = widget.event;
    if (e != null) {
      _ws = (e['workspace'] as Json)['id'] as int;
      _title.text = e['title'] as String;
      _location.text = e['location'] as String;
      _link.text = e['online_link'] as String;
      _topic.text = e['my_topic'] as String;
      _minutes.text = e['duration_minutes']?.toString() ?? '';
      _organizerOther.text = e['organizer_other'] as String;
      _desc.text = e['description'] as String;
      _prep.text = e['preparation'] as String;
      _kind = e['kind'] as String;
      _role = e['my_role'] as String;
      _status = e['status'] as String;
      _start = DateTime.parse(e['start'] as String).toLocal();
      _end = e['end'] == null ? null : DateTime.parse(e['end'] as String).toLocal();
      _organizer = (e['organizer_desk'] as String?)?.isEmpty == true ? null : e['organizer_desk'] as String?;
    } else {
      _ws = app.workspaceFilter ?? (app.workspaces.isNotEmpty ? app.workspaces.first['id'] as int : null);
    }
    _loadDesks();
  }

  Future<void> _loadDesks() async {
    if (_ws == null) return;
    try {
      final r = await AppScope.read(context).api!.get('workspaces/$_ws/desks');
      if (mounted) setState(() => _desks = (r['desks'] as List).cast<Json>());
    } catch (_) {}
  }

  Future<void> _save() async {
    if (_start == null) return toast(context, 'Pick when it starts.', error: true);
    setState(() { _busy = true; _err = null; });
    final app = AppScope.read(context);
    final data = <String, dynamic>{
      'title': _title.text.trim(), 'kind': _kind, 'my_role': _role, 'status': _status,
      'start': isoDateTime(_start!), 'end': _end == null ? '' : isoDateTime(_end!),
      'location': _location.text.trim(), 'online_link': _link.text.trim(),
      'organizer_desk': _organizer ?? '', 'organizer_other': _organizerOther.text.trim(),
      'my_topic': _presenting.contains(_role) ? _topic.text.trim() : '',
      'duration_minutes': _presenting.contains(_role) ? _minutes.text.trim() : '',
      'audience': '', 'description': _desc.text.trim(), 'preparation': _prep.text.trim(),
    };
    try {
      if (widget.event != null) {
        await app.api!.patch('events/${widget.event!['id']}', data);
        app.changed();
        if (mounted) Navigator.pop(context, true);
      } else {
        data['workspace'] = _ws;
        final r = await app.api!.post('events', data);
        app.changed();
        if (!mounted) return;
        HapticFeedback.mediumImpact();
        Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => EventDetailScreen(id: (r['event'] as Json)['id'] as int)));
      }
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
    DropdownButtonFormField<String> dd(String label, String value, String key, ValueChanged<String> on) => DropdownButtonFormField<String>(
          initialValue: value,
          isExpanded: true,
          decoration: InputDecoration(labelText: label),
          items: [for (final o in app.option(key)) DropdownMenuItem(value: o['value'] as String, child: Text(o['label'] as String, overflow: TextOverflow.ellipsis))],
          onChanged: (v) => on(v!),
        );
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.event == null ? 'New event' : 'Edit event'),
        actions: [Padding(padding: const EdgeInsets.only(right: 12), child: FilledButton(onPressed: _busy ? null : _save, child: const Text('Save')))],
      ),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 40), children: [
        if (widget.event == null && app.workspaces.length > 1) ...[
          Wrap(spacing: 8, children: [
            for (final w in app.workspaces)
              ChoiceChip(
                showCheckmark: false,
                selected: _ws == w['id'],
                label: Row(mainAxisSize: MainAxisSize.min, children: [Dot(workspaceColor(w['color'] as String?, b)), const SizedBox(width: 6), Text(w['name'] as String)]),
                onSelected: (_) => setState(() {
                  _ws = w['id'] as int;
                  _organizer = null;
                  _loadDesks();
                }),
              ),
          ]),
          gap,
        ],
        TextField(controller: _title, textCapitalization: TextCapitalization.sentences, decoration: InputDecoration(labelText: 'Title', errorText: fieldError(_err, 'title'))),
        gap,
        dd('My role', _role, 'event_roles', (v) => setState(() => _role = v)),
        AnimatedSize(
          duration: const Duration(milliseconds: 200),
          child: _presenting.contains(_role)
              ? Padding(
                  padding: const EdgeInsets.only(top: 14),
                  child: Row(children: [
                    Expanded(flex: 3, child: TextField(controller: _topic, decoration: const InputDecoration(labelText: 'My topic / talk title'))),
                    const SizedBox(width: 10),
                    Expanded(child: TextField(controller: _minutes, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Minutes'))),
                  ]),
                )
              : const SizedBox(width: double.infinity),
        ),
        gap,
        dd('Type of event', _kind, 'event_kinds', (v) => setState(() => _kind = v)),
        gap,
        dd('Status', _status, 'event_statuses', (v) => setState(() => _status = v)),
        gap,
        DateField(label: 'Starts', value: _start, withTime: true, onChanged: (v) => setState(() => _start = v)),
        gap,
        DateField(label: 'Ends (optional)', value: _end, withTime: true, onChanged: (v) => setState(() => _end = v)),
        if (fieldError(_err, 'end') != null) Text(fieldError(_err, 'end')!, style: TextStyle(color: Tones.red(context))),
        gap,
        TextField(controller: _location, decoration: const InputDecoration(labelText: 'Where', prefixIcon: Icon(Icons.place_outlined))),
        gap,
        TextField(controller: _link, keyboardType: TextInputType.url, decoration: InputDecoration(labelText: 'Online link (optional)', prefixIcon: const Icon(Icons.link), errorText: fieldError(_err, 'online_link'))),
        gap,
        DeskPicker(groups: _desks, value: _organizer, label: 'Organized / invited by', onChanged: (v) => setState(() => _organizer = v)),
        gap,
        TextField(controller: _organizerOther, decoration: const InputDecoration(labelText: '…or an organizer you don’t track')),
        gap,
        TextField(controller: _desc, maxLines: 4, minLines: 2, decoration: const InputDecoration(labelText: 'Details', alignLabelWithHint: true)),
        gap,
        TextField(controller: _prep, maxLines: 4, minLines: 2, decoration: const InputDecoration(labelText: 'Preparation / to-do', alignLabelWithHint: true)),
      ]),
    );
  }
}
