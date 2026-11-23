import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import 'screens/capture.dart';
import 'screens/dashboard.dart';
import 'screens/events.dart';
import 'screens/login.dart';
import 'screens/tasks.dart';
import 'screens/workspaces.dart';
import 'state.dart';
import 'ui.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  final state = AppState()..init();
  runApp(AppScope(state: state, child: const TasksApp()));
}

ThemeData _theme(Brightness b) {
  final scheme = ColorScheme.fromSeed(seedColor: brand, brightness: b);
  final base = ThemeData(colorScheme: scheme, useMaterial3: true, brightness: b);
  final dark = b == Brightness.dark;
  return base.copyWith(
    scaffoldBackgroundColor: dark ? const Color(0xFF0E1319) : const Color(0xFFF5F6F8),
    appBarTheme: AppBarTheme(
      backgroundColor: dark ? const Color(0xFF0E1319) : const Color(0xFFF5F6F8),
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 1,
      centerTitle: false,
      titleTextStyle: base.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700, color: scheme.onSurface),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: dark ? const Color(0xFF161D26) : Colors.white,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: dark ? const Color(0xFF26303C) : const Color(0xFFE4E7EC))),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF161D26) : Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: dark ? const Color(0xFF26303C) : const Color(0xFFDDE1E7))),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 68,
      backgroundColor: dark ? const Color(0xFF161D26) : Colors.white,
      indicatorColor: scheme.primaryContainer,
      labelTextStyle: WidgetStatePropertyAll(base.textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w600)),
    ),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
    }),
    filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
            minimumSize: const Size(0, 46), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)))),
    outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
            minimumSize: const Size(0, 46), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)))),
    snackBarTheme: SnackBarThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
  );
}

class TasksApp extends StatelessWidget {
  const TasksApp({super.key});
  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return MaterialApp(
      title: 'Tasks',
      debugShowCheckedModeBanner: false,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 350),
        child: app.loading
            ? const Scaffold(key: ValueKey('splash'), body: Center(child: CircularProgressIndicator()))
            : app.api == null
                ? const LoginScreen(key: ValueKey('login'))
                : const Shell(key: ValueKey('shell')),
      ),
    );
  }
}

/// Bottom tabs. Each tab has its own navigation stack, so the tab bar stays
/// visible on detail pages and every tab remembers where you were.
class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;
  final _keys = List.generate(5, (_) => GlobalKey<NavigatorState>());

  static const _destinations = [
    NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home_rounded), label: 'Home'),
    NavigationDestination(icon: Icon(Icons.checklist_rounded), selectedIcon: Icon(Icons.checklist_rounded), label: 'Tasks'),
    NavigationDestination(icon: Icon(Icons.bolt_outlined), selectedIcon: Icon(Icons.bolt), label: 'Capture'),
    NavigationDestination(icon: Icon(Icons.event_outlined), selectedIcon: Icon(Icons.event), label: 'Events'),
    NavigationDestination(icon: Icon(Icons.layers_outlined), selectedIcon: Icon(Icons.layers), label: 'Workspaces'),
  ];

  Widget _root(int i) => switch (i) {
        0 => const DashboardScreen(),
        1 => const TasksScreen(),
        2 => const CaptureScreen(),
        3 => const EventsScreen(),
        _ => const WorkspacesScreen(),
      };

  void _select(int i) {
    HapticFeedback.selectionClick();
    if (i == _index) {
      // Tapping the current tab returns to its first page.
      _keys[i].currentState?.popUntil((r) => r.isFirst);
    } else {
      setState(() => _index = i);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (app.requestedTab >= 0) {
      final t = app.requestedTab;
      app.requestedTab = -1;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _keys[t].currentState?.popUntil((r) => r.isFirst);
        setState(() => _index = t);
      });
    }
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        final nav = _keys[_index].currentState;
        if (nav != null && nav.canPop()) {
          nav.pop();
        } else if (_index != 0) {
          setState(() => _index = 0);
        } else {
          SystemNavigator.pop();
        }
      },
      child: Scaffold(
        body: Stack(children: [
          for (var i = 0; i < 5; i++)
            _FadeThroughTab(
              active: i == _index,
              child: Navigator(
                key: _keys[i],
                onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => _root(i)),
              ),
            ),
        ]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _select,
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          destinations: _destinations,
        ),
      ),
    );
  }
}

/// Keeps a tab alive but invisible when not selected; fades and lifts it in when selected.
class _FadeThroughTab extends StatelessWidget {
  const _FadeThroughTab({required this.active, required this.child});
  final bool active;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      ignoring: !active,
      child: TickerMode(
        enabled: active,
        child: AnimatedOpacity(
          opacity: active ? 1 : 0,
          duration: Duration(milliseconds: active ? 220 : 120),
          curve: Curves.easeOut,
          child: AnimatedSlide(
            offset: active ? Offset.zero : const Offset(0, .015),
            duration: const Duration(milliseconds: 260),
            curve: Curves.easeOutCubic,
            child: Offstage(offstage: false, child: child),
          ),
        ),
      ),
    );
  }
}
