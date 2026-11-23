import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

/// One choice in a picker sheet.
class PickOption<T> {
  const PickOption(
    this.value,
    this.label, {
    this.subtitle,
    this.leading,
    this.color,
    this.danger = false,
    this.icon,
  });
  final T value;
  final String label;
  final String? subtitle;
  final Widget? leading;
  final Color? color; // shows a colour dot
  final IconData? icon; // shows an icon in a soft circle
  final bool danger;
}

/// A titled section of choices (e.g. a department and its people).
class PickGroup<T> {
  const PickGroup(this.options, {this.title});
  final String? title;
  final List<PickOption<T>> options;
}

/// Wraps the chosen value so "nothing" (null) can be a real choice.
class Picked<T> {
  const Picked(this.value);
  final T value;
}

/// Slides up a themed sheet of choices. Returns null if dismissed.
Future<Picked<T>?> showPicker<T>(
  BuildContext context, {
  required String title,
  required List<PickGroup<T>> groups,
  T? selected,
  bool searchable = false,
}) {
  HapticFeedback.selectionClick();
  return showModalBottomSheet<Picked<T>>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (_) => _PickerSheet<T>(
      title: title,
      groups: groups,
      selected: selected,
      searchable: searchable,
    ),
  );
}

class _PickerSheet<T> extends StatefulWidget {
  const _PickerSheet({
    required this.title,
    required this.groups,
    required this.selected,
    required this.searchable,
  });
  final String title;
  final List<PickGroup<T>> groups;
  final T? selected;
  final bool searchable;
  @override
  State<_PickerSheet<T>> createState() => _PickerSheetState<T>();
}

