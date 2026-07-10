"""
Lunar Pack Merger
------------------
A small utility to merge multiple Minecraft (1.8.9 / Lunar Client) resource
pack .zip files into a single combined pack.

Simple flow:
  1. Add your "Collection" packs (the base look, merged by priority order).
  2. Optionally pick ONE "Source" pack (e.g. a sword pack) and check exactly
     which categories to pull from it (Swords, Blocks, GUI, ...). Nothing
     is touched unless you check its box.
  3. Optionally set a custom pack icon.
  4. Merge. Packs are safety-checked automatically unless you turn that off.

Need finer control than whole categories (just one specific file)? Use the
"Advanced: override individual files" button.

No network access, no telemetry, no personal data collected or embedded.
"""

import os
import re
import io
import shutil
import zipfile
import tempfile
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "Lunar Pack Merger"
APP_VERSION = "1.3.0"

JUNK_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}

DEFAULT_MCMETA = """{
  "pack": {
    "pack_format": 1,
    "description": "Merged pack created with Lunar Pack Merger"
  }
}
"""

MAX_ADVANCED_ROWS = 400

CATEGORY_ORDER = [
    "Swords",
    "Tools (axe/pickaxe/shovel/hoe)",
    "Armor",
    "Blocks",
    "Items (other)",
    "GUI (includes hearts/hunger/hotbar)",
    "Mobs & Entities",
    "Environment (sky/sun/moon/weather)",
    "Particles",
    "Effects",
    "Paintings",
    "Font",
    "Lunar Client HUD/Cosmetics",
    "Pack Metadata",
    "Other / Misc",
]

SUSPICIOUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs",
    ".js", ".jar", ".msi", ".sh", ".py", ".pyc", ".class", ".apk",
    ".dmg", ".jse", ".wsf", ".hta", ".cpl", ".lnk", ".vb", ".vbe",
}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def categorize(rel_path: str) -> str:
    lower = rel_path.lower()

    if lower.endswith(".mcmeta") or lower == "pack.png":
        return "Pack Metadata"
    if "/lunarclient/" in lower or "/lunar/" in lower or lower.startswith("lunar"):
        return "Lunar Client HUD/Cosmetics"
    if "/font/" in lower:
        return "Font"
    if "/gui/" in lower or lower.startswith("gui/"):
        return "GUI (includes hearts/hunger/hotbar)"
    if "/particle" in lower:
        return "Particles"
    if "/environment/" in lower:
        return "Environment (sky/sun/moon/weather)"
    if "/entity/" in lower:
        return "Mobs & Entities"
    if "/painting" in lower:
        return "Paintings"
    if "mob_effect" in lower or "/effect/" in lower:
        return "Effects"
    if "/armor/" in lower:
        return "Armor"
    if "/items/" in lower or "/item/" in lower:
        if "sword" in lower:
            return "Swords"
        if re.search(r"(axe|pickaxe|shovel|hoe)", lower) and "sword" not in lower:
            return "Tools (axe/pickaxe/shovel/hoe)"
        if any(k in lower for k in ("helmet", "chestplate", "leggings", "boots")):
            return "Armor"
        return "Items (other)"
    if "/blocks/" in lower or "/block/" in lower:
        return "Blocks"
    return "Other / Misc"


