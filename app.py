from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from config import DEFAULT_EXTENSIONS, load_config, save_config
from picker import FileScanner, RandomPicker, normalize_extension, normalized_path


def explorer_select_command(path: str) -> list[str]:
    """Build Explorer's /select command without merging the switch and path."""
    return ["explorer.exe", "/select,", str(Path(path))]


class PoolUpdateState:
    """Prevents older asynchronous scans from committing their result."""
    def __init__(self) -> None:
        self.generation = 0
        self.updating = False
        self.paths: list[str] = []

    def request(self) -> int:
        self.generation += 1
        self.updating = True
        return self.generation

    def commit(self, generation: int, paths: list[str]) -> bool:
        if generation != self.generation:
            return False
        self.paths = list(paths)
        self.updating = False
        return True

    def can_select(self) -> bool:
        return not self.updating and bool(self.paths)


class Tooltip:
    def __init__(self, widget: tk.Widget, text) -> None:
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show, add=True)
        widget.bind("<Leave>", self.hide, add=True)

    def show(self, _event=None) -> None:
        value = self.text()
        if not value or self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{self.widget.winfo_rootx() + 12}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}")
        ttk.Label(self.window, text=value, padding=5).pack()

    def hide(self, _event=None) -> None:
        if self.window:
            self.window.destroy(); self.window = None


