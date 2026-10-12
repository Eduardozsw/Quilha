//! Casca desktop do Quilha: sobe a API local (`serve`) e a encerra junto com a janela.
//!
//! No app instalado, o backend é o binário congelado que vai junto como recurso (`backend/`). Em
//! desenvolvimento (`tauri dev`), é o `hermes` do `.venv` do projeto, sem `uv run` no meio: assim,
//! matar o filho mata o servidor e não fica processo órfão escutando na porta. O token nasce aqui a
//! cada execução, vai para o servidor pelo ambiente (nunca pela linha de comando, que aparece no
//! `ps`) e para a interface pelo comando `api_info`.

use std::fs::{self, File};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Hermes {
    porta: u16,
    token: String,
    log: PathBuf,
    erro: Option<String>,
    processo: Mutex<Option<Child>>,
}

#[derive(serde::Serialize)]
struct ApiInfo {
    porta: u16,
    token: String,
    log: String,
}

#[tauri::command]
fn api_info(estado: tauri::State<Hermes>) -> Result<ApiInfo, String> {
    match &estado.erro {
        Some(erro) => Err(erro.clone()),
        None => Ok(ApiInfo {
            porta: estado.porta,
            token: estado.token.clone(),
            log: estado.log.display().to_string(),
        }),
    }
}

/// Raiz do projeto Python em desenvolvimento: `HERMES_ROOT`, ou duas pastas acima de `src-tauri`.
fn raiz_do_projeto() -> PathBuf {
    let raiz = std::env::var_os("HERMES_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../..")));
    raiz.canonicalize().unwrap_or(raiz)
}

/// Executável do backend e a pasta onde ele roda.
fn backend(app: &tauri::App) -> Result<(PathBuf, PathBuf), String> {
    let (executavel, pasta) = if cfg!(debug_assertions) {
        let raiz = raiz_do_projeto();
        let venv = if cfg!(windows) { ".venv/Scripts/hermes.exe" } else { ".venv/bin/hermes" };
        (raiz.join(venv), raiz)
    } else {
        let recursos = app.path().resource_dir().map_err(|e| e.to_string())?.join("backend");
        let nome = if cfg!(windows) { "quilha-backend.exe" } else { "quilha-backend" };
        (recursos.join(nome), recursos)
    };
    if !executavel.is_file() {
        let dica = if cfg!(debug_assertions) { " Rode `uv sync` na raiz do projeto." } else { " Reinstale o Quilha." };
        return Err(format!("{} não existe.{dica}", executavel.display()));
    }
    Ok((executavel, pasta))
}

fn novo_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("sem fonte de aleatoriedade para o token: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn porta_livre() -> Result<u16, String> {
    let ouvinte = TcpListener::bind("127.0.0.1:0").map_err(|e| format!("nenhuma porta livre em 127.0.0.1: {e}"))?;
    ouvinte.local_addr().map(|a| a.port()).map_err(|e| e.to_string())
}

fn subir(executavel: &Path, pasta: &Path, log: &Path, porta: u16, token: &str) -> Result<Child, String> {
    if let Some(dir) = log.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let saida = File::create(log).map_err(|e| e.to_string())?;
    let erros = saida.try_clone().map_err(|e| e.to_string())?;
    let mut comando = Command::new(executavel);
    comando
        .args(["serve", "--port", &porta.to_string()])
        .current_dir(pasta)
        .env("HERMES_API_TOKEN", token)
        .stdin(Stdio::null())
        .stdout(Stdio::from(saida))
        .stderr(Stdio::from(erros));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000; // sem janela de console atrás do app
        comando.creation_flags(CREATE_NO_WINDOW);
    }
    comando.spawn().map_err(|e| format!("não consegui iniciar o backend: {e}"))
}

fn preparar(app: &tauri::App) -> Hermes {
    let log = app
        .path()
        .app_log_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("quilha"))
        .join("backend.log");
    let tentativa = (|| {
        let (executavel, pasta) = backend(app)?;
        let token = novo_token()?;
        let porta = porta_livre()?;
        let filho = subir(&executavel, &pasta, &log, porta, &token)?;
        Ok::<_, String>((porta, token, filho))
    })();
    match tentativa {
        Ok((porta, token, filho)) => Hermes { porta, token, log, erro: None, processo: Mutex::new(Some(filho)) },
        Err(erro) => Hermes { porta: 0, token: String::new(), log, erro: Some(erro), processo: Mutex::new(None) },
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let estado = preparar(app);
            app.manage(estado);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_info])
        .build(tauri::generate_context!())
        .expect("falha ao montar o app")
        .run(|app, evento| {
            if let RunEvent::Exit = evento {
                let estado = app.state::<Hermes>();
                let mut guarda = estado.processo.lock().unwrap_or_else(|e| e.into_inner());
                if let Some(mut filho) = guarda.take() {
                    let _ = filho.kill();
                    let _ = filho.wait();
                }
            }
        });
}
