import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';
import 'state.dart';

// ---------------------------------------------------------------- colors & text

const brand = Color(0xFF1F3A5F);

Color workspaceColor(String? name, Brightness b) {
  final dark = b == Brightness.dark;
  switch (name) {
    case 'green':
      return dark ? const Color(0xFF74D29C) : const Color(0xFF2E7D4F);
    case 'purple':
      return dark ? const Color(0xFFB9A2F2) : const Color(0xFF6B46C1);
    case 'orange':
      return dark ? const Color(0xFFF2A65A) : const Color(0xFFC25E10);
    case 'teal':
      return dark ? const Color(0xFF62D0D4) : const Color(0xFF0F7C80);
    case 'red':
      return dark ? const Color(0xFFF07A70) : const Color(0xFFB8322A);
    case 'gray':
      return dark ? const Color(0xFFA3ACB9) : const Color(0xFF6B7585);
    default:
      return dark ? const Color(0xFF86B4EE) : const Color(0xFF2F6FB5);
  }
}

class Tones {
  static Color red(BuildContext c) => Theme.of(c).brightness == Brightness.dark
      ? const Color(0xFFF07A70)
      : const Color(0xFFC0362C);
  static Color amber(BuildContext c) =>
      Theme.of(c).brightness == Brightness.dark
      ? const Color(0xFFF0B55A)
      : const Color(0xFFA86400);
  static Color green(BuildContext c) =>
      Theme.of(c).brightness == Brightness.dark
      ? const Color(0xFF74D29C)
      : const Color(0xFF2E7D4F);
}

final _d = DateFormat('EEE, d MMM yyyy');
final _dShort = DateFormat('d MMM');
final _dt = DateFormat('EEE, d MMM · HH:mm');
final _t = DateFormat('HH:mm');

String fmtDate(String? iso) =>
    iso == null ? '—' : _d.format(DateTime.parse(iso));
String fmtShort(String? iso) =>
    iso == null ? '' : _dShort.format(DateTime.parse(iso));
String fmtDateTime(String? iso) =>
    iso == null ? '' : _dt.format(DateTime.parse(iso).toLocal());
String fmtTime(String? iso) =>
    iso == null ? '' : _t.format(DateTime.parse(iso).toLocal());
String isoDate(DateTime d) => DateFormat('yyyy-MM-dd').format(d);
String isoDateTime(DateTime d) => DateFormat("yyyy-MM-dd'T'HH:mm").format(d);

void toast(BuildContext context, String message, {bool error = false}) {
  final m = ScaffoldMessenger.of(context);
  m.hideCurrentSnackBar();
  m.showSnackBar(
    SnackBar(
      content: Text(message),
      behavior: SnackBarBehavior.floating,
      backgroundColor: error ? Tones.red(context) : null,
      duration: Duration(milliseconds: error ? 4000 : 2200),
    ),
  );
}

/// Shows an API error; logs out if the token was revoked.
void showApiError(BuildContext context, Object e) {
  if (e is ApiException && e.unauthorized) {
    AppScope.read(context).handleSessionExpired(context);
    return;
  }
  toast(context, e.toString(), error: true);
}

// ---------------------------------------------------------------- small pieces

class Dot extends StatelessWidget {
  const Dot(this.color, {super.key, this.size = 8});
  final Color color;
  final double size;
  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(color: color, shape: BoxShape.circle),
  );
}

class Pill extends StatelessWidget {
  const Pill(this.label, {super.key, this.tone = 'neutral'});
  final String label;
  final String tone;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    Color fg = cs.onSurfaceVariant;
    Color bg = cs.surfaceContainerHighest;
    Border? border;
    switch (tone) {
      case 'red':
        fg = Tones.red(context);
        bg = fg.withValues(alpha: .12);
      case 'amber':
        fg = Tones.amber(context);
        bg = fg.withValues(alpha: .14);
      case 'green':
        fg = Tones.green(context);
        bg = fg.withValues(alpha: .13);
      case 'ghost':
        bg = Colors.transparent;
        border = Border.all(color: cs.outlineVariant);
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(99),
        border: border,
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: fg),
      ),
    );
  }
}

String statusTone(String status) => switch (status) {
  'invited' => 'amber',
  'confirmed' => 'green',
  'declined' || 'cancelled' => 'red',
  _ => 'neutral',
};