class Localizer:
    def __init__(self, language: str) -> None:
        folder = Path(__file__).with_name("locales")
        self.fallback = json.loads((folder / "zh_CN.json").read_text(encoding="utf-8"))
        try:
            self.active = json.loads((folder / f"{language}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.active = self.fallback

    def text(self, key: str, **values: object) -> str:
        return self.active.get(key, self.fallback.get(key, key)).format(**values)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=10)
        self.master = master
        self.cfg = load_config()
        self.i18n = Localizer(self.cfg["language"])
        self.scanner, self.picker = FileScanner(), RandomPicker()
        self.pool_state = PoolUpdateState()
        self.paths: list[str] = []
        self.pending_scan = None
        self._variables()
        self.build()
        self.pack(fill="both", expand=True)
        self.master.protocol("WM_DELETE_WINDOW", self.close)
        self.master.bind("<Control-r>", lambda _e: self.refresh())
        self.master.bind("<Control-h>", lambda _e: self.show_history())
        self.master.bind("<space>", self.space_open)
        self.restore_geometry()
        if self.root_var.get():
            self.refresh()

    def t(self, key: str, **values: object) -> str:
        return self.i18n.text(key, **values)

    def restore_geometry(self) -> None:
        saved = self.cfg.get("geometry", "")
        match = re.match(r"(\d+)x(\d+)", saved)
        screen_width, screen_height = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if match:
            width = min(max(800, int(match.group(1))), max(800, screen_width - 80))
            height = min(max(550, int(match.group(2))), max(550, screen_height - 80))
            self.master.geometry(f"{width}x{height}+40+40")
        else:
            self.master.geometry("800x550")

    def _variables(self) -> None:
        c = self.cfg
        self.root_var = tk.StringVar(value=c["root"])
        self.mode_var = tk.StringVar(value=c["mode"])
        self.recent_var = tk.IntVar(value=c["recent_n"])
        self.behavior_var = tk.StringVar(value=c["open_behavior"])
        self.language_var = tk.StringVar(value=c["language"])
        self.custom_var = tk.StringVar()
        self.last_var = tk.StringVar(value=c["history"][0] if c["history"] else "")
        selected = set(c["selected_extensions"])
        self.extension_vars = {ext: tk.BooleanVar(value=ext in selected)
                               for ext in dict.fromkeys(DEFAULT_EXTENSIONS + c["custom_extensions"])}
        self.scope_vars: dict[str, tk.BooleanVar] = {}

    def build(self) -> None:
        self.master.title(self.t("app.title"))
        self.master.minsize(800, 550)
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        root = ttk.Frame(self); root.grid(row=0, column=0, sticky="ew"); root.columnconfigure(1, weight=1)
        ttk.Label(root, text=self.t("label.root")).grid(row=0, column=0, sticky="w")
        ttk.Entry(root, textvariable=self.root_var).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(root, text=self.t("button.browse"), command=self.browse).grid(row=0, column=2)
        ttk.Button(root, text=self.t("button.refresh"), command=self.refresh).grid(row=0, column=3, padx=(5, 0))

        middle = ttk.Frame(self); middle.grid(row=1, column=0, sticky="nsew", pady=(8, 0)); middle.columnconfigure(0, weight=1); middle.columnconfigure(1, weight=1)
        left = ttk.Frame(middle); left.grid(row=0, column=0, sticky="new", padx=(0, 4)); left.columnconfigure(0, weight=1)
        right = ttk.Frame(middle); right.grid(row=0, column=1, sticky="new", padx=(4, 0)); right.columnconfigure(0, weight=1)
        types = ttk.LabelFrame(left, text=self.t("section.file_types"), padding=6); types.grid(row=0, column=0, sticky="ew")
        self.type_frame = ttk.Frame(types); self.type_frame.grid(row=0, column=0, columnspan=5, sticky="w")
        self.draw_extensions()
        ttk.Button(types, text=self.t("button.select_all"), command=lambda: self.set_extensions(True)).grid(row=1, column=0, padx=2, pady=4)
        ttk.Button(types, text=self.t("button.select_none"), command=lambda: self.set_extensions(False)).grid(row=1, column=1, padx=2, pady=4)
        ttk.Button(types, text=self.t("button.defaults"), command=self.defaults).grid(row=1, column=2, padx=2, pady=4)
        ttk.Label(types, text=self.t("label.custom")).grid(row=2, column=0, sticky="w")
        ttk.Entry(types, textvariable=self.custom_var, width=13).grid(row=2, column=1, sticky="ew")
        ttk.Button(types, text=self.t("button.add"), command=self.add_extension).grid(row=2, column=2, padx=2)
        self.custom_combo = ttk.Combobox(types, values=self.custom_extensions(), state="readonly", width=11); self.custom_combo.grid(row=2, column=3, sticky="ew")
        ttk.Button(types, text=self.t("button.remove"), command=self.remove_extension).grid(row=2, column=4, padx=2)
        scope = ttk.LabelFrame(left, text=self.t("section.scope"), padding=6); scope.grid(row=1, column=0, sticky="ew", pady=(8, 0)); scope.columnconfigure(0, weight=1)
        self.scope_summary = ttk.Label(scope); self.scope_summary.grid(row=0, column=0, sticky="w")
        ttk.Button(scope, text=self.t("button.manage_scope"), command=self.manage_scope).grid(row=0, column=1, sticky="e")

        mode = ttk.LabelFrame(right, text=self.t("section.random_mode"), padding=6); mode.grid(row=0, column=0, sticky="ew")
        ttk.Radiobutton(mode, text=self.t("mode.pure"), variable=self.mode_var, value="pure", command=self.update_counts).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode, text=self.t("mode.recent"), variable=self.mode_var, value="recent", command=self.update_counts).grid(row=1, column=0, sticky="w")
        ttk.Spinbox(mode, from_=0, to=1000000, textvariable=self.recent_var, width=7, command=self.update_counts).grid(row=1, column=1, padx=5)
        ttk.Radiobutton(mode, text=self.t("mode.shuffle"), variable=self.mode_var, value="shuffle", command=self.update_counts).grid(row=2, column=0, sticky="w")
        tools = ttk.LabelFrame(right, text=self.t("section.exclusions"), padding=6); tools.grid(row=1, column=0, sticky="ew", pady=(8, 0)); tools.columnconfigure(0, weight=1)
        self.folder_label = ttk.Label(tools); self.folder_label.grid(row=0, column=0, sticky="w")
        ttk.Button(tools, text=self.t("button.manage"), command=self.manage_folders).grid(row=0, column=1, padx=5)
        self.file_label = ttk.Label(tools); self.file_label.grid(row=1, column=0, sticky="w")
        ttk.Button(tools, text=self.t("button.manage"), command=self.manage_files).grid(row=1, column=1, padx=5)
        self.filter_label = ttk.Label(tools); self.filter_label.grid(row=2, column=0, sticky="w")
        ttk.Button(tools, text=self.t("button.manage"), command=self.manage_filters).grid(row=2, column=1, padx=5)

        bottom = ttk.Frame(self); bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0)); bottom.columnconfigure(0, weight=1)
        self.eligible_label = ttk.Label(bottom); self.eligible_label.grid(row=0, column=0, sticky="w")
        status = ttk.Frame(bottom); status.grid(row=1, column=0, sticky="ew"); status.columnconfigure(0, weight=1)
        self.available_label = ttk.Label(status); self.available_label.grid(row=0, column=0, sticky="w")
        self.reset_button = ttk.Button(status, text=self.t("button.reset_picker"), command=self.reset_picker_state); self.reset_button.grid(row=0, column=1, sticky="e")
        ttk.Style(self.master).configure("Primary.TButton", font=("TkDefaultFont", 13, "bold"), padding=(16, 12))
        self.random_area = ttk.Frame(bottom); self.random_area.grid(row=2, column=0, sticky="ew", pady=(12, 10)); self.random_area.columnconfigure(0, weight=1)
        self.random_button = ttk.Button(self.random_area, text=self.t("button.random_open"), command=self.random_open, style="Primary.TButton"); self.random_button.grid(row=0, column=0, sticky="ew", padx=50)
        self.random_tooltip = Tooltip(self.random_area, self.random_tooltip_text); self.random_button.bind("<Enter>", self.random_tooltip.show, add=True); self.random_button.bind("<Leave>", self.random_tooltip.hide, add=True)
        behavior = ttk.Frame(bottom); behavior.grid(row=3, column=0, sticky="w")
        ttk.Label(behavior, text=self.t("label.open_behavior")).grid(row=0, column=0)
        for i, (key, value) in enumerate((("behavior.open", "open"), ("behavior.explorer", "explorer"), ("behavior.both", "both")), 1): ttk.Radiobutton(behavior, text=self.t(key), variable=self.behavior_var, value=value).grid(row=0, column=i, padx=3)
        last = ttk.Frame(bottom); last.grid(row=4, column=0, sticky="ew", pady=(6, 0)); last.columnconfigure(1, weight=1)
        ttk.Label(last, text=self.t("label.last")).grid(row=0, column=0, sticky="nw")
        ttk.Label(last, textvariable=self.last_var, wraplength=780).grid(row=0, column=1, sticky="w")
        ttk.Button(last, text=self.t("button.history"), command=self.show_history).grid(row=1, column=0, pady=3)
        ttk.Button(last, text=self.t("button.never"), command=self.never).grid(row=1, column=1, sticky="w", pady=3)
        lang = ttk.Frame(bottom); lang.grid(row=5, column=0, sticky="e")
        ttk.Label(lang, text=self.t("label.language")).grid(row=0, column=0)
        ttk.Combobox(lang, textvariable=self.language_var, values=["zh_CN", "en_US"], width=8, state="readonly").grid(row=0, column=1)
        self.language_var.trace_add("write", lambda *_: self.change_language()); self.root_var.trace_add("write", lambda *_: self.queue_refresh())
        self.update_management(); self.update_scope_summary(); self.update_counts()

    def draw_extensions(self) -> None:
        for child in self.type_frame.winfo_children(): child.destroy()
        for index, (ext, var) in enumerate(self.extension_vars.items()):
            ttk.Checkbutton(self.type_frame, text=ext.upper().lstrip("."), variable=var, command=self.queue_refresh).grid(row=index // 6, column=index % 6, padx=4, sticky="w")

    def custom_extensions(self) -> list[str]:
        return [x for x in self.extension_vars if x not in DEFAULT_EXTENSIONS]

    def browse(self) -> None:
        path = filedialog.askdirectory(title=self.t("message.choose_root"), initialdir=self.root_var.get() or None)
        if path: self.root_var.set(path); self.refresh()

    def selected_extensions(self) -> set[str]:
        return {x for x, var in self.extension_vars.items() if var.get()}

    def recent_n(self) -> int:
        try:
            return max(0, self.recent_var.get())
        except tk.TclError:
            return 0

    def scope_values(self) -> dict[str, bool]:
        return {name: value.get() for name, value in self.scope_vars.items()}

    def queue_refresh(self) -> None:
        generation = self.begin_pool_update()
        if self.pending_scan is not None:
            self.master.after_cancel(self.pending_scan)
        self.pending_scan = self.master.after(200, lambda: self.start_scan(generation))

    def refresh(self) -> None:
        generation = self.begin_pool_update()
        if self.pending_scan is not None:
            self.master.after_cancel(self.pending_scan); self.pending_scan = None
        self.start_scan(generation)

    def begin_pool_update(self) -> int:
        generation = self.pool_state.request()
        self.random_button.state(["disabled"])
        self.update_counts()
        return generation

    def start_scan(self, generation: int) -> None:
        self.pending_scan = None
        if generation != self.pool_state.generation:
            return
        root = self.root_var.get()
        if not os.path.isdir(root):
            self.finish_scan(generation, []); return
        extensions, scopes = self.selected_extensions(), self.scope_values()
        def work() -> None:
            found = self.scanner.scan(root, extensions, set(self.cfg["excluded_folders"]), set(self.cfg["excluded_files"]), self.cfg["filename_filters"], scopes)
            self.master.after(0, lambda: self.finish_scan(generation, found))
        threading.Thread(target=work, daemon=True).start()

    def finish_scan(self, generation: int, paths: list[str]) -> None:
        if not self.pool_state.commit(generation, paths):
            return
        self.paths = self.pool_state.paths; self.picker.set_pool(self.paths)
        self.draw_scopes(); self.update_counts()

    def draw_scopes(self) -> None:
        root = self.root_var.get()
        names = []
        try: names = [p.name for p in Path(root).iterdir() if p.is_dir()]
        except OSError: pass
        old = self.scope_values()
        self.scope_vars = {name: tk.BooleanVar(value=old.get(name, self.cfg["scope_enabled"].get(name, True))) for name in names}
        self.update_scope_summary()

    def update_scope_summary(self) -> None:
        if not hasattr(self, "scope_summary"):
            return
        total = len(self.scope_vars)
        self.scope_summary.config(text=self.t("label.scope_summary", enabled=sum(var.get() for var in self.scope_vars.values()), total=total))

    def manage_scope(self) -> None:
        window = tk.Toplevel(self); window.title(self.t("dialog.scope.title")); window.transient(self.master); window.geometry("620x500"); window.minsize(420, 300)
        outer = ttk.Frame(window, padding=8); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0); scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        choices = ttk.Frame(canvas)
        choices.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        choices_id = canvas.create_window((0, 0), window=choices, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(choices_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew"); scrollbar.grid(row=0, column=1, sticky="ns"); outer.rowconfigure(0, weight=1); outer.columnconfigure(0, weight=1)
        def changed() -> None:
            self.update_scope_summary(); self.queue_refresh()
        for row, (name, var) in enumerate(self.scope_vars.items()):
            ttk.Checkbutton(choices, text=name, variable=var, command=changed).grid(row=row, column=0, sticky="w", padx=4, pady=2)
        buttons = ttk.Frame(outer); buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        def set_all(value: bool) -> None:
            for var in self.scope_vars.values(): var.set(value)
            self.update_scope_summary(); self.queue_refresh()
        ttk.Button(buttons, text=self.t("button.select_all"), command=lambda: set_all(True)).grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text=self.t("button.select_none"), command=lambda: set_all(False)).grid(row=0, column=1, padx=3)
        ttk.Button(buttons, text=self.t("button.close"), command=window.destroy).grid(row=0, column=2, padx=3)

    def update_counts(self) -> None:
        if self.pool_state.updating:
            self.eligible_label.config(text=self.t("status.updating"))
            self.available_label.config(text="")
            self.reset_button.state(["disabled"])
            return
        available = self.picker.candidates(self.cfg["recent_picker_memory"], self.recent_n()) if self.mode_var.get() == "recent" else [p for p in self.paths if os.path.isfile(p)]
        self.eligible_label.config(text=self.t("status.eligible", count=len(self.paths)))
        self.available_label.config(text=self.t("status.available", count=len(available)))
        self.random_button.state(["!disabled"] if available else ["disabled"])
        self.reset_button.state(["!disabled"] if self.mode_var.get() in ("recent", "shuffle") else ["disabled"])
        self.update_management()

    def random_tooltip_text(self) -> str:
        if self.pool_state.updating:
            return self.t("tooltip.updating")
        if not self.pool_state.can_select():
            return self.t("tooltip.empty")
        return ""

    def update_management(self) -> None:
        self.folder_label.config(text=self.t("label.excluded_folders", count=len(self.cfg["excluded_folders"])))
        self.file_label.config(text=self.t("label.excluded_files", count=len(self.cfg["excluded_files"])))
        self.filter_label.config(text=self.t("label.filename_filters", count=len(self.cfg["filename_filters"])))

    def set_extensions(self, value: bool) -> None:
        for var in self.extension_vars.values(): var.set(value)
        self.queue_refresh()

    def defaults(self) -> None:
        for ext, var in self.extension_vars.items(): var.set(ext in DEFAULT_EXTENSIONS)
        self.queue_refresh()

    def add_extension(self) -> None:
        ext = normalize_extension(self.custom_var.get())
        if not ext or ext == ".": messagebox.showwarning(self.t("app.title"), self.t("message.bad_extension")); return
        if ext not in self.extension_vars: self.extension_vars[ext] = tk.BooleanVar(value=True)
        self.custom_var.set(""); self.custom_combo.configure(values=self.custom_extensions()); self.draw_extensions(); self.queue_refresh()

    def remove_extension(self) -> None:
        ext = self.custom_combo.get()
        if ext in self.custom_extensions(): del self.extension_vars[ext]; self.custom_combo.configure(values=self.custom_extensions()); self.draw_extensions(); self.queue_refresh()

    def enable_all_scopes(self) -> None:
        for value in self.scope_vars.values(): value.set(True)
        self.update_scope_summary(); self.queue_refresh()

    def random_open(self) -> None:
        if self.pool_state.updating or not self.pool_state.can_select():
            return
        path = self.picker.choose(self.mode_var.get(), self.cfg["recent_picker_memory"], self.recent_n())
        if not path: messagebox.showinfo(self.t("app.title"), self.t("message.no_files")); return
        self.open_path(path)

    def open_path(self, path: str) -> None:
        try:
            behavior = self.behavior_var.get()
            if behavior in ("open", "both"): os.startfile(path)
            if behavior in ("explorer", "both"): subprocess.Popen(explorer_select_command(path))
            self.cfg["recent_picker_memory"] = [path] + [p for p in self.cfg["recent_picker_memory"] if normalized_path(p) != normalized_path(path)]
            self.cfg["recent_picker_memory"] = self.cfg["recent_picker_memory"][:max(100, self.recent_n())]
            self.cfg["history"] = [path] + [p for p in self.cfg["history"] if normalized_path(p) != normalized_path(path)]
            self.cfg["history"] = self.cfg["history"][:50]; self.last_var.set(path); self.update_counts()
        except OSError as error: messagebox.showerror(self.t("app.title"), self.t("message.error", error=str(error)))

    def reset_picker_state(self) -> None:
        mode = self.mode_var.get()
        if self.pool_state.updating or mode not in ("recent", "shuffle"):
            return
        if not messagebox.askyesno(self.t("dialog.confirm.title"), self.t("message.confirm_reset_picker"), parent=self.master):
            return
        if mode == "recent":
            self.cfg["recent_picker_memory"] = []
        else:
            self.picker.reset_shuffle()
        self.update_counts()

    def space_open(self, event: tk.Event) -> str | None:
        if isinstance(event.widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Entry, tk.Text)): return None
        self.random_open(); return "break"

    def never(self) -> None:
        path = self.last_var.get()
        if not path: messagebox.showinfo(self.t("app.title"), self.t("message.no_last")); return
        if normalized_path(path) not in {normalized_path(x) for x in self.cfg["excluded_files"]}: self.cfg["excluded_files"].append(path)
        self.queue_refresh()

    def list_dialog(self, title_key: str, values: list[str], add=None, folder=False) -> None:
        window = tk.Toplevel(self); window.title(self.t(title_key)); window.transient(self.master); window.geometry("650x350")
        box = tk.Listbox(window); box.pack(fill="both", expand=True, padx=8, pady=8)
        def redraw(): box.delete(0, "end"); [box.insert("end", x) for x in values]
        def remove():
            for i in reversed(box.curselection()): values.pop(i)
            redraw(); self.queue_refresh()
        def add_item():
            if folder:
                value = filedialog.askdirectory(title=self.t("message.choose_excluded"), parent=window)
            else: value = simpledialog.askstring(self.t(title_key), self.t("dialog.add_filter"), parent=window)
            if value and value not in values: values.append(value); redraw(); self.queue_refresh()
        buttons = ttk.Frame(window); buttons.pack(pady=(0, 8))
        if add is not None: ttk.Button(buttons, text=self.t(add), command=add_item).grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text=self.t("button.delete"), command=remove).grid(row=0, column=1, padx=3)
        ttk.Button(buttons, text=self.t("button.close"), command=window.destroy).grid(row=0, column=2, padx=3)
        redraw()

    def manage_folders(self): self.list_dialog("dialog.excluded_folders.title", self.cfg["excluded_folders"], "button.add_folder", True)
    def manage_files(self): self.list_dialog("dialog.excluded_files.title", self.cfg["excluded_files"])
    def manage_filters(self): self.list_dialog("dialog.filters.title", self.cfg["filename_filters"], "button.add")

    def show_history(self) -> None:
        window = tk.Toplevel(self); window.title(self.t("dialog.history.title")); window.geometry("650x350")
        box = tk.Listbox(window); box.pack(fill="both", expand=True, padx=8, pady=8)
        [box.insert("end", p) for p in self.cfg["history"]]
        box.bind("<Double-Button-1>", lambda _e: self.open_path(box.get("active")) if box.curselection() else None)
        buttons = ttk.Frame(window); buttons.pack(pady=(0, 8))
        def clear():
            if messagebox.askyesno(self.t("dialog.confirm.title"), self.t("message.confirm_clear"), parent=window): self.cfg["history"] = []; self.last_var.set(""); box.delete(0, "end"); self.update_counts()
        ttk.Button(buttons, text=self.t("button.clear_history"), command=clear).grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text=self.t("button.close"), command=window.destroy).grid(row=0, column=1, padx=3)

    def change_language(self) -> None:
        if not hasattr(self, "i18n") or self.language_var.get() == self.cfg.get("language"): return
        self.cfg.update({"root": self.root_var.get(), "selected_extensions": sorted(self.selected_extensions()),
                         "custom_extensions": self.custom_extensions(), "mode": self.mode_var.get(),
                         "recent_n": self.recent_n(), "open_behavior": self.behavior_var.get(),
                         "scope_enabled": self.scope_values()})
        self.cfg["language"] = self.language_var.get(); self.i18n = Localizer(self.cfg["language"])
        self.destroy(); self._variables(); self.build(); self.pack(fill="both", expand=True)

    def close(self) -> None:
        self.cfg.update({"root": self.root_var.get(), "selected_extensions": sorted(self.selected_extensions()), "custom_extensions": self.custom_extensions(), "mode": self.mode_var.get(), "recent_n": self.recent_n(), "open_behavior": self.behavior_var.get(), "scope_enabled": self.scope_values(), "geometry": self.master.geometry()})
        save_config(self.cfg); self.master.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
