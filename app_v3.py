"""Interface locale Tkinter pour AI Workspace V3.

Lancer depuis le dossier du projet : .venv/bin/python app_v3.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from workspace_core import AppConfig, AgentService, Workspace, direct_local_inspection


class WorkspaceApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.config_data = AppConfig.load(Path(__file__).resolve().parent)
        self.workspace = Workspace(self.config_data)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.agent = AgentService(self.config_data, self.workspace, self._log_from_worker)
        self.busy = False
        self.title("AI Workspace V3")
        self.minsize(1050, 680)
        self.geometry("1280x790")
        self._build_style()
        self._build_ui()
        self.refresh_files()
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_style(self) -> None:
        self.configure(bg="#F5F7FB")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#F5F7FB")
        style.configure("Panel.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#F5F7FB", foreground="#172033", font=("Helvetica Neue", 13))
        style.configure("Title.TLabel", background="#F5F7FB", foreground="#14213D", font=("Helvetica Neue", 25, "bold"))
        style.configure("Sub.TLabel", background="#F5F7FB", foreground="#566178", font=("Helvetica Neue", 12))
        style.configure("PanelTitle.TLabel", background="#FFFFFF", foreground="#172033", font=("Helvetica Neue", 14, "bold"))
        style.configure("Status.TLabel", background="#EDF2FF", foreground="#304A89", font=("Helvetica Neue", 10))
        style.configure("Accent.TButton", background="#4263EB", foreground="#FFFFFF", borderwidth=0, font=("Helvetica Neue", 12, "bold"), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", "#3451C9"), ("disabled", "#AAB7E9")])
        style.configure("Soft.TButton", background="#EDF2FF", foreground="#29417F", borderwidth=0, font=("Helvetica Neue", 11), padding=(11, 7))
        style.map("Soft.TButton", background=[("active", "#DBE5FF")])
        style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#1C2740", rowheight=29, font=("Helvetica Neue", 11), borderwidth=0)
        style.configure("Treeview.Heading", background="#EFF3FB", foreground="#52617C", font=("Helvetica Neue", 10, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#DDE6FF")], foreground=[("selected", "#172033")])

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(26, 22, 26, 22))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 17))
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text="AI Workspace", style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text="Analyse locale de tableurs et documents, avec IA en renfort", style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Ajouter des fichiers", command=self.import_files, style="Accent.TButton").pack(side="right", padx=(10, 0))
        ttk.Button(header, text="Actualiser", command=self.refresh_files, style="Soft.TButton").pack(side="right")

        self.status_var = tk.StringVar(value=self.agent.health_summary())
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", padding=(12, 7)).pack(fill="x", pady=(0, 14))

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=33, minsize=330)
        content.columnconfigure(1, weight=67, minsize=600)
        content.rowconfigure(0, weight=1)

        files_panel = ttk.Frame(content, style="Panel.TFrame", padding=16)
        files_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        ttk.Label(files_panel, text="Fichiers de travail", style="PanelTitle.TLabel").pack(anchor="w")
        tk.Label(files_panel, text="Les originaux sont copiés dans data. Les sorties ne remplacent jamais la source.", bg="#FFFFFF", fg="#667085", wraplength=295, justify="left", font=("Helvetica Neue", 10)).pack(anchor="w", pady=(4, 12))
        columns = ("name", "type")
        self.tree = ttk.Treeview(files_panel, columns=columns, show="headings", selectmode="browse", height=17)
        self.tree.heading("name", text="Nom")
        self.tree.heading("type", text="Type")
        self.tree.column("name", width=245, anchor="w")
        self.tree.column("type", width=63, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self.inspect_selected())
        sidebar_actions = ttk.Frame(files_panel, style="Panel.TFrame")
        sidebar_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(sidebar_actions, text="Inspecter en local", command=self.inspect_selected, style="Soft.TButton").pack(fill="x")
        ttk.Button(sidebar_actions, text="Ouvrir le dossier de sortie", command=self.open_output_folder, style="Soft.TButton").pack(fill="x", pady=(8, 0))
        self.file_count_var = tk.StringVar(value="")
        tk.Label(files_panel, textvariable=self.file_count_var, bg="#FFFFFF", fg="#667085", anchor="w", font=("Helvetica Neue", 10)).pack(fill="x", pady=(12, 0))

        assistant_panel = ttk.Frame(content, style="Panel.TFrame", padding=16)
        assistant_panel.grid(row=0, column=1, sticky="nsew")
        top_line = ttk.Frame(assistant_panel, style="Panel.TFrame")
        top_line.pack(fill="x")
        ttk.Label(top_line, text="Assistant", style="PanelTitle.TLabel").pack(side="left")
        tk.Label(top_line, text="Les extraits nécessaires sont envoyés à Gemini uniquement quand vous posez une question.", bg="#FFFFFF", fg="#667085", font=("Helvetica Neue", 10)).pack(side="right")
        self.chat = tk.Text(assistant_panel, wrap="word", bg="#FFFFFF", fg="#172033", borderwidth=0, highlightthickness=0, font=("Helvetica Neue", 12), padx=5, pady=12, state="disabled")
        self.chat.pack(fill="both", expand=True, pady=(8, 10))
        self._configure_tags()
        self.add_chat("assistant", "Bonjour — ajoute un fichier puis demande, par exemple :\n\n• « Inspecte le fichier et explique ses colonnes. »\n• « Analyse les tendances et valeurs manquantes. »\n• « Cherche le terme “contrat” dans mes documents. »\n• « Crée un rapport Excel des statistiques. »\n\nL’inspection locale (à gauche) ne sollicite pas l’IA.")
        prompt_frame = ttk.Frame(assistant_panel, style="Panel.TFrame")
        prompt_frame.pack(fill="x")
        self.prompt = tk.Text(prompt_frame, height=4, wrap="word", bg="#F6F8FC", fg="#172033", relief="flat", highlightthickness=1, highlightbackground="#D8E0EF", highlightcolor="#4263EB", font=("Helvetica Neue", 12), padx=10, pady=8)
        self.prompt.pack(side="left", fill="x", expand=True)
        self.prompt.bind("<Command-Return>", lambda _: self.send_message())
        self.prompt.bind("<Control-Return>", lambda _: self.send_message())
        self.send_button = ttk.Button(prompt_frame, text="Envoyer", command=self.send_message, style="Accent.TButton")
        self.send_button.pack(side="left", padx=(11, 0), fill="y")
        tk.Label(assistant_panel, text="⌘↩ pour envoyer · Pour une analyse financière, les calculs restent locaux puis l’IA les explique.", bg="#FFFFFF", fg="#7A8599", font=("Helvetica Neue", 10)).pack(anchor="w", pady=(8, 0))

    def _configure_tags(self) -> None:
        self.chat.tag_configure("assistant_header", foreground="#4263EB", font=("Helvetica Neue", 11, "bold"), spacing1=13)
        self.chat.tag_configure("user_header", foreground="#475467", font=("Helvetica Neue", 11, "bold"), spacing1=13)
        self.chat.tag_configure("body", foreground="#172033", font=("Helvetica Neue", 12), spacing3=6)
        self.chat.tag_configure("error", foreground="#B42318", font=("Helvetica Neue", 12), spacing3=6)
        self.chat.tag_configure("meta", foreground="#667085", font=("Helvetica Neue", 10), spacing3=8)

    def add_chat(self, role: str, text: str, meta: str = "") -> None:
        self.chat.configure(state="normal")
        self.chat.insert("end", "Vous\n" if role == "user" else "Assistant\n", "user_header" if role == "user" else "assistant_header")
        self.chat.insert("end", text.strip() + "\n", "error" if role == "error" else "body")
        if meta:
            self.chat.insert("end", meta + "\n", "meta")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def refresh_files(self) -> None:
        self.workspace.refresh()
        for item in self.tree.get_children():
            self.tree.delete(item)
        files = self.workspace.list_files()
        for item in files:
            self.tree.insert("", "end", iid=item["file_id"], values=(item["name"], item["type"].upper()))
        self.file_count_var.set(f"{len(files)} fichier(s) dans data  ·  sorties : output")
        self.status_var.set(self.agent.health_summary())

    def import_files(self) -> None:
        choices = filedialog.askopenfilenames(title="Importer des fichiers", filetypes=[("Fichiers compatibles", "*.xlsx *.xlsm *.xls *.csv *.tsv *.pdf *.docx *.txt *.md"), ("Tous les fichiers", "*.*")])
        if not choices:
            return
        results = self.workspace.import_files(list(choices))
        self.refresh_files()
        failed = [item for item in results if "error" in item]
        added = [item for item in results if item.get("status") == "importé"]
        self.add_chat("assistant", f"{len(added)} fichier(s) importé(s) dans l’espace de travail." + (f" {len(failed)} import(s) ont échoué." if failed else ""))
        if failed:
            messagebox.showwarning("Import incomplet", "\n".join(f"{item['source']} : {item['error']}" for item in failed))

    def selected_file_id(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def inspect_selected(self) -> None:
        file_id = self.selected_file_id()
        if not file_id:
            messagebox.showinfo("Choisir un fichier", "Sélectionne d’abord un fichier à gauche.")
            return
        try:
            result = direct_local_inspection(self.workspace, file_id)
            self.add_chat("assistant", result, "Inspection locale : aucune donnée n’a été envoyée à un modèle.")
        except Exception as error:
            self.add_chat("error", str(error))

    def send_message(self) -> None:
        if self.busy:
            return
        message = self.prompt.get("1.0", "end").strip()
        if not message:
            return
        self.prompt.delete("1.0", "end")
        self.add_chat("user", message)
        self.busy = True
        self.send_button.configure(state="disabled", text="Analyse…")
        self.status_var.set("Traitement en cours — les analyses locales et les essais de secours restent dans cette fenêtre.")
        threading.Thread(target=self._ask_in_background, args=(message,), daemon=True).start()

    def _ask_in_background(self, message: str) -> None:
        try:
            result = self.agent.ask(message)
            self.events.put(("answer", json_text(result)))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _log_from_worker(self, message: str) -> None:
        self.events.put(("status", message))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "answer":
                    result = decode_result(payload)
                    events = ", ".join(result.get("tool_events", [])) or "réponse directe"
                    self.add_chat("assistant", result["answer"], f"{result.get('provider', 'IA')} · actions : {events}")
                    self._finish_request()
                    self.refresh_files()
                elif kind == "error":
                    self.add_chat("error", payload)
                    self._finish_request()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _finish_request(self) -> None:
        self.busy = False
        self.send_button.configure(state="normal", text="Envoyer")
        self.status_var.set(self.agent.health_summary())

    def open_output_folder(self) -> None:
        # A portable UI notification avoids shelling out with arbitrary paths.
        messagebox.showinfo("Dossier de sortie", f"Les rapports créés sont dans :\n{self.config_data.output_dir}")


def json_text(value: dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def decode_result(value: str) -> dict:
    import json
    return json.loads(value)


if __name__ == "__main__":
    WorkspaceApp().mainloop()
