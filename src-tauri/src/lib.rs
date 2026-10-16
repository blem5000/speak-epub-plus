use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tauri::{Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

mod updater;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RpcRequest {
    pub id: String,
    pub method: String,
    pub params: Option<serde_json::Value>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RpcResponse {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<RpcError>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RpcError {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retryable: Option<bool>,
}

/// Registry of live sidecar child processes so the UI can hard-stop a
/// long-running job (audio build / chapter fetch). Each RPC call spawns a
/// fresh interpreter (see `spawn_and_call`); killing the tree (`taskkill /T`)
/// also reaps ffmpeg children it spawned. Resume is safe because the Python
/// pipeline re-verifies existing artifacts on the next run.
#[derive(Default)]
pub struct SidecarJobs(pub std::sync::Mutex<Vec<(u32, String)>>);

/// Removes its pid from the registry on every exit path (Ok, Err, drop).
struct JobGuard<'a> {
    jobs: &'a SidecarJobs,
    pid: u32,
}

impl Drop for JobGuard<'_> {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.jobs.0.lock() {
            guard.retain(|(pid, _)| *pid != self.pid);
        }
    }
}

/// Methods long enough that a user-visible Stop must hard-kill the backend
/// process (short RPCs finish in well under a second and stay untouchable).
const CANCELABLE_METHODS: &[&str] = &[
    "buildAudio",
    "build_audio",
    "buildAudiobook",
    "fetchChapters",
    "buildEpub",
    "build_epub",
];

fn kill_process_tree(pid: u32) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let mut cmd = std::process::Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T", "/F"]);
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        let _ = cmd.stdout(Stdio::null()).stderr(Stdio::null()).status();
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = std::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// Hard-stop running sidecar jobs (GUI Stop buttons). `methods` narrows the
/// kill to specific RPC methods; omitted = all cancelable methods.
#[tauri::command]
async fn cancel_sidecar_job(
    jobs: tauri::State<'_, SidecarJobs>,
    methods: Option<Vec<String>>,
) -> Result<usize, String> {
    let targets: Vec<u32> = {
        let mut guard = jobs.0.lock().map_err(|e| e.to_string())?;
        let mut take = Vec::new();
        guard.retain(|(pid, method)| {
            let cancelable = CANCELABLE_METHODS.contains(&method.as_str());
            let selected = methods
                .as_ref()
                .map(|list| list.iter().any(|m| m == method))
                .unwrap_or(true);
            if cancelable && selected {
                take.push(*pid);
                false
            } else {
                true
            }
        });
        take
    };
    for pid in &targets {
        kill_process_tree(*pid);
    }
    Ok(targets.len())
}

#[tauri::command]
async fn python_sidecar_call(
    app: tauri::AppHandle,
    jobs: tauri::State<'_, SidecarJobs>,
    payload: RpcRequest,
) -> Result<RpcResponse, String> {
    // Resolve the Python backend: prefer the bundled runtime shipped with the
    // installer (<resource>/sidecar-runtime); fall back to the dev-checkout venv.
    let (venv_python, cwd) = resolve_sidecar_entry(&app);

    // Attempt to spawn sidecar as JSON-RPC over stdin/stdout
    // For spike we implement a minimal echo: if spawn fails, return error for JS fallback
    match spawn_and_call(&venv_python, cwd.as_deref(), &payload, &app, &jobs).await {
        Ok(resp) => {
            // Also emit via event bus for AD-6 compliance
            let _ = app.emit("python_sidecar_response", &resp);
            Ok(resp)
        }
        Err(e) => {
            // Log and keep app open — JS will fallback to http://localhost:17381
            eprintln!("sidecar failed: {} (venvPath={})", e, venv_python.display());
            Err(format!("sidecar failed: {} (venvPath={})", e, venv_python.display()))
        }
    }
}