class _PickerSheetState<T> extends State<_PickerSheet<T>> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final q = _q.toLowerCase();
    final rows = <Widget>[];
    var index = 0;
    for (final g in widget.groups) {
      final groupMatches =
          q.isEmpty || (g.title ?? '').toLowerCase().contains(q);
      final opts = g.options
          .where(
            (o) =>
                groupMatches ||
                o.label.toLowerCase().contains(q) ||
                (o.subtitle ?? '').toLowerCase().contains(q),
          )
          .toList();
      if (opts.isEmpty) continue;
      if (g.title != null) {
        rows.add(
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 6),
            child: Text(
              g.title!.toUpperCase(),
              style: TextStyle(
                fontSize: 11.5,
                letterSpacing: .8,
                fontWeight: FontWeight.w700,
                color: cs.onSurfaceVariant,
              ),
            ),
          ),
        );
      }
      for (final o in opts) {
        rows.add(
          _Stagger(
            index: index++,
            child: _OptionTile<T>(
              option: o,
              selected: o.value == widget.selected,
            ),
          ),
        );
      }
    }

    final maxH = MediaQuery.of(context).size.height * .82;
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxH),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
              child: Text(
                widget.title,
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
            ),
            if (widget.searchable)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                child: TextField(
                  autofocus: false,
                  onChanged: (v) => setState(() => _q = v.trim()),
                  decoration: InputDecoration(
                    hintText: 'Search',
                    prefixIcon: const Icon(Icons.search),
                    filled: true,
                    fillColor: cs.surfaceContainerHighest,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(99),
                      borderSide: BorderSide.none,
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(99),
                      borderSide: BorderSide.none,
                    ),
                    contentPadding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                ),
              ),
            Flexible(
              child: rows.isEmpty
                  ? Padding(
                      padding: const EdgeInsets.all(32),
                      child: Text(
                        'Nothing matches “$_q”.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: cs.onSurfaceVariant),
                      ),
                    )
                  : ListView(
                      shrinkWrap: true,
                      padding: const EdgeInsets.fromLTRB(8, 4, 8, 20),
                      children: rows,
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OptionTile<T> extends StatelessWidget {
  const _OptionTile({required this.option, required this.selected});
  final PickOption<T> option;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final o = option;
    final fg = o.danger ? cs.error : cs.onSurface;
    Widget? lead = o.leading;
    if (lead == null && o.color != null) {
      lead = Container(
        width: 12,
        height: 12,
        margin: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: o.color, shape: BoxShape.circle),
      );
    }
    if (lead == null && o.icon != null) {
      lead = CircleAvatar(
        radius: 17,
        backgroundColor: o.danger ? cs.errorContainer : cs.secondaryContainer,
        child: Icon(
          o.icon,
          size: 19,
          color: o.danger ? cs.onErrorContainer : cs.onSecondaryContainer,
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Material(
        color: selected
            ? cs.primaryContainer.withValues(alpha: .55)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () {
            HapticFeedback.selectionClick();
            Navigator.of(context).pop(Picked<T>(o.value));
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            child: Row(
              children: [
                if (lead != null) ...[lead, const SizedBox(width: 12)],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        o.label,
                        style: TextStyle(
                          fontSize: 15.5,
                          fontWeight: selected
                              ? FontWeight.w700
                              : FontWeight.w500,
                          color: fg,
                        ),
                      ),
                      if ((o.subtitle ?? '').isNotEmpty)
                        Text(
                          o.subtitle!,
                          style: TextStyle(
                            fontSize: 13,
                            color: cs.onSurfaceVariant,
                          ),
                        ),
                    ],
                  ),
                ),
                AnimatedScale(
                  scale: selected ? 1 : 0,
                  duration: const Duration(milliseconds: 180),
                  child: Icon(Icons.check_circle_rounded, color: cs.primary),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Fades and lifts each row in, one after another.
class _Stagger extends StatelessWidget {
  const _Stagger({required this.index, required this.child});
  final int index;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final delay = (index.clamp(0, 10)) * 22;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 220 + delay),
      curve: Interval(delay / (220 + delay), 1, curve: Curves.easeOutCubic),
      builder: (_, v, c) => Opacity(
        opacity: v,
        child: Transform.translate(offset: Offset(0, 10 * (1 - v)), child: c),
      ),
      child: child,
    );
  }
}

/// A form field that shows the current choice and opens the picker sheet when tapped.
class PickerField<T> extends StatelessWidget {
  const PickerField({
    super.key,
    required this.label,
    required this.groups,
    required this.value,
    required this.onChanged,
    this.searchable = false,
    this.placeholder,
    this.sheetTitle,
  });
  final String label;
  final List<PickGroup<T>> groups;
  final T? value;
  final ValueChanged<T?> onChanged;
  final bool searchable;
  final String? placeholder;
  final String? sheetTitle;

  PickOption<T>? get _current {
    for (final g in groups) {
      for (final o in g.options) {
        if (o.value == value) return o;
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final cur = _current;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () async {
        FocusScope.of(context).unfocus();
        final r = await showPicker<T>(
          context,
          title: sheetTitle ?? label,
          groups: groups,
          selected: value,
          searchable: searchable,
        );
        if (r != null) onChanged(r.value);
      },
      child: InputDecorator(
        isEmpty: cur == null && placeholder == null,
        decoration: InputDecoration(
          labelText: label,
          suffixIcon: const Icon(Icons.unfold_more_rounded),
        ),
        child: cur == null
            ? (placeholder == null
                  ? null
                  : Text(
                      placeholder!,
                      style: TextStyle(color: cs.onSurfaceVariant),
                    ))
            : Row(
                children: [
                  if (cur.color != null) ...[
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: cur.color,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 10),
                  ],
                  Flexible(
                    child: Text.rich(
                      TextSpan(
                        children: [
                          TextSpan(
                            text: cur.label,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          if ((cur.subtitle ?? '').isNotEmpty)
                            TextSpan(
                              text: '  ·  ${cur.subtitle}',
                              style: TextStyle(color: cs.onSurfaceVariant),
                            ),
                        ],
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

/// A themed action sheet (replaces pop-up menus).
Future<String?> showActions(
  BuildContext context, {
  required String title,
  required List<PickOption<String>> actions,
}) async {
  final r = await showPicker<String>(
    context,
    title: title,
    groups: [PickGroup(actions)],
  );
  return r?.value;
}

/// Turns [{value, label}] lists from the server into a single group.
List<PickGroup<T>> simpleGroups<T>(List<Map<String, dynamic>> items) => [
  PickGroup([
    for (final o in items) PickOption<T>(o['value'] as T, o['label'] as String),
  ]),
];

/// Initials avatar for people.
class Initials extends StatelessWidget {
  const Initials(this.name, {super.key, this.radius = 17});
  final String name;
  final double radius;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final parts = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty && RegExp(r'[A-Za-z؀-ۿ]').hasMatch(p[0]))
        .toList();
    final text = parts.isEmpty
        ? '?'
        : (parts.first[0] + (parts.length > 1 ? parts.last[0] : ''))
              .toUpperCase();
    return CircleAvatar(
      radius: radius,
      backgroundColor: cs.tertiaryContainer,
      child: Text(
        text,
        style: TextStyle(
          fontSize: radius * .72,
          fontWeight: FontWeight.w700,
          color: cs.onTertiaryContainer,
        ),
      ),
    );
  }
}
