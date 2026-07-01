# -*- coding: utf-8 -*-
"""
OpenList GUI Manager (Enhanced Version)
A modern, dark-themed Windows GUI client for managing OpenList server.
Features:
- Start/Stop/Restart server.
- Real-time log streaming with search filtering and exporting.
- Process CPU, RAM, and Uptime monitoring.
- Registry-based Windows Auto-Start on Boot.
- Auto-Restart on unexpected server crash.
- Configuration and SQLite database Backup & Restore.
- Visual configuration editor for data/config.json.
- Admin password query and reset.
- System Tray integration (graceful fallback if pystray not installed).
"""

import sys
import os
import subprocess
import threading
import time
import json
import webbrowser
import ctypes
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Import theme configurations
from theme import *

# Try importing optional dependencies
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

try:
    import winreg
    REG_AVAILABLE = True
except ImportError:
    REG_AVAILABLE = False

# Force dark mode globally to prevent system light-theme override
ctk.set_appearance_mode("dark")

# ==============================================================================
# DPI Awareness Setup
# ==============================================================================
def _enable_dpi_awareness():
    """Enables Per-Monitor DPI Awareness V2 for crisp rendering on high-DPI displays."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


class OpenListGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configure Window
        self.title("OpenList GUI 极速管理大师")
        self.geometry("1000x680")
        self.configure(fg_color=BG_MAIN)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Center Window
        self._center_window(1000, 680)

        # State Variables
        self.server_process = None
        self.external_server_pid = None
        self.alist_path = self._detect_alist_path()
        self.log_thread = None
        self.is_reading_logs = False
        self.start_time = None
        self.all_log_lines = []

        # GUI Settings Variables (initialized before loading config)
        self.enable_autorestart_var = ctk.BooleanVar(value=True)
        self.enable_tray_var = ctk.BooleanVar(value=TRAY_AVAILABLE)
        self.load_gui_config()

        # UI Setup
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Draw Sidebar & Main Content
        self.create_sidebar()
        self.create_main_container()
        
        # Setup System Tray
        self.setup_tray()

        # Default Active Tab
        self.select_tab("control")

        # Start periodic status checker
        self.check_server_status_loop()

    def _center_window(self, width, height):
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _detect_alist_path(self):
        """Detects alist.exe in the workspace root or current directory."""
        parent_dir_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alist.exe"))
        if os.path.exists(parent_dir_path):
            return parent_dir_path
        
        current_dir_path = os.path.abspath("alist.exe")
        if os.path.exists(current_dir_path):
            return current_dir_path
            
        return ""

    def get_gui_dir(self):
        """Gets the directory of the GUI manager (executable or workspace root)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(os.path.abspath(sys.executable))
        else:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _get_gui_config_path(self):
        return os.path.join(self.get_gui_dir(), "gui_config.json")

    def load_gui_config(self):
        """Loads GUI-specific configurations (like alist.exe path)."""
        config_path = self._get_gui_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved_path = data.get("alist_path", "")
                    if saved_path and os.path.exists(saved_path):
                        self.alist_path = saved_path
                    
                    autorestart = data.get("enable_autorestart", True)
                    if hasattr(self, 'enable_autorestart_var'):
                        self.enable_autorestart_var.set(autorestart)
                    
                    enable_tray = data.get("enable_tray", TRAY_AVAILABLE)
                    if hasattr(self, 'enable_tray_var'):
                        self.enable_tray_var.set(enable_tray and TRAY_AVAILABLE)
            except Exception:
                pass

    def save_gui_config(self):
        """Saves GUI-specific configurations to a local JSON file."""
        config_path = self._get_gui_config_path()
        path = self.path_entry.get().strip() if hasattr(self, 'path_entry') else self.alist_path
        data = {
            "alist_path": path,
            "enable_autorestart": self.enable_autorestart_var.get() if hasattr(self, 'enable_autorestart_var') else True,
            "enable_tray": self.enable_tray_var.get() if hasattr(self, 'enable_tray_var') else TRAY_AVAILABLE
        }
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ==============================================================================
    # System Tray Integration
    # ==============================================================================
    def setup_tray(self):
        """Initializes and runs the system tray icon in a background thread."""
        global TRAY_AVAILABLE
        if not TRAY_AVAILABLE:
            self.safe_append_log(f"[{time.strftime('%H:%M:%S')}] 💡 提示: 未安装 'pystray'，系统托盘功能已禁用。可执行 'pip install pystray' 开启。\n")
            return
        
        try:
            image = self._create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", self.show_window, default=True),
                pystray.MenuItem("启动服务", lambda: self.after(0, self.start_server), enabled=lambda item: self.server_process is None),
                pystray.MenuItem("停止服务", lambda: self.after(0, self.stop_server), enabled=lambda item: self.server_process is not None),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("彻底退出", self.quit_app)
            )
            self.tray_icon = pystray.Icon("OpenListGUI", image, "OpenList GUI", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            TRAY_AVAILABLE = False
            self.safe_append_log(f"[{time.strftime('%H:%M:%S')}] ⚠️ 系统托盘初始化失败: {str(e)}\n")

    def _create_tray_image(self):
        """Generates a premium-looking tray icon image dynamically using PIL."""
        image = Image.new("RGBA", (64, 64), (15, 23, 42, 255)) # BG_MAIN
        draw = ImageDraw.Draw(image)
        # Draw sky-blue circle
        draw.ellipse((8, 8, 56, 56), fill=(56, 189, 248, 255)) # COLOR_ACCENT
        # Draw white stylized 'A'
        draw.polygon([(32, 16), (20, 48), (44, 48)], fill=(255, 255, 255, 255))
        draw.polygon([(32, 24), (24, 44), (40, 44)], fill=(56, 189, 248, 255))
        draw.line([(26, 40), (38, 40)], fill=(255, 255, 255, 255), width=3)
        return image

    def show_window(self):
        """Restores the GUI window."""
        self.after(0, self.deiconify)
        self.after(0, self.focus_force)

    def quit_app(self):
        """Schedules the clean exit on the main Tkinter thread."""
        self.after(0, self._real_quit_app)

    def _real_quit_app(self):
        """Closes the GUI and cleanly terminates the server process on the main thread."""
        if self.server_process:
            self.stop_server()
        if TRAY_AVAILABLE and hasattr(self, 'tray_icon'):
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)

    # ==============================================================================
    # Navigation & Sidebar
    # ==============================================================================
    def create_sidebar(self):
        """Creates the navigation sidebar."""
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=BG_SIDEBAR, border_width=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(7, weight=1)

        # App Logo / Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="OpenList GUI", 
            font=FONT_TITLE, 
            text_color=COLOR_ACCENT
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 5))

        self.subtitle_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="极速管理大师 v1.1", 
            font=FONT_MUTED, 
            text_color=COLOR_TEXT_MUTED
        )
        self.subtitle_label.grid(row=1, column=0, padx=20, pady=(0, 25))

        # Sidebar Buttons
        self.btn_control = ctk.CTkButton(
            self.sidebar_frame, text="💻 控制面板", font=FONT_SUBTITLE,
            fg_color="transparent", text_color=COLOR_TEXT_MAIN, anchor="w",
            hover_color=BG_CARD_HOVER, height=40, corner_radius=8,
            command=lambda: self.select_tab("control")
        )
        self.btn_control.grid(row=2, column=0, padx=15, pady=6, sticky="ew")

        self.btn_config = ctk.CTkButton(
            self.sidebar_frame, text="⚙️ 配置编辑", font=FONT_SUBTITLE,
            fg_color="transparent", text_color=COLOR_TEXT_MAIN, anchor="w",
            hover_color=BG_CARD_HOVER, height=40, corner_radius=8,
            command=lambda: self.select_tab("config")
        )
        self.btn_config.grid(row=3, column=0, padx=15, pady=6, sticky="ew")

        self.btn_admin = ctk.CTkButton(
            self.sidebar_frame, text="🔑 管理员命令", font=FONT_SUBTITLE,
            fg_color="transparent", text_color=COLOR_TEXT_MAIN, anchor="w",
            hover_color=BG_CARD_HOVER, height=40, corner_radius=8,
            command=lambda: self.select_tab("admin")
        )
        self.btn_admin.grid(row=4, column=0, padx=15, pady=6, sticky="ew")

        self.btn_advanced = ctk.CTkButton(
            self.sidebar_frame, text="🔧 系统设置", font=FONT_SUBTITLE,
            fg_color="transparent", text_color=COLOR_TEXT_MAIN, anchor="w",
            hover_color=BG_CARD_HOVER, height=40, corner_radius=8,
            command=lambda: self.select_tab("advanced")
        )
        self.btn_advanced.grid(row=5, column=0, padx=15, pady=6, sticky="ew")

        self.btn_help = ctk.CTkButton(
            self.sidebar_frame, text="❓ 帮助说明", font=FONT_SUBTITLE,
            fg_color="transparent", text_color=COLOR_TEXT_MAIN, anchor="w",
            hover_color=BG_CARD_HOVER, height=40, corner_radius=8,
            command=lambda: self.select_tab("help")
        )
        self.btn_help.grid(row=6, column=0, padx=15, pady=6, sticky="ew")

        # Telemetry Metrics Frame
        self.metrics_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.metrics_frame.grid(row=8, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        self.uptime_lbl = ctk.CTkLabel(self.metrics_frame, text="运行时间: --:--:--", font=FONT_MUTED, text_color=COLOR_TEXT_MUTED, anchor="w")
        self.uptime_lbl.pack(fill="x", pady=2)
        
        self.resources_lbl = ctk.CTkLabel(self.metrics_frame, text="CPU: -- | RAM: --", font=FONT_MUTED, text_color=COLOR_TEXT_MUTED, anchor="w")
        self.resources_lbl.pack(fill="x", pady=2)

        # Status Badge
        self.status_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.status_frame.grid(row=9, column=0, padx=20, pady=(10, 25), sticky="ew")
        
        self.status_dot = ctk.CTkLabel(self.status_frame, text="●", font=(FONT_FAMILY, 16), text_color=COLOR_TEXT_MUTED)
        self.status_dot.pack(side="left", padx=(0, 8))
        
        self.status_text = ctk.CTkLabel(self.status_frame, text="未运行 (Stopped)", font=FONT_BODY, text_color=COLOR_TEXT_MUTED)
        self.status_text.pack(side="left")

    def create_main_container(self):
        """Creates the container frame for hosting different tabs."""
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        # Tab Frames
        self.tab_control = self.build_control_tab()
        self.tab_config = self.build_config_tab()
        self.tab_admin = self.build_admin_tab()
        self.tab_advanced = self.build_advanced_tab()
        self.tab_help = self.build_help_tab()

    def select_tab(self, tab_name):
        """Switches between tabs and updates button highlights."""
        # Hide all tabs
        self.tab_control.grid_forget()
        self.tab_config.grid_forget()
        self.tab_admin.grid_forget()
        self.tab_advanced.grid_forget()
        self.tab_help.grid_forget()

        # Reset button styles
        self.btn_control.configure(fg_color="transparent", text_color=COLOR_TEXT_MAIN)
        self.btn_config.configure(fg_color="transparent", text_color=COLOR_TEXT_MAIN)
        self.btn_admin.configure(fg_color="transparent", text_color=COLOR_TEXT_MAIN)
        self.btn_advanced.configure(fg_color="transparent", text_color=COLOR_TEXT_MAIN)
        self.btn_help.configure(fg_color="transparent", text_color=COLOR_TEXT_MAIN)

        # Show active tab & highlight button
        if tab_name == "control":
            self.tab_control.grid(row=0, column=0, sticky="nsew")
            self.btn_control.configure(fg_color=BG_CARD_HOVER, text_color=COLOR_ACCENT)
        elif tab_name == "config":
            self.tab_config.grid(row=0, column=0, sticky="nsew")
            self.btn_config.configure(fg_color=BG_CARD_HOVER, text_color=COLOR_ACCENT)
            self.load_config_values()
        elif tab_name == "admin":
            self.tab_admin.grid(row=0, column=0, sticky="nsew")
            self.btn_admin.configure(fg_color=BG_CARD_HOVER, text_color=COLOR_ACCENT)
        elif tab_name == "advanced":
            self.tab_advanced.grid(row=0, column=0, sticky="nsew")
            self.btn_advanced.configure(fg_color=BG_CARD_HOVER, text_color=COLOR_ACCENT)
            self.refresh_backups_list()
            self.update_advanced_tab_states()
        elif tab_name == "help":
            self.tab_help.grid(row=0, column=0, sticky="nsew")
            self.btn_help.configure(fg_color=BG_CARD_HOVER, text_color=COLOR_ACCENT)

    # ==============================================================================
    # TAB 1: Control Panel
    # ==============================================================================
    def build_control_tab(self):
        frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # ---- Section 1: Path Selection & Server Controls ----
        ctrl_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        ctrl_card.grid(row=0, column=0, sticky="ew", pady=(0, 15), padx=5)
        ctrl_card.grid_columnconfigure(1, weight=1)

        # Path Row
        path_label = ctk.CTkLabel(ctrl_card, text="程序路径:", font=FONT_SUBTITLE, text_color=COLOR_TEXT_MAIN)
        path_label.grid(row=0, column=0, padx=(15, 10), pady=15, sticky="w")

        self.path_entry = ctk.CTkEntry(ctrl_card, font=FONT_BODY, fg_color=BG_MAIN, border_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MAIN)
        self.path_entry.grid(row=0, column=1, padx=10, pady=15, sticky="ew")
        if self.alist_path:
            self.path_entry.insert(0, self.alist_path)
        else:
            self.path_entry.insert(0, "未检测到 alist.exe，请点击右侧浏览选择...")

        btn_browse = ctk.CTkButton(
            ctrl_card, text="浏览...", font=FONT_BODY, width=80,
            fg_color=BG_CARD_HOVER, hover_color=COLOR_ACCENT_HOVER, text_color=COLOR_TEXT_MAIN,
            command=self.browse_alist_path
        )
        btn_browse.grid(row=0, column=2, padx=(5, 15), pady=15)

        # Control Buttons Row
        btns_frame = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        btns_frame.grid(row=1, column=0, columnspan=3, padx=15, pady=(0, 15), sticky="ew")

        self.btn_start = ctk.CTkButton(
            btns_frame, text="▶ 启动服务", font=FONT_SUBTITLE,
            fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="#ffffff",
            command=self.start_server
        )
        self.btn_start.pack(side="left", padx=(0, 10), expand=True, fill="x")

        self.btn_stop = ctk.CTkButton(
            btns_frame, text="■ 停止服务", font=FONT_SUBTITLE,
            fg_color=COLOR_ERROR, hover_color="#dc2626", text_color="#ffffff",
            state="disabled", command=self.stop_server
        )
        self.btn_stop.pack(side="left", padx=10, expand=True, fill="x")

        self.btn_open_web = ctk.CTkButton(
            btns_frame, text="🌐 打开网盘网页", font=FONT_SUBTITLE,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            command=self.open_web_ui
        )
        self.btn_open_web.pack(side="left", padx=(10, 0), expand=True, fill="x")

        # ---- Section 2: Real-time Console Log ----
        log_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        log_card.grid(row=1, column=0, sticky="nsew", pady=5, padx=5)
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        # Log Toolbar
        log_header_frame = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=10)
        
        log_title = ctk.CTkLabel(log_header_frame, text="实时运行日志 (Console Logs)", font=FONT_HEADER, text_color=COLOR_ACCENT)
        log_title.pack(side="left")

        # Log Search Box
        self.log_search_entry = ctk.CTkEntry(
            log_header_frame, placeholder_text="🔍 过滤日志...", font=FONT_MUTED,
            width=180, height=25, fg_color=BG_MAIN, border_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MAIN
        )
        self.log_search_entry.pack(side="left", padx=20)
        self.log_search_entry.bind("<KeyRelease>", self.on_log_search_changed)

        # Export Logs Button
        btn_export_log = ctk.CTkButton(
            log_header_frame, text="📥 导出日志", font=FONT_MUTED, width=80, height=25,
            fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MUTED,
            command=self.export_logs
        )
        btn_export_log.pack(side="right", padx=(10, 0))

        # Clear Logs Button
        btn_clear_log = ctk.CTkButton(
            log_header_frame, text="🗑️ 清空日志", font=FONT_MUTED, width=80, height=25,
            fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MUTED,
            command=self.clear_logs
        )
        btn_clear_log.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            log_card, font=FONT_CONSOLE, fg_color=BG_CONSOLE, text_color=COLOR_TEXT_CONSOLE,
            border_width=1, border_color=BG_CARD_HOVER, wrap="none"
        )
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")

        return frame

    def browse_alist_path(self):
        file_path = filedialog.askopenfilename(
            title="选择 OpenList 主程序",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
        )
        if file_path:
            self.alist_path = file_path
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, file_path)
            self.save_gui_config()

    def start_server(self):
        """Starts the alist server in a background subprocess."""
        path = self.path_entry.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("错误", "请先指定正确的 alist.exe 程序路径！")
            return

        if self.server_process:
            messagebox.showwarning("警告", "服务已经在运行中！")
            return

        working_dir = os.path.dirname(path)
        
        try:
            self.save_gui_config()  # Save path if edited manually
            self.log_textbox.insert("end", f"[{time.strftime('%H:%M:%S')}] 正在启动 OpenList 服务...\n")
            self.log_textbox.see("end")

            # Spawn subprocess with forced data directory
            data_dir = os.path.join(self.get_gui_dir(), "data")
            self.server_process = subprocess.Popen(
                [path, "server", "--data", data_dir],
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=0x08000000
            )
            
            self.start_time = time.time()

            # Start Log Reading Thread
            self.is_reading_logs = True
            self.log_thread = threading.Thread(target=self._read_logs_loop, daemon=True)
            self.log_thread.start()

            # Update UI
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            
        except Exception as e:
            messagebox.showerror("启动失败", f"启动服务时发生异常：\n{str(e)}")
            self.server_process = None

    def stop_server(self):
        """Stops the alist server and kills the process tree."""
        pid = self.server_process.pid if self.server_process else getattr(self, 'external_server_pid', None)
        if not pid:
            return

        self.log_textbox.insert("end", f"\n[{time.strftime('%H:%M:%S')}] 正在关闭 OpenList 服务...\n")
        self.log_textbox.see("end")

        try:
            # Kill the process tree
            subprocess.run(
                f"taskkill /F /T /PID {pid}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            if self.server_process:
                try:
                    self.server_process.kill()
                except Exception:
                    pass

        self.server_process = None
        self.external_server_pid = None
        self.is_reading_logs = False
        self.start_time = None
        
        # Update UI
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.update_status_ui(running=False)
        self.log_textbox.insert("end", f"[{time.strftime('%H:%M:%S')}] 服务已安全停止。\n")
        self.log_textbox.see("end")

    def _read_logs_loop(self):
        """Background thread to read server output and append to textbox."""
        while self.is_reading_logs and self.server_process:
            line = self.server_process.stdout.readline()
            if not line:
                break
            self.safe_append_log(line)
        self.is_reading_logs = False

    def safe_append_log(self, text):
        def _append():
            # Append to master log
            self.all_log_lines.append(text)
            if len(self.all_log_lines) > 5000:
                self.all_log_lines.pop(0)
            
            # Check filter
            query = self.log_search_entry.get().strip().lower()
            if not query or query in text.lower():
                self.log_textbox.insert("end", text)
                self.log_textbox.see("end")
        self.after(0, _append)

    def on_log_search_changed(self, event=None):
        """Filters logs in real-time based on the search query."""
        query = self.log_search_entry.get().strip().lower()
        self.log_textbox.delete("1.0", "end")
        
        matching = []
        for line in self.all_log_lines:
            if not query or query in line.lower():
                matching.append(line)
                
        self.log_textbox.insert("end", "".join(matching))
        self.log_textbox.see("end")

    def clear_logs(self):
        self.all_log_lines.clear()
        self.log_textbox.delete("1.0", "end")

    def export_logs(self):
        """Saves current logs to a file."""
        if not self.all_log_lines:
            messagebox.showinfo("提示", "当前日志为空，无需导出！")
            return
            
        file_path = filedialog.asksaveasfilename(
            title="导出日志文件",
            defaultextension=".log",
            filetypes=[("Log Files", "*.log"), ("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("".join(self.all_log_lines))
                messagebox.showinfo("成功", f"日志已成功导出至：\n{file_path}")
            except Exception as e:
                messagebox.showerror("导出失败", f"导出日志时发生错误：\n{str(e)}")

    def open_web_ui(self):
        port = self.get_configured_port()
        webbrowser.open(f"http://localhost:{port}")

    def get_configured_port(self):
        config_path = self._get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("scheme", {}).get("http_port", 5244)
            except Exception:
                pass
        return 5244

    def _get_config_path(self):
        return os.path.join(self.get_gui_dir(), "data", "config.json")

    # ==============================================================================
    # TAB 2: Config Editor
    # ==============================================================================
    def build_config_tab(self):
        frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # Info Header Card
        info_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        info_card.grid(row=0, column=0, sticky="ew", pady=(0, 15), padx=5)
        info_card.grid_columnconfigure(0, weight=1)

        self.config_status_label = ctk.CTkLabel(
            info_card, text="🔧 配置文件编辑器", font=FONT_HEADER, text_color=COLOR_ACCENT
        )
        self.config_status_label.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        self.config_path_label = ctk.CTkLabel(
            info_card, text="未检测到配置文件", font=FONT_MUTED, text_color=COLOR_TEXT_MUTED
        )
        self.config_path_label.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")

        # Config Editor Fields Card
        self.fields_card = ctk.CTkScrollableFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        self.fields_card.grid(row=1, column=0, sticky="nsew", pady=5, padx=5)
        self.fields_card.grid_columnconfigure(1, weight=1)

        self.config_entries = {}
        
        # Save Button
        self.btn_save_config = ctk.CTkButton(
            frame, text="💾 保存配置更改 (需要重启服务生效)", font=FONT_SUBTITLE,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            command=self.save_config_values
        )
        self.btn_save_config.grid(row=2, column=0, sticky="ew", pady=15, padx=5)

        return frame

    def load_config_values(self):
        config_path = self._get_config_path()
        self.config_path_label.configure(text=f"配置文件路径: {config_path}")

        for widget in self.fields_card.winfo_children():
            widget.destroy()
        self.config_entries.clear()

        if not os.path.exists(config_path):
            warning_label = ctk.CTkLabel(
                self.fields_card, 
                text="⚠️ 配置文件 'data/config.json' 还未生成。\n第一次成功启动 OpenList 服务后，它将自动在程序目录下创建。\n创建后，您可以在这里可视化修改端口、数据库等参数。",
                font=FONT_BODY, text_color=COLOR_WARNING, justify="left"
            )
            warning_label.grid(row=0, column=0, columnspan=2, padx=20, pady=40, sticky="nsew")
            self.btn_save_config.configure(state="disabled")
            return

        self.btn_save_config.configure(state="normal")
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)
        except Exception as e:
            error_label = ctk.CTkLabel(
                self.fields_card, text=f"❌ 解析 JSON 失败：\n{str(e)}",
                font=FONT_BODY, text_color=COLOR_ERROR
            )
            error_label.grid(row=0, column=0, columnspan=2, padx=20, pady=40)
            return

        row = 0
        
        # --- Group 1: Scheme Settings ---
        scheme_header = ctk.CTkLabel(self.fields_card, text="🌐 网络与访问配置", font=FONT_HEADER, text_color=COLOR_ACCENT)
        scheme_header.grid(row=row, column=0, columnspan=2, padx=15, pady=(15, 10), sticky="w")
        row += 1

        http_port_val = self.config_data.get("scheme", {}).get("http_port", 5244)
        row = self._create_config_entry("http_port", "HTTP 监听端口 (http_port)", str(http_port_val), row)
        
        address_val = self.config_data.get("scheme", {}).get("address", "0.0.0.0")
        row = self._create_config_entry("address", "监听 IP 地址 (address)", address_val, row, tooltip="0.0.0.0 表示允许所有外部设备访问")

        https_port_val = self.config_data.get("scheme", {}).get("https_port", -1)
        row = self._create_config_entry("https_port", "HTTPS 监听端口 (https_port)", str(https_port_val), row, tooltip="-1 表示禁用 HTTPS")

        # --- Group 2: Database Settings ---
        db_header = ctk.CTkLabel(self.fields_card, text="🗄️ 数据库配置", font=FONT_HEADER, text_color=COLOR_ACCENT)
        db_header.grid(row=row, column=0, columnspan=2, padx=15, pady=(20, 10), sticky="w")
        row += 1

        db_type_val = self.config_data.get("database", {}).get("type", "sqlite3")
        row = self._create_config_entry("db_type", "数据库类型 (type)", db_type_val, row, tooltip="可选: sqlite3, mysql, postgres")

        db_host_val = self.config_data.get("database", {}).get("host", "localhost")
        row = self._create_config_entry("db_host", "数据库主机 (host)", db_host_val, row)

        db_port_val = self.config_data.get("database", {}).get("port", 0)
        row = self._create_config_entry("db_port", "数据库端口 (port)", str(db_port_val), row)

        db_name_val = self.config_data.get("database", {}).get("name", "")
        row = self._create_config_entry("db_name", "数据库库名 / 文件名 (name)", db_name_val, row)

        # --- Group 3: Log Settings ---
        log_header = ctk.CTkLabel(self.fields_card, text="📝 日志配置", font=FONT_HEADER, text_color=COLOR_ACCENT)
        log_header.grid(row=row, column=0, columnspan=2, padx=15, pady=(20, 10), sticky="w")
        row += 1

        log_level_val = self.config_data.get("log", {}).get("level", "info")
        row = self._create_config_entry("log_level", "日志输出级别 (level)", log_level_val, row, tooltip="可选: debug, info, warn, error")

    def _create_config_entry(self, key, label_text, value, row, tooltip=""):
        lbl = ctk.CTkLabel(self.fields_card, text=label_text, font=FONT_BODY, text_color=COLOR_TEXT_MAIN)
        lbl.grid(row=row, column=0, padx=15, pady=8, sticky="w")

        entry = ctk.CTkEntry(self.fields_card, font=FONT_BODY, fg_color=BG_MAIN, border_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MAIN)
        entry.insert(0, value)
        entry.grid(row=row, column=1, padx=(10, 15), pady=8, sticky="ew")

        if tooltip:
            help_lbl = ctk.CTkLabel(self.fields_card, text=f"   💡 {tooltip}", font=FONT_MUTED, text_color=COLOR_TEXT_MUTED)
            help_lbl.grid(row=row+1, column=1, padx=(10, 15), pady=(0, 5), sticky="w")
            row += 1

        self.config_entries[key] = entry
        return row + 1

    def save_config_values(self):
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return

        try:
            if "scheme" not in self.config_data:
                self.config_data["scheme"] = {}
            self.config_data["scheme"]["http_port"] = int(self.config_entries["http_port"].get().strip())
            self.config_data["scheme"]["address"] = self.config_entries["address"].get().strip()
            self.config_data["scheme"]["https_port"] = int(self.config_entries["https_port"].get().strip())

            if "database" not in self.config_data:
                self.config_data["database"] = {}
            self.config_data["database"]["type"] = self.config_entries["db_type"].get().strip()
            self.config_data["database"]["host"] = self.config_entries["db_host"].get().strip()
            self.config_data["database"]["port"] = int(self.config_entries["db_port"].get().strip())
            self.config_data["database"]["name"] = self.config_entries["db_name"].get().strip()

            if "log" not in self.config_data:
                self.config_data["log"] = {}
            self.config_data["log"]["level"] = self.config_entries["log_level"].get().strip()

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
                
            messagebox.showinfo("成功", "配置已成功保存！\n如果在运行中，请重启 OpenList 服务以应用新配置。")
            self.load_config_values()
        except ValueError:
            messagebox.showerror("错误", "端口号、数据库端口必须为数字类型，请检查输入格式！")
        except Exception as e:
            messagebox.showerror("保存失败", f"保存配置文件时发生异常：\n{str(e)}")

    # ==============================================================================
    # TAB 3: Admin Tools
    # ==============================================================================
    def build_admin_tab(self):
        frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)

        # Card 1: View Default Admin Password
        view_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        view_card.grid(row=0, column=0, sticky="ew", pady=(0, 15), padx=5)
        view_card.grid_columnconfigure(0, weight=1)

        view_title = ctk.CTkLabel(view_card, text="🔑 默认管理员信息查询", font=FONT_HEADER, text_color=COLOR_ACCENT)
        view_title.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
        
        view_desc = ctk.CTkLabel(
            view_card, text="点击下方按钮运行 admin 命令来读取当前生成的系统初始管理员用户名和密码。", 
            font=FONT_BODY, text_color=COLOR_TEXT_MUTED
        )
        view_desc.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")

        btn_get_admin = ctk.CTkButton(
            view_card, text="🔍 查询初始管理员账户/密码", font=FONT_SUBTITLE,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            command=self.run_admin_query
        )
        btn_get_admin.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="ew")

        # Card 2: Reset Password
        reset_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        reset_card.grid(row=1, column=0, sticky="ew", pady=10, padx=5)
        reset_card.grid_columnconfigure(1, weight=1)

        reset_title = ctk.CTkLabel(reset_card, text="🔒 重置管理员密码", font=FONT_HEADER, text_color=COLOR_ACCENT)
        reset_title.grid(row=0, column=0, columnspan=2, padx=15, pady=(15, 10), sticky="w")

        pwd_label = ctk.CTkLabel(reset_card, text="新密码:", font=FONT_BODY, text_color=COLOR_TEXT_MAIN)
        pwd_label.grid(row=1, column=0, padx=(15, 10), pady=15, sticky="w")

        self.new_pwd_entry = ctk.CTkEntry(
            reset_card, font=FONT_BODY, placeholder_text="请输入新管理员密码...",
            fg_color=BG_MAIN, border_color=BG_CARD_HOVER, text_color=COLOR_TEXT_MAIN
        )
        self.new_pwd_entry.grid(row=1, column=1, padx=(5, 15), pady=15, sticky="ew")

        btn_set_pwd = ctk.CTkButton(
            reset_card, text="设置新密码", font=FONT_SUBTITLE,
            fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="#ffffff",
            command=self.run_admin_reset
        )
        btn_set_pwd.grid(row=2, column=0, columnspan=2, padx=15, pady=(0, 15), sticky="ew")

        # Card 3: Output Area
        self.admin_output_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        self.admin_output_card.grid(row=2, column=0, sticky="ew", pady=15, padx=5)
        self.admin_output_card.grid_columnconfigure(0, weight=1)

        self.admin_output_title = ctk.CTkLabel(self.admin_output_card, text="命令输出结果:", font=FONT_SUBTITLE, text_color=COLOR_TEXT_MUTED)
        self.admin_output_title.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.admin_output_box = ctk.CTkTextbox(
            self.admin_output_card, font=FONT_CONSOLE, fg_color=BG_CONSOLE, text_color=COLOR_TEXT_CONSOLE,
            height=100, border_width=1, border_color=BG_CARD_HOVER
        )
        self.admin_output_box.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="ew")

        return frame

    def run_admin_query(self):
        path = self.path_entry.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("错误", "请先在控制面板中指定正确的 alist.exe 路径！")
            return

        if self.server_process:
            ans = messagebox.askyesno(
                "警告", 
                "服务正在运行中，此时运行管理员账户查询可能会因为数据库文件锁定而失败。\n是否仍要继续尝试？"
            )
            if not ans:
                return

        def _worker():
            self.admin_output_box.delete("1.0", "end")
            self.admin_output_box.insert("end", "正在查询，请稍候...\n")
            
            working_dir = os.path.dirname(path)
            data_dir = os.path.join(self.get_gui_dir(), "data")
            try:
                res = subprocess.run(
                    [path, "admin", "--data", data_dir],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000
                )
                output = res.stdout.strip() if res.stdout else res.stderr.strip()
                if not output:
                    output = "没有返回结果，这通常表示发生了静默错误（请检查服务日志）。"
                
                self.admin_output_box.delete("1.0", "end")
                self.admin_output_box.insert("end", output)
            except Exception as e:
                self.admin_output_box.delete("1.0", "end")
                self.admin_output_box.insert("end", f"查询发生异常：\n{str(e)}")

        threading.Thread(target=_worker, daemon=True).start()

    def run_admin_reset(self):
        path = self.path_entry.get().strip()
        new_pwd = self.new_pwd_entry.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("错误", "请先在控制面板中指定正确的 alist.exe 路径！")
            return

        if not new_pwd:
            messagebox.showerror("错误", "请输入新密码！")
            return

        if len(new_pwd) < 6:
            messagebox.showwarning("警告", "密码建议至少为6位！")

        if self.server_process:
            ans = messagebox.askyesno(
                "警告", 
                "服务正在运行中，重置管理员密码可能会因为数据库被服务进程锁定而失败。\n是否仍要继续尝试？"
            )
            if not ans:
                return

        def _worker():
            self.admin_output_box.delete("1.0", "end")
            self.admin_output_box.insert("end", f"正在重置密码为: {new_pwd} ...\n")
            
            working_dir = os.path.dirname(path)
            data_dir = os.path.join(self.get_gui_dir(), "data")
            try:
                res = subprocess.run(
                    [path, "admin", "set", new_pwd, "--data", data_dir],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000
                )
                output = res.stdout.strip() if res.stdout else res.stderr.strip()
                if not output:
                    output = f"重置密码指令执行成功。\n用户名：admin\n密码：{new_pwd}"
                
                self.admin_output_box.delete("1.0", "end")
                self.admin_output_box.insert("end", output)
                self.new_pwd_entry.delete(0, "end")
            except Exception as e:
                self.admin_output_box.delete("1.0", "end")
                self.admin_output_box.insert("end", f"重置密码失败：\n{str(e)}")

        threading.Thread(target=_worker, daemon=True).start()

    # ==============================================================================
    # TAB 4: Advanced Tools
    # ==============================================================================
    def build_advanced_tab(self):
        frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)

        # Card 1: Windows Integration (Auto-Start & Tray)
        int_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        int_card.grid(row=0, column=0, sticky="ew", pady=(0, 15), padx=5)
        int_card.grid_columnconfigure(0, weight=1)

        int_title = ctk.CTkLabel(int_card, text="⚙️ 系统集成与自动化设置", font=FONT_HEADER, text_color=COLOR_ACCENT)
        int_title.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="w")

        # Autostart switch
        self.autostart_var = ctk.BooleanVar(value=self.is_autostart_enabled())
        self.switch_autostart = ctk.CTkSwitch(
            int_card, text="开机自启动 (Windows Boot Auto-Start)", font=FONT_BODY,
            variable=self.autostart_var, progress_color=COLOR_ACCENT,
            text_color=COLOR_TEXT_MAIN,
            command=self.toggle_autostart
        )
        self.switch_autostart.grid(row=1, column=0, padx=15, pady=10, sticky="w")

        # Auto-restart switch
        self.switch_autorestart = ctk.CTkSwitch(
            int_card, text="崩溃自动重启服务 (Auto-Restart on Crash)", font=FONT_BODY,
            variable=self.enable_autorestart_var, progress_color=COLOR_ACCENT,
            text_color=COLOR_TEXT_MAIN,
            command=self.save_gui_config
        )
        self.switch_autorestart.grid(row=2, column=0, padx=15, pady=10, sticky="w")

        # Tray switch
        self.switch_tray = ctk.CTkSwitch(
            int_card, text="最小化到系统托盘 (Minimize to Tray on Close)", font=FONT_BODY,
            variable=self.enable_tray_var, progress_color=COLOR_ACCENT,
            text_color=COLOR_TEXT_MAIN,
            state="normal" if TRAY_AVAILABLE else "disabled",
            command=self.save_gui_config
        )
        self.switch_tray.grid(row=3, column=0, padx=15, pady=10, sticky="w")

        if not TRAY_AVAILABLE:
            # Add a small tip label below it
            self.tray_tip_lbl = ctk.CTkLabel(
                int_card, text="   💡 提示: 未安装 pystray, 可运行 'pip install pystray' 开启托盘功能",
                font=FONT_MUTED, text_color=COLOR_TEXT_MUTED
            )
            self.tray_tip_lbl.grid(row=4, column=0, padx=15, pady=(0, 10), sticky="w")

        # Card 2: Backup & Restore
        backup_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        backup_card.grid(row=1, column=0, sticky="ew", pady=10, padx=5)
        backup_card.grid_columnconfigure(1, weight=1)

        backup_title = ctk.CTkLabel(backup_card, text="💾 数据备份与还原", font=FONT_HEADER, text_color=COLOR_ACCENT)
        backup_title.grid(row=0, column=0, columnspan=3, padx=15, pady=(15, 10), sticky="w")

        btn_backup = ctk.CTkButton(
            backup_card, text="📸 备份当前数据 (Config & SQLite DB)", font=FONT_BODY,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            command=self.backup_data
        )
        btn_backup.grid(row=1, column=0, columnspan=3, padx=15, pady=10, sticky="ew")

        # Restore section
        restore_lbl = ctk.CTkLabel(backup_card, text="选择要恢复的备份:", font=FONT_BODY, text_color=COLOR_TEXT_MAIN)
        restore_lbl.grid(row=2, column=0, padx=(15, 10), pady=15, sticky="w")

        self.backups_dropdown = ctk.CTkOptionMenu(
            backup_card, values=["未发现备份"], font=FONT_BODY,
            fg_color=BG_MAIN, button_color=BG_CARD_HOVER, button_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT_MAIN, dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER
        )
        self.backups_dropdown.grid(row=2, column=1, padx=10, pady=15, sticky="ew")

        btn_restore = ctk.CTkButton(
            backup_card, text="还原选中备份", font=FONT_BODY, width=100,
            fg_color=COLOR_ERROR, hover_color="#dc2626", text_color="#ffffff",
            command=self.restore_data
        )
        btn_restore.grid(row=2, column=2, padx=(5, 15), pady=15)

        return frame

    def is_autostart_enabled(self):
        if not REG_AVAILABLE:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            winreg.QueryValueEx(key, "OpenListGUI")
            winreg.CloseKey(key)
            return True
        except WindowsError:
            return False

    def toggle_autostart(self):
        """Toggles Windows startup registry key."""
        if not REG_AVAILABLE:
            messagebox.showerror("错误", "当前系统不支持注册表操作！")
            return

        enable = self.autostart_var.get()
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            if enable:
                if getattr(sys, 'frozen', False):
                    cmd = f'"{sys.executable}"'
                else:
                    script_path = os.path.abspath(sys.argv[0])
                    cmd = f'"{sys.executable}" "{script_path}"'
                winreg.SetValueEx(key, "OpenListGUI", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "OpenListGUI")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            messagebox.showerror("错误", f"无法配置自启动：\n{str(e)}")
            self.autostart_var.set(not enable)

    def get_backups_dir(self):
        backups_dir = os.path.join(self.get_gui_dir(), "backups")
        os.makedirs(backups_dir, exist_ok=True)
        return backups_dir

    def refresh_backups_list(self):
        """Scans backups folder and populates dropdown."""
        backups_dir = self.get_backups_dir()
        try:
            dirs = [d for d in os.listdir(backups_dir) if os.path.isdir(os.path.join(backups_dir, d))]
            dirs.sort(reverse=True)
            if dirs:
                self.backups_dropdown.configure(values=dirs)
                self.backups_dropdown.set(dirs[0])
            else:
                self.backups_dropdown.configure(values=["未发现备份"])
                self.backups_dropdown.set("未发现备份")
        except Exception:
            self.backups_dropdown.configure(values=["读取出错"])
            self.backups_dropdown.set("读取出错")

    def update_advanced_tab_states(self):
        self.autostart_var.set(self.is_autostart_enabled())

    def backup_data(self):
        """Creates a timestamped backup of config.json and data.db."""
        path = self.path_entry.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("错误", "请先指定正确的 alist.exe 路径！")
            return
        
        data_dir = os.path.join(self.get_gui_dir(), "data")
        if not os.path.exists(data_dir):
            messagebox.showerror("错误", "未发现数据目录 'data/'，请先成功运行一次服务！")
            return

        import shutil
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_folder = os.path.join(self.get_backups_dir(), f"backup_{timestamp}")
        
        try:
            os.makedirs(backup_folder, exist_ok=True)
            
            # Copy config
            config_file = os.path.join(data_dir, "config.json")
            if os.path.exists(config_file):
                shutil.copy2(config_file, backup_folder)
                
            # Copy SQLite DB
            db_file = os.path.join(data_dir, "data.db")
            if os.path.exists(db_file):
                shutil.copy2(db_file, backup_folder)
                
            messagebox.showinfo("成功", f"备份已成功创建！\n已保存至：\n{backup_folder}")
            self.refresh_backups_list()
        except Exception as e:
            messagebox.showerror("备份失败", f"备份过程中发生错误：\n{str(e)}")

    def restore_data(self):
        """Restores selected backup (stops server first if running)."""
        selected_backup = self.backups_dropdown.get()
        if not selected_backup or selected_backup in ["未发现备份", "读取出错"]:
            messagebox.showerror("错误", "请先选择要恢复的有效备份！")
            return

        ans = messagebox.askyesno(
            "数据恢复确认",
            f"确定要恢复备份 {selected_backup} 吗？\n警告: 这将覆盖当前的配置文件和本地数据库！如果服务正在运行，将被自动重启。"
        )
        if not ans:
            return

        # Stop server if running
        was_running = self.server_process is not None
        if was_running:
            self.stop_server()
            time.sleep(1) # Let processes release file locks

        data_dir = os.path.join(self.get_gui_dir(), "data")
        backup_folder = os.path.join(self.get_backups_dir(), selected_backup)

        import shutil
        try:
            os.makedirs(data_dir, exist_ok=True)
            
            # Copy back config
            config_src = os.path.join(backup_folder, "config.json")
            if os.path.exists(config_src):
                shutil.copy2(config_src, data_dir)
                
            # Copy back DB
            db_src = os.path.join(backup_folder, "data.db")
            if os.path.exists(db_src):
                shutil.copy2(db_src, data_dir)

            messagebox.showinfo("成功", "备份数据已成功恢复！")
            
            # Restart if was running
            if was_running:
                self.start_server()
        except Exception as e:
            messagebox.showerror("恢复失败", f"恢复备份时发生错误：\n{str(e)}")

    # ==============================================================================
    # TAB 5: Help & FAQ
    # ==============================================================================
    def build_help_tab(self):
        frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)

        # Help Card 1
        card1 = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        card1.grid(row=0, column=0, sticky="ew", pady=10, padx=5)
        
        lbl_q1 = ctk.CTkLabel(card1, text="❓ Q: 启动后服务闪退或报错提示端口占用该怎么办？", font=FONT_SUBTITLE, text_color=COLOR_ACCENT)
        lbl_q1.pack(anchor="w", padx=15, pady=(15, 5))
        
        lbl_a1 = ctk.CTkLabel(
            card1, text="   A: 这说明配置的端口（默认 5244）已经被其他程序占用。\n   请前往 [配置编辑] 选项卡，将 'HTTP 监听端口' 修改为其他数字（例如 5245），点击保存后重新启动服务。",
            font=FONT_BODY, text_color=COLOR_TEXT_MAIN, justify="left"
        )
        lbl_a1.pack(anchor="w", padx=15, pady=(0, 15))

        # Help Card 2
        card2 = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        card2.grid(row=1, column=0, sticky="ew", pady=10, padx=5)
        
        lbl_q2 = ctk.CTkLabel(card2, text="❓ Q: 为什么点击 '查询管理员密码' 显示被锁定或报错？", font=FONT_SUBTITLE, text_color=COLOR_ACCENT)
        lbl_q2.pack(anchor="w", padx=15, pady=(15, 5))
        
        lbl_a2 = ctk.CTkLabel(
            card2, text="   A: 当 OpenList 服务处于运行中状态时，SQLite 数据库会被服务进程独占加锁。\n   请先在 [控制面板] 中点击 '停止服务'，然后到 [管理员命令] 选项卡进行密码查询或重置，完成后重新开启服务即可。",
            font=FONT_BODY, text_color=COLOR_TEXT_MAIN, justify="left"
        )
        lbl_a2.pack(anchor="w", padx=15, pady=(0, 15))

        # Help Card 3
        card3 = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BG_CARD_HOVER)
        card3.grid(row=2, column=0, sticky="ew", pady=10, padx=5)
        
        lbl_q3 = ctk.CTkLabel(card3, text="❓ Q: 系统托盘有什么作用？如何彻底退出程序？", font=FONT_SUBTITLE, text_color=COLOR_ACCENT)
        lbl_q3.pack(anchor="w", padx=15, pady=(15, 5))
        
        lbl_a3 = ctk.CTkLabel(
            card3, text="   A: 如果您安装了 'pystray'，点击主窗口右上角的关闭 (X) 按钮不会关闭网盘服务，而是将窗口隐藏到桌面右下角的系统托盘，保证服务在后台持续运行。\n   如果您需要彻底退出程序并关闭服务，请右键托盘图标选择 '彻底退出'；或者在未启用托盘时直接关闭窗口。",
            font=FONT_BODY, text_color=COLOR_TEXT_MAIN, justify="left"
        )
        lbl_a3.pack(anchor="w", padx=15, pady=(0, 15))

        return frame

    # ==============================================================================
    # Status Monitoring & App Lifecycle
    # ==============================================================================
    def find_running_alist_process(self):
        """Attempts to find an already running alist.exe process on the system,
        matching the configured port."""
        port = self.get_configured_port()
        
        # 1. Try to find the PID of the process listening on the configured port
        try:
            cmd = 'netstat -ano'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, creationflags=0x08000000)
            for line in res.stdout.splitlines():
                if "LISTENING" in line and f":{port}" in line:
                    parts = [p for p in line.split() if p]
                    if len(parts) >= 5:
                        possible_pid = int(parts[-1])
                        if self.is_pid_alist(possible_pid):
                            return possible_pid
        except Exception:
            pass
            
        # 2. Fallback: Find any running alist.exe process
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and proc.info['name'].lower() == 'alist.exe':
                    return proc.info['pid']
        except ImportError:
            try:
                output = subprocess.check_output('tasklist /FI "IMAGENAME eq alist.exe" /NH', shell=True, text=True, creationflags=0x08000000)
                if "alist.exe" in output.lower():
                    for line in output.strip().splitlines():
                        if "alist.exe" in line.lower():
                            parts = [p for p in line.split() if p]
                            if len(parts) >= 2:
                                return int(parts[1])
            except Exception:
                pass
        except Exception:
            pass
        return None

    def is_pid_alist(self, pid):
        """Checks if a given PID corresponds to alist.exe."""
        try:
            import psutil
            proc = psutil.Process(pid)
            return proc.name().lower() == 'alist.exe'
        except ImportError:
            try:
                output = subprocess.check_output(f'tasklist /FI "PID eq {pid}" /NH', shell=True, text=True, creationflags=0x08000000)
                return "alist.exe" in output.lower()
            except Exception:
                return False
        except Exception:
            return False

    def check_server_status_loop(self):
        """Checks if the server process is still alive, updates metrics and status UI."""
        if self.server_process:
            status = self.server_process.poll()
            if status is not None:
                # Server exited!
                self.server_process = None
                self.is_reading_logs = False
                self.start_time = None
                
                # Check for Auto-Restart
                if self.enable_autorestart_var.get() and status != 0:
                    self.safe_append_log(f"\n[{time.strftime('%H:%M:%S')}] ⚠️ 检测到服务异常退出 (退出码: {status})，正在自动重启...\n")
                    self.start_server()
                else:
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.update_status_ui(running=False, error=True)
                    self.log_textbox.insert("end", f"\n[{time.strftime('%H:%M:%S')}] ⚠️ 进程已中止，退出状态码: {status}\n")
                    self.log_textbox.see("end")
            else:
                self.update_status_ui(running=True)
                self._update_metrics_ui()
        else:
            # No process spawned by us is running. Check if there's an external alist.exe running.
            pid = self.find_running_alist_process()
            if pid is not None:
                if not getattr(self, 'external_server_pid', None):
                    self.external_server_pid = pid
                    try:
                        import psutil
                        self.start_time = psutil.Process(pid).create_time()
                    except Exception:
                        self.start_time = time.time()
                    self.btn_start.configure(state="disabled")
                    self.btn_stop.configure(state="normal")
                    self.safe_append_log(f"[{time.strftime('%H:%M:%S')}] 🔗 检测到外部 OpenList 服务已在运行 (PID: {pid})，已自动接管状态监控。\n")
                
                self.update_status_ui(running=True)
                self._update_metrics_ui()
            else:
                if getattr(self, 'external_server_pid', None):
                    self.external_server_pid = None
                    self.start_time = None
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.safe_append_log(f"[{time.strftime('%H:%M:%S')}] 🔌 检测到外部 OpenList 服务已停止。\n")
                
                self.update_status_ui(running=False)
                self._reset_metrics_ui()
            
        # Check every 2 seconds
        self.after(2000, self.check_server_status_loop)

    def _update_metrics_ui(self):
        # Uptime
        if self.start_time:
            delta = int(time.time() - self.start_time)
            hours, remainder = divmod(delta, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.uptime_lbl.configure(text=f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}")
        
        # CPU & RAM
        cpu_usage, mem_usage = self._get_process_resources()
        self.resources_lbl.configure(text=f"CPU: {cpu_usage} | RAM: {mem_usage}")

    def _reset_metrics_ui(self):
        self.uptime_lbl.configure(text="运行时间: --:--:--")
        self.resources_lbl.configure(text="CPU: -- | RAM: --")

    def _get_uptime_str(self):
        if not self.start_time:
            return "00:00:00"
        delta = int(time.time() - self.start_time)
        hours, remainder = divmod(delta, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _get_process_resources(self):
        pid = None
        if self.server_process:
            pid = self.server_process.pid
        elif getattr(self, 'external_server_pid', None):
            pid = self.external_server_pid
            
        if not pid:
            return "--", "--"
        
        # 1. Try using psutil (pre-checked to be installed)
        try:
            import psutil
            process = psutil.Process(pid)
            cpu = process.cpu_percent(interval=None)
            mem_bytes = process.memory_info().rss
            mem_mb = mem_bytes / (1024 * 1024)
            
            # If cpu is 0.0 initially, we just display it
            return f"{cpu:.1f}%", f"{mem_mb:.1f} MB"
        except Exception:
            pass

        # 2. Fallback to Windows tasklist
        try:
            cmd = f'tasklist /FI "PID eq {pid}" /FO CSV'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, creationflags=0x08000000)
            lines = res.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split(',')
                if len(parts) >= 5:
                    mem_str = parts[4].strip('"').replace(' K', '').replace(',', '').strip()
                    mem_kb = float(mem_str)
                    mem_mb = mem_kb / 1024.0
                    return "未知", f"{mem_mb:.1f} MB"
        except Exception:
            pass
            
        return "未知", "未知"

    def update_status_ui(self, running=True, error=False):
        if running:
            self.status_dot.configure(text_color=COLOR_SUCCESS)
            self.status_text.configure(text="运行中 (Running)", text_color=COLOR_SUCCESS)
            self.btn_open_web.configure(state="normal")
        else:
            if error:
                self.status_dot.configure(text_color=COLOR_ERROR)
                self.status_text.configure(text="运行异常 (Error)", text_color=COLOR_ERROR)
            else:
                self.status_dot.configure(text_color=COLOR_TEXT_MUTED)
                self.status_text.configure(text="未运行 (Stopped)", text_color=COLOR_TEXT_MUTED)
            self.btn_open_web.configure(state="disabled")

    def on_close(self):
        """Safely handles window close (minimizes to tray if available and enabled)."""
        self.save_gui_config()
        if TRAY_AVAILABLE and self.enable_tray_var.get():
            self.withdraw()
            # Show a one-time info tip in the log if needed
            self.safe_append_log(f"[{time.strftime('%H:%M:%S')}] 窗口已隐藏至系统托盘，后台服务继续运行。通过右键托盘图标可彻底退出。\n")
        else:
            if self.server_process:
                ans = messagebox.askyesno("退出确认", "OpenList 服务正在运行中。\n退出本管理程序将会关闭网盘服务，是否确认退出？")
                if not ans:
                    return
                self.stop_server()
            self.destroy()
            sys.exit(0)


if __name__ == "__main__":
    _enable_dpi_awareness()
    app = OpenListGUI()
    app.mainloop()
