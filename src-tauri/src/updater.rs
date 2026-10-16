//! In-app updater (mirrors the cisco-acl-helper pattern, adapted to Tauri).
//!
//! The frontend checks GitHub Releases; the portable ZIP is downloaded by
//! Rust (`update_download_asset`) — GitHub release assets send no CORS
//! headers, so a webview fetch always fails with "Failed to fetch".
//! Progress is emitted as `updateDownloadProgress`, cancel is a flag set by
//! `update_discard`. `apply_update` writes a hidden `.bat` that waits for our
//! PID (with a start-time guard against PID reuse), extracts the ZIP,
//! robocopies it over the install dir (never touching preserved user files),
//! restarts the exe and cleans up — then the app exits so its own files can
//! be replaced.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, State};

/// Files in the install dir that must never be overwritten.
/// (User data lives in Documents\speak-epub and AppData, not the install dir,
/// so the list is empty — kept per the cisco-acl-helper pattern.)
const PRESERVED_FILES: &[&str] = &[];

#[derive(Default)]
pub struct UpdateState {
    pub path: Mutex<Option<PathBuf>>,
    pub cancel: AtomicBool,
}

fn sanitize_tag(tag: &str) -> String {
    tag.chars()
        .map(|c| if c.is_ascii_alphanumeric() || "._-".contains(c) { c } else { '_' })
        .take(64)
        .collect()
}

/// Downloads the portable ZIP asset into a Rust-managed temp file.
/// Emits `updateDownloadProgress` ({ received, total }); returns bytes written.
/// The webview never supplies filesystem paths and only release URLs are
/// accepted. Cancelled (or failed) downloads leave nothing behind.
#[tauri::command]
pub async fn update_download_asset(
    app: AppHandle,
    url: String,
    tag: String,
    state: State<'_, UpdateState>,
) -> Result<u64, String> {
    if !url.starts_with("https://github.com/") || !url.contains("/releases/download/") {
        return Err("refusing to download a non-release URL".into());
    }
    let safe = sanitize_tag(&tag);
    let path = std::env::temp_dir().join(format!(
        "speak_epub_update_{}_{}.zip",
        safe,
        std::process::id()
    ));
    state.cancel.store(false, Ordering::SeqCst);
    *state.path.lock().map_err(|_| "update state poisoned")? = Some(path.clone());

    let fail = |state: &UpdateState, path: &Path, msg: String| -> String {
        let _ = std::fs::remove_file(path);
        if let Ok(mut guard) = state.path.lock() {
            *guard = None;
        }
        msg
    };

    let client = reqwest::Client::builder()
        .user_agent("speak-epub-updater")
        .connect_timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| fail(&state, &path, e.to_string()))?;
    let mut res = client
        .get(&url)
        .send()
        .await
        .map_err(|e| fail(&state, &path, e.to_string()))?;
    if !res.status().is_success() {
        let code = res.status().as_u16();
        return Err(fail(&state, &path, format!("HTTP {code}")));
    }
    let total = res.content_length().unwrap_or(0);
    let mut file = std::fs::File::create(&path).map_err(|e| fail(&state, &path, e.to_string()))?;
    let mut received: u64 = 0;
    let mut last_emit: u64 = 0;
    loop {
        if state.cancel.load(Ordering::SeqCst) {
            drop(file);
            return Err(fail(&state, &path, "cancelled".into()));
        }
        let chunk = match res.chunk().await {
            Ok(Some(c)) => c,
            Ok(None) => break,
            Err(e) => {
                drop(file);
                return Err(fail(&state, &path, e.to_string()));
            }
        };
        if let Err(e) = file.write_all(&chunk) {
            drop(file);
            return Err(fail(&state, &path, e.to_string()));
        }
        received += chunk.len() as u64;
        if received - last_emit >= 256 * 1024 {
            last_emit = received;
            let _ = app.emit(
                "updateDownloadProgress",
                serde_json::json!({ "received": received, "total": total }),
            );
        }
    }
    if let Err(e) = file.flush() {
        drop(file);
        return Err(fail(&state, &path, e.to_string()));
    }
    let _ = app.emit(
        "updateDownloadProgress",
        serde_json::json!({ "received": received, "total": if total > 0 { total } else { received } }),
    );
    Ok(received)
}

