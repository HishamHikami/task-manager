import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../state.dart';
import '../ui.dart';
import 'dashboard.dart' show appBarActions;
import 'events.dart';
import 'tasks.dart';

/// One item in the conversation.
class _Msg {
  _Msg.me(this.text, this.workspace) : kind = 'me';
  _Msg.thinking() : kind = 'thinking', text = '';
  _Msg.reply(this.reply, this.workspace, this.text) : kind = 'reply';
  _Msg.saved(this.saved) : kind = 'saved', text = '';
  final String kind;
  final String text;
  Json? workspace;
  Json? reply; // suggestion response
  Json? saved; // save result
}

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key});
  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _msgs = <_Msg>[];
  int? _ws;
  bool _useAi = true;
  bool _sending = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final app = AppScope.of(context);
    _ws ??= app.workspaceFilter ?? (app.workspaces.isNotEmpty ? app.workspaces.first['id'] as int : null);
    final shared = app.takeSharedText();
    if (shared != null) {
      _input.text = shared;
      _input.selection = TextSelection.collapsed(offset: shared.length);
    }
  }

  Json? get _workspace => AppScope.read(context).workspaces.where((w) => w['id'] == _ws).firstOrNull;
  bool get _aiAllowed => AppScope.read(context).aiReady && (_workspace?['ai_enabled'] == true);

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 400, duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic);
      }
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _ws == null || _sending) return;
    HapticFeedback.lightImpact();
    final ws = _workspace;
    final thinking = _Msg.thinking();
    setState(() {
      _sending = true;
      _msgs.add(_Msg.me(text, ws));
      _msgs.add(thinking);
      _input.clear();
    });
    _toEnd();
    try {
      final r = await AppScope.read(context).api!.post(
          'capture/suggest', {'workspace': _ws, 'text': text, 'use_ai': _useAi && _aiAllowed}, const Duration(seconds: 80));
      setState(() => _msgs[_msgs.indexOf(thinking)] = _Msg.reply(r, ws, text));
    } catch (e) {
      setState(() => _msgs.remove(thinking));
      if (mounted) showApiError(context, e);
    } finally {
      if (mounted) setState(() => _sending = false);
      _toEnd();
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    final b = Theme.of(context).brightness;
    return Scaffold(
      appBar: AppBar(title: const Text('Capture'), actions: [
        if (_msgs.isNotEmpty)
          IconButton(tooltip: 'Clear', icon: const Icon(Icons.cleaning_services_outlined), onPressed: () => setState(_msgs.clear)),
        ...appBarActions(context),
      ]),
      body: Column(children: [
        Expanded(
          child: GestureDetector(
            onTap: () => FocusScope.of(context).unfocus(),
            child: ListView(
              controller: _scroll,
              padding: const EdgeInsets.fromLTRB(14, 8, 14, 16),
              children: [
                _AiBubble(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('Paste or share a message', style: TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    Text(
                      app.aiReady
                          ? 'An email, a WhatsApp message or meeting minutes. I’ll summarize it and suggest which task it belongs to, who has it now, and any dates. Nothing is saved until you press Save.'
                          : 'AI isn’t set up yet, so you’ll file it yourself. Add your Anthropic key on the website’s Settings page to get suggestions.',
                      style: TextStyle(color: cs.onSurfaceVariant),
                    ),
                  ]),
                ),
                for (final m in _msgs)
                  _Appear(
                    key: ObjectKey(m),
                    child: switch (m.kind) {
                      'me' => _MeBubble(text: m.text, workspace: m.workspace?['name'] as String? ?? ''),
                      'thinking' => const _AiBubble(child: _TypingDots()),
                      'reply' => _ReplyCard(
                          key: ObjectKey(m.reply),
                          data: m.reply!,
                          workspace: m.workspace!,
                          text: m.text,
                          onSaved: (r) {
                            setState(() => _msgs[_msgs.indexOf(m)] = _Msg.saved(r));
                            app.changed();
                            _toEnd();
                          },
                          onDiscard: () => setState(() {
                            final i = _msgs.indexOf(m);
                            _msgs.removeAt(i);
                            if (i > 0 && _msgs[i - 1].kind == 'me') _msgs.removeAt(i - 1);
                          }),
                        ),
                      _ => _SavedBubble(m.saved!),
                    },
                  ),
              ],
            ),
          ),
        ),
        // ---------------------------------------------------------------- composer
        SafeArea(
          top: false,
          child: Container(
            margin: const EdgeInsets.fromLTRB(10, 0, 10, 10),
            padding: const EdgeInsets.fromLTRB(14, 6, 6, 6),
            decoration: BoxDecoration(
              color: Theme.of(context).cardTheme.color,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: cs.outlineVariant),
              boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .06), blurRadius: 14, offset: const Offset(0, 4))],
            ),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: _input,
                minLines: 1,
                maxLines: 6,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(hintText: 'Paste a message…', border: InputBorder.none, enabledBorder: InputBorder.none, focusedBorder: InputBorder.none, filled: false, isDense: true, contentPadding: EdgeInsets.symmetric(vertical: 10)),
              ),
              Row(children: [
                PopupMenuButton<int>(
                  tooltip: 'Workspace',
                  onSelected: (v) => setState(() => _ws = v),
                  itemBuilder: (_) => [
                    for (final w in app.workspaces)
                      PopupMenuItem(value: w['id'] as int, child: Row(children: [Dot(workspaceColor(w['color'] as String?, b)), const SizedBox(width: 8), Text(w['name'] as String)])),
                  ],
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                    decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(99)),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      if (_workspace != null) ...[Dot(workspaceColor(_workspace!['color'] as String?, b)), const SizedBox(width: 6)],
                      Text(_workspace?['name'] as String? ?? 'Workspace', style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
                      const Icon(Icons.arrow_drop_down, size: 20),
                    ]),
                  ),
                ),
                const SizedBox(width: 6),
                FilterChip(
                  label: const Text('AI'),
                  avatar: Icon(Icons.auto_awesome, size: 16, color: _useAi && _aiAllowed ? cs.onSecondaryContainer : cs.outline),
                  selected: _useAi && _aiAllowed,
                  showCheckmark: false,
                  visualDensity: VisualDensity.compact,
                  tooltip: _aiAllowed ? 'Use AI suggestions' : (app.aiReady ? 'AI is off for this workspace' : 'AI isn’t set up'),
                  onSelected: _aiAllowed ? (v) => setState(() => _useAi = v) : null,
                ),
                const Spacer(),
                ValueListenableBuilder<TextEditingValue>(
                  valueListenable: _input,
                  builder: (_, v, _) => AnimatedScale(
                    scale: v.text.trim().isEmpty ? .85 : 1,
                    duration: const Duration(milliseconds: 150),
                    child: IconButton.filled(
                      onPressed: v.text.trim().isEmpty || _sending ? null : _send,
                      icon: const Icon(Icons.arrow_upward_rounded),
                    ),
                  ),
                ),
              ]),
            ]),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- bubbles