/// Shrinks slightly while pressed — a light, responsive feel for tappable cards.
class Pressable extends StatefulWidget {
  const Pressable({
    super.key,
    required this.child,
    this.onTap,
    this.borderRadius = 14,
  });
  final Widget child;
  final VoidCallback? onTap;
  final double borderRadius;
  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  @override
  Widget build(BuildContext context) {
    return AnimatedScale(
      scale: _down ? .975 : 1,
      duration: const Duration(milliseconds: 110),
      curve: Curves.easeOut,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(widget.borderRadius),
          onTap: widget.onTap == null
              ? null
              : () {
                  HapticFeedback.selectionClick();
                  widget.onTap!();
                },
          onHighlightChanged: (v) => setState(() => _down = v),
          child: widget.child,
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 22, 4, 8),
      child: Row(
        children: [
          Text(
            text.toUpperCase(),
            style: TextStyle(
              fontSize: 12,
              letterSpacing: .8,
              fontWeight: FontWeight.w700,
              color: cs.onSurfaceVariant,
            ),
          ),
          const Spacer(),
          ?trailing,
        ],
      ),
    );
  }
}

/// A card that holds a list of rows separated by thin lines.
class ListCard extends StatelessWidget {
  const ListCard({super.key, required this.children});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final items = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      if (i > 0) {
        items.add(
          Divider(
            height: 1,
            indent: 16,
            endIndent: 16,
            color: cs.outlineVariant.withValues(alpha: .6),
          ),
        );
      }
      items.add(children[i]);
    }
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: Column(children: items),
    );
  }
}

class Meta extends StatelessWidget {
  const Meta(this.parts, {super.key, this.dot});
  final List<String> parts;
  final Color? dot;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final text = parts.where((p) => p.isNotEmpty).join('  ·  ');
    return Row(
      children: [
        if (dot != null) ...[Dot(dot!), const SizedBox(width: 7)],
        Expanded(
          child: Text(
            text,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant),
          ),
        ),
      ],
    );
  }
}

