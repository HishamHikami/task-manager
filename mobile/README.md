# Task Manager — Android app

A native Flutter app for the Task Manager server in this repository. It talks to
your own server's `/api/v1/` (token login, nothing else is stored on the phone).

## Features
- Bottom tabs: Home · Tasks · Capture · Events · Workspaces (each tab keeps its place)
- Task page with hand-off, add update, move stage, follow-up; AI summarize
- Capture as a chat: paste or **Share → Tasks** from WhatsApp/Outlook/Gmail
- Events with one-tap status; departments, people, call/email/copy
- Smooth page and tab transitions, haptics, pull-to-refresh, dark mode

## Build

Requires Flutter (stable) and the Android SDK.

```bash
cd mobile
flutter pub get
flutter build apk --release      # build/app/outputs/flutter-apk/app-release.apk
```

### Signing
Release builds use `android/key.properties` if present (never commit it or the key):

```
storePassword=…
keyPassword=…
keyAlias=tasks
storeFile=/path/to/your-release-key.jks
```

Without it, the build is signed with the debug key. Android only installs an update
over an existing install when it is signed with the **same** key — keep yours safe.

## First run
Enter your server address (e.g. `tasks.example.com`), username and password.
The app stores a revocable token in Android's encrypted storage; log out in
Settings to revoke it.
