"""
app.py  –  BudgetPal
Unified account model: every expense/goal builds an account toward a target.
Run:  python3 app.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime, date
import os, zipfile, copy, urllib.request, threading, json
import numpy as np
from collections import deque

import sys as _sys
# When frozen as a PyInstaller exe, use the exe's directory, not the temp bundle
if getattr(_sys, "frozen", False):
    APP_DIR = os.path.dirname(_sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

VERSION = "1.0.0"
try:
    with open(os.path.join(APP_DIR, "version.txt"), "r") as _vf:
        VERSION = _vf.readline().strip() or VERSION
except Exception:
    pass
REPO_RAW = "https://raw.githubusercontent.com/log-and43/BudgetPal/main"

import platform
IS_MAC = platform.system() == "Darwin"

from data_manager import (
    create_profile, load_profile, save_profile, profile_exists,
    uid_taken, make_uid, CURRENCIES, PAY_PERIODS,
    DAYS_OF_WEEK, DAYS_OF_MONTH, RECUR_OPTIONS, DEFAULT_THEME,
    PALETTES, PALETTE_NAMES,
    build_budget, apply_deposits, check_overdue, mark_paid,
    advance_due_date, _next_due_date, due_label_from, _ordinal, DATA_DIR,
)

def _ensure_pil():
    """Try to import PIL. On failure, attempt to install the missing package."""
    global PIL_AVAILABLE
    try:
        from PIL import Image, ImageTk
        PIL_AVAILABLE = True
        return
    except ImportError:
        pass

    # ImageTk missing — try to install silently
    import subprocess, sys
    PIL_AVAILABLE = False

    if platform.system() == "Linux":
        # Try apt first (Ubuntu/Debian), then pip
        result = subprocess.run(
            ["sudo", "apt-get", "install", "-y", "python3-pil.imagetk"],
            capture_output=True)
        if result.returncode != 0:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pillow",
                 "--break-system-packages"], capture_output=True)
    elif platform.system() == "Darwin":
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pillow"],
            capture_output=True)
    else:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pillow"],
            capture_output=True)

    # Try again after install
    try:
        from PIL import Image, ImageTk
        PIL_AVAILABLE = True
    except ImportError:
        PIL_AVAILABLE = False

_ensure_pil()
try:
    from PIL import Image, ImageTk
except ImportError:
    pass

BG_DIR = os.path.join(os.path.dirname(__file__), "backgrounds")
os.makedirs(BG_DIR, exist_ok=True)



# ── Theme helpers ─────────────────────────────────────────────────────────────
def _t(p, key): return p.get("theme", DEFAULT_THEME).get(key, DEFAULT_THEME.get(key,"#000"))
def _f(p, size=10, bold=False):
    face = p.get("theme",{}).get("font","Arial")
    return (face, size, "bold" if bold else "normal")


# ── Widget helpers ─────────────────────────────────────────────────────────────
def _lbl(parent, text, p=None, size=10, bold=False, fg=None, bg=None, **kw):
    font = _f(p, size, bold) if p else ("Arial", size, "bold" if bold else "normal")
    return tk.Label(parent, text=text, font=font,
                    fg=fg or (p and _t(p,"dark")) or "#2E4057",
                    bg=bg or (p and _t(p,"white")) or "#FFFFFF", **kw)

def _btn(parent, text, cmd, p=None, bg=None, fg="#FFFFFF", width=16, **kw):
    bg   = bg or (p and _t(p,"teal")) or "#048A81"
    font = _f(p, 10, True) if p else ("Arial",10,"bold")
    if IS_MAC:
        return tk.Button(parent, text=text, command=cmd,
                         font=font, width=width, cursor="hand2", **kw)
    return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                     font=font, width=width, relief="raised",
                     activebackground="#222", activeforeground="#FFF",
                     cursor="hand2", **kw)

def _raw_btn(parent, text, cmd, bg, fg, font, width, relief="raised", **kw):
    """Inline button that degrades gracefully on macOS."""
    if IS_MAC:
        return tk.Button(parent, text=text, command=cmd,
                         font=font, width=width, cursor="hand2", **kw)
    return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                     font=font, width=width, relief=relief,
                     cursor="hand2", **kw)

def _entry(parent, var=None, width=22, **kw):
    return ttk.Entry(parent, textvariable=var, width=width, font=("Arial",10), **kw)

def _combo(parent, var, values, width=14, **kw):
    return ttk.Combobox(parent, textvariable=var, values=values,
                        state="readonly", width=width, font=("Arial",10), **kw)

def _fmt(p, v):
    sym = CURRENCIES[p["currency"]]
    return f"{sym}{int(v):,}" if p["currency"]=="JPY" else f"{sym}{v:,.2f}"


# ── Scrollable frame ──────────────────────────────────────────────────────────
def _scrollable(parent, bg="#FFFFFF"):
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
    sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(fill="both", expand=True)
    frame = tk.Frame(canvas, bg=bg, padx=40, pady=20)
    win = canvas.create_window((0,0), window=frame, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind_all("<MouseWheel>",
        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
    return canvas, frame


# ── Separator label ───────────────────────────────────────────────────────────
def _sep(parent, text, color, bg, col=4):
    tk.Label(parent, text=f"── {text} ──", font=("Arial",10,"bold"),
             fg=color, bg=bg).grid(columnspan=col, pady=(18,4))


# ══════════════════════════════════════════════════════════════════════════════
class BudgetApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BudgetPal 💰")
        self.geometry("1020x740")
        self.minsize(860, 620)
        self.resizable(True, True)
        self.configure(bg="#FFFFFF")
        self.profile  = None
        self.bg_image = None
        self.bg_label = None
        self._build_style()
        self._show_landing()

    def _build_style(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("TEntry",    padding=4, font=("Arial",10))
        s.configure("TCombobox", padding=4, font=("Arial",10))
        s.configure("Treeview",  font=("Arial",10), rowheight=28)
        s.configure("Treeview.Heading", font=("Arial",10,"bold"),
                    background="#2E4057", foreground="white")
        s.map("Treeview", background=[("selected","#048A81")])

    def _apply_theme(self):
        if not self.profile: return
        p = self.profile; s = ttk.Style(self)
        s.configure("Treeview.Heading", background=_t(p,"dark"),
                    font=_f(p,10,True))
        s.map("Treeview", background=[("selected",_t(p,"teal"))])

    # ── Background ────────────────────────────────────────────────────────────
    def _set_bg(self, path):
        if not PIL_AVAILABLE:
            if platform.system() == "Linux":
                msg = "Run in terminal:\n  sudo apt install python3-pil.imagetk"
            else:
                msg = "Run in terminal:\n  pip3 install pillow"
            messagebox.showinfo("Pillow needed", msg); return
        try:
            img = Image.open(path).resize(
                (self.winfo_width() or 1020, self.winfo_height() or 740), Image.LANCZOS)
            self.bg_image = ImageTk.PhotoImage(img)
            try:
                if self.bg_label and self.bg_label.winfo_exists():
                    self.bg_label.destroy()
            except Exception:
                pass
            self.bg_label = tk.Label(self, image=self.bg_image)
            self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.bg_label.lower()
            self._bg_path = path
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _change_bg(self):
        path = filedialog.askopenfilename(
            title="Choose background image",
            filetypes=[("Images","*.png *.jpg *.jpeg *.gif *.bmp *.webp")])
        if path: self._set_bg(path)

    def _clear(self):
        for w in self.winfo_children():
            try:
                if w is not self.bg_label:
                    w.destroy()
            except Exception:
                pass
        # Reapply background if one was set
        if getattr(self, "_bg_path", None):
            try:
                img = Image.open(self._bg_path).resize(
                    (self.winfo_width() or 1020, self.winfo_height() or 740), Image.LANCZOS)
                self.bg_image = ImageTk.PhotoImage(img)
                self.bg_label = tk.Label(self, image=self.bg_image)
                self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
                self.bg_label.lower()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # PIGGY ANIMATION
    # ══════════════════════════════════════════════════════════════════════════

    def _play_piggy(self, on_done=None):
        if not PIL_AVAILABLE:
            if on_done: on_done()
            return

        # Support both filenames
        bg_dir = os.path.join(os.path.dirname(__file__), "backgrounds")
        gif_path = None
        for name in ("piggy_bank.gif", "piggybank.gif"):
            candidate = os.path.join(bg_dir, name)
            if os.path.exists(candidate):
                gif_path = candidate
                break

        if not gif_path:
            if on_done: on_done()
            return

        # ── Blurred backdrop ─────────────────────────────────────────────
        self.update_idletasks()
        try:
            from PIL import ImageGrab, ImageFilter
            screenshot = ImageGrab.grab(bbox=(
                self.winfo_rootx(), self.winfo_rooty(),
                self.winfo_rootx() + self.winfo_width(),
                self.winfo_rooty() + self.winfo_height(),
            ))
            blurred   = screenshot.filter(ImageFilter.GaussianBlur(radius=10))
            # Darken slightly so piggy pops
            darkened  = Image.blend(blurred, Image.new("RGB", blurred.size, "#000000"), 0.5)
            bg_photo  = ImageTk.PhotoImage(darkened)
        except Exception:
            bg_photo  = None

        backdrop = tk.Label(self, bd=0, highlightthickness=0)
        if bg_photo:
            backdrop.configure(image=bg_photo)
            backdrop._img = bg_photo
        else:
            backdrop.configure(bg="#000000")
        backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        backdrop.lift()

        # ── Load GIF frames ───────────────────────────────────────────────
        try:
            gif = Image.open(gif_path)
            frames = []
            bw = self.winfo_width()
            bh = self.winfo_height()
            for i in range(gif.n_frames):
                gif.seek(i)
                frame   = gif.convert("RGBA")
                resized = frame.resize((420, 315), Image.LANCZOS)
                # Composite onto a crop of the darkened backdrop so bg is invisible
                x = (bw - 420) // 2
                y = (bh - 315) // 2
                base = darkened.crop((x, y, x+420, y+315)).convert("RGBA")
                base.paste(resized, mask=resized)
                frames.append(ImageTk.PhotoImage(base))


        except Exception as e:
            backdrop.destroy()
            if on_done: on_done()
            return

        lbl = tk.Label(backdrop, bd=0, highlightthickness=0)
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        lbl._frames = frames
        idx = [0]

        def _next():
            idx[0] += 1
            if idx[0] >= len(frames):
                backdrop.destroy()
                if on_done: on_done()
                return
            lbl.configure(image=frames[idx[0]])
            self.after(40, _next)

        lbl.configure(image=frames[0])
        self.after(40, _next)

    # ══════════════════════════════════════════════════════════════════════════
    # AUTO-UPDATE
    # ══════════════════════════════════════════════════════════════════════════

    def _check_for_update(self, banner_parent):
        """
        Runs in a background thread. Fetches version.txt from GitHub.
        If a newer version exists, shows an update banner in banner_parent.
        """
        def _fetch():
            try:
                url  = f"{REPO_RAW}/version.txt"
                with urllib.request.urlopen(url, timeout=5) as r:
                    remote = r.read().decode().strip()
                print(f"Remote version: '{remote}', Local: '{VERSION}'")
                if self._version_newer(remote, VERSION):
                    self.after(0, lambda: self._show_update_banner(
                        banner_parent, remote))
            except Exception:
                pass  # silently ignore — no internet, repo missing, etc.
        threading.Thread(target=_fetch, daemon=True).start()

    def _version_newer(self, remote, local):
        """Return True if remote version > local version."""
        try:
            r = tuple(int(x) for x in remote.split("."))
            l = tuple(int(x) for x in local.split("."))
            return r > l
        except Exception:
            return False

    def _show_update_banner(self, parent, remote_version):
        """Show a dismissible update banner at the top of parent."""
        p = self.profile
        GOLD = _t(p, "gold") if p else "#F6AE2D"
        DARK = _t(p, "dark") if p else "#2E4057"

        banner = tk.Frame(parent, bg=GOLD, pady=6)
        banner.pack(fill="x", before=parent.winfo_children()[0]
                    if parent.winfo_children() else None)

        tk.Label(banner,
                 text=f"  Version {remote_version} is available!",
                 font=("Arial", 10, "bold"), fg=DARK, bg=GOLD).pack(side="left", padx=8)

        def _do_update():
            btn.configure(text="Updating...", state="disabled")
            banner.update_idletasks()
            threading.Thread(target=_run_update, daemon=True).start()

        def _write_update_handler():
            """
            Write an OS-specific update handler script next to the app.
            On Windows (frozen exe): rebuilds the exe via pip+pyinstaller,
            then relaunches. On Linux/Mac: just relaunches app.py.
            The script is launched on app exit via atexit.
            """
            import sys as _sys
            frozen = getattr(_sys, "frozen", False)
            system = platform.system()

            if system == "Windows" and frozen:
                # Windows: refreeze with PyInstaller then relaunch
                handler_path = os.path.join(APP_DIR, "budgetpal_update.bat")
                exe_path     = os.path.join(APP_DIR, "BudgetPal.exe")
                pyinstaller_cmd = (
                    "python -m PyInstaller --onefile --windowed --name BudgetPal"
                    " --add-data user_data;user_data"
                    " --add-data backgrounds;backgrounds"
                    " --hidden-import numpy"
                    " --hidden-import PIL --hidden-import PIL.Image"
                    " --hidden-import PIL.ImageTk --hidden-import PIL.ImageFilter"
                    " --hidden-import PIL.ImageGrab --hidden-import PIL.ImageEnhance"
                    " --clean --noconfirm app.py"
                )
                lines = [
                    "@echo off",
                    "title BudgetPal Update",
                    "echo.",
                    "echo  ========================================",
                    "echo   BudgetPal - Applying Update",
                    "echo  ========================================",
                    "echo.",
                    "echo  Installing dependencies...",
                    "pip install --upgrade openpyxl pillow numpy pyinstaller --quiet",
                    "echo  Rebuilding BudgetPal.exe (this takes 1-2 minutes)...",
                    'cd /d "' + APP_DIR + '"',
                    pyinstaller_cmd,
                    "copy /y dist\\BudgetPal.exe \"" + exe_path + "\"",
                    "echo  Update complete! Launching BudgetPal...",
                    'start "" "' + exe_path + '"',
                    "del %~f0",
                ]
                script = "\r\n".join(lines) + "\r\n"
                with open(handler_path, "w") as f:
                    f.write(script)
                return handler_path

                return handler_path

            elif system == "Darwin":
                # macOS: relaunch app.py with the same Python that's running now
                handler_path = os.path.join(APP_DIR, "budgetpal_update.command")
                lines = [
                    "#!/bin/bash",
                    'cd "$(dirname "$0")"',
                    "echo '========================================='",
                    "echo ' BudgetPal - Applying Update'",
                    "echo '========================================='",
                    f'"{_sys.executable}" app.py',
                    'rm -- "$0"',
                ]
                script = "\n".join(lines) + "\n"
                with open(handler_path, "w") as f:
                    f.write(script)
                os.chmod(handler_path, 0o755)
                return handler_path

            else:
                # Linux: relaunch app.py
                handler_path = os.path.join(APP_DIR, "budgetpal_update.sh")
                lines = [
                    "#!/bin/bash",
                    'cd "$(dirname "$0")"',
                    "echo '========================================='",
                    "echo ' BudgetPal - Applying Update'",
                    "echo '========================================='",
                    "python3 app.py",
                    'rm -- "$0"',
                ]
                script = "\n".join(lines) + "\n"
                with open(handler_path, "w") as f:
                    f.write(script)
                os.chmod(handler_path, 0o755)
                return handler_path

        def _run_update():
            try:
                files_to_update = ["app.py", "data_manager.py"]

                # Fetch backgrounds manifest if it exists
                try:
                    murl = f"{REPO_RAW}/backgrounds_manifest.txt"
                    with urllib.request.urlopen(murl, timeout=5) as r:
                        bg_files = [l.strip() for l in r.read().decode().splitlines()
                                    if l.strip() and not l.startswith("#")]
                    for bg in bg_files:
                        files_to_update.append(f"backgrounds/{bg}")
                except Exception:
                    pass  # no manifest = no background updates

                # Download each file
                for rel_path in files_to_update:
                    url      = f"{REPO_RAW}/{rel_path}"
                    dest     = os.path.join(APP_DIR, rel_path)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with urllib.request.urlopen(url, timeout=15) as r:
                        data = r.read()
                    tmp = dest + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, dest)

                # Update local version.txt
                with open(os.path.join(APP_DIR, "version.txt"), "w") as f:
                    f.write(remote_version)

                # Write the OS update handler and register it for on-exit launch
                handler = _write_update_handler()
                if handler:
                    import atexit, subprocess
                    system = platform.system()
                    def _launch_handler():
                        try:
                            if system == "Windows":
                                subprocess.Popen(
                                    ["cmd", "/c", "start", "cmd", "/k", handler],
                                    shell=False, close_fds=True)
                            elif system == "Darwin":
                                subprocess.Popen(["open", handler])
                            else:
                                # Linux: open terminal emulator
                                for term in ["x-terminal-emulator", "gnome-terminal",
                                             "xterm", "konsole"]:
                                    try:
                                        subprocess.Popen([term, "--", "bash", handler])
                                        break
                                    except FileNotFoundError:
                                        continue
                        except Exception:
                            pass
                    atexit.register(_launch_handler)

                self.after(0, _update_done)
            except Exception as e:
                self.after(0, lambda: _update_failed(str(e)))

        def _update_done():
            for w in banner.winfo_children(): w.destroy()
            import sys as _sys
            if getattr(_sys, "frozen", False) and platform.system() == "Windows":
                msg = ("  Files updated! Close the app — a terminal will open "
                       "to rebuild and relaunch automatically.")
            else:
                msg = ("  Files updated! Close the app — it will relaunch "
                       "with the new version automatically.")
            tk.Label(banner,
                     text=msg,
                     font=("Arial", 10, "bold"), fg=DARK, bg=GOLD).pack(side="left", padx=8)
            tk.Button(banner, text="Close App", command=self.destroy,
                      font=("Arial", 9), relief="raised",
                      cursor="hand2").pack(side="right", padx=8)
            tk.Button(banner, text="Later", command=banner.destroy,
                      font=("Arial", 9), relief="raised",
                      cursor="hand2").pack(side="right", padx=4)

        def _update_failed(err):
            for w in banner.winfo_children(): w.destroy()
            tk.Label(banner,
                     text=f"  Update failed: {err}",
                     font=("Arial", 10), fg=DARK, bg="#C0392B").pack(side="left", padx=8)
            tk.Button(banner, text="Dismiss", command=banner.destroy,
                      font=("Arial", 9), relief="raised",
                      cursor="hand2").pack(side="right", padx=8)

        btn = tk.Button(banner, text="Update Now", command=_do_update,
                        font=("Arial", 10, "bold"), bg=DARK, fg="white",
                        relief="raised", cursor="hand2")
        btn.pack(side="right", padx=4)
        tk.Button(banner, text="Dismiss", command=banner.destroy,
                  font=("Arial", 9), relief="raised",
                  cursor="hand2").pack(side="right", padx=4)

    # ══════════════════════════════════════════════════════════════════════════
    # LANDING
    # ══════════════════════════════════════════════════════════════════════════
    def _show_landing(self):
        self._clear()
        f = tk.Frame(self, bg="#FFFFFF"); f.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(f, text="BudgetPal", font=("Arial",22,"bold"),
                 fg="#2E4057", bg="#FFFFFF").pack(pady=(0,6))
        tk.Label(f, text="Personal budget planner", font=("Arial",11),
                 fg="#048A81", bg="#FFFFFF").pack(pady=(0,28))
        _btn(f, "New User – Create Profile", self._show_setup, bg="#048A81", width=28).pack(pady=8)
        _btn(f, "Returning User – Log In",   self._show_load,  bg="#2E4057", width=28).pack(pady=8)
        _raw_btn(self, "BG", self._change_bg,
                  bg="#BDC3C7", fg="#2E4057", font=("Arial",9), width=4
                  ).place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

    # ══════════════════════════════════════════════════════════════════════════
    # LOAD / LOGIN
    # ══════════════════════════════════════════════════════════════════════════
    def _show_load(self):
        self._clear()
        f = tk.Frame(self, bg="#FFFFFF", padx=40, pady=40)
        f.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(f, text="Enter your User ID", font=("Arial",14,"bold"),
                 fg="#2E4057", bg="#FFFFFF").pack(pady=(0,16))
        uid_var = tk.StringVar()
        e = _entry(f, uid_var, width=22); e.pack(pady=8); e.focus()

        def _load():
            uid = uid_var.get().strip().lower()
            if not uid: return
            try:
                self.profile = load_profile(uid)
                self._apply_theme()
                self._check_overdue_then_login()
            except FileNotFoundError:
                messagebox.showerror("Not Found", f"No profile found for ID: '{uid}'")

        self.bind_all("<Return>", lambda _: _load())
        _btn(f, "Load Profile", _load, bg="#048A81").pack(pady=12)
        _btn(f, "← Back", self._show_landing, bg="#BDC3C7", fg="#2E4057").pack()

    # ── Overdue check on login ─────────────────────────────────────────────
    def _check_overdue_then_login(self):
        overdue = check_overdue(self.profile)
        if not overdue:
            self._show_login_options()
            return
        self._show_overdue_confirmation(overdue, on_done=self._show_login_options)

    def _show_overdue_confirmation(self, overdue_list, on_done):
        """Show a screen asking user to confirm which past-due items were paid."""
        self._clear()
        p = self.profile
        WHITE = _t(p,"white"); DARK = _t(p,"dark"); RED = _t(p,"red")
        GREEN = _t(p,"green"); TEAL = _t(p,"teal")

        f = tk.Frame(self, bg=WHITE); f.place(relx=0.5, rely=0.5, anchor="center")
        _lbl(f, "⚠ Past-Due Items", p=p, size=14, bold=True, fg=RED, bg=WHITE).pack(pady=(0,6))
        _lbl(f, "Were these paid? Confirm each one.", p=p, fg=DARK, bg=WHITE).pack(pady=(0,16))

        remaining = list(overdue_list)

        def _handle(ob, paid):
            if paid:
                self.profile = mark_paid(self.profile, ob["name"])
            remaining.remove(ob)
            save_profile(self.profile)
            if paid:
                # Play piggy, then continue to next overdue or dashboard
                def _after():
                    if not remaining:
                        on_done()
                    else:
                        self._show_overdue_confirmation(remaining, on_done)
                self._play_piggy(on_done=_after)
            else:
                if not remaining:
                    on_done()
                else:
                    self._show_overdue_confirmation(remaining, on_done)

        for ob in overdue_list:
            row = tk.Frame(f, bg=WHITE, pady=6); row.pack(fill="x")
            due_lbl = due_label_from(ob["due_type"], ob["due_value"])
            _lbl(row, f"  {ob['name']}  –  {_fmt(p, ob['target'])}  ({due_lbl})",
                 p=p, fg=DARK, bg=WHITE).pack(side="left")
            _btn(row, "Yes, Paid", lambda o=ob: _handle(o, True),
                 bg=GREEN, width=12).pack(side="right", padx=4)
            _btn(row, "Not Yet", lambda o=ob: _handle(o, False),
                 bg=RED, width=12).pack(side="right", padx=4)

    def _show_login_options(self):
        self._clear()
        p = self.profile
        WHITE = _t(p,"white"); DARK = _t(p,"dark"); TEAL = _t(p,"teal")
        f = tk.Frame(self, bg=WHITE); f.place(relx=0.5, rely=0.5, anchor="center")
        _lbl(f, f"Welcome back, {p['name']}! 👋", p=p, size=14, bold=True,
             fg=DARK, bg=WHITE).pack(pady=(0,6))

        status = _lbl(f, "", p=p, size=9, fg=TEAL, bg=WHITE)
        status.pack(pady=(0,12))

        def _set_status(msg): status.config(text=msg)

        def _edit_obligs():
            self._obligation_editor_popup(on_done=lambda: _set_status("✓ Saved."))
        def _edit_accts():
            self._account_editor_popup(on_done=lambda: _set_status("✓ Accounts saved."))

        for txt, cmd, color in [
            ("Edit Obligations",       _edit_obligs,        DARK),
            ("Update Accounts", _edit_accts,       TEAL),
            ("Go to Dashboard",        self._show_dashboard, _t(p,"green")),
        ]:
            _btn(f, txt, cmd, p=p, bg=color, width=28).pack(pady=5)
        _btn(f, "Log Out", self._show_landing, p=p,
             bg=_t(p,"gray"), fg=DARK, width=28).pack(pady=8)

    # ══════════════════════════════════════════════════════════════════════════
    # SETUP WIZARD
    # ══════════════════════════════════════════════════════════════════════════
    def _show_setup(self):
        self._clear()
        _, frame = _scrollable(self)
        WHITE = "#FFFFFF"; DARK = "#2E4057"; TEAL = "#048A81"
        GREEN = "#27AE60"; PURPLE = "#8E44AD"; GOLD = "#F6AE2D"

        tk.Label(frame, text="Create Your Profile", font=("Arial",14,"bold"),
                 fg=DARK, bg=WHITE).grid(row=0, columnspan=5, pady=(0,18))

        # Basic info
        name_var = tk.StringVar(); uid_var = tk.StringVar()
        cur_var  = tk.StringVar(value="USD"); pp_var = tk.StringVar(value="Monthly")

        for r, (lbl, widget) in enumerate([
            ("Your Name:", lambda: _entry(frame, name_var, width=22)),
            ("Currency:",  lambda: _combo(frame, cur_var, list(CURRENCIES.keys()), 10)),
            ("Pay Period:",lambda: _combo(frame, pp_var,  list(PAY_PERIODS.keys()), 12)),
        ], start=1):
            tk.Label(frame, text=lbl, font=("Arial",10), fg=DARK, bg=WHITE
                     ).grid(row=r, column=0, sticky="w", pady=4, padx=(0,10))
            widget().grid(row=r, column=1, sticky="ew", pady=4, columnspan=3)

        # UID row
        uid_row = tk.Frame(frame, bg=WHITE)
        uid_row.grid(row=4, column=0, columnspan=5, sticky="ew", pady=4)
        tk.Label(uid_row, text="User ID:", font=("Arial",10), fg=DARK, bg=WHITE).pack(side="left")
        _entry(uid_row, uid_var, width=22).pack(side="left", padx=8)
        tk.Label(uid_row, text="(auto-filled; you can change it)",
                 font=("Arial",9), fg="#BDC3C7", bg=WHITE).pack(side="left")
        def _autofill(*_): uid_var.set(make_uid(name_var.get()))
        name_var.trace_add("write", _autofill)

        # ── Bank Accounts ──────────────────────────────────────────────────
        tk.Label(frame, text="-- Bank Accounts --", font=("Arial",10,"bold"),
                 fg=GREEN, bg=WHITE).grid(row=5, columnspan=5, pady=(18,4))
        tk.Label(frame, text="Name  |  Starting Balance",
                 font=("Arial",9), fg="#BDC3C7", bg=WHITE).grid(row=6, columnspan=5)

        acct_frame = tk.Frame(frame, bg=WHITE)
        acct_frame.grid(row=7, columnspan=5, sticky="ew")
        acct_rows = []

        def _add_acct(name="", bal="0"):
            r = len(acct_rows)
            nv = tk.StringVar(value=name); bv = tk.StringVar(value=bal)
            _entry(acct_frame, nv, width=22).grid(row=r, column=0, padx=(0,6), pady=3)
            _entry(acct_frame, bv, width=12).grid(row=r, column=1, pady=3)
            rm = _raw_btn(acct_frame, "X", lambda: None,
                           bg="#C0392B", fg="white", font=("Arial",9), width=2, padx=4)
            rm.grid(row=r, column=2, padx=4)
            idx = len(acct_rows); acct_rows.append((nv, bv))
            rm.configure(command=lambda i=idx: _rm_row(acct_rows, acct_frame, i))

        def _rm_row(rows, parent, idx):
            rows[idx] = None
            for w in parent.grid_slaves(row=idx): w.grid_remove()

        _raw_btn(acct_frame, "+ Add Account", lambda: _add_acct(),
                  bg=TEAL, fg="white", font=("Arial",10,"bold"), width=16
                  ).grid(row=99, columnspan=3, pady=6)

        # ── Obligations ────────────────────────────────────────────────────
        tk.Label(frame, text="-- Obligations (Expenses & Goals) --",
                 font=("Arial",10,"bold"), fg=TEAL, bg=WHITE
                 ).grid(row=8, columnspan=5, pady=(22,2))
        tk.Label(frame,
                 text="Name  |  Target $  |  Kind  |  Recurrence / Due  |  Deposit Account",
                 font=("Arial",9), fg="#BDC3C7", bg=WHITE).grid(row=9, columnspan=5)

        ob_frame = tk.Frame(frame, bg=WHITE)
        ob_frame.grid(row=10, columnspan=5, sticky="ew")
        ob_rows = []

        def _add_ob_row(defaults=None):
            self._obligation_row(ob_frame, ob_rows,
                                 acct_getter=lambda: [row[0].get() for row in acct_rows if row is not None and row[0].get().strip()],
                                 defaults=defaults)

        _raw_btn(ob_frame, "+ Add Obligation", _add_ob_row,
                  bg=TEAL, fg="white", font=("Arial",10,"bold"), width=18
                  ).grid(row=99, columnspan=7, pady=6)

        # ── Colour Palette ─────────────────────────────────────────────────
        tk.Label(frame, text="-- Colour Palette --", font=("Arial",10,"bold"),
                 fg=DARK, bg=WHITE).grid(row=11, columnspan=5, pady=(22,4))
        tk.Label(frame, text="Choose a colour scheme for the app.",
                 font=("Arial",9), fg="#BDC3C7", bg=WHITE).grid(row=12, columnspan=5)

        palette_var = tk.StringVar(value="White")
        palette_frame = tk.Frame(frame, bg=WHITE)
        palette_frame.grid(row=13, columnspan=5, pady=8)

        swatch_labels = {}
        for i, pname in enumerate(PALETTE_NAMES):
            pal = PALETTES[pname]
            col_frame = tk.Frame(palette_frame, bg=WHITE, padx=8, pady=4)
            col_frame.grid(row=0, column=i)
            # Canvas preview — single widget, no child interception issues
            cv = tk.Canvas(col_frame, width=56, height=36,
                           highlightthickness=2, highlightbackground="#CCCCCC",
                           cursor="hand2")
            cv.pack()
            cv.create_rectangle(0, 0, 28, 36, fill=pal["dark"], outline="")
            cv.create_rectangle(28, 0, 56, 36, fill=pal["teal"], outline="")
            tk.Label(col_frame, text=pname, font=("Arial",9), bg=WHITE).pack(pady=(4,0))
            swatch_labels[pname] = cv
            def _select(name=pname):
                palette_var.set(name)
                for n, sw in swatch_labels.items():
                    sw.configure(highlightbackground="#2E4057" if n==name else "#CCCCCC",
                                 highlightthickness=3 if n==name else 2)
            cv.bind("<Button-1>", lambda e, fn=_select: fn())
        # Default selection highlight
        swatch_labels["White"].configure(highlightbackground="#2E4057", highlightthickness=3)

        # Hidden font_var still needed for _create compatibility
        font_var = tk.StringVar(value="Arial")

        # ── Create ─────────────────────────────────────────────────────────
        def _create():
            name = name_var.get().strip(); uid = uid_var.get().strip().lower()
            if not name: messagebox.showwarning("Input","Enter your name."); return
            if not uid:  messagebox.showwarning("Input","Enter a User ID."); return
            if uid_taken(uid):
                messagebox.showerror("ID Taken", f"'{uid}' already exists."); return

            accounts = []
            for row in acct_rows:
                if row is None: continue
                nv, bv = row; n = nv.get().strip()
                if n:
                    try: b = float(bv.get().strip() or 0)
                    except ValueError:
                        messagebox.showerror("Input", f"Bad balance for '{n}'"); return
                    accounts.append({"name":n,"balance":b,"type":"bank"})

            obligations = []
            for row in ob_rows:
                ob = self._read_ob_row(row)
                if ob is None: return
                if ob.get("name"): obligations.append(ob)

            theme = dict(PALETTES[palette_var.get()])
            create_profile(uid, name, cur_var.get(), pp_var.get(),
                           obligations, accounts, theme)
            self.profile = load_profile(uid)
            self._apply_theme()
            messagebox.showinfo("Created! 🎉",
                f"Welcome, {name}!\nYour User ID:  {uid}\nSave this to log in later.")
            self._show_dashboard()

        _raw_btn(frame, "Create Profile", _create,
                  bg=GREEN, fg="white", font=("Arial",10,"bold"), width=26
                  ).grid(row=14, columnspan=5, pady=20)
        _raw_btn(frame, "<- Back", self._show_landing,
                  bg="#BDC3C7", fg=DARK, font=("Arial",10,"bold"), width=16
                  ).grid(row=15, columnspan=5)
        frame.columnconfigure(1, weight=1)

    # ── Obligation row widget ─────────────────────────────────────────────────
    def _obligation_row(self, parent, rows_list, acct_getter, defaults=None):
        """
        One row in the obligation editor.
        Kind dropdown drives what fields are shown:
          expense -> recurrence + due type/value dropdowns
          goal    -> single deadline date entry (YYYY-MM-DD), no recurrence
        Uses a single container frame with pack/pack_forget to swap fields
        cleanly without grid cell conflicts.
        """
        d   = defaults or {}
        idx = len(rows_list)
        r   = len([x for x in rows_list if x is not None])

        nv          = tk.StringVar(value=d.get("name",""))
        tv          = tk.StringVar(value=str(d.get("target","")))
        recv        = tk.StringVar(value=d.get("recurrence","Monthly"))
        dtv         = tk.StringVar(value=d.get("due_type","Day of month"))
        dvv         = tk.StringVar(value=d.get("due_value","1"))
        acv         = tk.StringVar(value=d.get("deposit_account",""))
        kv          = tk.StringVar(value=d.get("kind","expense"))
        goal_date_v = tk.StringVar(value=d.get("due_date",""))

        _entry(parent, nv, width=13).grid(row=r, column=0, padx=(0,3), pady=3)
        _entry(parent, tv, width=8).grid( row=r, column=1, padx=(0,3))

        # Kind dropdown
        kind_cb = _combo(parent, kv, ["expense","goal","running","allowance"], 11)
        kind_cb.grid(row=r, column=2, padx=(0,3))

        # Single container in column 3 — contents swap on kind change
        container = tk.Frame(parent, bg="#FFFFFF")
        container.grid(row=r, column=3, padx=(0,3), sticky="w")

        # Expense sub-frame
        exp_f   = tk.Frame(container, bg="#FFFFFF")
        recv_cb = _combo(exp_f, recv, RECUR_OPTIONS, 9)
        recv_cb.pack(side="left", padx=(0,3))
        dt_cb   = _combo(exp_f, dtv, ["Day of month","Day of week"], 11)
        dt_cb.pack(side="left", padx=(0,3))
        dv_cb   = _combo(exp_f, dvv, DAYS_OF_MONTH, 5)
        dv_cb.pack(side="left")

        def _on_dt(*_):
            vals = DAYS_OF_WEEK if dtv.get()=="Day of week" else DAYS_OF_MONTH
            dv_cb["values"] = vals
            dv_cb.set(vals[0])
        dtv.trace_add("write", _on_dt)

        # Goal sub-frame
        goal_f = tk.Frame(container, bg="#FFFFFF")
        tk.Label(goal_f, text="Deadline:", font=("Arial",9),
                 fg="#2E4057", bg="#FFFFFF").pack(side="left", padx=(0,4))
        _entry(goal_f, goal_date_v, width=12).pack(side="left")
        tk.Label(goal_f, text="YYYY-MM-DD", font=("Arial",8),
                 fg="#BDC3C7", bg="#FFFFFF").pack(side="left", padx=4)

        def _on_kind(*_):
            k = kv.get()
            if k == "goal":
                exp_f.pack_forget()
                goal_f.pack(side="left", fill="x")
            elif k == "allowance":
                # No due date or recurrence — just name, amount, account
                exp_f.pack_forget()
                goal_f.pack_forget()
            else:
                # expense / running: show recurrence + due fields
                goal_f.pack_forget()
                exp_f.pack(side="left", fill="x")

        kv.trace_add("write", _on_kind)
        _on_kind()  # set initial state immediately

        # Account dropdown
        ac_cb = _combo(parent, acv, acct_getter() or [""], 13)
        ac_cb.grid(row=r, column=4, padx=(0,3))
        def _refresh_accts(e=None):
            vals = acct_getter() or [""]
            ac_cb["values"] = vals
            if acv.get() not in vals and vals:
                acv.set(vals[0])
        ac_cb.bind("<ButtonPress>", _refresh_accts)
        ac_cb.bind("<FocusIn>", _refresh_accts)
        # Populate immediately in case accounts already exist
        _refresh_accts()

        rm = _raw_btn(parent, "X", lambda: None,
                      bg="#C0392B", fg="white", font=("Arial",9), width=2, padx=4)
        rm.grid(row=r, column=5, padx=2)

        row_data = [nv, tv, recv, dtv, dvv, acv, kv, rm, goal_date_v]
        rows_list.append(row_data)

        def _remove(i=idx):
            container.grid_remove()
            for w in parent.grid_slaves(row=r):
                w.grid_remove()
            rows_list[i] = None
        rm.configure(command=_remove)

    def _read_ob_row(self, row):
        if row is None: return {"name":""}
        nv, tv, recv, dtv, dvv, acv, kv, _, goal_date_v = row
        name = nv.get().strip()
        if not name: return {"name":""}
        try: target = float(tv.get().strip() or 0)
        except ValueError:
            messagebox.showerror("Input", f"Bad target for '{name}'"); return None

        kind = kv.get()

        if kind == "goal":
            # Goals are one-time — just a deadline date
            raw_date = goal_date_v.get().strip()
            try:
                datetime.strptime(raw_date, "%Y-%m-%d")
                due_date = raw_date
            except ValueError:
                messagebox.showerror("Input",
                    f"'{name}': deadline must be YYYY-MM-DD (e.g. 2026-12-25)")
                return None
            return {
                "name": name, "target": target,
                "recurrence": "One-time",
                "due_type": "Date", "due_value": due_date,
                "due_date": due_date,
                "deposit_account": acv.get(),
                "kind": "goal", "paid": False,
            }
        elif kind == "allowance":
            # Allowance: fixed amount per paycheck, no due date
            return {
                "name": name, "target": target,
                "recurrence": "Each paycheck",
                "due_type": "", "due_value": "", "due_date": "",
                "deposit_account": acv.get(),
                "kind": "allowance", "paid": False,
            }
        else:
            # Expense or running — recurring with due type/value
            recurrence = recv.get()
            due_type   = dtv.get()
            due_value  = dvv.get()
            due_date   = _next_due_date(due_type, due_value, recurrence).isoformat()
            return {
                "name": name, "target": target, "recurrence": recurrence,
                "due_type": due_type, "due_value": due_value, "due_date": due_date,
                "deposit_account": acv.get(), "kind": kind, "paid": False,
            }

    # ══════════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════
    def _show_dashboard(self):
        self._clear()
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GRAY=_t(p,"gray");   RED=_t(p,"red")

        # Top bar
        topbar = tk.Frame(self, bg=DARK, height=56)
        topbar.pack(fill="x"); topbar.pack_propagate(False)
        tk.Label(topbar, text=f"💰 BudgetPal  –  {p['name']}",
                 font=_f(p,14,True), fg=WHITE, bg=DARK).pack(side="left", padx=16)
        tk.Label(topbar, text=f"ID: {p['uid']}  |  {p['currency']}  |  {p['pay_period']}",
                 font=_f(p,9), fg=GRAY, bg=DARK).pack(side="left", padx=8)
        _btn(topbar,"Log Out",self._show_landing,p=p,bg=RED,fg=WHITE,width=9
             ).pack(side="right", padx=8, pady=8)
        _raw_btn(topbar, "BG", self._change_bg,
                  bg=DARK, fg=GRAY, font=("Arial",9), width=4, bd=0
                  ).pack(side="right", padx=4)

        # Quick bar
        qbar = tk.Frame(self, bg=_t(p,"light"), pady=5); qbar.pack(fill="x")
        for txt, cmd, color in [
            ("Obligations",  lambda: self._obligation_editor_popup(on_done=self._show_dashboard), DARK),
            ("Accounts",    lambda: self._account_editor_popup(on_done=self._show_dashboard),    TEAL),
            ("Theme",       self._theme_editor,                                                   DARK),
            ("Export Zip",  self._export_zip,                                                     GRAY),
        ]:
            _raw_btn(qbar, txt, cmd,
                         bg=color, fg=WHITE if color!=GRAY else "#2E4057",
                         font=_f(p,9,True), width=0, padx=10, pady=4
                         ).pack(side="left", padx=4, pady=2)

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=6)

        # Check for updates silently in background
        self._check_for_update(self)

        self._tab_overview(nb)
        self._tab_paycheck(nb)
        self._tab_accounts(nb)
        self._tab_obligations(nb)
        self._tab_history(nb)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: OVERVIEW
    # ══════════════════════════════════════════════════════════════════════════
    def _tab_overview(self, nb):
        p = self.profile
        LIGHT=_t(p,"light"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GREEN=_t(p,"green"); RED=_t(p,"red"); GOLD="#F6AE2D"

        f = tk.Frame(nb, bg=LIGHT); nb.add(f, text="  Overview  ")

        log = p.get("paycheck_log",[])
        net = log[-1]["net"] if log else 0.0
        budget = build_budget(p, net)
        total_bal = sum(a["balance"] for a in p.get("accounts",[]))

        tk.Label(f, text="Account Snapshot", font=_f(p,14,True),
                 fg=DARK, bg=LIGHT).pack(pady=(14,4))
        tk.Label(f, text=f"Pay period: {p['pay_period']}  •  {p['currency']}",
                 font=_f(p,9), fg=TEAL, bg=LIGHT).pack(pady=(0,10))

        # Summary cards
        cards = tk.Frame(f, bg=LIGHT); cards.pack(pady=6)
        def _card(title, val, color, sub=None):
            c = tk.Frame(cards, bg=color, padx=16, pady=10, relief="groove", bd=1)
            c.pack(side="left", padx=6)
            tk.Label(c, text=title,    font=_f(p,8),    fg="white", bg=color).pack()
            tk.Label(c, text=_fmt(p,val), font=_f(p,13,True), fg="white", bg=color).pack()
            if sub: tk.Label(c, text=sub, font=_f(p,8), fg="white", bg=color).pack()

        _card("Bank Total",    total_bal,           GREEN)
        _card("Net Pay",       net,                 TEAL)
        _card("Total Deposits",budget["total_needed"], DARK)
        shortfall = budget["shortfall"]
        _card("Shortfall" if shortfall>0 else "On Track",
              shortfall, RED if shortfall>0 else GREEN,
              "Proportional" if shortfall>0 else "✓")

        if not log:
            tk.Label(f, text="Log a paycheck to see your budget breakdown.",
                     fg=RED, bg=LIGHT).pack(pady=12)
            return

        # Per-account spendable table
        tk.Label(f, text="Per-Account Spendable", font=_f(p,11,True),
                 fg=DARK, bg=LIGHT).pack(pady=(18,4))

        acct_totals = {}  # account name -> (deposit, spendable)
        for line in budget["lines"]:
            an = line["deposit_account"]
            if an not in acct_totals:
                acct_totals[an] = {"deposit":0.0, "spendable": line["spendable"],
                                   "balance": line["acct_balance"]}
            acct_totals[an]["deposit"] += line["deposit"]

        cols = ("Account","Current Balance","Deposit This Pay","Spendable")
        tree = ttk.Treeview(f, columns=cols, show="headings",
                            height=min(len(acct_totals)+1, 10))
        for c, w in zip(cols,[200,160,160,160]):
            tree.heading(c,text=c); tree.column(c,width=w,anchor="center")
        tree.pack(padx=20, fill="x")

        for an, data in acct_totals.items():
            new_bal = data["balance"] + data["deposit"]
            sp_color = "pos" if data["spendable"]>=0 else "neg"
            tree.insert("","end",
                values=(an, _fmt(p,data["balance"]),
                        _fmt(p,data["deposit"]), _fmt(p,data["spendable"])),
                tags=(sp_color,))

        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: PAYCHECK
    # ══════════════════════════════════════════════════════════════════════════
    def _tab_paycheck(self, nb):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GREEN=_t(p,"green"); RED=_t(p,"red"); LIGHT=_t(p,"light")
        GOLD="#F6AE2D"

        f = tk.Frame(nb, bg=WHITE); nb.add(f, text="  Paycheck  ")
        left  = tk.Frame(f, bg=WHITE, padx=30, pady=20); left.pack(side="left", fill="y")
        right = tk.Frame(f, bg=LIGHT, padx=16, pady=16)
        right.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="Log a Paycheck", font=_f(p,13,True),
                 fg=DARK, bg=WHITE).grid(row=0, columnspan=2, pady=(0,14))

        date_var  = tk.StringVar(value=date.today().isoformat())
        gross_var = tk.StringVar(); net_var = tk.StringVar()

        for r,(lbl,var) in enumerate([("Date (YYYY-MM-DD):",date_var),
                                       ("Gross Pay:", gross_var),
                                       ("Net Pay:", net_var)], start=1):
            tk.Label(left, text=lbl, font=_f(p), fg=DARK, bg=WHITE
                     ).grid(row=r, column=0, sticky="w", pady=6)
            _entry(left, var, width=16).grid(row=r, column=1, sticky="w")

        _btn(left,"Update Accounts First",
             lambda: self._account_editor_popup(on_done=lambda: None),
             p=p, bg=TEAL, width=24).grid(row=4, columnspan=2, pady=(12,4))

        result = tk.Frame(right, bg=LIGHT); result.pack(fill="both", expand=True)

        def _log():
            for w in result.winfo_children(): w.destroy()
            try:
                d = date_var.get().strip(); datetime.strptime(d,"%Y-%m-%d")
                gross = float(gross_var.get().strip())
                net   = float(net_var.get().strip())
            except ValueError:
                messagebox.showerror("Input","Check date and amounts."); return

            budget = build_budget(p, net)
            updated = apply_deposits(p, budget)
            updated["paycheck_log"].append({"date":d,"gross":gross,"net":net})
            self.profile = updated
            save_profile(updated)

            # Play piggy animation, then refresh dashboard tabs in background
            def _after_anim():
                # Rebuild dashboard so account balances update without re-login
                self._show_dashboard()
            self._play_piggy(on_done=_after_anim)

            tk.Label(result, text="Paycheck logged & accounts updated:",
                     font=_f(p,11,True), fg=GREEN, bg=LIGHT).pack(pady=(0,8))

            # Header row
            hdr = tk.Frame(result, bg=_t(p,"dark")); hdr.pack(fill="x", pady=(0,4))
            for txt, w in [("Account",200),("Deposit",120),("New Balance",130),("Spendable",120)]:
                tk.Label(hdr, text=txt, font=_f(p,9,True), fg="white",
                         bg=_t(p,"dark"), width=w//8).pack(side="left", padx=4)

            # Aggregate by account
            acct_map = {a["name"]: a["balance"] for a in updated["accounts"]}
            seen = {}
            for line in budget["lines"]:
                an = line["deposit_account"]
                if an not in seen:
                    seen[an] = {"deposit":0.0, "old_bal":line["acct_balance"],
                                "spendable":line["spendable"]}
                seen[an]["deposit"] += line["deposit"]

            for an, data in seen.items():
                new_bal = acct_map.get(an, data["old_bal"] + data["deposit"])
                row = tk.Frame(result, bg=LIGHT); row.pack(fill="x", pady=2)
                sp_color = GREEN if data["spendable"]>=0 else RED
                for txt, w, color in [
                    (an,                      200, DARK),
                    (_fmt(p,data["deposit"]), 120, TEAL),
                    (_fmt(p,new_bal),         130, DARK),
                    (_fmt(p,data["spendable"]),120, sp_color),
                ]:
                    tk.Label(row, text=txt, font=_f(p,10), fg=color,
                             bg=LIGHT, width=w//8, anchor="center").pack(side="left", padx=4)

            # Obligation detail
            tk.Label(result, text="-"*52, bg=LIGHT).pack(pady=6)
            tk.Label(result, text="Obligation Detail", font=_f(p,10,True),
                     fg=DARK, bg=LIGHT).pack(anchor="w")
            for line in budget["lines"]:
                pct = (line["deposit"]/net*100) if net else 0
                row = tk.Frame(result, bg=LIGHT); row.pack(fill="x", pady=1)
                if line["kind"] == "expense":     kind_color = TEAL
                elif line["kind"] == "running":   kind_color = "#8E44AD"
                elif line["kind"] == "allowance": kind_color = GREEN
                else:                             kind_color = GOLD
                tk.Label(row, text=f"  {line['name']}",
                         font=_f(p), fg=kind_color, bg=LIGHT).pack(side="left")
                tk.Label(row, text=f"{_fmt(p,line['deposit'])} ({pct:.1f}%)"
                              f"  →  {line['deposit_account']}",
                         font=_f(p), fg=DARK, bg=LIGHT).pack(side="right", padx=8)

            if budget["shortfall"] > 0:
                tk.Label(result,
                    text=f"Shortfall: {_fmt(p,budget['shortfall'])} — deposits scaled proportionally.",
                    font=_f(p,9,True), fg=RED, bg=LIGHT).pack(pady=6)
            else:
                tk.Label(result,
                    text=f"Extra {_fmt(p, budget['leftover_raw'])} spread proportionally — accounts ahead of schedule.",
                    font=_f(p,9), fg=GREEN, bg=LIGHT).pack(pady=6)

        _btn(left, "Log & Update Accounts", _log, p=p, bg=GREEN, width=26
             ).grid(row=5, columnspan=2, pady=14)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: ACCOUNTS
    # ══════════════════════════════════════════════════════════════════════════
    def _tab_accounts(self, nb):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GREEN=_t(p,"green"); RED=_t(p,"red")

        f = tk.Frame(nb, bg=WHITE); nb.add(f, text="  Accounts  ")
        tk.Label(f, text="Bank Accounts", font=_f(p,14,True),
                 fg=DARK, bg=WHITE).pack(pady=(18,4))

        cols = ("Account","Balance","Spendable")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c,w in zip(cols,[280,180,180]):
            tree.heading(c,text=c); tree.column(c,width=w,anchor="center")
        tree.pack(padx=40, pady=8, fill="x")

        total_lbl = tk.Label(f, text="", font=_f(p,10,True), fg=GREEN, bg=WHITE)
        total_lbl.pack()

        def _refresh():
            tree.delete(*tree.get_children())
            log = p.get("paycheck_log",[])
            net = log[-1]["net"] if log else 0.0
            budget = build_budget(p, net)
            spendable_by_acct = {}
            for line in budget["lines"]:
                an = line["deposit_account"]
                spendable_by_acct[an] = spendable_by_acct.get(an, 0) + line["spendable"]

            total = 0.0
            for a in p.get("accounts",[]):
                sp = spendable_by_acct.get(a["name"], a["balance"])
                total += a["balance"]
                tag = "neg" if a["balance"]<0 else ("sp" if sp>=0 else "low")
                tree.insert("","end",
                    values=(a["name"], _fmt(p,a["balance"]), _fmt(p,sp)),
                    tags=(tag,))
            tree.tag_configure("neg", foreground=RED)
            tree.tag_configure("low", foreground="#E67E22")
            tree.tag_configure("sp",  foreground=GREEN)
            total_lbl.config(text=f"Total:  {_fmt(p, total)}")

        _refresh()
        _btn(f, "Edit Balances",
             lambda: self._account_editor_popup(on_done=lambda: _refresh()),
             p=p, width=18).pack(pady=10)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: OBLIGATIONS
    # ══════════════════════════════════════════════════════════════════════════
    def _tab_obligations(self, nb):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GREEN=_t(p,"green"); RED=_t(p,"red"); GOLD="#F6AE2D"

        f = tk.Frame(nb, bg=WHITE); nb.add(f, text="  Obligations  ")
        tk.Label(f, text="Obligations (Expenses & Goals)", font=_f(p,14,True),
                 fg=DARK, bg=WHITE).pack(pady=(18,4))

        log = p.get("paycheck_log",[])
        net = log[-1]["net"] if log else 0.0
        budget = build_budget(p, net)
        deposit_map = {l["name"]: l for l in budget["lines"]}

        cols = ("Name","Target","Kind","Recurrence","Due","Account","Deposit/Pay","Spendable")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=12)
        widths = [160,90,90,160,140,110,100,80]
        for c,w in zip(cols,widths):
            tree.heading(c,text=c); tree.column(c,width=w,anchor="center")
        tree.pack(padx=10, pady=8, fill="x")

        def _refresh():
            tree.delete(*tree.get_children())
            for ob in p.get("obligations",[]):
                dl = due_label_from(ob["due_type"],ob["due_value"])
                line = deposit_map.get(ob["name"],{})
                dep  = _fmt(p, line.get("deposit",0)) if line else "—"
                sp   = _fmt(p, line.get("spendable",0)) if line else "—"
                if ob["kind"] == "goal":        tag = "goal"
                elif ob["kind"] == "running":   tag = "run"
                elif ob["kind"] == "allowance": tag = "allow"
                else:                           tag = "exp"
                tree.insert("","end",
                    values=(ob["name"], _fmt(p,ob["target"]), ob["kind"],
                            ob["recurrence"], dl, ob["deposit_account"], dep, sp),
                    tags=(tag,))
            tree.tag_configure("goal",  background="#FFF3CD")
            tree.tag_configure("run",   background="#F3E5F5")
            tree.tag_configure("allow", background="#E8F5E9")
            tree.tag_configure("exp",   background="#FFFFFF")

        _refresh()

        btn_row = tk.Frame(f, bg=WHITE); btn_row.pack(pady=8)

        def _mark_paid():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Select", "Select an obligation to mark as paid.")
                return
            idx  = tree.index(sel[0])
            ob   = p["obligations"][idx]
            kind = ob.get("kind","expense")

            if kind == "allowance":
                messagebox.showinfo("Allowance",
                    "Allowances are not paid off — they deposit each paycheck automatically.")
                return
            name_str  = ob["name"]
            acct_str  = ob["deposit_account"]
            amt_str   = _fmt(p, ob["target"])
            if kind == "goal":
                confirm_msg = (f"Mark '{name_str}' as complete?\n\n"
                               f"This will deduct {amt_str} from "
                               f"'{acct_str}' and remove the goal.")
            else:
                confirm_msg = (f"Mark '{name_str}' as paid?\n\n"
                               f"This will deduct {amt_str} from "
                               f"'{acct_str}' and roll the due date forward.")

            if not messagebox.askyesno("Confirm Payment", confirm_msg):
                return

            self.profile = mark_paid(self.profile, ob["name"])
            save_profile(self.profile)

            # Play piggy then refresh
            def _after():
                # Rebuild budget map with fresh profile
                nonlocal deposit_map
                log2 = self.profile.get("paycheck_log",[])
                net2 = log2[-1]["net"] if log2 else 0.0
                deposit_map = {l["name"]: l for l in build_budget(self.profile, net2)["lines"]}
                _refresh()
            self._play_piggy(on_done=_after)

        _btn(btn_row, "Mark as Paid",
             _mark_paid, p=p, bg=GREEN, width=16).pack(side="left", padx=6)
        _btn(btn_row, "Manage Obligations",
             lambda: self._obligation_editor_popup(on_done=_refresh),
             p=p, width=20).pack(side="left", padx=6)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: HISTORY
    # ══════════════════════════════════════════════════════════════════════════
    def _tab_history(self, nb):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); GRAY=_t(p,"gray")
        f = tk.Frame(nb, bg=WHITE); nb.add(f, text="  History  ")
        tk.Label(f, text="Paycheck History", font=_f(p,14,True),
                 fg=DARK, bg=WHITE).pack(pady=(18,4))

        cols = ("Date","Gross","Net")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        for c,w in zip(cols,[220,200,200]):
            tree.heading(c,text=c); tree.column(c,width=w,anchor="center")
        tree.pack(padx=40, pady=8, fill="x")
        for e in reversed(p.get("paycheck_log",[])):
            tree.insert("","end", values=(e["date"],_fmt(p,e["gross"]),_fmt(p,e["net"])))

        tk.Label(f, text=f"Total logged: {len(p.get('paycheck_log',[]))}",
                 font=_f(p,9), fg=GRAY, bg=WHITE).pack()
        _btn(f,"Export Zip",self._export_zip,p=p,bg=DARK,width=20).pack(pady=12)

    # ══════════════════════════════════════════════════════════════════════════
    # POPUP: Obligation editor
    # ══════════════════════════════════════════════════════════════════════════
    def _obligation_editor_popup(self, on_done=None):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal")
        GREEN=_t(p,"green"); RED=_t(p,"red")

        win = tk.Toplevel(self); win.title("Manage Obligations")
        win.configure(bg=WHITE); win.geometry("980x540"); win.grab_set()

        tk.Label(win, text="Obligations", font=_f(p,13,True),
                 fg=DARK, bg=WHITE).pack(pady=(14,2))
        tk.Label(win, text="Expenses, running expenses (e.g. credit card), and goals. Each needs a deposit account.",
                 font=_f(p,9), fg="#888", bg=WHITE).pack(pady=(0,8))

        cols = ("Name","Target","Kind","Recurrence","Due","Account")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=8)
        for c,w in zip(cols,[180,100,100,180,160,80]):
            tree.heading(c,text=c); tree.column(c,width=w,anchor="center")
        tree.pack(padx=16, pady=6, fill="x")

        def _refresh():
            tree.delete(*tree.get_children())
            for ob in p.get("obligations",[]):
                dl = due_label_from(ob["due_type"],ob["due_value"])
                tree.insert("","end",
                    values=(ob["name"],_fmt(p,ob["target"]),ob["kind"],
                            ob["recurrence"],dl,ob["deposit_account"]),
                    tags=("goal",) if ob["kind"]=="goal" else
                          ("run",) if ob["kind"]=="running" else ())
            tree.tag_configure("goal", background="#FFF3CD")

        _refresh()

        # Add area
        add_lf = tk.LabelFrame(win, text=" Add New Obligation ",
                               bg=WHITE, fg=TEAL, font=_f(p,10,True))
        add_lf.pack(fill="x", padx=16, pady=6)

        acct_names = lambda: [a["name"] for a in p.get("accounts",[])]
        new_rows = []
        self._obligation_row(add_lf, new_rows, acct_getter=acct_names)
        _raw_btn(add_lf, "+ Another",
                  lambda: self._obligation_row(add_lf, new_rows, acct_getter=acct_names),
                  bg=TEAL, fg="white", font=_f(p,9,True), width=14
                  ).grid(row=99, columnspan=7, pady=4)

        btn_row = tk.Frame(win, bg=WHITE); btn_row.pack(pady=6)

        def _save_new():
            for row in new_rows:
                ob = self._read_ob_row(row)
                if ob is None: return
                if ob.get("name"): p["obligations"].append(ob)
            save_profile(p); _refresh()
            for w in add_lf.winfo_children(): w.destroy()
            new_rows.clear()
            self._obligation_row(add_lf, new_rows, acct_getter=acct_names)
            _raw_btn(add_lf, "+ Another",
                      lambda: self._obligation_row(add_lf, new_rows, acct_getter=acct_names),
                      bg=TEAL, fg="white", font=_f(p,9,True), width=14
                      ).grid(row=99, columnspan=7, pady=4)

        def _edit_sel():
            sel = tree.selection()
            if not sel: messagebox.showinfo("Select","Select an obligation to edit."); return
            idx = tree.index(sel[0]); ob = p["obligations"][idx]
            sub = tk.Toplevel(win); sub.title("Edit Obligation")
            sub.configure(bg=WHITE); sub.geometry("820x140"); sub.grab_set()
            edit_rows = []
            self._obligation_row(sub, edit_rows, acct_getter=acct_names, defaults=ob)
            def _save_edit():
                data = self._read_ob_row(edit_rows[0])
                if data is None: return
                data["paid"] = ob.get("paid", False)
                p["obligations"][idx] = data
                save_profile(p); _refresh(); sub.destroy()
            _raw_btn(sub, "Save", _save_edit,
                      bg=DARK, fg="white", font=_f(p,10,True), width=12
                      ).grid(row=99, columnspan=7, pady=10)

        def _delete_sel():
            sel = tree.selection()
            if not sel: return
            idx = tree.index(sel[0])
            if messagebox.askyesno("Delete",
                    f"Delete '{p['obligations'][idx]['name']}'?"):
                p["obligations"].pop(idx); save_profile(p); _refresh()

        for txt, cmd, color in [
            ("Save New",    _save_new,   GREEN),
            ("✏ Edit Sel.",   _edit_sel,   DARK),
            ("🗑 Delete Sel.", _delete_sel, RED),
        ]:
            _btn(btn_row, txt, cmd, p=p, bg=color, width=14).pack(side="left", padx=5)

        def _close():
            if on_done: on_done()
            win.destroy()
        _btn(win, "Done", _close, p=p, bg=GREEN, width=14).pack(pady=8)
        win.protocol("WM_DELETE_WINDOW", _close)

    # ══════════════════════════════════════════════════════════════════════════
    # POPUP: Account editor
    # ══════════════════════════════════════════════════════════════════════════
    def _account_editor_popup(self, on_done=None):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); TEAL=_t(p,"teal"); GREEN=_t(p,"green")

        win = tk.Toplevel(self); win.title("Edit Account Balances")
        win.configure(bg=WHITE); win.geometry("460x460"); win.grab_set()
        tk.Label(win, text="Bank Accounts", font=_f(p,13,True),
                 fg=DARK, bg=WHITE).pack(pady=(14,8))

        canvas = tk.Canvas(win, bg=WHITE, highlightthickness=0, height=260)
        sb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); canvas.pack(fill="x", padx=16)
        inner = tk.Frame(canvas, bg=WHITE)
        cwin = canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))

        row_vars = []

        def _build():
            for w in inner.winfo_children(): w.destroy(); row_vars.clear()
            hdr = tk.Frame(inner, bg=DARK); hdr.pack(fill="x", pady=(0,4))
            tk.Label(hdr, text="Account", fg="white", bg=DARK, width=22, anchor="w"
                     ).pack(side="left", padx=8)
            tk.Label(hdr, text="Balance", fg="white", bg=DARK, width=14, anchor="center"
                     ).pack(side="left")
            for acct in p.get("accounts",[]):
                row = tk.Frame(inner, bg="#E8F5E9"); row.pack(fill="x", pady=2)
                nv = tk.StringVar(value=acct["name"])
                bv = tk.StringVar(value=str(acct["balance"]))
                _entry(row, nv, width=20).pack(side="left", padx=(8,6), pady=4)
                _entry(row, bv, width=12).pack(side="left", padx=4)
                row_vars.append((nv, bv))

        _build()

        def _add(): p["accounts"].append({"name":"New Account","balance":0.0,"type":"bank"}); _build()
        def _rem():
            if p["accounts"]: p["accounts"].pop(); _build()

        br = tk.Frame(win, bg=WHITE); br.pack(pady=6)
        _btn(br,"+ Add",_add,p=p,bg=TEAL,width=12).pack(side="left",padx=5)
        _btn(br,"Remove Last",_rem,p=p,bg=_t(p,"gray"),fg=DARK,width=14).pack(side="left",padx=5)

        def _save_close():
            for i,(nv,bv) in enumerate(row_vars):
                try: b = float(bv.get().strip() or 0)
                except ValueError:
                    messagebox.showerror("Error",f"Bad balance row {i+1}"); return
                if i < len(p["accounts"]):
                    p["accounts"][i]["name"]    = nv.get().strip()
                    p["accounts"][i]["balance"] = b
            save_profile(p)
            if on_done: on_done()
            win.destroy()

        _btn(win,"Save & Close",_save_close,p=p,bg=GREEN,width=18).pack(pady=10)
        win.protocol("WM_DELETE_WINDOW", _save_close)

    # ══════════════════════════════════════════════════════════════════════════
    # THEME EDITOR
    # ══════════════════════════════════════════════════════════════════════════
    def _theme_editor(self):
        p = self.profile
        WHITE=_t(p,"white"); DARK=_t(p,"dark"); GREEN=_t(p,"green")

        win = tk.Toplevel(self); win.title("Colour Palette")
        win.configure(bg=WHITE); win.geometry("480x300"); win.grab_set()
        tk.Label(win, text="Choose a Colour Palette", font=_f(p,13,True),
                 fg=DARK, bg=WHITE).pack(pady=(16,4))
        tk.Label(win, text="Changes the entire colour scheme of the app.",
                 font=_f(p,9), fg=_t(p,"gray"), bg=WHITE).pack(pady=(0,16))

        # Find current palette name
        current = next((n for n,pal in PALETTES.items()
                        if pal["dark"] == p.get("theme",{}).get("dark")), "White")
        sel_var = tk.StringVar(value=current)
        swatch_refs = {}

        row_f = tk.Frame(win, bg=WHITE); row_f.pack()
        for i, pname in enumerate(PALETTE_NAMES):
            pal = PALETTES[pname]
            col = tk.Frame(row_f, bg=WHITE, padx=10, pady=6)
            col.grid(row=0, column=i)
            cv = tk.Canvas(col, width=56, height=36,
                           highlightthickness=2, highlightbackground="#CCCCCC",
                           cursor="hand2")
            cv.pack()
            cv.create_rectangle(0, 0, 28, 36, fill=pal["dark"], outline="")
            cv.create_rectangle(28, 0, 56, 36, fill=pal["teal"], outline="")
            tk.Label(col, text=pname, font=("Arial",10), bg=WHITE).pack(pady=(4,0))
            swatch_refs[pname] = cv

            def _sel(name=pname):
                sel_var.set(name)
                for n, sw in swatch_refs.items():
                    sw.configure(highlightbackground="#2E4057" if n==name else "#CCCCCC",
                                 highlightthickness=3 if n==name else 2)
            cv.bind("<Button-1>", lambda e, fn=_sel: fn())

        # Highlight current
        swatch_refs[current].configure(highlightbackground="#2E4057", highlightthickness=3)

        def _apply():
            chosen = sel_var.get()
            p["theme"] = dict(PALETTES[chosen])
            save_profile(p)
            self._apply_theme()
            win.destroy()
            self._show_dashboard()

        _btn(win, "Apply & Save", _apply, p=p, bg=GREEN, width=18).pack(pady=20)

    # ══════════════════════════════════════════════════════════════════════════
    # EXPORT ZIP
    # ══════════════════════════════════════════════════════════════════════════
    def _export_zip(self):
        p = self.profile; save_profile(p)
        dest = filedialog.asksaveasfilename(
            title="Save BudgetPal as zip",
            defaultextension=".zip",
            initialfile=f"BudgetPal_{p['uid']}.zip",
            filetypes=[("Zip archive","*.zip")])
        if not dest: return
        app_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as zf:
                for fname in ("app.py","data_manager.py","README.md",
                              "build_mac.sh","build_windows.bat","mac_setup.command"):
                    fp = os.path.join(app_dir, fname)
                    if os.path.exists(fp):
                        info = zipfile.ZipInfo(f"BudgetPal/{fname}")
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = (0o755 if fname.endswith(
                            (".command",".sh",".bat")) else 0o644) << 16
                        with open(fp,"rb") as f2: zf.writestr(info, f2.read())
                for fname in os.listdir(DATA_DIR):
                    if fname.endswith(".xlsx"):
                        zf.write(os.path.join(DATA_DIR,fname),
                                 f"BudgetPal/user_data/{fname}")
                zf.writestr("BudgetPal/user_data/.keep","")
                zf.writestr("BudgetPal/backgrounds/.keep","")
            messagebox.showinfo("Export Complete ✅", f"Saved to:\n{dest}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))


if __name__ == "__main__":
    app = BudgetApp()
    app.mainloop()
