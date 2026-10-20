//! The Python runtime tier: download once, cache, reuse across updates.
//!
//! The release is split in two tiers:
//!
//! - **app tier** — the executable + our `core`/`adapters` code (bundled).
//! - **runtime tier** — the embedded CPython interpreter + dependencies
//!   (published as a release asset, downloaded once, cached in the user
//!   profile).
//!
//! The cache key comes from `runtime.json` (interpreter build + dependency
//! digest), so an app update re-downloads the runtime only when the
//! dependencies actually changed. Everything else updates with the app tier.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use serde::Deserialize;
use tauri::{AppHandle, Emitter};
use tokio::sync::Mutex;

/// The GUI fires several RPCs at once on startup — without this lock two
/// preparations would use the same staging directory and delete each
/// other's download in flight.
static PREPARE_LOCK: Mutex<()> = Mutex::const_new(());

/// Counter that keeps every attempt's staging directory unique.
static ATTEMPT: AtomicU64 = AtomicU64::new(0);

/// Descriptor written by the release build next to the app tier.
#[derive(Debug, Clone, Deserialize)]
pub struct RuntimeDescriptor {
    /// Descriptor format version (1 = runtime tier only, 2 = + local engine).
    pub format: u32,
    /// Cache key of the runtime.
    pub hash: String,
    /// Exact interpreter build, e.g. "3.11.17+20261013".
    pub python_version: String,
    /// Release asset carrying the runtime.
    pub asset: String,
    /// Base URL of the release the assets live in (the release build writes
    /// the concrete URL, so the app does not have to know its own version).
    pub release_url: String,
}

impl RuntimeDescriptor {
    fn asset_url(&self) -> String {
        format!(
            "{}/{}",
            self.release_url.trim_end_matches('/'),
            self.asset
        )
    }
}

/// Read `runtime.json` from the app resources (None in a dev checkout).
pub fn load_descriptor(resources_dir: &Path) -> Option<RuntimeDescriptor> {
    let path = resources_dir.join("sidecar-runtime").join("runtime.json");
    let raw = std::fs::read_to_string(path).ok()?;
    let parsed: RuntimeDescriptor = serde_json::from_str(&raw).ok()?;
        if parsed.format != 1 && parsed.format != 2 {
            eprintln!(
                "runtime descriptor format {} is not supported by this build",
                parsed.format
            );
            return None;
        }
    if parsed.hash.is_empty() || parsed.asset.is_empty() {
        return None;
    }
    Some(parsed)
}

/// Append a line to the app log (a GUI app has no console, so the file is
/// the only place where a support question can be answered).
pub fn log_line(message: &str) {
    use std::io::Write;
    let dir = cache_root()
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(cache_root);
    if std::fs::create_dir_all(&dir).is_err() {
        return;
    }
    let path = dir.join("app.log");
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
    {
        let _ = writeln!(file, "{}", message);
    }
}

/// Where the runtime cache lives (per user, never inside the install dir).
pub fn cache_root() -> PathBuf {    #[cfg(target_os = "windows")]
    {
        let base = std::env::var("LOCALAPPDATA")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                std::env::var("USERPROFILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| std::env::temp_dir())
            });
        base.join("speak-epub").join("runtime")
    }
    #[cfg(target_os = "macos")]
    {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| std::env::temp_dir())
            .join("Library")
            .join("Application Support")
            .join("speak-epub")
            .join("runtime")
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| std::env::temp_dir())
            .join(".local")
            .join("share")
            .join("speak-epub")
            .join("runtime")
    }
}

/// Interpreter path inside a cached runtime directory.
fn interpreter_in(runtime_dir: &Path) -> PathBuf {
    runtime_dir.join("python").join("python.exe")
}

/// Is a usable interpreter cached for this descriptor?
pub fn is_cached(descriptor: &RuntimeDescriptor) -> Option<PathBuf> {
    let dir = cache_root().join(&descriptor.hash);
    let python = interpreter_in(&dir);
    if python.is_file() {
        Some(python)
    } else {
        None
    }
}

/// After a failed attempt the runtime must not be downloaded again on every
/// RPC (the sidecar is spawned per call — that would re-download 100 MB per
/// click). The cooldown is a marker file next to the cache.
fn failure_marker(descriptor: &RuntimeDescriptor) -> PathBuf {
    cache_root().join(format!(".{}.failed", descriptor.hash))
}

