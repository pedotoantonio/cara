// CARA desktop — Tauri 2 wrapper.
//
// Strategy: a slim native shell (~8 MB on disk, ~50 MB RAM) that loads
// the home backend in a system webview. Implementing the UI natively
// in Rust/C++ would mean rewriting the React PWA — months of work for
// roughly the same end-user feel. The PWA is already PWA-installable
// from the browser; this exists to give a "real" Start-menu / .desktop
// entry without the awkward "install web app" affordance, and to keep
// a system tray icon so users can hide CARA without losing it.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

fn main() {
    cara_desktop_lib::run();
}
