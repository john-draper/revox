#!/usr/bin/env python
"""
Revox â€” Modern GUI
Built with CustomTkinter. Provides a sleek, dark-themed interface for the pipeline.

Usage:
    python gui.py
"""

import os
import sys
import threading
import queue
import subprocess
import shutil
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print("CustomTkinter is not installed. Installing now...")
    subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter"], check=True)
    import customtkinter as ctk


# ---------------------------------------------------------------------------
# Theme Configuration
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Color palette
COLORS = {
    "bg": "#1a1a2e",
    "card": "#16213e",
    "card_light": "#1c2645",
    "accent": "#00c0ed",
    "accent_hover": "#0093b8",
    "accent_dark": "#006077",
    "success": "#00d68f",
    "warning": "#ffb547",
    "error": "#ff5252",
    "text": "#ffffff",
    "text_dim": "#8892b0",
    "text_dimmer": "#5a6788",
    "border": "#233356",
}

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".wmv", ".flv"}


# ---------------------------------------------------------------------------
# Pipeline Runner Thread
# ---------------------------------------------------------------------------


class PipelineRunner(threading.Thread):
    """Runs the pipeline in a background thread, streaming output via queue."""

    def __init__(self, cmd_queue: queue.Queue, log_queue: queue.Queue):
        super().__init__(daemon=True)
        self.cmd_queue = cmd_queue
        self.log_queue = log_queue

    def run(self):
        while True:
            try:
                task = self.cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if task is None:
                break

            cmd, label = task
            self.log_queue.put(("stage_start", label, ""))
            self.log_queue.put(("log", "", f"$ {' '.join(cmd)}\n"))

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=self._creation_flags(),
                )
                for line in process.stdout:
                    self.log_queue.put(("log", "", line))
                process.wait()
                rc = process.returncode
            except Exception as e:
                self.log_queue.put(("log", "", f"Error: {e}\n"))
                rc = 1

            self.log_queue.put(("stage_done", label, rc))

    @staticmethod
    def _creation_flags():
        """Hide console window on Windows."""
        if sys.platform == "win32":
            return 0x08000000  # CREATE_NO_WINDOW
        return 0


# ---------------------------------------------------------------------------
# Main GUI Window
# ---------------------------------------------------------------------------


class RevoxGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Window setup ---
        self.title("Revox")
        self.geometry("1000x720")
        self.minsize(850, 600)
        self.configure(fg_color=COLORS["bg"])

        # --- State ---
        self.audio_path = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value="output")
        self.provider = ctk.StringVar(value="fish-speech")
        self.is_running = False
        self.current_stage = 0
        self.total_stages = 5

        # Queues for thread communication
        self.cmd_queue = queue.Queue()
        self.log_queue = queue.Queue()

        # Stage tracking
        self.stage_labels = []
        self.stage_statuses = []  # "pending", "running", "done", "error"
        self.stage_callbacks = {}

        # Start the pipeline runner thread
        self.runner = PipelineRunner(self.cmd_queue, self.log_queue)
        self.runner.start()

        # Build UI
        self._build_ui()

        # Poll the log queue
        self.after(100, self._poll_queue)

    # -------------------------------------------------------------------
    # UI Construction
    # -------------------------------------------------------------------

    def _build_ui(self):
        """Build the entire UI layout."""

        # === Header Bar ===
        header = ctk.CTkFrame(self, fg_color=COLORS["card"], height=64, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        logo_frame = ctk.CTkFrame(header, fg_color="transparent")
        logo_frame.pack(side="left", padx=24, pady=12)

        logo_label = ctk.CTkLabel(
            logo_frame,
            text="ðŸŽ¬",
            font=(FONT_FAMILY, 28),
            width=40,
        )
        logo_label.pack(side="left", padx=(0, 12))

        title_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        title_frame.pack(side="left")

        ctk.CTkLabel(
            title_frame,
            text="Revox",
            font=(FONT_FAMILY, 20, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Rewrite the Vox — Clean audio, keep the video",
            font=(FONT_FAMILY, 12),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        # === Main Content ===
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=20)

        left = ctk.CTkFrame(main, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True)

        self._build_config_card(left)
        self._build_action_bar(left)
        self._build_stages_card(left)
        self._build_log_card(right)

    def _build_config_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 12))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header,
            text="âš™ï¸  Configuration",
            font=(FONT_FAMILY, 16, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")

        # File selection
        file_frame = ctk.CTkFrame(card, fg_color="transparent")
        file_frame.pack(fill="x", padx=20, pady=(4, 10))

        ctk.CTkLabel(
            file_frame,
            text="Video File:",
            font=(FONT_FAMILY, 13),
            text_color=COLORS["text_dim"],
            width=90,
            anchor="w",
        ).pack(side="left")

        self.file_entry = ctk.CTkEntry(
            file_frame,
            textvariable=self.audio_path,
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["card_light"],
            text_color=COLORS["text"],
            border_color=COLORS["border"],
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))

        ctk.CTkButton(
            file_frame,
            text="Browseâ€¦",
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["accent_dark"],
            hover_color=COLORS["accent"],
            width=90,
            command=self._browse_file,
        ).pack(side="left")

        # Output dir
        out_frame = ctk.CTkFrame(card, fg_color="transparent")
        out_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(
            out_frame,
            text="Output Folder:",
            font=(FONT_FAMILY, 13),
            text_color=COLORS["text_dim"],
            width=90,
            anchor="w",
        ).pack(side="left")

        ctk.CTkEntry(
            out_frame,
            textvariable=self.output_dir,
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["card_light"],
            text_color=COLORS["text"],
            border_color=COLORS["border"],
        ).pack(side="left", fill="x", expand=True, padx=(8, 8))

        ctk.CTkButton(
            out_frame,
            text="Browseâ€¦",
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["accent_dark"],
            hover_color=COLORS["accent"],
            width=90,
            command=self._browse_output,
        ).pack(side="left")

        # Provider
        prov_frame = ctk.CTkFrame(card, fg_color="transparent")
        prov_frame.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkLabel(
            prov_frame,
            text="TTS Provider:",
            font=(FONT_FAMILY, 13),
            text_color=COLORS["text_dim"],
            width=90,
            anchor="w",
        ).pack(side="left")

        ctk.CTkOptionMenu(
            prov_frame,
            variable=self.provider,
            values=["fish-speech", "elevenlabs"],
            font=(FONT_FAMILY, 13),
            fg_color=COLORS["card_light"],
            button_color=COLORS["accent_dark"],
            button_hover_color=COLORS["accent"],
            text_color=COLORS["text"],
            width=160,
        ).pack(side="left", padx=(8, 0))

    def _build_action_bar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))

        self.run_button = ctk.CTkButton(
            bar,
            text="â–¶  Start Pipeline",
            font=(FONT_FAMILY, 15, "bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            height=44,
            command=self._start_pipeline,
        )
        self.run_button.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_button = ctk.CTkButton(
            bar,
            text="âœ•  Cancel",
            font=(FONT_FAMILY, 14, "bold"),
            fg_color=COLORS["error"],
            hover_color="#cc3333",
            height=44,
            width=110,
            state="disabled",
            command=self._cancel_pipeline,
        )
        self.cancel_button.pack(side="left")

    def _build_stages_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        card.pack(fill="both", expand=True, pady=(0, 12))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header,
            text="ðŸ“‹  Pipeline Stages",
            font=(FONT_FAMILY, 16, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")

        # Progress
        prog_frame = ctk.CTkFrame(card, fg_color="transparent")
        prog_frame.pack(fill="x", padx=20, pady=(0, 12))

        self.overall_progress = ctk.CTkProgressBar(
            prog_frame,
            fg_color=COLORS["card_light"],
            progress_color=COLORS["accent"],
            height=8,
        )
        self.overall_progress.set(0)
        self.overall_progress.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.overall_label = ctk.CTkLabel(
            prog_frame,
            text="0%",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["accent"],
            width=40,
        )
        self.overall_label.pack(side="left")

        stages_container = ctk.CTkFrame(card, fg_color="transparent")
        stages_container.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        stages = [
            "Stage 1: Transcription",
            "Stage 2: Profanity Detection",
            "Stage 3: Reference Extraction",
            "Stage 4: Audio Generation",
            "Stage 5: Splicing + Video Mux",
        ]
        for s in stages:
            row = ctk.CTkFrame(stages_container, fg_color="transparent")
            row.pack(fill="x", pady=3)

            icon = ctk.CTkLabel(
                row,
                text="â—‹",
                font=(FONT_FAMILY, 18),
                text_color=COLORS["text_dimmer"],
                width=30,
            )
            icon.pack(side="left")

            name = ctk.CTkLabel(
                row,
                text=s,
                font=(FONT_FAMILY, 13),
                text_color=COLORS["text"],
                anchor="w",
            )
            name.pack(side="left", fill="x", expand=True)

            self.stage_labels.append((icon, name))
            self.stage_statuses.append("pending")

    def _build_log_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        card.pack(fill="both", expand=True)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            header,
            text="ðŸ–¥ï¸  Console Log",
            font=(FONT_FAMILY, 16, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="Clear",
            font=(FONT_FAMILY, 12),
            fg_color=COLORS["card_light"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_dim"],
            width=70,
            height=28,
            command=self._clear_log,
        ).pack(side="right")

        self.log_text = ctk.CTkTextbox(
            card,
            font=(FONT_MONO, 12),
            fg_color=COLORS["bg"],
            text_color=COLORS["text"],
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 16))

    # -------------------------------------------------------------------
    # File Browsers
    # -------------------------------------------------------------------

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select a Video File",
            filetypes=[
                ("Video files", "*.mkv *.mp4 *.m4v *.mov *.avi *.webm *.wmv *.flv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.audio_path.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_dir.set(path)

    # -------------------------------------------------------------------
    # Pipeline Control
    # -------------------------------------------------------------------

    def _start_pipeline(self):
        audio = self.audio_path.get().strip()
        if not audio:
            messagebox.showwarning("No File Selected", "Please select a video file first.")
            return
        if not Path(audio).is_file():
            messagebox.showerror("File Not Found", f"The file does not exist:\n{audio}")
            return

        self._reset_stages()

        self.is_running = True
        self.run_button.configure(state="disabled", text="â³  Runningâ€¦")
        self.cancel_button.configure(state="normal")
        self.file_entry.configure(state="disabled")

        output_dir = Path(self.output_dir.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        basename = Path(audio).stem
        input_ext = Path(audio).suffix.lower()
        out_ext = input_ext if input_ext in VIDEO_EXTS else ".mkv"

        words_json = str(output_dir / f"{basename}.json")
        replacements_json = str(output_dir / f"{basename}_replacements.json")
        ref_audio = str(output_dir / "reference_voice.wav")
        ref_text = str(output_dir / "reference_text.txt")
        audio_dir = str(output_dir / "generated_audio")
        final_output = str(output_dir / f"{basename}_censored{out_ext}")
        provider = self.provider.get()

        self.final_output = final_output
        self.output_dir_path = str(output_dir)

        py = sys.executable

        self._queue_stage(0, "Stage 1: Transcription", [
            py, "transcribe_whisperx.py", audio, "-o", words_json,
        ])
        self._queue_stage(1, "Stage 2: Profanity Detection", [
            py, "find_replacements.py", words_json, "-o", replacements_json,
        ])
        self._queue_stage(2, "Stage 3: Reference Extraction", [
            py, "extract_reference.py",
            "--audio", audio,
            "--words-json", words_json,
            "--output-audio", ref_audio,
            "--output-text", ref_text,
        ])
        self._queue_stage(3, "Stage 4: Audio Generation", [
            py, "generate_replacement_audio.py",
            replacements_json,
            "--output-dir", audio_dir,
            "--provider", provider,
            "--skip-existing",
            "--ref-audio", ref_audio,
            "--ref-text", ref_text,
        ])
        self._queue_stage(4, "Stage 5: Splicing + Video Mux", [
            py, "splice_audio.py",
            audio,
            "--replacements-json", replacements_json,
            "--audio-dir", audio_dir,
            "--output", final_output,
        ])

        self._log(f"\n{'='*60}\nStarting pipeline for: {audio}\nOutput: {output_dir}\nProvider: {provider}\n{'='*60}\n\n")

    def _queue_stage(self, idx: int, label: str, cmd: list):
        self.cmd_queue.put((cmd, label))

        def on_done(rc):
            if rc == 0:
                self._set_stage_status(idx, "done")
                self.current_stage = idx + 1
                self._update_progress()
            else:
                self._set_stage_status(idx, "error")
                self._on_pipeline_failed(label, rc)

        self.stage_callbacks[label] = on_done

    def _cancel_pipeline(self):
        if self.is_running:
            self._log("\n[CANCELLED] Pipeline cancelled by user.\n")
            self.is_running = False
            self._finish_pipeline()

    def _on_pipeline_failed(self, stage_name: str, rc: int):
        self._log(f"\n[FAILED] {stage_name} exited with code {rc}\n")
        self.is_running = False
        self._finish_pipeline()
        messagebox.showerror("Pipeline Failed", f"{stage_name} failed with exit code {rc}.\nCheck the console output for details.")

    # -------------------------------------------------------------------
    # Queue Polling
    # -------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                msg_type, label, content = self.log_queue.get_nowait()

                if msg_type == "log":
                    self._log(content)

                elif msg_type == "stage_start":
                    idx = self._get_stage_index(label)
                    if idx is not None:
                        self._set_stage_status(idx, "running")

                elif msg_type == "stage_done":
                    callback = self.stage_callbacks.get(label)
                    if callback:
                        callback(int(content) if content else 0)

                    if label == "Stage 5: Splicing + Video Mux" and int(content) == 0:
                        self._on_pipeline_success()

        except queue.Empty:
            pass

        self.after(100, self._poll_queue)

    def _get_stage_index(self, label: str) -> int | None:
        mapping = {
            "Stage 1: Transcription": 0,
            "Stage 2: Profanity Detection": 1,
            "Stage 3: Reference Extraction": 2,
            "Stage 4: Audio Generation": 3,
            "Stage 5: Splicing + Video Mux": 4,
        }
        return mapping.get(label)

    # -------------------------------------------------------------------
    # Stage Status Updates
    # -------------------------------------------------------------------

    def _set_stage_status(self, idx: int, status: str):
        if idx >= len(self.stage_labels):
            return
        self.stage_statuses[idx] = status
        icon, name = self.stage_labels[idx]

        if status == "running":
            icon.configure(text="â—", text_color=COLORS["accent"])
            name.configure(text_color=COLORS["accent"])
        elif status == "done":
            icon.configure(text="âœ“", text_color=COLORS["success"])
            name.configure(text_color=COLORS["success"])
        elif status == "error":
            icon.configure(text="âœ•", text_color=COLORS["error"])
            name.configure(text_color=COLORS["error"])
        else:
            icon.configure(text="â—‹", text_color=COLORS["text_dimmer"])
            name.configure(text_color=COLORS["text"])

    def _reset_stages(self):
        for i in range(len(self.stage_labels)):
            self._set_stage_status(i, "pending")
        self.current_stage = 0
        self.overall_progress.set(0)
        self.overall_label.configure(text="0%")

    def _update_progress(self):
        pct = self.current_stage / self.total_stages
        self.overall_progress.set(pct)
        self.overall_label.configure(text=f"{int(pct * 100)}%")

    # -------------------------------------------------------------------
    # Pipeline Completion
    # -------------------------------------------------------------------

    def _on_pipeline_success(self):
        self.is_running = False
        self._log(f"\n{'='*60}\n[SUCCESS] Pipeline complete!\nOutput: {getattr(self, 'final_output', 'N/A')}\n{'='*60}\n")
        self._finish_pipeline()

        result = messagebox.askyesno(
            "Pipeline Complete! ðŸŽ‰",
            "The video audio has been successfully censored.\n\nWould you like to open the output folder?",
        )
        if result:
            self._open_output_folder()

    def _finish_pipeline(self):
        self.run_button.configure(state="normal", text="â–¶  Start Pipeline")
        self.cancel_button.configure(state="disabled")
        self.file_entry.configure(state="normal")
        if self.current_stage == self.total_stages:
            self.overall_progress.set(1.0)
            self.overall_label.configure(text="100%")

    def _open_output_folder(self):
        out = getattr(self, "output_dir_path", self.output_dir.get())
        if sys.platform == "win32":
            os.startfile(out)
        elif sys.platform == "darwin":
            subprocess.run(["open", out])
        else:
            subprocess.run(["xdg-open", out])

    # -------------------------------------------------------------------
    # Log Helpers
    # -------------------------------------------------------------------

    def _log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = RevoxGUI()
    app.mainloop()
