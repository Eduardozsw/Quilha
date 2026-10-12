fn main() {
    // `backend/` é o binário congelado (PyInstaller), copiado de ../../dist/quilha-backend antes do
    // build de release. Em desenvolvimento o app usa o .venv e a pasta só precisa existir.
    let backend = std::path::Path::new("backend");
    let nome = if std::env::var("CARGO_CFG_WINDOWS").is_ok() { "quilha-backend.exe" } else { "quilha-backend" };
    if std::env::var("PROFILE").as_deref() == Ok("release") && !backend.join(nome).is_file() {
        panic!("backend/{nome} não existe: gere com PyInstaller (packaging/) e copie dist/quilha-backend/* para src-tauri/backend/");
    }
    std::fs::create_dir_all(backend).expect("não consegui criar src-tauri/backend");
    println!("cargo:rerun-if-changed=backend");
    tauri_build::build()
}