class TaskTile extends StatelessWidget {
  const TaskTile(
    this.t, {
    super.key,
    required this.onTap,
    this.hideDesk = false,
    this.showNote = false,
  });
  final Json t;
  final VoidCallback onTap;
  final bool hideDesk;
  final bool showNote;

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    final ws = t['workspace'] as Json;
    final pill = t['pill'] as Json?;
    final pri = t['priority'] as int;
    final edge = pri >= 4
        ? Tones.red(context)
        : pri == 3
        ? const Color(0xFFC25E10)
        : null;
    return Pressable(
      onTap: onTap,
      borderRadius: 0,
      child: Container(
        decoration: BoxDecoration(
          border: edge == null
              ? null
              : Border(left: BorderSide(color: edge, width: 3)),
        ),
        padding: EdgeInsets.fromLTRB(edge == null ? 16 : 13, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              t['title'] as String,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 15.5,
                color: t['is_closed'] == true
                    ? Theme.of(context).colorScheme.onSurfaceVariant
                    : null,
              ),
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                if (pill != null) ...[
                  Pill(pill['label'] as String, tone: pill['tone'] as String),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: Meta(
                    [
                      if (!hideDesk) (t['desk'] as String),
                      if (t['days_with_holder'] != null)
                        '${t['days_with_holder']}d',
                      (t['stage'] as Json)['name'] as String,
                    ],
                    dot: hideDesk
                        ? null
                        : workspaceColor(ws['color'] as String?, b),
                  ),
                ),
              ],
            ),
            if (showNote &&
                (t['follow_up_note'] as String? ?? '').isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                t['follow_up_note'] as String,
                style: TextStyle(fontSize: 13, color: Tones.amber(context)),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class EventTile extends StatelessWidget {
  const EventTile(this.e, {super.key, required this.onTap});
  final Json e;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final start = DateTime.parse(e['start'] as String).toLocal();
    final off = e['is_off'] == true;
    return Pressable(
      onTap: onTap,
      borderRadius: 0,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Row(
          children: [
            Container(
              width: 46,
              height: 48,
              decoration: BoxDecoration(
                color: cs.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    '${start.day}',
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      height: 1.1,
                    ),
                  ),
                  Text(
                    DateFormat('MMM').format(start).toUpperCase(),
                    style: TextStyle(
                      fontSize: 10.5,
                      letterSpacing: .5,
                      color: cs.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    e['title'] as String,
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 15.5,
                      decoration: off ? TextDecoration.lineThrough : null,
                      color: off ? cs.onSurfaceVariant : null,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Pill(
                        e['status_short'] as String,
                        tone: statusTone(e['status'] as String),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Meta([
                          DateFormat('EEE, HH:mm').format(start),
                          e['my_role_label'] as String,
                          (e['location'] as String?) ?? '',
                        ]),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView(
    this.text, {
    super.key,
    this.icon = Icons.inbox_outlined,
    this.action,
  });
  final String text;
  final IconData icon;
  final Widget? action;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 24),
      child: Column(
        children: [
          Icon(icon, size: 40, color: cs.outline),
          const SizedBox(height: 10),
          Text(
            text,
            textAlign: TextAlign.center,
            style: TextStyle(color: cs.onSurfaceVariant),
          ),
          if (action != null) ...[const SizedBox(height: 12), action!],
        ],
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView(this.error, {super.key, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => EmptyView(
    error.toString(),
    icon: Icons.cloud_off_outlined,
    action: FilledButton.tonal(
      onPressed: onRetry,
      child: const Text('Try again'),
    ),
  );
}

/// Loads JSON, shows a spinner / error / content, reloads on pull-down and when data changes elsewhere.
class Loader extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder});
  final Future<Json> Function() load;
  final Widget Function(BuildContext, Json, Future<void> Function() reload)
  builder;
  @override
  State<Loader> createState() => _LoaderState();
}

class _LoaderState extends State<Loader> {
  Json? _data;
  Object? _error;
  int _seen = -1;

  Future<void> _reload() async {
    try {
      final d = await widget.load();
      if (mounted) {
        setState(() {
          _data = d;
          _error = null;
        });
      }
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.unauthorized) {
        AppScope.read(context).handleSessionExpired(context);
        return;
      }
      setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final v = AppScope.of(context).dataVersion;
    if (v != _seen) {
      _seen = v;
      Future.microtask(_reload);
    }
    Widget child;
    if (_data != null) {
      child = KeyedSubtree(
        key: const ValueKey('data'),
        child: widget.builder(context, _data!, _reload),
      );
    } else if (_error != null) {
      child = ListView(
        children: [
          ErrorView(
            _error!,
            onRetry: () {
              setState(() => _error = null);
              _reload();
            },
          ),
        ],
      );
    } else {
      child = const Center(
        key: ValueKey('loading'),
        child: CircularProgressIndicator(strokeWidth: 2.5),
      );
    }
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 220),
      child: child,
    );
  }
}

/// Standard scrollable page body with pull-to-refresh.
class RefreshList extends StatelessWidget {
  const RefreshList({
    super.key,
    required this.onRefresh,
    required this.children,
    this.padding,
  });
  final Future<void> Function() onRefresh;
  final List<Widget> children;
  final EdgeInsets? padding;
  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(
          parent: BouncingScrollPhysics(),
        ),
        padding: padding ?? const EdgeInsets.fromLTRB(16, 8, 16, 120),
        children: children,
      ),
    );
  }
}

// ---------------------------------------------------------------- contacts

class ContactActions extends StatelessWidget {
  const ContactActions({super.key, this.phone, this.email});
  final String? phone;
  final String? email;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    if ((phone ?? '').isNotEmpty) {
      rows.add(
        _row(
          context,
          Icons.call_outlined,
          phone!,
          'tel:${phone!.replaceAll(RegExp(r'[^0-9+]'), '')}',
        ),
      );
    }
    if ((email ?? '').isNotEmpty) {
      rows.add(_row(context, Icons.mail_outline, email!, 'mailto:$email'));
    }
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  Widget _row(BuildContext context, IconData icon, String value, String url) {
    final cs = Theme.of(context).colorScheme;
    return Row(
      children: [
        Expanded(
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () => launchUrl(Uri.parse(url)),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Icon(icon, size: 18, color: cs.primary),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      value,
                      style: TextStyle(
                        color: cs.primary,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        IconButton(
          visualDensity: VisualDensity.compact,
          tooltip: 'Copy',
          icon: Icon(Icons.copy_rounded, size: 18, color: cs.onSurfaceVariant),
          onPressed: () {
            Clipboard.setData(ClipboardData(text: value));
            HapticFeedback.lightImpact();
            toast(context, 'Copied $value');
          },
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------- form fields

/// Grouped picker for "who has it": departments with their people, plus individuals.
class DeskPicker extends StatelessWidget {
  const DeskPicker({
    super.key,
    required this.groups,
    required this.value,
    required this.onChanged,
    this.label = 'Who has it',
    this.allowNone = true,
  });
  final List<Json> groups;
  final String? value;
  final ValueChanged<String?> onChanged;
  final String label;
  final bool allowNone;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final items = <DropdownMenuItem<String?>>[];
    if (allowNone) {
      items.add(
        const DropdownMenuItem(value: null, child: Text('— Nobody / not sure')),
      );
    }
    final values = <String>{};
    for (final g in groups) {
      items.add(
        DropdownMenuItem(
          enabled: false,
          value: '__${g['label']}',
          child: Text(
            (g['label'] as String).toUpperCase(),
            style: TextStyle(
              fontSize: 11.5,
              letterSpacing: .6,
              fontWeight: FontWeight.w700,
              color: cs.primary,
            ),
          ),
        ),
      );
      for (final o in (g['options'] as List).cast<Json>()) {
        values.add(o['value'] as String);
        final whole = (o['label'] as String).contains('— whole');
        items.add(
          DropdownMenuItem(
            value: o['value'] as String,
            child: Padding(
              padding: EdgeInsets.only(left: whole ? 0 : 12),
              child: Text(
                o['label'] as String,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        );
      }
    }
    return DropdownButtonFormField<String?>(
      initialValue: values.contains(value) ? value : null,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      items: items,
      onChanged: onChanged,
    );
  }
}

class DateField extends StatelessWidget {
  const DateField({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
    this.withTime = false,
  });
  final String label;
  final DateTime? value;
  final ValueChanged<DateTime?> onChanged;
  final bool withTime;

  @override
  Widget build(BuildContext context) {
    final text = value == null
        ? ''
        : (withTime
                  ? DateFormat('EEE, d MMM yyyy · HH:mm')
                  : DateFormat('EEE, d MMM yyyy'))
              .format(value!);
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () async {
        final now = DateTime.now();
        final d = await showDatePicker(
          context: context,
          initialDate: value ?? now,
          firstDate: DateTime(now.year - 5),
          lastDate: DateTime(now.year + 5),
        );
        if (d == null || !context.mounted) return;
        if (!withTime) return onChanged(d);
        final t = await showTimePicker(
          context: context,
          initialTime: TimeOfDay.fromDateTime(value ?? now),
        );
        onChanged(
          DateTime(d.year, d.month, d.day, t?.hour ?? 9, t?.minute ?? 0),
        );
      },
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          suffixIcon: value == null
              ? const Icon(Icons.event_outlined)
              : IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => onChanged(null),
                ),
        ),
        isEmpty: value == null,
        child: Text(text),
      ),
    );
  }
}

/// Shows field errors from the API under the right inputs.
String? fieldError(ApiException? e, String field) {
  final list = e?.fieldErrors[field];
  return (list == null || list.isEmpty) ? null : list.first;
}

/// Bottom sheet with a title, used for quick actions.
Future<T?> showSheet<T>(
  BuildContext context, {
  required String title,
  required Widget Function(BuildContext) builder,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    useSafeArea: true,
    builder: (ctx) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              title,
              style: Theme.of(ctx).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 16),
            builder(ctx),
          ],
        ),
      ),
    ),
  );
}

/// Workspace filter chips shown at the top of Home, Tasks and Events.
class WorkspaceFilter extends StatelessWidget {
  const WorkspaceFilter({super.key});
  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final b = Theme.of(context).brightness;
    if (app.workspaces.length < 2) return const SizedBox.shrink();
    Widget chip(String label, int? id, {Color? color}) {
      final on = app.workspaceFilter == id;
      return Padding(
        padding: const EdgeInsets.only(right: 8),
        child: ChoiceChip(
          label: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (color != null) ...[Dot(color), const SizedBox(width: 6)],
              Text(label),
            ],
          ),
          selected: on,
          showCheckmark: false,
          onSelected: (_) {
            HapticFeedback.selectionClick();
            app.setWorkspaceFilter(id);
          },
        ),
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
        child: Row(
          children: [
            chip('All', null),
            for (final w in app.workspaces)
              chip(
                w['name'] as String,
                w['id'] as int,
                color: workspaceColor(w['color'] as String?, b),
              ),
          ],
        ),
      ),
    );
  }
}