def safety_scan_pack(pack_path: str) -> list:
    """Heuristic-only static checks: suspicious file types, disguised files,
    path traversal, and zip-bomb-style size ratios. This is NOT a real
    antivirus engine — it just flags patterns that never belong in a
    legitimate resource pack."""
    issues = []
    try:
        with zipfile.ZipFile(pack_path, "r") as zf:
            total_uncompressed = 0
            for info in zf.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                total_uncompressed += info.file_size

                parts = Path(name).parts
                if ".." in parts or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                    issues.append({
                        "file": name,
                        "issue": "Suspicious path (possible path-traversal / zip-slip attempt)",
                        "severity": "high",
                    })

                ext = Path(name).suffix.lower()
                if ext in SUSPICIOUS_EXTENSIONS:
                    issues.append({
                        "file": name,
                        "issue": f"Unexpected executable/script file type ({ext}) — resource "
                        f"packs should only contain images, text, audio, and .mcmeta files",
                        "severity": "high",
                    })

                if info.compress_size > 0:
                    ratio = info.file_size / max(info.compress_size, 1)
                    if info.file_size > 50 * 1024 * 1024 and ratio > 100:
                        issues.append({
                            "file": name,
                            "issue": "Unusually high compression ratio for its size (possible zip bomb)",
                            "severity": "high",
                        })

                if ext == ".png":
                    try:
                        with zf.open(info) as f:
                            header = f.read(8)
                        if header[:2] == b"MZ":
                            issues.append({
                                "file": name,
                                "issue": "Named .png but starts with a Windows EXE header — disguised executable",
                                "severity": "high",
                            })
                        elif header[:4] == b"\x7fELF":
                            issues.append({
                                "file": name,
                                "issue": "Named .png but is a Linux ELF executable — disguised file",
                                "severity": "high",
                            })
                        elif len(header) >= 8 and header != PNG_MAGIC:
                            issues.append({
                                "file": name,
                                "issue": "Named .png but does not have a valid PNG header",
                                "severity": "medium",
                            })
                    except Exception:
                        pass

            if total_uncompressed > 500 * 1024 * 1024:
                issues.append({
                    "file": "(entire pack)",
                    "issue": f"Very large uncompressed size "
                    f"({total_uncompressed / 1024 / 1024:.0f} MB) for a texture pack — "
                    f"possible zip bomb",
                    "severity": "medium",
                })
    except zipfile.BadZipFile:
        issues.append({
            "file": "(entire pack)",
            "issue": "Not a valid zip file / corrupted",
            "severity": "medium",
        })
    return issues


def format_issues(issues: list) -> str:
    lines = []
    for issue in issues:
        marker = "\U0001F534" if issue["severity"] == "high" else "\U0001F7E1"
        lines.append(f"{marker} {issue['file']}: {issue['issue']}")
    return "\n".join(lines)


class PackEntry:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)


class MergerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("880x820")
        self.minsize(760, 700)

        self.collection: list = []           # base packs, priority order
        self.selected_index = None

        self.source_pack: PackEntry | None = None
        self.category_vars: dict = {}          # category -> BooleanVar

        self.icon_path: str | None = None

        # rel_path -> [pack_path,...] (collection only)
        self.file_index: dict = {}
        # rel_path -> pack_path (explicit override)
        self.assignments: dict = {}

        self.safety_enabled = ctk.BooleanVar(value=True)

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = 16

        scroll_root = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll_root.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll_root, fg_color="transparent")
        header.pack(fill="x", padx=pad, pady=(pad, 4))
        ctk.CTkLabel(
            header, text="Lunar Pack Merger",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="1. Add your Collection.  2. (Optional) pick one Source pack and "
                 "check which categories to pull from it.  3. Merge.",
            font=ctk.CTkFont(size=12), text_color="gray70",
            wraplength=800, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # ---- Collection ----
        coll_frame = ctk.CTkFrame(scroll_root)
        coll_frame.pack(fill="x", padx=pad, pady=(10, 8))
        ctk.CTkLabel(
            coll_frame, text="1. Collection (base packs, merged by priority order)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))

        coll_body = ctk.CTkFrame(coll_frame, fg_color="transparent")
        coll_body.pack(fill="x", padx=12, pady=(0, 12))

        self.list_scroll = ctk.CTkScrollableFrame(
            coll_body, label_text="", height=140)
        self.list_scroll.pack(side="left", fill="both",
                              expand=True, padx=(0, 10))

        coll_btns = ctk.CTkFrame(coll_body, fg_color="transparent", width=170)
        coll_btns.pack(side="left", fill="y")
        ctk.CTkButton(coll_btns, text="\uFF0B Add Pack(s)", command=self.add_packs).pack(
            fill="x", pady=(0, 6)
        )
        ctk.CTkButton(
            coll_btns, text="\U0001F6E1\uFE0F Check Safety", command=self.check_selected_safety
        ).pack(fill="x", pady=6)
        ctk.CTkButton(
            coll_btns, text="\u2715 Remove", fg_color="#7f1d1d", hover_color="#991b1b",
            command=self.remove_selected
        ).pack(fill="x", pady=6)
        ctk.CTkButton(
            coll_btns, text="Clear All", fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self.clear_all
        ).pack(fill="x", pady=6)

        # ---- Source pack + categories ----
        src_frame = ctk.CTkFrame(scroll_root)
        src_frame.pack(fill="x", padx=pad, pady=8)
        ctk.CTkLabel(
            src_frame, text="2. Import specific categories from ONE Source pack (optional)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            src_frame,
            text="Nothing is imported unless you check its box below. Example: check only "
                 "\u201cSwords\u201d to pull just the sword textures from the Source pack, "
                 "leaving everything else from your Collection untouched.",
            text_color="gray60", font=ctk.CTkFont(size=11), wraplength=800, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        src_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        src_row.pack(fill="x", padx=12, pady=(0, 10))
        self.source_label = ctk.CTkLabel(
            src_row, text="No source pack selected.", text_color="gray60", anchor="w"
        )
        self.source_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(src_row, text="Choose Source Pack", command=self.choose_source_pack).pack(
            side="left", padx=(8, 4)
        )
        ctk.CTkButton(
            src_row, text="Clear", fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), width=70, command=self.clear_source_pack,
        ).pack(side="left")

        cat_grid = ctk.CTkFrame(src_frame, fg_color="transparent")
        cat_grid.pack(fill="x", padx=12, pady=(0, 12))
        cols = 3
        for idx, cat in enumerate(CATEGORY_ORDER):
            var = ctk.BooleanVar(value=False)
            self.category_vars[cat] = var
            cb = ctk.CTkCheckBox(cat_grid, text=cat,
                                 variable=var, font=ctk.CTkFont(size=12))
            cb.grid(row=idx // cols, column=idx %
                    cols, sticky="w", padx=8, pady=6)
        for c in range(cols):
            cat_grid.columnconfigure(c, weight=1)

        # ---- Icon ----
        icon_frame = ctk.CTkFrame(scroll_root)
        icon_frame.pack(fill="x", padx=pad, pady=8)
        ctk.CTkLabel(
            icon_frame, text="3. Pack icon (optional)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))
        icon_row = ctk.CTkFrame(icon_frame, fg_color="transparent")
        icon_row.pack(fill="x", padx=12, pady=(0, 12))
        self.icon_label = ctk.CTkLabel(
            icon_row,
            text="No custom icon \u2014 will use pack.png from a Collection pack if one exists.",
            text_color="gray60", anchor="w", wraplength=500,
        )
        self.icon_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(icon_row, text="Choose Icon (PNG)", command=self.choose_icon).pack(
            side="left", padx=(8, 4)
        )
        ctk.CTkButton(
            icon_row, text="Clear", fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), width=70, command=self.clear_icon,
        ).pack(side="left")

        # ---- Advanced ----
        adv_frame = ctk.CTkFrame(scroll_root, fg_color="transparent")
        adv_frame.pack(fill="x", padx=pad, pady=(0, 8))
        ctk.CTkButton(
            adv_frame, text="\U0001F50D Advanced: override individual files",
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=self.open_advanced_window,
        ).pack(fill="x")

        # ---- Safety toggle ----
        safety_row = ctk.CTkFrame(
            scroll_root, fg_color="#1f2937", corner_radius=8)
        safety_row.pack(fill="x", padx=pad, pady=8)
        ctk.CTkCheckBox(
            safety_row, text="\U0001F6E1\uFE0F Safety-check packs (recommended)",
            variable=self.safety_enabled, font=ctk.CTkFont(
                size=12, weight="bold"),
        ).pack(side="left", padx=12, pady=10)
        ctk.CTkLabel(
            safety_row,
            text="Flags suspicious file types, disguised files, and zip bombs. Basic "
                 "heuristic check, not a full antivirus.",
            text_color="#93c5fd", font=ctk.CTkFont(size=11),
            wraplength=480, justify="left",
        ).pack(side="left", padx=(0, 12), pady=10)

        # ---- Output ----
        out = ctk.CTkFrame(scroll_root)
        out.pack(fill="x", padx=pad, pady=8)
        ctk.CTkLabel(out, text="Output pack name:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        self.output_name = ctk.CTkEntry(out, placeholder_text="MyMergedPack")
        self.output_name.grid(
            row=0, column=1, sticky="ew", padx=10, pady=(10, 4))
        out.columnconfigure(1, weight=1)
        ctk.CTkLabel(out, text="Description (optional):").grid(
            row=1, column=0, sticky="w", padx=10, pady=(4, 10)
        )
        self.output_desc = ctk.CTkEntry(
            out, placeholder_text="Merged pack created with Lunar Pack Merger"
        )
        self.output_desc.grid(
            row=1, column=1, sticky="ew", padx=10, pady=(4, 10))

        # ---- Merge ----
        action = ctk.CTkFrame(scroll_root, fg_color="transparent")
        action.pack(fill="x", padx=pad, pady=(0, 6))
        self.merge_btn = ctk.CTkButton(
            action, text="Merge Packs", height=42,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.merge_packs,
        )
        self.merge_btn.pack(fill="x")
        self.progress = ctk.CTkProgressBar(action)
        self.progress.pack(fill="x", pady=(8, 0))
        self.progress.set(0)

        # ---- Log ----
        log_frame = ctk.CTkFrame(scroll_root)
        log_frame.pack(fill="both", expand=False, padx=pad, pady=(0, pad))
        ctk.CTkLabel(log_frame, text="Log", anchor="w").pack(
            fill="x", padx=10, pady=(8, 0))
        self.log_box = ctk.CTkTextbox(
            log_frame, height=140, font=ctk.CTkFont(size=11))
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self.log_box.configure(state="disabled")

        self._refresh_list()

    # -------------------------------------------------------------- helpers
    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.update_idletasks()

    def _refresh_list(self):
        for child in self.list_scroll.winfo_children():
            child.destroy()

        if not self.collection:
            ctk.CTkLabel(
                self.list_scroll, text="No packs added yet.", text_color="gray60",
            ).pack(pady=10)
            return

        for i, entry in enumerate(self.collection):
            row = ctk.CTkFrame(
                self.list_scroll,
                fg_color="#2563eb" if i == self.selected_index else "#242424",
                corner_radius=6,
            )
            row.pack(fill="x", pady=3, padx=2)
            row.bind("<Button-1>", lambda e, idx=i: self._select(idx))
            label = ctk.CTkLabel(row, text=entry.name,
                                 anchor="w", font=ctk.CTkFont(size=13))
            label.pack(side="left", padx=10, pady=8, fill="x", expand=True)
            label.bind("<Button-1>", lambda e, idx=i: self._select(idx))

    def _select(self, idx):
        self.selected_index = idx
        self._refresh_list()

    # -------------------------------------------------------------- safety
    def _run_safety_check(self, pack_path: str, pack_name: str, silent_if_clean=False):
        issues = safety_scan_pack(pack_path)
        high = [i for i in issues if i["severity"] == "high"]
        medium = [i for i in issues if i["severity"] == "medium"]

        if high:
            self.log(
                f"\U0001F534 SAFETY WARNING in {pack_name}: {len(high)} suspicious item(s) found.")
            messagebox.showwarning(
                "\u26A0\uFE0F Possible malicious content",
                f"\"{pack_name}\" contains suspicious content:\n\n"
                f"{format_issues(high)}\n\n"
                f"We recommend deleting this file immediately and not opening it in "
                f"Minecraft.\n\nNote: this is a basic automated check \u2014 not a full "
                f"antivirus scan. If you're unsure, also scan it with your antivirus or "
                f"upload it to virustotal.com.",
            )
        elif medium:
            self.log(
                f"\U0001F7E1 {pack_name}: {len(medium)} minor issue(s) flagged.")
        elif not silent_if_clean:
            self.log(f"\u2705 {pack_name}: no issues found.")

        return issues

    def check_selected_safety(self):
        i = self.selected_index
        if i is None:
            messagebox.showinfo(
                APP_TITLE, "Click a pack in the Collection list first.")
            return
        entry = self.collection[i]
        self.log(f"Running safety check on {entry.name}...")
        issues = self._run_safety_check(entry.path, entry.name)
        if not issues:
            messagebox.showinfo(
                APP_TITLE, f"\u2705 No issues found in \"{entry.name}\".")

    # -------------------------------------------------------------- actions
    def add_packs(self):
        paths = filedialog.askopenfilenames(
            title="Select resource pack .zip files", filetypes=[("Zip files", "*.zip")],
        )
        if not paths:
            return
        for p in paths:
            self.collection.append(PackEntry(p))
        self.log(f"Added {len(paths)} pack(s) to Collection.")
        self.file_index = {}
        if self.safety_enabled.get():
            for p in paths:
                self._run_safety_check(
                    p, os.path.basename(p), silent_if_clean=True)
        self._refresh_list()

    def remove_selected(self):
        i = self.selected_index
        if i is None:
            messagebox.showinfo(APP_TITLE, "Click a pack in the list first.")
            return
        removed = self.collection.pop(i)
        self.log(f"Removed {removed.name}.")
        self.selected_index = None
        self.file_index = {}
        self._prune_assignments()
        self._refresh_list()

    def clear_all(self):
        self.collection = []
        self.selected_index = None
        self.file_index = {}
        self.assignments = {}
        self._refresh_list()
        self.log("Cleared Collection.")

    def choose_source_pack(self):
        path = filedialog.askopenfilename(
            title="Select the Source pack", filetypes=[("Zip files", "*.zip")],
        )
        if not path:
            return
        self.source_pack = PackEntry(path)
        self.source_label.configure(
            text=f"Source: {self.source_pack.name}", text_color="white")
        self.log(f"Source pack set to {self.source_pack.name}.")
        if self.safety_enabled.get():
            self._run_safety_check(
                path, self.source_pack.name, silent_if_clean=True)

    def clear_source_pack(self):
        self.source_pack = None
        self.source_label.configure(
            text="No source pack selected.", text_color="gray60")
        for var in self.category_vars.values():
            var.set(False)

    def choose_icon(self):
        path = filedialog.askopenfilename(
            title="Select a pack icon", filetypes=[("PNG images", "*.png")],
        )
        if not path:
            return
        self.icon_path = path
        self.icon_label.configure(
            text=f"Icon: {os.path.basename(path)}", text_color="white")

    def clear_icon(self):
        self.icon_path = None
        self.icon_label.configure(
            text="No custom icon \u2014 will use pack.png from a Collection pack if one exists.",
            text_color="gray60",
        )

    def _prune_assignments(self):
        valid_paths = {p.path for p in self.collection}
        if self.source_pack:
            valid_paths.add(self.source_pack.path)
        self.assignments = {k: v for k,
                            v in self.assignments.items() if v in valid_paths}

    # -------------------------------------------------------- file scanning
    def scan_file_index(self):
        self.file_index = {}
        for entry in self.collection:
            try:
                with zipfile.ZipFile(entry.path, "r") as zf:
                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        parts = Path(name).parts
                        if any(p in JUNK_NAMES or p.startswith("._") for p in parts):
                            continue
                        rel = name.replace("\\", "/")
                        self.file_index.setdefault(rel, []).append(entry.path)
            except zipfile.BadZipFile:
                self.log(
                    f"\u26A0 Skipped {entry.name} \u2014 not a valid zip file.")
        self._prune_assignments()

    def default_winner(self, rel_path: str):
        owners = set(self.file_index.get(rel_path, []))
        for entry in self.collection:
            if entry.path in owners:
                return entry.path
        return None

    def winner_for(self, rel_path: str):
        assigned = self.assignments.get(rel_path)
        if assigned and assigned in self.file_index.get(rel_path, []):
            return assigned
        return self.default_winner(rel_path)

    # ---------------------------------------------------- advanced (popup)
    def open_advanced_window(self):
        if not self.collection:
            messagebox.showinfo(
                APP_TITLE, "Add at least one Collection pack first.")
            return

        self.log("Scanning packs for files...")
        self.scan_file_index()
        conflicts = sorted(
            p for p, owners in self.file_index.items() if len(set(owners)) > 1)
        self.log(
            f"Found {len(conflicts)} file(s) that differ across your Collection.")

        win = ctk.CTkToplevel(self)
        win.title("Advanced: override individual files")
        win.geometry("760x620")
        win.grab_set()

        tip = ("For fine control over one specific file (e.g. just diamond_sword.png), "
               "search for it here and preview before choosing.")
        if not PIL_AVAILABLE:
            tip += "\n(Preview needs the 'Pillow' package: pip install Pillow)"
        ctk.CTkLabel(
            win, text=tip, font=ctk.CTkFont(size=12), text_color="gray70",
            wraplength=720, justify="left",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        search_row = ctk.CTkFrame(win, fg_color="transparent")
        search_row.pack(fill="x", padx=14, pady=(0, 8))
        search_var = ctk.StringVar()
        ctk.CTkEntry(
            search_row, placeholder_text="Search files, e.g. diamond_sword...",
            textvariable=search_var,
        ).pack(fill="x")

        results_scroll = ctk.CTkScrollableFrame(win, label_text="Files")
        results_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        status_label = ctk.CTkLabel(win, text="Type above to search files.",
                                    text_color="gray60", font=ctk.CTkFont(size=11))
        status_label.pack(anchor="w", padx=14, pady=(0, 10))

        def render(filtered_paths):
            for child in results_scroll.winfo_children():
                child.destroy()
            shown = filtered_paths[:MAX_ADVANCED_ROWS]
            for rel_path in shown:
                owner_set = set(self.file_index[rel_path])
                owners = [p.path for p in self.collection if p.path in owner_set]
                owner_names = [os.path.basename(p) for p in owners]
                current_winner = self.winner_for(rel_path)
                current_name = os.path.basename(
                    current_winner) if current_winner else owner_names[0]
                path_by_name = {os.path.basename(p): p for p in owners}

                row = ctk.CTkFrame(
                    results_scroll, fg_color="#242424", corner_radius=6)
                row.pack(fill="x", pady=2, padx=2)
                ctk.CTkLabel(
                    row, text=rel_path, anchor="w", font=ctk.CTkFont(size=11), wraplength=340,
                ).pack(side="left", padx=(10, 6), pady=6, fill="x", expand=True)

                if PIL_AVAILABLE and rel_path.lower().endswith((".png", ".jpg", ".jpeg")):
                    ctk.CTkButton(
                        row, text="\U0001F441 Preview", width=90, fg_color="transparent",
                        border_width=1, text_color=("gray10", "gray90"),
                        command=lambda rp=rel_path, ow=owners, on=owner_names:
                            self.open_image_preview(rp, ow, on),
                    ).pack(side="right", padx=(0, 8), pady=6)

                def on_pick(choice, rp=rel_path, pbn=path_by_name):
                    self.assignments[rp] = pbn[choice]

                menu = ctk.CTkOptionMenu(
                    row, values=owner_names, width=160, command=on_pick)
                menu.set(current_name)
                menu.pack(side="right", padx=10, pady=6)

            extra = len(filtered_paths) - len(shown)
            if extra > 0:
                status_label.configure(
                    text=f"Showing {len(shown)} of {len(filtered_paths)} \u2014 narrow your "
                    f"search to see the rest ({extra} hidden)."
                )
            elif filtered_paths:
                status_label.configure(
                    text=f"Showing {len(shown)} of {len(filtered_paths)} matches.")
            else:
                status_label.configure(text="Type above to search files.")

        def on_search(*_):
            q = search_var.get().strip().lower()
            for child in results_scroll.winfo_children():
                child.destroy()
            if not q:
                status_label.configure(text="Type above to search files.")
                return
            render([p for p in conflicts if q in p.lower()])

        search_var.trace_add("write", on_search)
        ctk.CTkButton(win, text="Done", height=38, command=win.destroy).pack(
            fill="x", padx=14, pady=(0, 14)
        )

    def open_image_preview(self, rel_path, owners, owner_names):
        if not PIL_AVAILABLE:
            messagebox.showinfo(
                APP_TITLE, "Preview needs the 'Pillow' package.")
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Preview: {rel_path}")
        win.geometry("420x480")
        win.grab_set()
        ctk.CTkLabel(win, text=rel_path, font=ctk.CTkFont(size=12), wraplength=380).pack(
            padx=14, pady=(14, 6)
        )
        img_label = ctk.CTkLabel(win, text="")
        img_label.pack(padx=14, pady=6, fill="both", expand=True)
        path_by_name = dict(zip(owner_names, owners))

        def load(pack_name):
            pack_path = path_by_name[pack_name]
            try:
                with zipfile.ZipFile(pack_path, "r") as zf:
                    data = zf.read(rel_path)
                image = Image.open(io.BytesIO(data))
                image.thumbnail((360, 360), Image.NEAREST)
                ctk_img = ctk.CTkImage(
                    light_image=image, dark_image=image, size=image.size)
                img_label.configure(image=ctk_img, text="")
                img_label.image = ctk_img
            except Exception as e:
                img_label.configure(
                    image=None, text=f"Couldn't preview this file:\n{e}")

        picker = ctk.CTkOptionMenu(win, values=owner_names, command=load)
        picker.set(owner_names[0])
        picker.pack(padx=14, pady=(0, 14))
        load(owner_names[0])

    # -------------------------------------------------------------- merge
    def merge_packs(self):
        if not self.collection:
            messagebox.showwarning(
                APP_TITLE, "Add at least one Collection pack.")
            return

        checked_categories = {
            c for c, v in self.category_vars.items() if v.get()}
        if self.source_pack and not checked_categories:
            proceed = messagebox.askyesno(
                APP_TITLE,
                "You picked a Source pack but didn't check any categories, so nothing "
                "will be imported from it. Continue anyway?",
            )
            if not proceed:
                return

        packs_to_check = list(self.collection)
        if self.source_pack:
            packs_to_check.append(self.source_pack)

        if self.safety_enabled.get():
            self.log("Running safety check on all packs before merging...")
            blocking = []
            for entry in packs_to_check:
                issues = safety_scan_pack(entry.path)
                high = [i for i in issues if i["severity"] == "high"]
                if high:
                    blocking.append((entry.name, high))
            if blocking:
                details = "\n\n".join(
                    f"{name}:\n{format_issues(iss)}" for name, iss in blocking)
                self.log(
                    f"\U0001F534 Merge blocked \u2014 {len(blocking)} pack(s) flagged.")
                messagebox.showerror(
                    "\u26A0\uFE0F Merge blocked \u2014 possible malicious content",
                    f"Flagged and stopped:\n\n{details}\n\nRemove the flagged pack(s), or "
                    f"turn off \u201cSafety-check packs\u201d if you're sure it's a false "
                    f"positive, then try again.",
                )
                return

        out_name = self.output_name.get().strip() or "MergedPack"
        out_name = "".join(c for c in out_name if c not in '\\/:*?"<>|')

        dest = filedialog.asksaveasfilename(
            title="Save merged pack as...", defaultextension=".zip",
            initialfile=f"{out_name}.zip", filetypes=[("Zip files", "*.zip")],
        )
        if not dest:
            return

        self.merge_btn.configure(state="disabled", text="Merging...")
        self.progress.set(0)
        self.log("---- Starting merge ----")
        self.log(f"Collection: {', '.join(p.name for p in self.collection)}")
        if self.source_pack and checked_categories:
            self.log(
                f"Importing from {self.source_pack.name}: {', '.join(sorted(checked_categories))}")

        try:
            self._do_merge(dest, checked_categories)
            self.log(f"\u2705 Done! Saved to: {dest}")
            messagebox.showinfo(APP_TITLE, f"Merged pack saved to:\n{dest}")
        except Exception as e:
            self.log(f"\u274C Error: {e}")
            self.log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"Merge failed:\n{e}")
        finally:
            self.merge_btn.configure(state="normal", text="Merge Packs")
            self.progress.set(1)

    def _do_merge(self, dest_path: str, checked_categories: set):
        self.log("Scanning Collection for files...")
        self.scan_file_index()

        imported_count = 0
        if self.source_pack and checked_categories:
            self.log(f"Scanning Source pack ({self.source_pack.name})...")
            try:
                with zipfile.ZipFile(self.source_pack.path, "r") as zf:
                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        parts = Path(name).parts
                        if any(p in JUNK_NAMES or p.startswith("._") for p in parts):
                            continue
                        rel = name.replace("\\", "/")
                        if categorize(rel) in checked_categories:
                            self.file_index.setdefault(rel, [])
                            if self.source_pack.path not in self.file_index[rel]:
                                self.file_index[rel].append(
                                    self.source_pack.path)
                            self.assignments[rel] = self.source_pack.path
                            imported_count += 1
            except zipfile.BadZipFile:
                self.log(
                    f"\u26A0 Could not read Source pack \u2014 not a valid zip.")

        zip_handles = {}
        try:
            for entry in self.collection:
                zip_handles[entry.path] = zipfile.ZipFile(entry.path, "r")
            if self.source_pack:
                zip_handles[self.source_pack.path] = zipfile.ZipFile(
                    self.source_pack.path, "r")

            with tempfile.TemporaryDirectory(prefix="lunarpackmerger_") as tmp:
                merged_root = Path(tmp) / "merged"
                merged_root.mkdir()

                total = len(self.file_index)
                for i, (rel_path, owners) in enumerate(self.file_index.items(), start=1):
                    winner_path = self.winner_for(rel_path)
                    if winner_path is None:
                        continue
                    target = merged_root / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zip_handles[winner_path].open(rel_path) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                    if i % 50 == 0:
                        self.progress.set(min(i / max(total, 1), 0.95))
                        self.update_idletasks()

                if self.icon_path:
                    shutil.copyfile(self.icon_path, merged_root / "pack.png")
                    self.log("Applied custom pack icon.")

                mcmeta_path = merged_root / "pack.mcmeta"
                if not mcmeta_path.exists():
                    desc = self.output_desc.get().strip() or \
                        "Merged pack created with Lunar Pack Merger"
                    mcmeta_path.write_text(
                        DEFAULT_MCMETA.replace(
                            "Merged pack created with Lunar Pack Merger", desc
                        ),
                        encoding="utf-8",
                    )
                    self.log(
                        "No pack.mcmeta found in inputs \u2014 wrote a default one.")

                if imported_count:
                    self.log(
                        f"Imported {imported_count} file(s) from Source pack.")

                self.log("Zipping merged output...")
                self._zip_dir(merged_root, dest_path)
        finally:
            for zf in zip_handles.values():
                zf.close()

    def _zip_dir(self, src_dir: Path, dest_zip: str):
        if os.path.exists(dest_zip):
            os.remove(dest_zip)
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(src_dir):
                for f in files:
                    full = Path(root) / f
                    arcname = full.relative_to(src_dir)
                    zf.write(full, arcname)


def main():
    app = MergerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