class _Appear extends StatelessWidget {
  const _Appear({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: 1),
        duration: const Duration(milliseconds: 280),
        curve: Curves.easeOutCubic,
        builder: (_, v, c) => Opacity(opacity: v, child: Transform.translate(offset: Offset(0, 12 * (1 - v)), child: c)),
        child: child,
      );
}

class _MeBubble extends StatelessWidget {
  const _MeBubble({required this.text, required this.workspace});
  final String text;
  final String workspace;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.only(top: 14, left: 48),
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
        decoration: BoxDecoration(
          color: cs.primaryContainer,
          borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(6), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(18)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(text.length > 600 ? '${text.substring(0, 600)}…' : text, style: TextStyle(color: cs.onPrimaryContainer)),
          const SizedBox(height: 4),
          Text(workspace, style: TextStyle(fontSize: 11.5, color: cs.onPrimaryContainer.withValues(alpha: .7))),
        ]),
      ),
    );
  }
}

class _AiBubble extends StatelessWidget {
  const _AiBubble({required this.child, this.wide = false});
  final Widget child;
  final bool wide;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: EdgeInsets.only(top: 14, right: wide ? 0 : 40),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: Theme.of(context).cardTheme.color,
          border: Border.all(color: cs.outlineVariant),
          borderRadius: const BorderRadius.only(topLeft: Radius.circular(6), topRight: Radius.circular(18), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(18)),
        ),
        child: child,
      ),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();
  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.outline;
    return SizedBox(
      width: 46,
      height: 16,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          for (var i = 0; i < 3; i++)
            Transform.translate(
              offset: Offset(0, -3 * (0.5 - ((_c.value * 3 - i) % 3 - .5).abs().clamp(0, .5)) * 2),
              child: Opacity(
                opacity: .35 + .65 * (1 - (((_c.value * 3 - i) % 3) - .5).abs().clamp(0, 1)),
                child: Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              ),
            ),
        ]),
      ),
    );
  }
}

