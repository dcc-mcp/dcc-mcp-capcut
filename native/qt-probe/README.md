# Optional native Qt metadata probe

This experimental C++ probe implements a real Qt host consumer for
`host.describe` and `qt.inspect`. It is independent of the existing panel broker.
It does **not** implement CapCut editing, TTS, export, arbitrary invocation, input
injection, or property value reads. Object IDs are snapshot-local indices.

## Loading and portability

Two loaders share the same probe: a generic Qt plugin and `qttestability`, which
exports Qt's `qt_testability_init` startup hook. The latter avoids the generic
plugin meta-object dependency stripped from the tested CapCut Qt6Gui build.
For testability, make the staged `lib/qttestability` library discoverable to that
host and launch with `-testability --dcc-capcut-probe-config <absolute-json-path>`.
The configuration has `token`, `exe_sha256`, and `endpoint` string fields, with
the same meanings as the environment variables below. Keep this file private.
Never replace an existing testability library. A vendor executable directory is
one Windows search location; deployment there must be explicit and reversible.
Loading the probe requires a new host process and does not attach to a running one.

Qt's documented generic plugin loader accepts `QT_QPA_GENERIC_PLUGINS` and
`QT_PLUGIN_PATH`. See [Qt 6.2.2 application initialization](https://github.com/qt/qtbase/blob/v6.2.2/src/gui/kernel/qguiapplication.cpp)
and [QGenericPlugin](https://doc.qt.io/qt-6/qgenericplugin.html).
Use a separate process launch environment, never machine-wide environment changes.
Do not overwrite CapCut's Qt DLLs or copy a second Qt runtime into its directory.

Build separately for each OS, CPU architecture and matching Qt SDK. The runtime
requires the exact compiled Qt version and an explicit executable SHA-256 before
listening. Matching version strings are necessary but not proof of vendor ABI
compatibility. A host can disable plugin loading; signed macOS applications can
also reject third-party libraries. No injection fallback is included.

Windows, macOS and Linux share the C++ implementation and Python protocol client.
The CI matrix exercises a disposable Qt fixture on each OS. Linux fixture support
does not imply a Linux release of CapCut exists. CapCut host acceptance is a
separate test, not inferred from fixture success.

## Build

```text
cmake -S native/qt-probe -B build/qt-probe -DCMAKE_PREFIX_PATH=<matching-Qt-SDK>
cmake --build build/qt-probe --config Release
cmake --install build/qt-probe --config Release --prefix build/qt-probe/stage
```

Set these variables only for the intended host launch:

* `QT_PLUGIN_PATH`: absolute `stage` directory (contains `generic/`).
* `QT_QPA_GENERIC_PLUGINS`: `dcc-capcut-probe`.
* `DCC_CAPCUT_PROBE_TOKEN`: random secret, at least 32 bytes.
* `DCC_CAPCUT_PROBE_EXE_SHA256`: lowercase SHA-256 of the intended executable.
* `DCC_CAPCUT_PROBE_ENDPOINT`: new task-local endpoint JSON file.

The endpoint contains port, PID, version and executable hash, never the token.
Use the same probe variables and `DCC_MCP_CAPCUT_PID` for the MCP adapter.
The `capcut-native` skill exposes `describe_qt_host` and `inspect_qt_objects`.
They fail when unconfigured and never claim an active editing project.

Protocol: one bounded UTF-8 JSON line per TCP connection on IPv4 loopback.
Requests carry protocol version 1, PID, token and operation. Responses repeat host
identity. The plugin processes requests on the Qt application thread, bounds tree
depth/node count, and returns metadata only. Token authorization does not establish
security against another process already able to read this user's environment.
Delete stale endpoint files after the host exits; clients reject a mismatched PID.

## Validation and distribution

`tools/test_qt_probe_native.py <fixture> <stage>` validates loading, metadata,
limits, authentication and unsupported operations using the real compiled plugin.
The matching Qt runtime must be discoverable by the fixture, e.g. its `bin` on
Windows PATH. The SDK is a build/test dependency, not a Python wheel dependency.

Keep native binaries in an optional versioned adapter bundle, outside the shared
Python runtime. Before publishing such a bundle, record its SHA-256, architecture,
compiler ABI, Qt version, probe protocol and exact host-build acceptance evidence.
This change supplies source and build tests, not a production native release.

## Windows CapCut acceptance

CapCut 9.4.0.4015 / Qt 6.2.2 loaded the testability library through a DCC-CUA
structured launch request. A bound live request returned 1,094 objects from the
home window, including application ViewModels, with no tree truncation.
The generic loader is not compatible with this vendor Qt6Gui: it lacks the
`QGenericPlugin::staticMetaObject` import required by the standard plugin.
This is metadata acceptance only; project state, editing, TTS and export are not
validated by that result. macOS and Linux have fixture coverage only.
