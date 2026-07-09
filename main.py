"""
Lunar Pack Merger
------------------
A small utility to merge multiple Minecraft (1.8.9 / Lunar Client) resource
pack .zip files into a single combined pack, with a priority order you
control (top of the list wins on file conflicts).

No network access, no telemetry, no personal data collected or embedded.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "Lunar Pack Merger"
APP_VERSION = "1.0.0"

# Files/folders that commonly show up in zips and should never be copied
JUNK_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}

DEFAULT_MCMETA = """{
  "pack": {
    "pack_format": 1,
    "description": "Merged pack created with Lunar Pack Merger"
  }
}
"""


class PackEntry:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)


class MergerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("760x640")
        self.minsize(680, 560)

        self.packs: list[PackEntry] = []
        self.selected_index: int | None = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = 16

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=pad, pady=(pad, 4))

        ctk.CTkLabel(
            header, text="Lunar Pack Merger",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Combine multiple resource packs into one. "
                 "Reorder the list below — packs higher up win when files clash.",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # Tip banner
        tip = ctk.CTkFrame(self, fg_color="#1f2937", corner_radius=8)
        tip.pack(fill="x", padx=pad, pady=(8, 8))
        ctk.CTkLabel(
            tip,
            text="💡 Recommended: put your main / base pack (the one with the most "
                 "textures, e.g. a full PvP pack) at the TOP. Small add-on packs "
                 "(GUI-only, cape, HUD tweaks) work best lower down, so they only "
                 "overwrite the few files they actually change.",
            font=ctk.CTkFont(size=12),
            wraplength=700,
            justify="left",
            text_color="#93c5fd",
        ).pack(padx=12, pady=10, anchor="w")

        # Main body: list + buttons
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=pad, pady=0)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        list_frame = ctk.CTkFrame(body)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.list_scroll = ctk.CTkScrollableFrame(
            list_frame, label_text="Packs (top = highest priority)"
        )
        self.list_scroll.pack(fill="both", expand=True, padx=8, pady=8)

        btns = ctk.CTkFrame(body, fg_color="transparent", width=160)
        btns.grid(row=0, column=1, sticky="ns")

        ctk.CTkButton(btns, text="＋ Add Pack(s)", command=self.add_packs).pack(
            fill="x", pady=(0, 8)
        )
        ctk.CTkButton(btns, text="↑ Move Up", command=self.move_up).pack(
            fill="x", pady=4
        )
        ctk.CTkButton(btns, text="↓ Move Down", command=self.move_down).pack(
            fill="x", pady=4
        )
        ctk.CTkButton(
            btns, text="✕ Remove", fg_color="#7f1d1d", hover_color="#991b1b",
            command=self.remove_selected
        ).pack(fill="x", pady=(4, 20))

        ctk.CTkButton(
            btns, text="Clear All", fg_color="transparent",
            border_width=1, text_color=("gray10", "gray90"),
            command=self.clear_all
        ).pack(fill="x", pady=4)

        # Output section
        out = ctk.CTkFrame(self)
        out.pack(fill="x", padx=pad, pady=(10, 8))

        ctk.CTkLabel(out, text="Output pack name:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        self.output_name = ctk.CTkEntry(out, placeholder_text="MyMergedPack")
        self.output_name.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 4))
        out.columnconfigure(1, weight=1)

        ctk.CTkLabel(out, text="Description (optional):").grid(
            row=1, column=0, sticky="w", padx=10, pady=(4, 10)
        )
        self.output_desc = ctk.CTkEntry(
            out, placeholder_text="Merged pack created with Lunar Pack Merger"
        )
        self.output_desc.grid(row=1, column=1, sticky="ew", padx=10, pady=(4, 10))

        # Merge button + progress
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.pack(fill="x", padx=pad, pady=(0, 6))

        self.merge_btn = ctk.CTkButton(
            action, text="Merge Packs", height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.merge_packs,
        )
        self.merge_btn.pack(fill="x")

        self.progress = ctk.CTkProgressBar(action)
        self.progress.pack(fill="x", pady=(8, 0))
        self.progress.set(0)

        # Log box
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=False, padx=pad, pady=(0, pad))
        ctk.CTkLabel(log_frame, text="Log", anchor="w").pack(
            fill="x", padx=10, pady=(8, 0)
        )
        self.log_box = ctk.CTkTextbox(log_frame, height=120, font=ctk.CTkFont(size=11))
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

        if not self.packs:
            ctk.CTkLabel(
                self.list_scroll,
                text="No packs added yet. Click “Add Pack(s)” to choose .zip files.",
                text_color="gray60",
            ).pack(pady=20)
            return

        for i, entry in enumerate(self.packs):
            row = ctk.CTkFrame(
                self.list_scroll,
                fg_color="#2563eb" if i == self.selected_index else "#242424",
                corner_radius=6,
            )
            row.pack(fill="x", pady=3, padx=2)
            row.bind("<Button-1>", lambda e, idx=i: self._select(idx))

            tag = "🔝 " if i == 0 else f"{i + 1}. "
            label = ctk.CTkLabel(
                row, text=f"{tag}{entry.name}", anchor="w",
                font=ctk.CTkFont(size=13, weight="bold" if i == 0 else "normal"),
            )
            label.pack(side="left", padx=10, pady=8, fill="x", expand=True)
            label.bind("<Button-1>", lambda e, idx=i: self._select(idx))

            if i == 0 and len(self.packs) > 1:
                ctk.CTkLabel(
                    row, text="highest priority", text_color="#bfdbfe",
                    font=ctk.CTkFont(size=10, slant="italic"),
                ).pack(side="right", padx=10)

    def _select(self, idx):
        self.selected_index = idx
        self._refresh_list()

    # -------------------------------------------------------------- actions
    def add_packs(self):
        paths = filedialog.askopenfilenames(
            title="Select resource pack .zip files",
            filetypes=[("Zip files", "*.zip")],
        )
        if not paths:
            return
        for p in paths:
            self.packs.append(PackEntry(p))
        self.log(f"Added {len(paths)} pack(s).")
        self._refresh_list()

    def move_up(self):
        i = self.selected_index
        if i is None or i == 0:
            return
        self.packs[i - 1], self.packs[i] = self.packs[i], self.packs[i - 1]
        self.selected_index = i - 1
        self._refresh_list()

    def move_down(self):
        i = self.selected_index
        if i is None or i >= len(self.packs) - 1:
            return
        self.packs[i + 1], self.packs[i] = self.packs[i], self.packs[i + 1]
        self.selected_index = i + 1
        self._refresh_list()

    def remove_selected(self):
        i = self.selected_index
        if i is None:
            return
        removed = self.packs.pop(i)
        self.log(f"Removed {removed.name}.")
        self.selected_index = None
        self._refresh_list()

    def clear_all(self):
        self.packs = []
        self.selected_index = None
        self._refresh_list()
        self.log("Cleared list.")

    # -------------------------------------------------------------- merge
    def merge_packs(self):
        if len(self.packs) < 2:
            messagebox.showwarning(
                APP_TITLE, "Add at least two packs to merge."
            )
            return

        out_name = self.output_name.get().strip() or "MergedPack"
        out_name = "".join(c for c in out_name if c not in '\\/:*?"<>|')

        dest = filedialog.asksaveasfilename(
            title="Save merged pack as...",
            defaultextension=".zip",
            initialfile=f"{out_name}.zip",
            filetypes=[("Zip files", "*.zip")],
        )
        if not dest:
            return

        self.merge_btn.configure(state="disabled", text="Merging...")
        self.progress.set(0)
        self.log("---- Starting merge ----")

        try:
            self._do_merge(dest, out_name)
            self.log(f"✅ Done! Saved to: {dest}")
            messagebox.showinfo(APP_TITLE, f"Merged pack saved to:\n{dest}")
        except Exception as e:
            self.log(f"❌ Error: {e}")
            self.log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"Merge failed:\n{e}")
        finally:
            self.merge_btn.configure(state="normal", text="Merge Packs")
            self.progress.set(1)

    def _do_merge(self, dest_path: str, out_name: str):
        # Priority order in self.packs is top = highest priority.
        # We extract lowest priority first, then overwrite with higher
        # priority packs on top, so the final file on disk is whichever
        # pack "wins" that conflict.
        extract_order = list(reversed(self.packs))  # lowest -> highest

        with tempfile.TemporaryDirectory(prefix="lunarpackmerger_") as tmp:
            merged_root = Path(tmp) / "merged"
            merged_root.mkdir()

            conflicts = {}  # relative path -> pack name that currently owns it
            total = len(extract_order)

            for step, entry in enumerate(extract_order, start=1):
                self.log(f"Extracting: {entry.name}")
                self._extract_zip_flat(entry.path, merged_root, entry.name, conflicts)
                self.progress.set(step / (total + 1))
                self.update_idletasks()

            # pack.mcmeta: prefer the highest priority pack's own mcmeta if
            # it has one, otherwise write a default one.
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
                self.log("No pack.mcmeta found in inputs — wrote a default one.")

            self.log(f"Total conflicting files resolved: "
                      f"{sum(1 for v in conflicts.values() if v['count'] > 1)}")

            self.log("Zipping merged output...")
            self._zip_dir(merged_root, dest_path)

    def _extract_zip_flat(self, zip_path, dest_root: Path, pack_name: str, conflicts: dict):
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                # skip directories, junk files
                if name.endswith("/"):
                    continue
                parts = Path(name).parts
                if any(p in JUNK_NAMES or p.startswith("._") for p in parts):
                    continue

                target = dest_root / name
                target.parent.mkdir(parents=True, exist_ok=True)

                rel = name.replace("\\", "/")
                if rel in conflicts:
                    conflicts[rel]["count"] += 1
                    conflicts[rel]["owner"] = pack_name
                    self.log(f"  ⚠ conflict: {rel}  (now from {pack_name})")
                else:
                    conflicts[rel] = {"owner": pack_name, "count": 1}

                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)

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
