# Experimental — Android client

**Status: not part of the build. Do not dispatch agents for this.**

The Android client is kept here for reference only. It was scaffolded during v1
(Kotlin + Gradle, F-Droid compatible, four screens, adaptive layouts) and is
preserved in the v1 archive bundle.

The Manager should **not** schedule work for it, test it, or reference it in any
phase. If a future version wants a mobile client, it becomes its own phase with
its own doc.

---

## Why it is not in the build

The APK cannot be built on this host, and the reason is environmental, not a
defect in the scaffold:

- The Android SDK ships its native tools (`aapt2`, `adb`) as **x86_64** binaries.
- This host is **aarch64**. Those tools run only under `qemu-user` emulation.
- A one-shot `aapt2` invocation does work that way — a minimal APK was built
  successfully.
- But **Gradle's Android plugin drives `aapt2` in a long-running daemon mode that
  does not survive emulation.** A full `assembleDebug` therefore never completes.

Do not "fix" this by patching the SDK's `aapt2` with a qemu wrapper. It gets you
as far as resource compilation, it leaves the SDK modified, and it does not make
the build succeed. That workaround was tried and reverted.

---

## If you want the APK

Build it on **x86_64** or in **CI**, where `aapt2` runs natively. A GitHub Actions
workflow for this was written in v1 and is preserved in the archive bundle.

---

## What was verified, honestly

**Verified:** the scaffold's structure and files; Gradle runs; JDK present; SDK
installed; `aapt2` executes under qemu; a minimal hand-built APK was produced.

**Not verified:** that the scaffold compiles end to end — no Gradle-built APK was
ever produced. No runtime testing on a device or emulator. No F-Droid submission.

The scaffold is a reasonable starting point, not a proven build.
