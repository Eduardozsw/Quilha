// Tema escolhido à mão (Configurações → Aparência) antes do app carregar: sem isso, o primeiro quadro segue o
// sistema e pisca. Arquivo à parte porque o CSP do Tauri só aceita script de 'self', não inline.
try {
  var t = localStorage.getItem("quilha.tema");
  if (t === "claro" || t === "escuro") document.documentElement.setAttribute("data-tema", t);
} catch (e) {}