class _SavedBubble extends StatelessWidget {
  const _SavedBubble(this.r);
  final Json r;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final notes = (r['notes'] as List).cast<String>();
    return _AiBubble(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.check_circle, color: Tones.green(context), size: 20),
          const SizedBox(width: 8),
          Flexible(child: Text(r['headline'] as String, style: const TextStyle(fontWeight: FontWeight.w700))),
        ]),
        const SizedBox(height: 4),
        Text(r['title'] as String, style: TextStyle(color: cs.primary, fontWeight: FontWeight.w600)),
        if (notes.isNotEmpty) Text(notes.join(' · '), style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant)),
        const SizedBox(height: 8),
        FilledButton.tonal(
          onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => r['type'] == 'event' ? EventDetailScreen(id: r['id'] as int) : TaskDetailScreen(id: r['id'] as int))),
          child: Text(r['type'] == 'event' ? 'Open event' : 'Open task'),
        ),
      ]),
    );
  }
}

/// The assistant's suggestion as an editable card.
class _ReplyCard extends StatefulWidget {
  const _ReplyCard({super.key, required this.data, required this.workspace, required this.text, required this.onSaved, required this.onDiscard});
  final Json data;
  final Json workspace;
  final String text;
  final ValueChanged<Json> onSaved;
  final VoidCallback onDiscard;
  @override
  State<_ReplyCard> createState() => _ReplyCardState();
}

class _ReplyCardState extends State<_ReplyCard> {
  late final Json s = Map.of(widget.data['suggestion'] as Json);
  late String _action = s['action'] as String? ?? 'new_task';
  late final _summary = TextEditingController(text: s['summary'] as String? ?? '');
  late final _source = TextEditingController(text: s['source'] as String? ?? '');
  late final _title = TextEditingController(text: s['new_task_title'] as String? ?? '');
  late final _next = TextEditingController(text: s['next_action'] as String? ?? '');
  late final _eventTitle = TextEditingController(text: s['event_title'] as String? ?? '');
  late final _eventWhere = TextEditingController(text: s['event_location'] as String? ?? '');
  late int? _task = s['task'] as int?;
  late String? _desk = s['desk'] as String?;
  late bool _handoff = s['handoff'] == true;
  late String _kind = s['kind'] as String? ?? 'note';
  late String _role = s['my_role'] as String? ?? 'following';
  late String _eventRole = s['event_my_role'] as String? ?? 'guest';
  late DateTime? _follow = _parse(s['follow_up_date']);
  late DateTime? _due = _parse(s['due_date']);
  late DateTime? _eventStart = _parse(s['event_start']);
  bool _more = false;
  bool _saving = false;

  static DateTime? _parse(Object? v) => v is String && v.isNotEmpty ? DateTime.tryParse(v) : null;