#[tauri::command]
async fn emit_event(app: tauri::AppHandle, event: String, payload: serde_json::Value) -> Result<(), String> {
    let _ = app.emit(&event, payload);
    Ok(())
}

/// Resolve the Python backend program.
/// Returns the executable path plus, for the bundled runtime, the working
/// directory that exposes the `core`/`adapters` packages (so the inline
/// `from core.config import handle_rpc` sidecar code can import them).
fn resolve_sidecar_entry(app: &tauri::AppHandle) -> (PathBuf, Option<PathBuf>) {
    // 1) Bundled self-contained runtime (installed app / release build).
    if let Ok(res_dir) = app.path().resource_dir() {
        let python = res_dir.join("sidecar-runtime/python/python.exe");
        if python.is_file() {
            return (python, Some(res_dir.join("sidecar-runtime/code")));
        }
    }

    // 2) Dev checkout — resolve the repo venv no matter where the exe is
    //    launched from (repo root, src-tauri/target/release, ...).
    //    The venv ships speak-epub.pth, so `from core.config import ...`
    //    resolves from any cwd once the right interpreter is found.
    //    (Mirrors core/config.py:get_venv_python, made cwd-robust: a bare
    //    relative path fails with "file not found" → SIDECAR_FAILED when the
    //    exe is double-clicked outside the repo root.)
    #[cfg(target_os = "windows")]
    const DEV_VENV_REL: &str = "venv/Scripts/python.exe";
    #[cfg(not(target_os = "windows"))]
    const DEV_VENV_REL: &str = "venv/bin/python";
    let rel = PathBuf::from(DEV_VENV_REL);
    if rel.is_file() {
        return (rel, None);
    }
    if let Ok(exe) = std::env::current_exe() {
        for anc in exe.ancestors() {
            let cand = anc.join(&rel);
            if cand.is_file() {
                return (cand, None);
            }
        }
    }
    (rel, None)
}

