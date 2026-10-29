import json
import re
import urllib.error
import urllib.request
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_VERSION = "1.0.1"
UPDATE_CONFIG_FILE = APP_DIR / "update_config.json"
DEFAULT_UPDATE_CONFIG = {"github_repo": "YOUR_GITHUB_USERNAME/YOUR_REPOSITORY"}
AUTHOR_NAME = "Võ Thế Anh"
APP_DISPLAY_NAME = "DAV sang MP4"


def read_update_config():
    config = dict(DEFAULT_UPDATE_CONFIG)
    try:
        loaded = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            config.update(loaded)
    except (OSError, ValueError):
        pass
    return config


def parse_version(value):
    """Parse simple versions such as v1.2.3 or 1.2.3."""
    value = str(value or "").strip().lower()
    if value.startswith("v"):
        value = value[1:]
    value = re.split(r"[-+]", value, maxsplit=1)[0]
    try:
        parts = [int(part) for part in value.split(".")]
        return tuple((parts + [0, 0, 0])[:3])
    except (TypeError, ValueError):
        return None
APPDATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "DAVtoMP4"
SETTINGS_FILE = APPDATA_DIR / "settings.json"
DEFAULT_FFMPEG = str(APP_DIR / "ffmpeg.exe") if (APP_DIR / "ffmpeg.exe").is_file() else "ffmpeg.exe"
# Common camera/DVR formats. FFmpeg support still depends on the actual container/codec.
VIDEO_EXTENSIONS = {
    ".dav", ".avi", ".mp4", ".m4v", ".mkv", ".mov", ".qt", ".wmv", ".asf",
    ".flv", ".f4v", ".ts", ".m2ts", ".mts", ".m2t", ".mpg", ".mpeg", ".mpe",
    ".vob", ".3gp", ".3g2", ".webm", ".ogv", ".mpv", ".264", ".h264", ".265",
    ".h265", ".hevc", ".yuv", ".mxf", ".gxf", ".nut", ".ps", ".rec", ".r3d"
}


def read_settings():
    defaults = {"ffmpeg": DEFAULT_FFMPEG, "output_dir": "", "mode": "fast"}
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            defaults.update(saved)
    except (OSError, ValueError):
        pass
    return defaults