  Future<void> _save() async {
    setState(() => _saving = true);
    final app = AppScope.read(context);
    try {
      final r = await app.api!.post('capture/save', {
        'workspace': widget.workspace['id'],
        'body': widget.text,
        'summary': _summary.text.trim(),
        'kind': _kind,
        'source': _source.text.trim(),
        'action': _action,
        'task': _task ?? '',
        'handoff': _handoff,
        'new_task_title': _title.text.trim(),
        'my_role': _role,
        'desk': _desk ?? '',
        'next_action': _next.text.trim(),
        'due_date': _due == null ? '' : isoDate(_due!),
        'follow_up_date': _follow == null ? '' : isoDate(_follow!),
        'event_title': _eventTitle.text.trim(),
        'event_kind': s['event_kind'] ?? 'meeting',
        'event_my_role': _eventRole,
        'event_start': _eventStart == null ? '' : isoDateTime(_eventStart!),
        'event_location': _eventWhere.text.trim(),
      });
      HapticFeedback.mediumImpact();
      widget.onSaved(r);
    } catch (e) {
      if (mounted) showApiError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final app = AppScope.of(context);
    final tasks = (widget.data['tasks'] as List).cast<Json>();
    final desks = (widget.data['desks'] as List).cast<Json>();
    final usedAi = widget.data['used_ai'] == true;
    final error = widget.data['error'] as String? ?? '';
    const gap = SizedBox(height: 12);

    return _AiBubble(
      wide: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (error.isNotEmpty) ...[
          Text(error, style: TextStyle(color: Tones.red(context))),
          Text('You can still file it yourself below.', style: TextStyle(color: cs.onSurfaceVariant)),
        ] else if (usedAi) ...[
          Text(_summary.text, style: const TextStyle(fontSize: 15.5, height: 1.35)),
          const SizedBox(height: 4),
          Row(children: [
            Icon(Icons.auto_awesome, size: 14, color: cs.primary),
            const SizedBox(width: 4),
            Flexible(
                child: Text(
                    'Suggested by AI${widget.data['cached'] == true ? ' · reused, no cost' : ''}${widget.data['shortened'] == true ? ' · long message, first part read' : ''}',
                    style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant))),
          ]),
        ] else
          const Text('Choose where this goes', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 12),
        SegmentedButton<String>(
          showSelectedIcon: false,
          style: const ButtonStyle(visualDensity: VisualDensity.compact),
          segments: const [
            ButtonSegment(value: 'update_task', label: Text('Existing')),
            ButtonSegment(value: 'new_task', label: Text('New task')),
            ButtonSegment(value: 'new_event', label: Text('Event')),
          ],
          selected: {_action},
          onSelectionChanged: (v) => setState(() => _action = v.first),
        ),
        gap,
        AnimatedSize(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
          alignment: Alignment.topCenter,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (_action == 'update_task') ...[
              DropdownButtonFormField<int>(
                initialValue: tasks.any((t) => t['id'] == _task) ? _task : null,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Task'),
                items: [for (final t in tasks) DropdownMenuItem(value: t['id'] as int, child: Text('${t['title']}${(t['desk'] as String).isNotEmpty ? ' — ${t['desk']}' : ''}', overflow: TextOverflow.ellipsis))],
                onChanged: (v) => setState(() => _task = v),
              ),
              gap,
            ],
            if (_action == 'new_task') ...[
              TextField(controller: _title, decoration: const InputDecoration(labelText: 'Title')),
              gap,
              SegmentedButton<String>(
                showSelectedIcon: false,
                style: const ButtonStyle(visualDensity: VisualDensity.compact),
                segments: const [
                  ButtonSegment(value: 'assigned', label: Text('Assigned')),
                  ButtonSegment(value: 'following', label: Text('Following')),
                  ButtonSegment(value: 'executing', label: Text('Doing it')),
                ],
                selected: {_role},
                onSelectionChanged: (v) => setState(() => _role = v.first),
              ),
              gap,
            ],
            if (_action != 'new_event' && !(_action == 'new_task' && _role == 'executing')) ...[
              DeskPicker(groups: desks, value: _desk, label: 'Who has it now', onChanged: (v) => setState(() => _desk = v)),
              if (_action == 'update_task')
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('Record a hand-off to them'),
                  value: _handoff,
                  onChanged: (v) => setState(() => _handoff = v ?? false),
                ),
              gap,
            ],
            if (_action != 'new_event') ...[
              DateField(label: 'Follow up on', value: _follow, onChanged: (v) => setState(() => _follow = v)),
              gap,
              DateField(label: 'Due date', value: _due, onChanged: (v) => setState(() => _due = v)),
              gap,
              TextField(controller: _next, decoration: const InputDecoration(labelText: 'Next action / what to check')),
            ],
            if (_action == 'new_event') ...[
              TextField(controller: _eventTitle, decoration: const InputDecoration(labelText: 'Event title')),
              gap,
              DateField(label: 'Starts', value: _eventStart, withTime: true, onChanged: (v) => setState(() => _eventStart = v)),
              gap,
              TextField(controller: _eventWhere, decoration: const InputDecoration(labelText: 'Where')),
              gap,
              DropdownButtonFormField<String>(
                initialValue: _eventRole,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'My role'),
                items: [for (final o in app.option('event_roles')) DropdownMenuItem(value: o['value'] as String, child: Text(o['label'] as String))],
                onChanged: (v) => setState(() => _eventRole = v!),
              ),
            ],
          ]),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
            icon: AnimatedRotation(turns: _more ? .5 : 0, duration: const Duration(milliseconds: 200), child: const Icon(Icons.expand_more, size: 18)),
            label: const Text('Summary, type and sender'),
            onPressed: () => setState(() => _more = !_more),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 200),
          child: !_more
              ? const SizedBox(width: double.infinity)
              : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  TextField(controller: _summary, maxLines: 3, minLines: 1, onChanged: (_) => setState(() {}), decoration: const InputDecoration(labelText: 'Summary')),
                  gap,
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final k in app.option('update_kinds'))
                      ChoiceChip(visualDensity: VisualDensity.compact, showCheckmark: false, label: Text(k['label'] as String), selected: _kind == k['value'], onSelected: (_) => setState(() => _kind = k['value'] as String)),
                  ]),
                  gap,
                  TextField(controller: _source, decoration: const InputDecoration(labelText: 'From')),
                  gap,
                ]),
        ),
        Row(children: [
          TextButton(onPressed: _saving ? null : widget.onDiscard, child: const Text('Discard')),
          const Spacer(),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.check),
            label: const Text('Save'),
          ),
        ]),
      ]),
    );
  }
}