/// Drops the pending download (user cancelled or download failed) and asks
/// any in-flight Rust download to stop.
#[tauri::command]
pub fn update_discard(state: State<'_, UpdateState>) -> Result<(), String> {
    state.cancel.store(true, Ordering::SeqCst);
    if let Some(path) = state.path.lock().map_err(|_| "update state poisoned")?.take() {
        let _ = std::fs::remove_file(path);
    }
    Ok(())
}

/// Spawns the apply script and schedules an app exit so the exe can be replaced.
#[tauri::command]
pub fn apply_update(app: AppHandle, tag: String, state: State<'_, UpdateState>) -> Result<(), String> {
    let zip = state
        .path
        .lock()
        .map_err(|_| "update state poisoned")?
        .clone()
        .ok_or("no downloaded update")?;
    if !zip.is_file() {
        return Err("downloaded update missing".into());
    }
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let install_dir = exe.parent().ok_or("cannot resolve install dir")?.to_path_buf();
    let exe_name = exe
        .file_name()
        .ok_or("cannot resolve exe name")?
        .to_string_lossy()
        .into_owned();
    let pid = std::process::id();
    let pid_start = own_pid_start_unix();
    let stage = std::env::temp_dir().join(format!("speak_epub_update_stage_{pid}"));
    let bat_path = std::env::temp_dir().join(format!("speak_epub_apply_{pid}.bat"));
    let log_path = std::env::temp_dir().join(format!("speak_epub_update_{pid}.log"));
    let bat = build_apply_bat(&zip, &install_dir, &exe_name, pid, pid_start, &stage, &log_path, &tag);
    std::fs::write(&bat_path, bat).map_err(|e| e.to_string())?;
    launch_hidden_detached(&bat_path)?;
    let app2 = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(400));
        app2.exit(0);
    });
    Ok(())
}

/// Unix seconds of this process start (0 when unavailable) — PID-reuse guard.
#[cfg(target_os = "windows")]
fn own_pid_start_unix() -> u64 {
    #[repr(C)]
    struct FileTime {
        low: u32,
        high: u32,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut core::ffi::c_void;
        fn GetProcessTimes(
            process: *mut core::ffi::c_void,
            creation: *mut FileTime,
            exit: *mut FileTime,
            kernel: *mut FileTime,
            user: *mut FileTime,
        ) -> i32;
    }
    unsafe {
        let mut creation = FileTime { low: 0, high: 0 };
        let mut exit = FileTime { low: 0, high: 0 };
        let mut kernel = FileTime { low: 0, high: 0 };
        let mut user = FileTime { low: 0, high: 0 };
        if GetProcessTimes(
            GetCurrentProcess(),
            &mut creation,
            &mut exit,
            &mut kernel,
            &mut user,
        ) == 0
        {
            return 0;
        }
        let ft = ((creation.high as u64) << 32) | creation.low as u64;
        (ft / 10_000_000u64).saturating_sub(11_644_473_600)
    }
}

#[cfg(not(target_os = "windows"))]
fn own_pid_start_unix() -> u64 {
    0
}

#[cfg(target_os = "windows")]
fn launch_hidden_detached(bat: &Path) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const DETACHED_PROCESS: u32 = 0x0000_0008;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
    std::process::Command::new("cmd")
        .arg("/c")
        .arg(bat)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(not(target_os = "windows"))]
fn launch_hidden_detached(_bat: &Path) -> Result<(), String> {
    Err("automatic updates are supported on Windows only".into())
}

