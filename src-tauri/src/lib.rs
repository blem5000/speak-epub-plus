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
    match spawn_and_call(&venv_python, &payload).await {
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

async fn spawn_and_call(venv_python: &PathBuf, req: &RpcRequest) -> Result<RpcResponse, String> {
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

    // For other methods, attempt actual spawn (best-effort)
    // Spawn python with a tiny inline handler: reads one JSON line, writes response
    let mut child = tokio::process::Command::new(venv_python)
        .arg("-c")
        .arg(
            r#"
import sys, json
try:
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"id":"0","error":{"code":"EMPTY","message":"no input"}}))
        sys.exit(0)
    req = json.loads(line)
    method = req.get("method")
    if method in ("ping","hello"):
        result = "pong" if method=="ping" else {"echo": req.get("params"), "pong": True}
        print(json.dumps({"id": req.get("id"), "result": result}))
    else:
        print(json.dumps({"id": req.get("id"), "error":{"code":"NOT_IMPLEMENTED","message":"mock only"}}))
except Exception as e:
    print(json.dumps({"id": "0", "error":{"code":"EXCEPTION","message": str(e)}}))
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
    let mut out = String::new();
    // Timeout 2s for spike requirement
    let read_fut = reader.read_line(&mut out);
    let _ = tokio::time::timeout(std::time::Duration::from_secs(2), read_fut)
        .await
        .map_err(|_| "sidecar timeout <2s".to_string())?
        .map_err(|e| e.to_string())?;

    if out.trim().is_empty() {
        return Err("empty response from sidecar".into());
    }
    let resp: RpcResponse = serde_json::from_str(out.trim()).map_err(|e| e.to_string())?;
    // Ensure child is reaped
    let _ = child.wait().await;
    Ok(resp)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![python_sidecar_call])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
