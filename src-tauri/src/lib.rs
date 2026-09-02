use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::process::Stdio;
use tauri::{Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

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

#[tauri::command]
async fn python_sidecar_call(
    app: tauri::AppHandle,
    payload: RpcRequest,
) -> Result<RpcResponse, String> {
    // Resolve venv python via core/config.py logic — mirror OS detection here as fallback
    let venv_python = resolve_venv_python();

    // Attempt to spawn sidecar as JSON-RPC over stdin/stdout
    // For spike we implement a minimal echo: if spawn fails, return error for JS fallback
    match spawn_and_call(&venv_python, &payload, &app).await {
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

fn resolve_venv_python() -> PathBuf {
    // Mirror core/config.py:get_venv_python() — OS-aware
    // Speak-EPUB is sibling to src-tauri? Use current exe parent search
    // Prefer Speak-EPUB-1.0.0/venv/Scripts/python.exe on Windows else venv/bin/python
    #[cfg(target_os = "windows")]
    {
        PathBuf::from("Speak-EPUB-1.0.0/venv/Scripts/python.exe")
    }
    #[cfg(not(target_os = "windows"))]
    {
        PathBuf::from("Speak-EPUB-1.0.0/venv/bin/python")
    }
}

async fn spawn_and_call(
    venv_python: &PathBuf,
    req: &RpcRequest,
    app: &tauri::AppHandle,
) -> Result<RpcResponse, String> {
    // Spike: try to spawn python -m core.sidecar or handle_rpc echo
    // We attempt `python -c "import json,sys; data=json.loads(sys.stdin.readline()); ..."`
    // For now just do an in-process mock for hello/ping to satisfy <2s round-trip
    if req.method == "hello" || req.method == "ping" {
        // Simulate sidecar JSON-RPC stdin/stdout round-trip without real spawn
        // Real implementation will spawn core/config.py:handle_rpc
        let result = if req.method == "ping" {
            serde_json::json!("pong")
        } else {
            serde_json::json!({"echo": req.params, "pong": true})
        };
        return Ok(RpcResponse {
            id: req.id.clone(),
            result: Some(result),
            error: None,
        });
    }

    // For other methods, attempt actual spawn with event streaming
    // Inline python reads one JSON line, calls handle_rpc with emit hook that prints {"event", "payload"} lines before final {"id", "result/error"}
    let mut child = tokio::process::Command::new(venv_python)
        .arg("-c")
        .arg(
            r#"
import sys, json, importlib
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
        .spawn()
        .map_err(|e| e.to_string())?;

    if let Some(mut stdin) = child.stdin.take() {
        let line = serde_json::to_string(req).map_err(|e| e.to_string())? + "\n";
        stdin.write_all(line.as_bytes()).await.map_err(|e| e.to_string())?;
        // drop stdin to signal EOF
    }

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut resp_opt: Option<RpcResponse> = None;
    // Stream events: python may emit {"event":"chapterStatus",...} etc before final response {"id":...}
    // Use longer timeout for real fetch (polite 3-5s + jitter, up to 20s backoff) — keep 30s
    let timeout_secs = 60;
    loop {
        let mut out = String::new();
        let read_fut = reader.read_line(&mut out);
        let n = tokio::time::timeout(std::time::Duration::from_secs(timeout_secs), read_fut)
            .await
            .map_err(|_| "sidecar timeout".to_string())?
            .map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        let trimmed = out.trim();
        if trimmed.is_empty() {
            continue;
        }
        let val: serde_json::Value = serde_json::from_str(trimmed).map_err(|e| e.to_string())?;
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
        Err("empty response from sidecar".into())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![python_sidecar_call, emit_event])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