def write_settings(settings):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class DavToMp4App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.set_app_icon()
        self.root.geometry("1020x760")
        self.root.minsize(900, 700)
        self.root.configure(bg="#f3f6fb")

        self.settings = read_settings()
        self.ffmpeg = tk.StringVar(value=self.settings["ffmpeg"])
        self.output_dir = tk.StringVar(value=self.settings["output_dir"])
        self.mode = tk.StringVar(value=self.settings.get("mode", "fast"))
        self.rename_var = tk.StringVar()
        self.status = tk.StringVar(value="Chọn video camera/đầu ghi (DAV, AVI, MP4, H.264/H.265 và nhiều định dạng khác).")
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="0%")

        self.files = []           # source Paths
        self.output_names = {}    # source path string -> output stem
        self.events = queue.Queue()
        self.running = False
        self.stop_requested = False
        self.proc = None

        self.build_ui()
        self.root.after(100, self.process_events)
        self.root.after(1500, lambda: self.check_for_updates(silent=True))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.log("Sẵn sàng. Hỗ trợ nhiều định dạng video camera/đầu ghi; kết quả phụ thuộc codec và FFmpeg.")

    def set_app_icon(self):
        """Apply the bundled icon to the main window and dialogs where supported."""
        icon_path = APP_DIR / "app_icon.ico"
        try:
            if icon_path.is_file():
                self.root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

    def about_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Giới thiệu về DAV sang MP4")
        win.resizable(False, False)
        win.transient(self.root)
        win.configure(bg="#f2f6fc")
        try:
            icon_path = APP_DIR / "app_icon.ico"
            if icon_path.is_file():
                win.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

        outer = ttk.Frame(win, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="DAV sang MP4", font=("Segoe UI", 18, "bold"), foreground="#153b66").pack(anchor="w")
        ttk.Label(outer, text="Chuyển đổi video camera và đầu ghi sang MP4", wraplength=390).pack(anchor="w", pady=(4, 14))
        ttk.Separator(outer).pack(fill="x", pady=(0, 12))
        info = ttk.Frame(outer)
        info.pack(fill="x")
        ttk.Label(info, text="Phiên bản:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=3)
        ttk.Label(info, text=APP_VERSION).grid(row=0, column=1, sticky="nw", pady=3)
        ttk.Label(info, text="Tác giả:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="nw", padx=(0, 10), pady=3)
        ttk.Label(info, text=AUTHOR_NAME).grid(row=1, column=1, sticky="nw", pady=3)
        ttk.Label(info, text="Công cụ:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="nw", padx=(0, 10), pady=3)
        ttk.Label(info, text="FFmpeg · PyInstaller · Inno Setup").grid(row=2, column=1, sticky="nw", pady=3)
        repo = str(read_update_config().get("github_repo", "")).strip().strip("/")
        if repo and repo.count("/") == 1 and "YOUR_GITHUB_" not in repo:
            url = f"https://github.com/{repo}"
            ttk.Label(info, text="Mã nguồn:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="nw", padx=(0, 10), pady=3)
            link = ttk.Label(info, text=url, foreground="#1769aa", cursor="hand2")
            link.grid(row=3, column=1, sticky="nw", pady=3)
            link.bind("<Button-1>", lambda _event, target=url: __import__("webbrowser").open(target))
        ttk.Label(outer, text="Cảm ơn bạn đã sử dụng chương trình.", wraplength=390).pack(anchor="w", pady=(16, 12))
        ttk.Button(outer, text="Đóng", command=win.destroy).pack(anchor="e")
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()

    def check_for_updates(self, silent=False):
        config = read_update_config()
        repo = str(config.get("github_repo", "")).strip().strip("/")
        if not repo or "YOUR_GITHUB_" in repo or repo.count("/") != 1:
            if not silent:
                messagebox.showinfo(
                    "Thiết lập cập nhật",
                    "Chưa cấu hình kho GitHub để kiểm tra phiên bản.\n\n"
                    "Mở update_config.json cạnh chương trình và đặt github_repo thành "
                    "chu_tai_khoan/ten_repository.\n"
                    "Ví dụ: TheAnh/DAV-to-MP4."
                )
            return
        self.status.set("Đang kiểm tra phiên bản mới...")
        threading.Thread(target=self._update_check_worker, args=(repo, silent), daemon=True).start()

    def _update_check_worker(self, repo, silent):
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        request = urllib.request.Request(api_url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DAV-to-MP4-Updater",
        })
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                release = json.loads(response.read().decode("utf-8"))
            tag = str(release.get("tag_name", "")).strip()
            page_url = str(release.get("html_url", f"https://github.com/{repo}/releases/latest"))
            latest = parse_version(tag)
            current = parse_version(APP_VERSION)
            if not latest:
                raise ValueError("GitHub Release không có tag phiên bản hợp lệ.")
            if current and latest > current:
                self.root.after(0, lambda: self._show_update_available(tag, page_url))
            elif not silent:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Kiểm tra cập nhật",
                    f"Bạn đang dùng phiên bản {APP_VERSION}. Đây là phiên bản mới nhất ({tag})."
                ))
            self.root.after(0, lambda: self.status.set(f"Phiên bản {APP_VERSION}"))
        except urllib.error.HTTPError as exc:
            detail = "Không tìm thấy bản Release công khai." if exc.code == 404 else f"GitHub trả về lỗi HTTP {exc.code}."
            self.root.after(0, lambda d=detail: self._update_check_failed(d, silent))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            detail = f"Không kiểm tra được cập nhật: {exc}"
            self.root.after(0, lambda d=detail: self._update_check_failed(d, silent))

    def _show_update_available(self, latest_version, release_url):
        self.status.set(f"Có phiên bản mới: {latest_version}")
        if messagebox.askyesno(
            "Có bản cập nhật mới",
            f"Đã có DAV sang MP4 phiên bản {latest_version}.\n"
            f"Phiên bản hiện tại: {APP_VERSION}.\n\n"
            "Bạn có muốn mở trang tải bản cập nhật không?\n"
            "Ứng dụng sẽ không tự cài đặt hoặc thay đổi file trên máy.",
        ):
            import webbrowser
            webbrowser.open(release_url)

    def _update_check_failed(self, detail, silent):
        self.status.set(f"Phiên bản {APP_VERSION}")
        if not silent:
            messagebox.showwarning(
                "Kiểm tra cập nhật",
                detail + "\n\nKiểm tra kết nối Internet và cấu hình GitHub Releases."
            )

    def build_ui(self):
        # Use the clam theme so accent colors are consistent across Windows themes.
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.colors = {
            "page": "#f2f6fc", "card": "#ffffff", "navy": "#153b66",
            "blue": "#1769aa", "blue_hover": "#0f568f", "text": "#203247",
            "muted": "#64748b", "border": "#d9e2ef", "green": "#16804a",
            "green_hover": "#11683c", "soft_blue": "#eaf3fc"
        }
        c = self.colors
        self.root.configure(bg=c["page"])
        style.configure(".", font=("Segoe UI", 10), background=c["page"], foreground=c["text"])
        style.configure("TFrame", background=c["page"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("Header.TFrame", background=c["navy"])
        style.configure("MainTitle.TLabel", font=("Segoe UI", 22, "bold"), foreground="#ffffff", background=c["navy"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#d8e7f7", background=c["navy"])
        style.configure("TLabel", background=c["page"], foreground=c["text"])
        style.configure("Hint.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
        style.configure("TLabelframe", background=c["page"], bordercolor=c["border"], relief="solid", padding=10)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground=c["navy"], background=c["page"])
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 10), background="#ffffff", foreground=c["text"], bordercolor=c["border"])
        style.map("TButton", background=[("active", c["soft_blue"]), ("disabled", "#e8edf3")])
        style.configure("Accent.TButton", padding=(12, 8), font=("Segoe UI", 10, "bold"), background=c["blue"], foreground="#ffffff", bordercolor=c["blue"])
        style.map("Accent.TButton", background=[("active", c["blue_hover"]), ("disabled", "#aabed2")], foreground=[("disabled", "#f7f9fc")])
        style.configure("Start.TButton", font=("Segoe UI", 12, "bold"), padding=(20, 11), background=c["green"], foreground="#ffffff", bordercolor=c["green"])
        style.map("Start.TButton", background=[("active", c["green_hover"]), ("disabled", "#aab8b1")], foreground=[("disabled", "#ffffff")])
        style.configure("Treeview", rowheight=31, font=("Segoe UI", 10), background="#ffffff", fieldbackground="#ffffff", foreground=c["text"], bordercolor=c["border"])
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=(8, 9), background="#e7eef7", foreground=c["navy"])
        style.map("Treeview", background=[("selected", c["blue"])], foreground=[("selected", "#ffffff")])
        style.configure("Horizontal.TProgressbar", thickness=16, troughcolor="#e3eaf3", background=c["blue"], bordercolor="#e3eaf3", lightcolor=c["blue"], darkcolor=c["blue"])
        style.configure("TRadiobutton", background=c["page"], font=("Segoe UI", 10))
        style.configure("TEntry", padding=7, fieldbackground="#ffffff")

        main = ttk.Frame(self.root, padding=(16, 14, 16, 14))
        main.pack(fill="both", expand=True)

        # Dedicated bottom action panel is packed first to reserve its full height; buttons stay visible.
        action_box = ttk.LabelFrame(main, text="  CHUYỂN ĐỔI  ", padding=(12, 9))
        action_box.pack(fill="x", side="bottom")
        status_row = ttk.Frame(action_box)
        status_row.pack(fill="x")
        ttk.Label(status_row, textvariable=self.status, wraplength=760).pack(side="left", fill="x", expand=True, anchor="w")
        ttk.Label(status_row, textvariable=self.progress_text, font=("Segoe UI", 11, "bold"), foreground=c["blue"]).pack(side="right", padx=(10, 0))
        self.progress = ttk.Progressbar(action_box, variable=self.progress_value, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 10))
        action_row = ttk.Frame(action_box)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="📂  Mở thư mục MP4", command=self.open_output).pack(side="left")
        ttk.Button(action_row, text="Nhật ký", command=self.show_log).pack(side="left", padx=8)
        self.stop_button = ttk.Button(action_row, text="Dừng sau file hiện tại", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(action_row, text="▶  BẮT ĐẦU CHUYỂN ĐỔI", style="Start.TButton", command=self.start)
        self.start_button.pack(side="right")


        # Header banner
        header = ttk.Frame(main, style="Header.TFrame", padding=(18, 15))
        header.pack(fill="x", pady=(0, 12))
        title_col = ttk.Frame(header, style="Header.TFrame")
        title_col.pack(side="left", fill="x", expand=True)
        ttk.Label(title_col, text="Video camera sang MP4", style="MainTitle.TLabel").pack(anchor="w")
        ttk.Label(title_col, text="Hỗ trợ nhiều định dạng camera/đầu ghi · Giữ nguyên file gốc", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Button(header, text="Giới thiệu", command=self.about_dialog).pack(side="right", anchor="center", padx=(8, 0))
        ttk.Button(header, text="Cập nhật", command=lambda: self.check_for_updates(silent=False)).pack(side="right", anchor="center", padx=(8, 0))
        ttk.Button(header, text="⚙  FFmpeg / Cài đặt", command=self.settings_dialog).pack(side="right", anchor="center", padx=(12, 0))

        # Step 1
        source_box = ttk.LabelFrame(main, text="  1. CHỌN VIDEO CAMERA / ĐẦU GHI  ", padding=10)
        source_box.pack(fill="x", pady=(0, 8))
        source_buttons = ttk.Frame(source_box)
        source_buttons.pack(fill="x")
        ttk.Button(source_buttons, text="＋  Chọn video...", style="Accent.TButton", command=self.choose_files).pack(side="left")
        ttk.Button(source_buttons, text="▣  Quét thư mục...", command=self.choose_folder).pack(side="left", padx=8)
        ttk.Button(source_buttons, text="Xóa danh sách", command=self.clear_list).pack(side="left")
        self.count_label = ttk.Label(source_buttons, text="0 file", font=("Segoe UI", 10, "bold"), foreground=c["blue"])
        self.count_label.pack(side="right", padx=(8, 4))

        # Step 2
        out_box = ttk.LabelFrame(main, text="  2. NƠI LƯU MP4  ", padding=10)
        out_box.pack(fill="x", pady=(0, 8))
        out_row = ttk.Frame(out_box)
        out_row.pack(fill="x")
        ttk.Entry(out_row, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="Chọn thư mục...", command=self.choose_output).pack(side="left", padx=(8, 0))
        ttk.Label(out_box, text="Để trống để lưu MP4 cạnh video gốc. File gốc sẽ không bị xóa.", style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        # Conversion mode
        options = ttk.Frame(main)
        options.pack(fill="x", pady=(0, 8))
        ttk.Label(options, text="CHẾ ĐỘ:", font=("Segoe UI", 10, "bold"), foreground=c["navy"]).pack(side="left", padx=(2, 8))
        ttk.Radiobutton(options, text="Nhanh — giữ nguyên chất lượng", variable=self.mode, value="fast").pack(side="left")
        ttk.Radiobutton(options, text="Tương thích — dễ phát hơn", variable=self.mode, value="compatible").pack(side="left", padx=(14, 0))

        # Step 3: queue
        list_box = ttk.LabelFrame(main, text="  3. DANH SÁCH VIDEO VÀ TÊN ĐẦU RA  ", padding=9)
        list_box.pack(fill="both", expand=True, pady=(0, 8))
        list_box.rowconfigure(0, weight=1)
        list_box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_box, columns=("source", "output", "status"), show="headings", height=5, selectmode="browse")
        self.tree.heading("source", text="VIDEO GỐC")
        self.tree.heading("output", text="TÊN MP4 SẼ TẠO")
        self.tree.heading("status", text="TRẠNG THÁI")
        self.tree.column("source", width=360, minwidth=180, anchor="w", stretch=True)
        self.tree.column("output", width=330, minwidth=180, anchor="w", stretch=True)
        self.tree.column("status", width=145, minwidth=120, anchor="center", stretch=False)
        scrollbar = ttk.Scrollbar(list_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("pending", foreground="#64748b")
        self.tree.tag_configure("working", foreground="#1769aa")
        self.tree.tag_configure("success", foreground="#16804a")
        self.tree.tag_configure("error", foreground="#c0392b")
        self.tree.tag_configure("skipped", foreground="#9a6700")
        self.tree.bind("<<TreeviewSelect>>", self.on_select_file)

        rename_row = ttk.Frame(list_box)
        rename_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        ttk.Label(rename_row, text="Tên MP4:").pack(side="left")
        self.rename_entry = ttk.Entry(rename_row, textvariable=self.rename_var)
        self.rename_entry.pack(side="left", fill="x", expand=True, padx=9)
        self.rename_entry.bind("<Return>", lambda _event: self.apply_rename())
        ttk.Button(rename_row, text="Áp dụng tên", command=self.apply_rename).pack(side="left")
        ttk.Label(list_box, text="Chọn một dòng để đổi tên. Không cần nhập đuôi .mp4.", style="Hint.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.log_lines = []
    def log(self, message):
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-500:]

    def show_log(self):
        win = tk.Toplevel(self.root)
        win.title("Nhật ký và lỗi")
        win.geometry("760x400")
        text = tk.Text(win, wrap="word", font=("Consolas", 9))
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        text.insert("end", "\n".join(self.log_lines) or "Chưa có nhật ký.")
        text.configure(state="disabled")

    def choose_files(self):
        patterns = " ".join("*" + ext for ext in sorted(VIDEO_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Chọn một hoặc nhiều video camera/đầu ghi",
            filetypes=(("Video camera phổ biến", patterns), ("Tất cả file", "*.*"))
        )
        if paths:
            self.add_files([Path(p) for p in paths])

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa video camera/đầu ghi")
        if not folder:
            return
        paths = sorted((p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
                       key=lambda p: str(p).lower())
        self.add_files(paths)
        self.log(f"Đã quét thư mục {folder}: tìm thấy {len(paths)} video có đuôi được hỗ trợ.")
        self.status.set(f"Đã tìm thấy {len(paths)} video camera/đầu ghi trong thư mục đã chọn.")

    def add_files(self, paths):
        known = {str(p).lower() for p in self.files}
        added = 0
        for p in paths:
            if not p.is_file() or str(p).lower() in known:
                continue
            self.files.append(p)
            self.output_names[str(p)] = p.stem
            known.add(str(p).lower())
            self.tree.insert("", "end", iid=str(p),
                             values=(p.name, self.output_names[str(p)] + ".mp4", "Chờ xử lý"), tags=("pending",))
            added += 1
        self.update_count()
        if added:
            self.log(f"Đã thêm {added} video camera/đầu ghi.")
            self.status.set(f"Đã thêm {added} video. Kiểm tra danh sách rồi bấm BẮT ĐẦU CHUYỂN ĐỔI.")

    def update_count(self):
        self.count_label.configure(text=f"{len(self.files)} file")

    def clear_list(self):
        if self.running:
            return
        self.files.clear()
        self.output_names.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.rename_var.set("")
        self.progress_value.set(0)
        self.progress_text.set("0%")
        self.update_count()
        self.status.set("Danh sách đã được xóa.")

    def on_select_file(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self.rename_var.set(self.output_names.get(selected[0], ""))

    def apply_rename(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Chưa chọn file", "Hãy chọn một dòng trong danh sách trước.")
            return
        name = self.rename_var.get().strip()
        if name.lower().endswith(".mp4"):
            name = name[:-4]
        invalid = any(ch in name for ch in r'\/:*?"<>|')
        if not name or name in (".", "..") or invalid:
            messagebox.showerror("Tên file chưa hợp lệ", "Nhập tên file đơn giản, không chứa ký tự \\ / : * ? \" < > |.")
            return
        source_id = selected[0]
        # Prevent two input files from generating the same output name.
        if any(k != source_id and v.casefold() == name.casefold() for k, v in self.output_names.items()):
            messagebox.showerror("Tên bị trùng", "Một file khác trong danh sách đã dùng tên này. Hãy chọn tên khác.")
            return
        self.output_names[source_id] = name
        vals = list(self.tree.item(source_id, "values"))
        vals[1] = name + ".mp4"
        self.tree.item(source_id, values=vals)
        self.log(f"Đổi tên đầu ra cho {Path(source_id).name} thành {name}.mp4")
        self.status.set(f"Tên đầu ra đã đổi thành {name}.mp4.")

    def choose_output(self):
        folder = filedialog.askdirectory(title="Chọn thư mục lưu file MP4")
        if folder:
            self.output_dir.set(folder)
            self.settings["output_dir"] = folder
            self.save_settings()
            self.log(f"Thư mục đầu ra: {folder}")

    def save_settings(self):
        self.settings.update({"ffmpeg": self.ffmpeg.get(), "output_dir": self.output_dir.get(), "mode": self.mode.get()})
        write_settings(self.settings)

    def settings_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("FFmpeg / Cài đặt")
        win.geometry("660x190")
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Đường dẫn ffmpeg.exe").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=6)
        ttk.Entry(row, textvariable=self.ffmpeg).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Chọn...", command=lambda: self.pick_ffmpeg(win)).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="FFmpeg là công cụ cần thiết để chuyển đổi video.").pack(anchor="w", pady=(0, 8))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Kiểm tra FFmpeg", command=lambda: self.check_ffmpeg(win)).pack(side="left")
        ttk.Button(buttons, text="Lưu", command=lambda: (self.save_settings(), win.destroy())).pack(side="right")

    def pick_ffmpeg(self, parent):
        path = filedialog.askopenfilename(parent=parent, title="Chọn ffmpeg.exe",
                                          filetypes=(("ffmpeg.exe", "ffmpeg.exe"), ("EXE", "*.exe"), ("Tất cả", "*.*")))
        if path:
            self.ffmpeg.set(path)

    def check_ffmpeg(self, parent=None):
        path = Path(self.ffmpeg.get().strip().strip('"'))
        if not path.is_file():
            answer = messagebox.askyesno(
                "Thiếu FFmpeg",
                "Ứng dụng cần FFmpeg để xử lý video.\n\n"
                "Bạn có thể tải bản Windows tại trang tải chính thức của nhà phát triển, "
                "sau đó giải nén và chọn ffmpeg.exe.\n\nMở trang tải FFmpeg ngay không?",
                parent=parent or self.root)
            if answer:
                import webbrowser
                webbrowser.open("https://www.gyan.dev/ffmpeg/builds/")
            return False
        try:
            result = subprocess.run([str(path), "-version"], capture_output=True, text=True,
                                    errors="replace", timeout=10)
            if result.returncode == 0:
                self.log("Kiểm tra FFmpeg thành công.")
                messagebox.showinfo("FFmpeg sẵn sàng", "Đã tìm thấy và chạy được FFmpeg.", parent=parent or self.root)
                return True
            messagebox.showerror("FFmpeg gặp lỗi", (result.stderr or result.stdout)[-1200:], parent=parent or self.root)
        except (OSError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror("Không chạy được FFmpeg", str(exc), parent=parent or self.root)
        return False

    def start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showwarning("Chưa chọn video", "Hãy bấm 'Chọn video...' hoặc 'Quét thư mục...' trước.")
            return
        ffmpeg = Path(self.ffmpeg.get().strip().strip('"'))
        if not ffmpeg.is_file():
            choice = messagebox.askyesnocancel(
                "Thiếu FFmpeg",
                "Chưa tìm thấy ffmpeg.exe.\n\n"
                "Chọn Có để chọn file FFmpeg đã có.\n"
                "Chọn Không để mở trang tải FFmpeg.\n"
                "Chọn Hủy để quay lại.")
            if choice is True:
                self.settings_dialog()
            elif choice is False:
                import webbrowser
                webbrowser.open("https://www.gyan.dev/ffmpeg/builds/")
                messagebox.showinfo("Cài FFmpeg", "Tải gói Windows, giải nén rồi chọn file bin\\ffmpeg.exe trong phần Cài đặt FFmpeg.")
            return
        self.save_settings()
        self.settings.update({"ffmpeg": self.ffmpeg.get(), "output_dir": self.output_dir.get(), "mode": self.mode.get()})
        self.running = True
        self.stop_requested = False
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress_value.set(0)
        self.progress_text.set("0%")
        self.status.set("Đang chuẩn bị chuyển đổi...")
        thread = threading.Thread(target=self.worker, daemon=True)
        thread.start()

    def stop(self):
        if self.running:
            self.stop_requested = True
            self.stop_button.configure(state="disabled")
            self.status.set("Đã yêu cầu dừng; file hiện tại sẽ hoàn tất trước khi dừng.")
            self.log("Người dùng yêu cầu dừng sau file hiện tại.")

    def worker(self):
        succeeded = failed = skipped = 0
        items = list(self.files)
        total = len(items)
        ffmpeg = self.settings["ffmpeg"].strip().strip('"')
        chosen_out = self.settings["output_dir"].strip().strip('"')
        mode = self.settings.get("mode", "fast")

        for i, source in enumerate(items, 1):
            if self.stop_requested:
                break
            output_dir = Path(chosen_out) if chosen_out else source.parent
            output = output_dir / (self.output_names.get(str(source), source.stem) + ".mp4")
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                failed += 1
                self.events.put(("log", f"Không tạo được thư mục {output_dir}: {exc}"))
                self.events.put(("row", str(source), "Lỗi thư mục"))
                self.events.put(("progress", i, total))
                continue

            if output.exists():
                skipped += 1
                self.events.put(("row", str(source), "Đã tồn tại"))
                self.events.put(("log", f"Bỏ qua {source.name}: {output.name} đã tồn tại, không ghi đè."))
                self.events.put(("progress", i, total))
                continue

            self.events.put(("status", f"Đang chuyển {i}/{total}: {source.name}"))
            self.events.put(("row", str(source), "Đang chuyển"))
            # In fast mode, try stream-copy first. If the source codec/container is not
            # suitable for MP4, automatically retry with H.264/AAC re-encoding.
            attempts = ["copy", "encode"] if mode == "fast" else ["encode"]
            final_rc = 1
            stderr = []
            try:
                for attempt_index, attempt in enumerate(attempts):
                    try:
                        if output.exists():
                            output.unlink()
                    except OSError:
                        pass
                    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-i", str(source),
                           "-map", "0:v:0", "-map", "0:a?"]
                    if attempt == "copy":
                        cmd += ["-c", "copy", "-movflags", "+faststart"]
                    else:
                        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart"]
                    cmd.append(str(output))
                    self.events.put(("status", f"Đang chuyển {i}/{total}: {source.name}" if attempt == "copy" else f"Đang mã hóa tương thích {i}/{total}: {source.name}"))
                    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                            text=True, errors="replace")
                    self.proc = proc
                    stderr = []
                    while True:
                        line = proc.stderr.readline()
                        if line:
                            stderr.append(line.rstrip())
                            stderr = stderr[-30:]
                        elif proc.poll() is not None:
                            break
                    final_rc = proc.wait()
                    self.proc = None
                    if final_rc == 0 and output.is_file() and output.stat().st_size > 0:
                        break
                    if attempt == "copy" and len(attempts) > 1:
                        self.events.put(("log", f"{source.name}: không phù hợp với chế độ giữ nguyên luồng; tự động thử mã hóa H.264/AAC."))
                if final_rc == 0 and output.is_file() and output.stat().st_size > 0:
                    succeeded += 1
                    self.events.put(("row", str(source), "Thành công"))
                    method = " (đã mã hóa tương thích)" if mode == "fast" and attempts[-1] == "encode" and attempt == "encode" else ""
                    self.events.put(("log", f"Chuyển thành công: {source.name} → {output.name}{method}"))
                else:
                    failed += 1
                    self.events.put(("row", str(source), "Lỗi"))
                    detail = "\n".join(stderr[-8:]) or "FFmpeg không cung cấp chi tiết lỗi."
                    self.events.put(("log", f"{source.name}: FFmpeg không thể đọc hoặc chuyển đổi file này. File có thể dùng định dạng độc quyền, bị hỏng hoặc cần phần mềm xuất video chính hãng.\n{detail}"))
                    try:
                        if output.exists():
                            output.unlink()
                    except OSError:
                        pass
            except OSError as exc:
                self.proc = None
                failed += 1
                self.events.put(("row", str(source), "Lỗi"))
                self.events.put(("log", f"Không chạy được FFmpeg: {exc}"))
            self.events.put(("progress", i, total))

        self.events.put(("finished", succeeded, failed, skipped, total, self.stop_requested))

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self.log(event[1])
                elif kind == "status":
                    self.status.set(event[1])
                elif kind == "row":
                    _, iid, value = event
                    if self.tree.exists(iid):
                        vals = list(self.tree.item(iid, "values"))
                        vals[2] = value
                        tag = "pending"
                        if value in ("Đang chuyển",):
                            tag = "working"
                        elif value == "Thành công":
                            tag = "success"
                        elif value in ("Lỗi", "Lỗi thư mục"):
                            tag = "error"
                        elif value == "Đã tồn tại":
                            tag = "skipped"
                        self.tree.item(iid, values=vals, tags=(tag,))
                elif kind == "progress":
                    _, index, total = event
                    pct = index / max(total, 1) * 100
                    self.progress_value.set(pct)
                    self.progress_text.set(f"{pct:.0f}%  ·  {index}/{total} file")
                elif kind == "finished":
                    _, succeeded, failed, skipped, total, stopped = event
                    self.running = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("Đã dừng theo yêu cầu." if stopped else "Hoàn tất! Bấm 'Mở thư mục MP4' để xem video.")
                    if total and not stopped:
                        self.progress_text.set(f"100%  ·  {total}/{total} file")
                    summary = f"Kết quả: {succeeded} thành công, {failed} lỗi, {skipped} bỏ qua."
                    self.log(summary)
                    if not stopped:
                        messagebox.showinfo("Hoàn tất", f"Đã xử lý {total} file.\n\nThành công: {succeeded}\nLỗi: {failed}\nBỏ qua: {skipped}\n\nCác file video gốc được giữ nguyên.")
        except queue.Empty:
            pass
        self.root.after(100, self.process_events)

    def open_output(self):
        folder = self.output_dir.get().strip().strip('"')
        if not folder:
            selected = self.tree.selection()
            if selected:
                folder = str(Path(selected[0]).parent)
            elif self.files:
                folder = str(self.files[0].parent)
            else:
                messagebox.showinfo("Chưa có video", "Hãy chọn video camera/đầu ghi trước.")
                return
        path = Path(folder)
        if not path.is_dir():
            messagebox.showinfo("Chưa có thư mục kết quả", "Thư mục chưa tồn tại. Hãy bắt đầu chuyển đổi trước.")
            return
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("Không mở được thư mục", str(exc))

    def close(self):
        if self.running:
            if not messagebox.askyesno("Đang chuyển đổi", "Yêu cầu dừng sau file hiện tại rồi thoát?"):
                return
            self.stop_requested = True
            self.save_settings()
            self.wait_close()
        else:
            self.save_settings()
            self.root.destroy()

    def wait_close(self):
        if self.running:
            self.root.after(200, self.wait_close)
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.0)
    except tk.TclError:
        pass
    DavToMp4App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
