//! CARA desktop wrapper (lib entry — re-exported by `main.rs`).
//!
//! The whole app fits in this file because Tauri does the heavy lifting:
//! window, IPC, tray, packaging all come from the framework. We add a
//! tray menu with `Apri CARA` / `Esci`, restore the last window position
//! across launches, and that's it.

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            // ── System tray ─────────────────────────────────────────
            // Single icon in the system tray. Left click toggles the
            // main window; right click opens a 2-item menu (open/quit).
            let open_item = MenuItemBuilder::with_id("open", "Apri CARA").build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "Esci").build(app)?;
            let menu = MenuBuilder::new(app)
                .items(&[&open_item, &quit_item])
                .build()?;

            TrayIconBuilder::with_id("cara-tray")
                .tooltip("CARA")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => show_main(app),
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Left click → toggle. Right click is handled by the menu.
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        toggle_main(tray.app_handle());
                    }
                })
                .build(app)?;

            // ── Window close = hide-to-tray (not quit) ─────────────
            // Standard desktop affordance for assistant-style apps:
            // the user sees the [X] as "minimise to tray", quitting
            // only happens through the explicit tray menu. Prevents
            // accidentally losing the app behind a closed window.
            if let Some(win) = app.get_webview_window("main") {
                let handle = app.handle().clone();
                win.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        if let Some(w) = handle.get_webview_window("main") {
                            let _ = w.hide();
                            api.prevent_close();
                        }
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running CARA desktop");
}

fn show_main<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

fn toggle_main<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(win) = app.get_webview_window("main") {
        match win.is_visible() {
            Ok(true) => {
                let _ = win.hide();
            }
            _ => show_main(app),
        }
    }
}
