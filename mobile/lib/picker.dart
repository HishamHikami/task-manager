import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
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

// ======================================================================= date & time

/// Slides up a themed date (and optionally time) sheet.
/// Returns Picked(null) when cleared, null when dismissed.
Future<Picked<DateTime?>?> showDateSheet(
  BuildContext context, {
  required String title,
  DateTime? initial,
  bool withTime = false,
  bool allowClear = true,
}) {
  HapticFeedback.selectionClick();
  return showModalBottomSheet<Picked<DateTime?>>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (_) => _DateSheet(
      title: title,
      initial: initial,
      withTime: withTime,
      allowClear: allowClear,
    ),
  );
}

class _DateSheet extends StatefulWidget {
  const _DateSheet({
    required this.title,
    required this.initial,
    required this.withTime,
    required this.allowClear,
  });
  final String title;
  final DateTime? initial;
  final bool withTime;
  final bool allowClear;
  @override
  State<_DateSheet> createState() => _DateSheetState();
}

class _DateSheetState extends State<_DateSheet> {
  late DateTime _day;
  late int _hour;
  late int _minute; // multiple of 5
  int _calendarKey =
      0; // forces the calendar to jump when a quick choice is tapped
  bool _timeMode = false; // date+time sheet: calendar tab or time tab

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    final v = widget.initial;
    _day = DateUtils.dateOnly(v ?? now);
    _hour = v?.hour ?? (widget.withTime ? 9 : 0);
    _minute = ((v?.minute ?? 0) / 5).round() * 5 % 60;
  }

  DateTime get _result => widget.withTime
      ? DateTime(_day.year, _day.month, _day.day, _hour, _minute)
      : _day;

  /// Picks a day. Quick choices also move the calendar ([jump]); with time,
  /// picking a day moves on to the time wheels.
  void _setDay(DateTime d, {bool jump = true}) {
    HapticFeedback.selectionClick();
    setState(() {
      _day = DateUtils.dateOnly(d);
      if (jump) _calendarKey++;
      if (widget.withTime) _timeMode = true;
    });
  }

  Widget _datePanel(List<(String, DateTime)> quick, DateTime today) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      SizedBox(
        height: 40,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 20),
          children: [
            for (final q in quick)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(q.$1),
                  selected: DateUtils.isSameDay(q.$2, _day),
                  showCheckmark: false,
                  onSelected: (_) => _setDay(q.$2),
                ),
              ),
          ],
        ),
      ),
      CalendarDatePicker(
        key: ValueKey(_calendarKey),
        initialDate: _day,
        currentDate: today,
        firstDate: DateTime(today.year - 5),
        lastDate: DateTime(today.year + 5),
        onDateChanged: (d) => _setDay(d, jump: false),
      ),
    ],
  );

  Widget _timePanel(ColorScheme cs) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      const SizedBox(height: 12),
      Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _Wheel(
            count: 24,
            value: _hour,
            label: (i) => i.toString().padLeft(2, '0'),
            onChanged: (v) => setState(() => _hour = v),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              ':',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: cs.onSurfaceVariant,
              ),
            ),
          ),
          _Wheel(
            count: 12,
            value: _minute ~/ 5,
            label: (i) => (i * 5).toString().padLeft(2, '0'),
            onChanged: (v) => setState(() => _minute = v * 5),
          ),
        ],
      ),
      const SizedBox(height: 16),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.center,
          children: [
            for (final t in const [
              (9, 0),
              (10, 0),
              (12, 0),
              (16, 0),
              (18, 0),
              (19, 30),
              (20, 0),
            ])
              ChoiceChip(
                label: Text(
                  '${t.$1.toString().padLeft(2, '0')}:${t.$2.toString().padLeft(2, '0')}',
                ),
                selected: _hour == t.$1 && _minute == t.$2,
                showCheckmark: false,
                onSelected: (_) {
                  HapticFeedback.selectionClick();
                  setState(() {
                    _hour = t.$1;
                    _minute = t.$2;
                  });
                },
              ),
          ],
        ),
      ),
      const SizedBox(height: 8),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final today = DateUtils.dateOnly(DateTime.now());
    final quick = <(String, DateTime)>[
      ('Today', today),
      ('Tomorrow', today.add(const Duration(days: 1))),
      ('In 3 days', today.add(const Duration(days: 3))),
      ('Next week', today.add(const Duration(days: 7))),
      ('Next month', DateTime(today.year, today.month + 1, today.day)),
    ];
    final preview = DateFormat(
      widget.withTime ? 'EEEE, d MMMM yyyy · HH:mm' : 'EEEE, d MMMM yyyy',
    ).format(_result);

    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 2),
            child: Text(
              widget.title,
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w800),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 10),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              layoutBuilder: (current, previous) => Stack(
                alignment: Alignment.centerLeft,
                children: [...previous, ?current],
              ),
              child: Text(
                preview,
                key: ValueKey(preview),
                style: TextStyle(
                  color: cs.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
          if (widget.withTime)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
              child: _ModeTabs(
                timeMode: _timeMode,
                dateLabel: DateFormat('EEE d MMM').format(_day),
                timeLabel:
                    '${_hour.toString().padLeft(2, '0')}:${_minute.toString().padLeft(2, '0')}',
                onChanged: (t) {
                  HapticFeedback.selectionClick();
                  setState(() => _timeMode = t);
                },
              ),
            ),
          AnimatedSize(
            duration: const Duration(milliseconds: 260),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topCenter,
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 220),
              switchInCurve: Curves.easeOut,
              switchOutCurve: Curves.easeIn,
              layoutBuilder: (current, previous) => Stack(
                alignment: Alignment.topCenter,
                children: [...previous, ?current],
              ),
              transitionBuilder: (child, a) => FadeTransition(
                opacity: a,
                child: SlideTransition(
                  position: Tween(
                    begin: Offset(
                      child.key == const ValueKey('time') ? .06 : -.06,
                      0,
                    ),
                    end: Offset.zero,
                  ).animate(a),
                  child: child,
                ),
              ),
              child: widget.withTime && _timeMode
                  ? KeyedSubtree(
                      key: const ValueKey('time'),
                      child: _timePanel(cs),
                    )
                  : KeyedSubtree(
                      key: const ValueKey('date'),
                      child: _datePanel(quick, today),
                    ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
            child: Row(
              children: [
                if (widget.allowClear && widget.initial != null)
                  TextButton.icon(
                    style: TextButton.styleFrom(foregroundColor: cs.error),
                    icon: const Icon(Icons.close, size: 18),
                    label: const Text('Clear'),
                    onPressed: () =>
                        Navigator.pop(context, const Picked<DateTime?>(null)),
                  ),
                const Spacer(),
                FilledButton(
                  onPressed: () {
                    HapticFeedback.mediumImpact();
                    Navigator.pop(context, Picked<DateTime?>(_result));
                  },
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 18),
                    child: Text('Done'),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Two pill tabs for the date+time sheet: shows the picked date and time,
/// and switches between the calendar and the time wheels.
class _ModeTabs extends StatelessWidget {
  const _ModeTabs({
    required this.timeMode,
    required this.dateLabel,
    required this.timeLabel,
    required this.onChanged,
  });
  final bool timeMode;
  final String dateLabel;
  final String timeLabel;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    Widget tab(bool isTime, IconData icon, String label) {
      final on = timeMode == isTime;
      return Expanded(
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: on ? null : () => onChanged(isTime),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            height: 44,
            decoration: BoxDecoration(
              color: on ? cs.primaryContainer : Colors.transparent,
              borderRadius: BorderRadius.circular(12),
            ),
            alignment: Alignment.center,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  icon,
                  size: 18,
                  color: on ? cs.onPrimaryContainer : cs.onSurfaceVariant,
                ),
                const SizedBox(width: 8),
                Text(
                  label,
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    color: on ? cs.onPrimaryContainer : cs.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: cs.outlineVariant),
      ),
      child: Row(
        children: [
          tab(false, Icons.calendar_today_rounded, dateLabel),
          const SizedBox(width: 4),
          tab(true, Icons.schedule_rounded, timeLabel),
        ],
      ),
    );
  }
}

/// A smooth scroll wheel for picking a number (hours / minutes).
class _Wheel extends StatefulWidget {
  const _Wheel({
    required this.count,
    required this.value,
    required this.label,
    required this.onChanged,
  });
  final int count;
  final int value;
  final String Function(int) label;
  final ValueChanged<int> onChanged;
  @override
  State<_Wheel> createState() => _WheelState();
}

class _WheelState extends State<_Wheel> {
  late final FixedExtentScrollController _c = FixedExtentScrollController(
    initialItem: widget.value,
  );

  @override
  void didUpdateWidget(_Wheel old) {
    super.didUpdateWidget(old);
    if (widget.value != old.value &&
        _c.hasClients &&
        _c.selectedItem % widget.count != widget.value) {
      _c.animateToItem(
        widget.value,
        duration: const Duration(milliseconds: 280),
        curve: Curves.easeOutCubic,
      );
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return SizedBox(
      width: 84,
      height: 132,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            height: 44,
            decoration: BoxDecoration(
              color: cs.primaryContainer.withValues(alpha: .55),
              borderRadius: BorderRadius.circular(14),
            ),
          ),
          ListWheelScrollView.useDelegate(
            controller: _c,
            itemExtent: 44,
            diameterRatio: 1.6,
            perspective: .004,
            physics: const FixedExtentScrollPhysics(),
            onSelectedItemChanged: (i) {
              HapticFeedback.selectionClick();
              widget.onChanged(i % widget.count);
            },
            childDelegate: ListWheelChildBuilderDelegate(
              childCount: widget.count,
              builder: (_, i) => Center(
                child: Text(
                  widget.label(i),
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: i == widget.value
                        ? FontWeight.w800
                        : FontWeight.w500,
                    color: i == widget.value
                        ? cs.onSurface
                        : cs.onSurfaceVariant,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