async fn spawn_and_call(
    venv_python: &Path,
    cwd: Option<&Path>,
    req: &RpcRequest,
    app: &tauri::AppHandle,
    jobs: &SidecarJobs,
) -> Result<RpcResponse, String> {
    // H4: no in-process mock — even ping/hello spawn the real interpreter so
    // a green health-check proves the backend actually works.

    // Spawn the interpreter with event streaming.
    // Inline python reads one JSON line, calls handle_rpc with emit hook that prints {"event", "payload"} lines before final {"id", "result/error"}
    let mut cmd = tokio::process::Command::new(venv_python);
    cmd.arg("-c")
        .arg(
            r#"
import sys, json, importlib
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"id":"0","error":{"code":"EMPTY","message":"no input"}}))
        sys.exit(0)
    req = json.loads(line)
    def emit(event, payload):
        try:
            sys.stdout.write(json.dumps({"event": event, "payload": payload}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    try:
        from core.config import handle_rpc
        resp = handle_rpc(req, emit_fn=emit)
    except Exception as e:
        # fallback: try direct import via path adjustment
        import pathlib, sys
        p = pathlib.Path(__file__).resolve() if "__file__" in globals() else pathlib.Path(".")
        # fallback mock
        resp = {"id": req.get("id","0"), "error": {"code":"EXCEPTION","message": str(e)}}
    print(json.dumps(resp, ensure_ascii=False))
    sys.stdout.flush()
except Exception as e:
    try:
        print(json.dumps({"id": "0", "error":{"code":"EXCEPTION","message": str(e)}}))
    except Exception:
        pass
"#,
        )
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    // Windows consoles default to a legacy codepage (cp1252); force UTF-8 so
    // non-ASCII chapter text never dies with "'charmap' codec can't encode".
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    // Never flash a console window: the sidecar spawns on every Find/fetch/
    // EPUB/TTS call, and a popup per call is unacceptable in a GUI app.
    // (tokio's Command provides creation_flags inherently on Windows.)
    #[cfg(target_os = "windows")]
    {
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;

    // Track the pid so the UI can hard-stop long jobs (cancel_sidecar_job).
    // The guard unregisters on every exit path, including early `?` returns.
    let _job_guard = child.id().map(|pid| {
        if let Ok(mut guard) = jobs.0.lock() {
            guard.push((pid, req.method.clone()));
        }
        JobGuard { jobs, pid }
    });

    // H4: drain stderr so a chatty backend can never fill the pipe and deadlock.
    if let Some(stderr) = child.stderr.take() {
        tokio::spawn(async move {
            let mut err_reader = BufReader::new(stderr);
            let mut line = String::new();
            loop {
                line.clear();
                match err_reader.read_line(&mut line).await {
                    Ok(0) => break,
                    Ok(_) => {
                        let t = line.trim();
                        if !t.is_empty() {
                            let short: String = t.chars().take(500).collect();
                            eprintln!("sidecar stderr: {short}");
                        }
                    }
                    Err(_) => break,
                }
            }
        });
    }

    if let Some(mut stdin) = child.stdin.take() {
        let line = serde_json::to_string(req).map_err(|e| e.to_string())? + "\n";
        stdin.write_all(line.as_bytes()).await.map_err(|e| e.to_string())?;
        // drop stdin to signal EOF
    }

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut resp_opt: Option<RpcResponse> = None;
    // Stream events: python may emit {"event":"chapterStatus",...} etc before final response {"id":...}
    // Long silent stretches (multi-minute M4B re-encode) are kept alive by
    // heartbeat log lines from the backend; this timeout only catches truly
    // hung sidecars, so it is generous.
    let timeout_secs = 300;
    loop {
        let mut out = String::new();
        let read_fut = reader.read_line(&mut out);
        let n = match tokio::time::timeout(std::time::Duration::from_secs(timeout_secs), read_fut).await {
            Ok(inner) => inner.map_err(|e| e.to_string())?,
            Err(_) => {
                // H4: kill hung child explicitly instead of leaving it orphaned
                // (start_kill is sync across tokio 1.x; kill_on_drop reaps on drop).
                let _ = child.start_kill();
                return Err("sidecar timeout".to_string());
            }
        };
        if n == 0 {
            break;
        }
        let trimmed = out.trim();
        if trimmed.is_empty() {
            continue;
        }
        let val: serde_json::Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(_) => {
                // The Python pipeline also writes human-readable progress
                // prints to stdout (TTS/fetch logs). A non-JSON line must
                // never kill the call — forward truncated to stderr and keep streaming.
                let short: String = trimmed.chars().take(300).collect();
                eprintln!("sidecar noise ignored: {short}");
                continue;
            }
        };
        if val.get("event").is_some() {
            // forward event via app.emit
            if let Some(event) = val.get("event").and_then(|v| v.as_str()) {
                let payload = val.get("payload").cloned().unwrap_or(serde_json::Value::Null);
                let _ = app.emit(event, payload);
                // also emit specific typed events for frontend listeners
                // payload shapes already match ChapterStatusEvent etc (see sidecar.ts:129-141)
            }
            continue;
        }
        if val.get("id").is_some() {
            let resp: RpcResponse = serde_json::from_value(val).map_err(|e| e.to_string())?;
            // ensure child is reaped eventually but don't block event forwarding
            let _ = child.wait().await;
            resp_opt = Some(resp);
            break;
        }
        // unknown line, ignore
    }

    if let Some(resp) = resp_opt {
        Ok(resp)
    } else {
        let _ = child.start_kill();
        Err("empty response from sidecar".into())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(updater::UpdateState::default())
        .manage(SidecarJobs::default())
        .invoke_handler(tauri::generate_handler![
            python_sidecar_call,
            emit_event,
            cancel_sidecar_job,
            updater::update_download_path,
            updater::update_write_chunk,
            updater::update_discard,
            updater::apply_update
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