fn download_cooldown_active(descriptor: &RuntimeDescriptor) -> bool {
    let marker = failure_marker(descriptor);
    match std::fs::metadata(&marker) {
        Ok(meta) => {
            let age = meta
                .modified()
                .ok()
                .and_then(|t| t.elapsed().ok())
                .map(|d| d.as_secs())
                .unwrap_or(u64::MAX);
            age < 300 // 5 minutes
        }
        Err(_) => false,
    }
}

fn mark_failed(descriptor: &RuntimeDescriptor) {
    let marker = failure_marker(descriptor);
    if let Some(parent) = marker.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&marker, b"failed");
}

/// Extract a zip with the tools every target has (no new Rust dependency).
fn extract_zip(zip: &Path, dest: &Path) -> Result<(), String> {
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        // .output() (pipes) instead of .status(): a GUI app has no console,
        // so the inherited stdout handle is invalid and the child fails
        // while writing to it.
        let out = std::process::Command::new("powershell")
            .args([
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                &format!(
                    "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '{}' -DestinationPath '{}' -Force",
                    zip.display(),
                    dest.display()
                ),
            ])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .output()
            .map_err(|e| format!("cannot run powershell: {e}"))?;
        if !out.status.success() {
            let err = String::from_utf8_lossy(&out.stderr);
            let err = err.trim();
            return Err(format!(
                "runtime archive extraction failed{}",
                if err.is_empty() {
                    String::new()
                } else {
                    format!(": {err}")
                }
            ));
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        let out = std::process::Command::new("unzip")
            .args(["-q", "-o", &zip.display().to_string(), "-d", &dest.display().to_string()])
            .output()
            .map_err(|e| format!("cannot run unzip: {e}"))?;
        if !out.status.success() {
            let err = String::from_utf8_lossy(&out.stderr);
            return Err(format!(
                "runtime archive extraction failed: {}",
                err.trim()
            ));
        }
    }
    Ok(())
}

