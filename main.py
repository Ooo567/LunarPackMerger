"""
Lunar Pack Merger
------------------
A small utility to merge multiple Minecraft (1.8.9 / Lunar Client) resource
pack .zip files into a single combined pack.

Two ways to control conflicts:
  1. Priority order (drag packs up/down — top wins ties by default)
  2. Per-file overrides (search e.g. "sword", pick which pack wins that
     specific file, apply to one file or in bulk to every search match)

No network access, no telemetry, no personal data collected or embedded.
"""

import os
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
APP_VERSION = "1.1.0"

JUNK_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}

DEFAULT_MCMETA = """{
  "pack": {
    "pack_format": 1,
    "description": "Merged pack created with Lunar Pack Merger"
  }
}
"""

MAX_REVIEW_ROWS = 400  # cap rendered rows for performance; narrow the search to see more


class PackEntry:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)


class MergerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("820x680")
        self.minsize(720, 580)

        self.packs: list[PackEntry] = []
        self.selected_index: int | None = None

        # rel_path -> list of pack paths that contain that file
        self.file_index: dict[str, list[str]] = {}
        # rel_path -> pack path chosen to win (explicit override)
        self.assignments: dict[str, str] = {}

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
            text="Combine multiple resource packs into one. Reorder for default "
                 "priority, or use \u201cReview & Assign Files\u201d to control specific "
                 "files (like which pack's sword texture wins).",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        tip = ctk.CTkFrame(self, fg_color="#1f2937", corner_radius=8)
        tip.pack(fill="x", padx=pad, pady=(8, 8))
        ctk.CTkLabel(
            tip,
            text="\U0001F4A1 Quick default: order matters (top = wins ties). Want "
                 "more control? Click \u201cReview & Assign Files\u201d below, search "
                 "e.g. \"sword\", and pick which pack wins \u2014 you can apply the "
                 "same pack to every matching file in one click.",
            font=ctk.CTkFont(size=12),
            wraplength=760,
            justify="left",
            text_color="#93c5fd",
        ).pack(padx=12, pady=10, anchor="w")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=pad, pady=0)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        list_frame = ctk.CTkFrame(body)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.list_scroll = ctk.CTkScrollableFrame(
            list_frame, label_text="Packs (top = default priority)"
        )
        self.list_scroll.pack(fill="both", expand=True, padx=8, pady=8)

        btns = ctk.CTkFrame(body, fg_color="transparent", width=180)
        btns.grid(row=0, column=1, sticky="ns")

        ctk.CTkButton(btns, text="\uFF0B Add Pack(s)", command=self.add_packs).pack(
            fill="x", pady=(0, 8)
        )
        ctk.CTkButton(btns, text="\u2191 Move Up", command=self.move_up).pack(
            fill="x", pady=4
        )
        ctk.CTkButton(btns, text="\u2193 Move Down", command=self.move_down).pack(
            fill="x", pady=4
        )
        ctk.CTkButton(
            btns, text="\u2715 Remove", fg_color="#7f1d1d", hover_color="#991b1b",
            command=self.remove_selected
        ).pack(fill="x", pady=(4, 16))

        ctk.CTkButton(
            btns, text="\U0001F50D Review &\nAssign Files", height=44,
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=self.open_review_window,
        ).pack(fill="x", pady=(0, 16))

        ctk.CTkButton(
            btns, text="Clear All", fg_color="transparent",
            border_width=1, text_color=("gray10", "gray90"),
            command=self.clear_all
        ).pack(fill="x", pady=4)

        out = ctk.CTkFrame(self)
        out.pack(fill="x", padx=pad, pady=(10, 8))

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

        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=False, padx=pad, pady=(0, pad))
        ctk.CTkLabel(log_frame, text="Log", anchor="w").pack(
            fill="x", padx=10, pady=(8, 0)
        )
        self.log_box = ctk.CTkTextbox(
            log_frame, height=120, font=ctk.CTkFont(size=11))
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
                text="No packs added yet. Click \u201cAdd Pack(s)\u201d to choose .zip files.",
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

            tag = "\U0001F51D " if i == 0 else f"{i + 1}. "
            label = ctk.CTkLabel(
                row, text=f"{tag}{entry.name}", anchor="w",
                font=ctk.CTkFont(
                    size=13, weight="bold" if i == 0 else "normal"),
            )
            label.pack(side="left", padx=10, pady=8, fill="x", expand=True)
            label.bind("<Button-1>", lambda e, idx=i: self._select(idx))

            if i == 0 and len(self.packs) > 1:
                ctk.CTkLabel(
                    row, text="default priority", text_color="#bfdbfe",
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
        self.file_index = {}  # stale, rebuild on next review/merge
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
        self.file_index = {}
        self._prune_assignments()
        self._refresh_list()

    def clear_all(self):
        self.packs = []
        self.selected_index = None
        self.file_index = {}
        self.assignments = {}
        self._refresh_list()
        self.log("Cleared list.")

    def _prune_assignments(self):
        valid_paths = {p.path for p in self.packs}
        self.assignments = {
            k: v for k, v in self.assignments.items() if v in valid_paths
        }

    # -------------------------------------------------------- file scanning
    def scan_file_index(self):
        """Build rel_path -> [pack.path, ...] by reading zip namelists only
        (no extraction), so this is fast even with many/large packs."""
        self.file_index = {}
        for entry in self.packs:
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
        """Top-most pack (current order) that contains this file."""
        owners = set(self.file_index.get(rel_path, []))
        for entry in self.packs:
            if entry.path in owners:
                return entry.path
        return None

    def winner_for(self, rel_path: str):
        assigned = self.assignments.get(rel_path)
        if assigned and assigned in self.file_index.get(rel_path, []):
            return assigned
        return self.default_winner(rel_path)

    # -------------------------------------------------------- review window
    def open_review_window(self):
        if len(self.packs) < 2:
            messagebox.showinfo(APP_TITLE, "Add at least two packs first.")
            return

        self.log("Scanning packs for files...")
        self.scan_file_index()
        conflicts = sorted(
            path for path, owners in self.file_index.items() if len(set(owners)) > 1
        )
        self.log(
            f"Found {len(conflicts)} file(s) that appear in more than one pack.")

        win = ctk.CTkToplevel(self)
        win.title("Review & Assign Files")
        win.geometry("780x600")
        win.grab_set()

        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 6))

        ctk.CTkLabel(
            top,
            text=f"{len(conflicts)} conflicting file(s). Search to narrow down, "
            f"then assign one file or bulk-apply to every match.",
            font=ctk.CTkFont(size=12), text_color="gray70", wraplength=720,
            justify="left",
        ).pack(anchor="w")

        search_row = ctk.CTkFrame(win, fg_color="transparent")
        search_row.pack(fill="x", padx=14, pady=(4, 4))

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            search_row, placeholder_text="Search files, e.g. sword, gui, cape...",
            textvariable=search_var,
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        pack_names = [p.name for p in self.packs]
        path_by_name = {p.name: p.path for p in self.packs}

        bulk_row = ctk.CTkFrame(win, fg_color="transparent")
        bulk_row.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(bulk_row, text="Bulk-assign filtered results to:").pack(
            side="left", padx=(0, 8)
        )
        bulk_choice = ctk.StringVar(value=pack_names[0] if pack_names else "")
        bulk_menu = ctk.CTkOptionMenu(
            bulk_row, values=pack_names, variable=bulk_choice)
        bulk_menu.pack(side="left", padx=(0, 8))

        results_scroll = ctk.CTkScrollableFrame(win, label_text="Files")
        results_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        status_label = ctk.CTkLabel(
            win, text="", text_color="gray60", font=ctk.CTkFont(size=11))
        status_label.pack(anchor="w", padx=14, pady=(0, 10))

        row_widgets = {}

        def render(filtered_paths):
            for child in results_scroll.winfo_children():
                child.destroy()
            row_widgets.clear()

            shown = filtered_paths[:MAX_REVIEW_ROWS]
            for rel_path in shown:
                owner_set = set(self.file_index[rel_path])
                owners = [p.path for p in self.packs if p.path in owner_set]
                owner_names = [os.path.basename(p) for p in owners]
                current_winner = self.winner_for(rel_path)
                current_name = os.path.basename(
                    current_winner) if current_winner else owner_names[0]

                row = ctk.CTkFrame(
                    results_scroll, fg_color="#242424", corner_radius=6)
                row.pack(fill="x", pady=2, padx=2)

                ctk.CTkLabel(
                    row, text=rel_path, anchor="w", font=ctk.CTkFont(size=11),
                    wraplength=420,
                ).pack(side="left", padx=(10, 6), pady=6, fill="x", expand=True)

                def on_pick(choice, rp=rel_path):
                    self.assignments[rp] = path_by_name[choice]

                menu = ctk.CTkOptionMenu(
                    row, values=owner_names, width=170,
                    command=on_pick,
                )
                menu.set(current_name)
                menu.pack(side="right", padx=10, pady=6)
                row_widgets[rel_path] = menu

            extra = len(filtered_paths) - len(shown)
            if extra > 0:
                status_label.configure(
                    text=f"Showing {len(shown)} of {len(filtered_paths)} matches \u2014 "
                    f"narrow your search to see the rest ({extra} hidden)."
                )
            else:
                status_label.configure(
                    text=f"Showing {len(shown)} of {len(filtered_paths)} matches.")

        def current_filtered():
            q = search_var.get().strip().lower()
            if not q:
                return conflicts
            return [p for p in conflicts if q in p.lower()]

        def on_search(*_):
            render(current_filtered())

        search_var.trace_add("write", on_search)

        def apply_bulk():
            target_name = bulk_choice.get()
            target_path = path_by_name.get(target_name)
            if not target_path:
                return
            count = 0
            for rel_path in current_filtered():
                if target_path in set(self.file_index.get(rel_path, [])):
                    self.assignments[rel_path] = target_path
                    count += 1
            render(current_filtered())
            status_label.configure(
                text=f"Assigned {target_name} to {count} matching file(s)."
            )

        def reset_bulk():
            count = 0
            for rel_path in current_filtered():
                if rel_path in self.assignments:
                    del self.assignments[rel_path]
                    count += 1
            render(current_filtered())
            status_label.configure(
                text=f"Reset {count} file(s) to default priority order.")

        ctk.CTkButton(bulk_row, text="Apply to Filtered", command=apply_bulk).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            bulk_row, text="Reset Filtered to Default", fg_color="transparent",
            border_width=1, text_color=("gray10", "gray90"), command=reset_bulk,
        ).pack(side="left")

        ctk.CTkButton(win, text="Done", command=win.destroy, height=38).pack(
            fill="x", padx=14, pady=(0, 14)
        )

        render(conflicts)

    # -------------------------------------------------------------- merge
    def merge_packs(self):
        if len(self.packs) < 2:
            messagebox.showwarning(
                APP_TITLE, "Add at least two packs to merge.")
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
            self._do_merge(dest)
            self.log(f"\u2705 Done! Saved to: {dest}")
            messagebox.showinfo(APP_TITLE, f"Merged pack saved to:\n{dest}")
        except Exception as e:
            self.log(f"\u274C Error: {e}")
            self.log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"Merge failed:\n{e}")
        finally:
            self.merge_btn.configure(state="normal", text="Merge Packs")
            self.progress.set(1)

    def _do_merge(self, dest_path: str):
        self.log("Scanning packs for files...")
        self.scan_file_index()

        zip_handles = {}
        try:
            for entry in self.packs:
                zip_handles[entry.path] = zipfile.ZipFile(entry.path, "r")

            with tempfile.TemporaryDirectory(prefix="lunarpackmerger_") as tmp:
                merged_root = Path(tmp) / "merged"
                merged_root.mkdir()

                total = len(self.file_index)
                conflict_count = 0
                override_count = 0

                for i, (rel_path, owners) in enumerate(self.file_index.items(), start=1):
                    unique_owners = set(owners)
                    if len(unique_owners) > 1:
                        conflict_count += 1
                    winner_path = self.winner_for(rel_path)
                    if winner_path is None:
                        continue
                    if rel_path in self.assignments and self.assignments[rel_path] == winner_path \
                            and len(unique_owners) > 1:
                        override_count += 1

                    target = merged_root / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zip_handles[winner_path].open(rel_path) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)

                    if i % 50 == 0:
                        self.progress.set(min(i / max(total, 1), 0.95))
                        self.update_idletasks()

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

                self.log(f"Conflicting files: {conflict_count} "
                         f"({override_count} resolved by your manual assignment, "
                         f"rest by pack priority order).")

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