/// Hidden apply script: wait for PID -> extract -> robocopy -> restart -> cleanup.
fn build_apply_bat(
    zip: &Path,
    dst: &Path,
    exe_name: &str,
    pid: u32,
    pid_start: u64,
    stage: &Path,
    log: &Path,
    tag: &str,
) -> String {
    // If the PID holder started at a different second than us, the PID was
    // reused after our exit -> do NOT wait (install immediately).
    let wait_ps = format!(
        "\"$t = {pid_start}; try {{ $p = Get-Process -Id {pid} -ErrorAction Stop; \
if ($t -ne 0) {{ $e = [datetime]::new(1970,1,1,0,0,0,[DateTimeKind]::Utc); \
$s = [int][double]($p.StartTime.ToUniversalTime().Subtract($e).TotalSeconds); \
if ($s -ne $t) {{ exit 0 }} }}; $p.WaitForExit() }} catch {{ }}\""
    );
    let xf = if PRESERVED_FILES.is_empty() {
        String::new()
    } else {
        format!(" /XF {}", PRESERVED_FILES.join(" "))
    };
    // placeholders keep PowerShell's braces away from format! escaping
    let template = "@echo off\r\n\
setlocal\r\n\
set \"ZIP=@@ZIP@@\"\r\n\
set \"DST=@@DST@@\"\r\n\
set \"STAGE=@@STAGE@@\"\r\n\
set \"PIDW=@@PID@@\"\r\n\
set \"PIDSTART=@@PIDSTART@@\"\r\n\
set \"EXE=@@EXE@@\"\r\n\
set \"LOG=@@LOG@@\"\r\n\
echo [%date% %time%] updating to @@TAG@@ (waiting for PID %PIDW% start %PIDSTART%) > \"%LOG%\"\r\n\
powershell -NoProfile -ExecutionPolicy Bypass -Command @@WAITPS@@ >> \"%LOG%\" 2>&1\r\n\
echo [%date% %time%] process gone, extracting >> \"%LOG%\"\r\n\
if exist \"%STAGE%\" rmdir /s /q \"%STAGE%\"\r\n\
mkdir \"%STAGE%\"\r\n\
powershell -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%STAGE%' -Force\" >> \"%LOG%\" 2>&1\r\n\
if errorlevel 1 (\r\n\
  echo Update failed: cannot extract zip. See \"%LOG%\". >> \"%LOG%\"\r\n\
  start \"\" /wait cmd /c \"echo Update failed while extracting. See \"%LOG%\" & pause\"\r\n\
  exit /b 1\r\n\
)\r\n\
set \"SRC=%STAGE%\"\r\n\
if exist \"%STAGE%\\@@PRODUCT@@\\%EXE%\" set \"SRC=%STAGE%\\@@PRODUCT@@\"\r\n\
robocopy \"%SRC%\" \"%DST%\" /E /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS@@XF@@ >> \"%LOG%\" 2>&1\r\n\
ver>nul\r\n\
echo [%date% %time%] copy done, restarting >> \"%LOG%\"\r\n\
start \"\" \"%DST%\\%EXE%\"\r\n\
del \"%ZIP%\" >nul 2>&1\r\n\
rmdir /s /q \"%STAGE%\" >nul 2>&1\r\n\
(goto) 2>nul & del \"%~f0\" >nul 2>&1\r\n";
    template
        .replace("@@ZIP@@", &zip.to_string_lossy())
        .replace("@@DST@@", &dst.to_string_lossy())
        .replace("@@STAGE@@", &stage.to_string_lossy())
        .replace("@@PID@@", &pid.to_string())
        .replace("@@PIDSTART@@", &pid_start.to_string())
        .replace("@@EXE@@", exe_name)
        .replace("@@LOG@@", &log.to_string_lossy())
        .replace("@@WAITPS@@", &wait_ps)
        .replace("@@TAG@@", &sanitize_tag(tag))
        .replace("@@PRODUCT@@", "Speak-EPUB")
        .replace("@@XF@@", &xf)
}