/// Download the runtime asset and publish it into the cache.
///
/// Returns the interpreter path. The download is idempotent: a cached
/// runtime short-circuits, and a partially extracted runtime is discarded.
pub async fn ensure_runtime(
    app: &AppHandle,
    descriptor: &RuntimeDescriptor,
) -> Result<PathBuf, String> {
    if let Some(python) = is_cached(descriptor) {
        return Ok(python);
    }
    // A debug build must never reach for the network (dev checkout).
    if cfg!(debug_assertions) {
        return Err("debug build: runtime download disabled".into());
    }
    // A recent failure must not turn every RPC into a 100 MB download.
    if download_cooldown_active(descriptor) {
        return Err("the runtime download failed recently — retrying in a few minutes".into());
    }
    // Only one preparation at a time (see PREPARE_LOCK).
    let _guard = PREPARE_LOCK.lock().await;
    // ... and re-check: another caller may have finished while we waited.
    if let Some(python) = is_cached(descriptor) {
        return Ok(python);
    }

    let url = descriptor.asset_url();
    if !url.starts_with("https://github.com/") || !url.contains("/releases/download/") {
        return Err("refusing to download a non-release URL".into());
    }
    eprintln!(
        "downloading the Python runtime tier (python {}, cache key {})...",
        descriptor.python_version,
        descriptor.hash
    );
    log_line(&format!(
        "runtime download start: python={} hash={} url={}",
        descriptor.python_version, descriptor.hash, url
    ));

    let root = cache_root();
    std::fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    let attempt = ATTEMPT.fetch_add(1, Ordering::SeqCst);
    let staging = root.join(format!(
        ".staging-{}-{}-{}",
        descriptor.hash,
        std::process::id(),
        attempt
    ));
    let _ = std::fs::remove_dir_all(&staging);
    std::fs::create_dir_all(&staging).map_err(|e| e.to_string())?;
    let zip_path = staging.join("runtime.zip");

    let result = (async {
        let client = reqwest::Client::builder()
            .user_agent("speak-epub-runtime")
            .connect_timeout(Duration::from_secs(30))
            .build()
            .map_err(|e| e.to_string())?;
        let mut res = client
            .get(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            let code = res.status().as_u16();
            log_line(&format!("runtime download failed: HTTP {code} ({url})"));
            return Err(format!("HTTP {code}"));
        }
        let total = res.content_length().unwrap_or(0);
        let mut file = std::fs::File::create(&zip_path).map_err(|e| e.to_string())?;
        let mut received: u64 = 0;
        let mut last_emit: u64 = 0;
        while let Some(chunk) = res.chunk().await.map_err(|e| e.to_string())? {
            file.write_all(&chunk).map_err(|e| e.to_string())?;
            received += chunk.len() as u64;
            if received - last_emit >= 1024 * 1024 {
                last_emit = received;
                let _ = app.emit(
                    "runtimeDownloadProgress",
                    serde_json::json!({ "received": received, "total": total }),
                );
            }
        }
        file.flush().map_err(|e| e.to_string())?;
        drop(file);
        let _ = app.emit(
            "runtimeDownloadProgress",
            serde_json::json!({ "received": received, "total": if total > 0 { total } else { received } }),
        );

        extract_zip(&zip_path, &staging)?;
        let staged_python = interpreter_in(&staging);
        if !staged_python.is_file() {
            return Err("the runtime archive has no python interpreter".into());
        }
        // Publish atomically: the cache dir appears only when it is complete.
        let target = root.join(&descriptor.hash);
        let _ = std::fs::remove_dir_all(&target);
        std::fs::rename(&staging, &target).map_err(|e| e.to_string())?;
        let interpreter = interpreter_in(&target);
        // a previous failure must not block the next attempt
        let _ = std::fs::remove_file(failure_marker(descriptor));
        let _ = app.emit("runtimeReady", serde_json::json!({ "hash": descriptor.hash }));
        log_line(&format!("runtime ready: {}", interpreter.display()));
        Ok(interpreter)
    })
    .await;

    if result.is_err() {
        let _ = std::fs::remove_dir_all(&staging);
        mark_failed(descriptor);
        log_line("runtime download failed (see the error above)");
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn descriptor() -> RuntimeDescriptor {
        RuntimeDescriptor {
            format: 2,
            hash: "abc123".into(),
            python_version: "3.11.17+20261013".into(),
            asset: "speak-epub-runtime-abc123.zip".into(),
            release_url: "https://github.com/owner/repo/releases/download/v0.3.10".into(),
        }
    }

    #[test]
    fn asset_url_fills_the_template() {
        let d = RuntimeDescriptor {
            format: 2,
            hash: "abc123".into(),
            python_version: "3.11.17+20261013".into(),
            asset: "speak-epub-runtime-abc123.zip".into(),
            release_url: "https://github.com/owner/repo/releases/download/v0.3.10".into(),
        };
        assert_eq!(
            d.asset_url(),
            "https://github.com/owner/repo/releases/download/v0.3.10/speak-epub-runtime-abc123.zip"
        );
    }

    #[test]
    fn cache_root_ends_with_the_runtime_folder() {
        let root = cache_root();
        assert!(root.ends_with("runtime"), "{root:?}");
        assert!(root.to_string_lossy().contains("speak-epub"));
    }

    #[test]
    fn interpreter_lives_under_python_in_the_cache_dir() {
        let dir = PathBuf::from("C:/cache/abc123");
        assert!(interpreter_in(&dir).ends_with("python/python.exe"));
    }

    #[test]
    fn descriptor_is_parsed_and_unknown_formats_are_refused() {
        let dir = std::env::temp_dir().join("speak-epub-runtime-test");
        let runtime_dir = dir.join("sidecar-runtime");
        std::fs::create_dir_all(&runtime_dir).unwrap();
        let file = runtime_dir.join("runtime.json");
        std::fs::write(
            &file,
            r#"{"format":2,"hash":"h1","python_version":"3.11","requirements_sha256":"x","asset":"a.zip","release_url":"https://github.com/o/r/releases/download/v1.2.3","local_hash":"l1","local_asset":"l.zip"}"#,
        )
        .unwrap();
        let parsed = load_descriptor(&dir).expect("descriptor must parse");
        assert_eq!(parsed.hash, "h1");
        assert_eq!(parsed.asset, "a.zip");
        assert_eq!(
            parsed.asset_url(),
            "https://github.com/o/r/releases/download/v1.2.3/a.zip"
        );

        std::fs::write(&file, r#"{"format":99,"hash":"h","asset":"a.zip","release_url":"x"}"#).unwrap();
        assert!(load_descriptor(&dir).is_none(), "unknown format must be refused");

        // a missing descriptor (dev checkout) is not an error
        std::fs::remove_dir_all(&dir).unwrap();
        assert!(load_descriptor(&dir).is_none());
    }
}
