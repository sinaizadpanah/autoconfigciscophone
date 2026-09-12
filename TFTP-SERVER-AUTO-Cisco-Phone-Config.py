# -*- coding: utf-8 -*-
r"""
برنامه یکپارچه کانفیگ و TFTP سرور تلفن‌های سیسکو (Cisco TFTP Configurator + Server)
-------------------------------------------------------------------------------------
دو قابلیت توی یک برنامه:

۱) ساخت خودکار فایل کانفیگ با بارکدخوان:
   - یک پوشه ریشه (مثلا D:\tftp) داریم که داخلش زیرپوشه‌هایی به اسم مدل تلفن
     وجود داره (8841 / 7975 / 78xx و ...).
   - داخل هر زیرپوشه یک فایل قالب به اسم SEPMAC.cnf.xml از قبل آماده شده.
   - فنی، مدل رو انتخاب می‌کنه، بارکد MAC رو اسکن می‌کنه، برنامه بلافاصله یک کپی
     از قالب می‌سازه با اسم SEP<MAC>.cnf.xml و یک بوق موفقیت/خطا پخش می‌کنه.

۲) سرور TFTP داخلی (RFC 1350، فقط خواندن):
   - روی پورت استاندارد 69 گوش میده.
   - وقتی تلفن سیسکو یک فایل (کانفیگ یا فرمور) رو درخواست کنه، برنامه توی کل
     زیرپوشه‌های پوشه ریشه دنبالش می‌گرده و ارسال می‌کنه. دیگه نیازی به
     موبا ایکس‌ترم یا هیچ نرم‌افزار TFTP جداگانه‌ای نیست.
   - نکته مهم: پورت 69 یک پورت سیستمی/محافظت‌شده است و روی ویندوز نیاز به
     اجرا با دسترسی Administrator داره.

اجرا: python cisco_tftp_configurator.py   (روی ویندوز با Run as Administrator)

تبدیل به یک فایل exe مستقل که خودش هر بار دسترسی ادمین (UAC) درخواست می‌کنه:
    pip install pyinstaller
    pyinstaller --onefile --noconsole --uac-admin --name CiscoTftpConfigurator cisco_tftp_configurator.py
فایل خروجی: dist\CiscoTftpConfigurator.exe -- همین یک فایل رو روی هر سیستم
ویندوزی کپی کنید، نیازی به نصب پایتون نیست.
"""

import os
import re
import csv
import socket
import struct
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

TEMPLATE_NAME = "SEPMAC.cnf.xml"
MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")

TFTP_PORT = 69
TFTP_BLOCK_SIZE = 512
OPCODE_RRQ = 1
OPCODE_WRQ = 2
OPCODE_DATA = 3
OPCODE_ACK = 4
OPCODE_ERROR = 5

# ---------------------------------------------------------------- COLORS
COLOR_BG = "#1f2530"
COLOR_PANEL = "#2a3140"
COLOR_ACCENT = "#3b82f6"
COLOR_TEXT = "#e6e9ef"
COLOR_MUTED = "#9aa4b2"
COLOR_OK = "#22c55e"
COLOR_ERR = "#ef4444"
COLOR_ENTRY_BG = "#0f1420"


# ============================================================ TFTP SERVER
class TftpServer:
    """سرور TFTP ساده و فقط-خواندنی. فایل‌ها رو با گشتن توی کل زیرپوشه‌های
    root_dir_getter() پیدا می‌کنه (بدون توجه به مسیر پوشه در درخواست، چون
    تلفن‌های سیسکو معمولا فقط اسم فایل رو می‌فرستن، نه مسیر کامل)."""

    def __init__(self, root_dir_getter, log_callback, status_callback):
        self.root_dir_getter = root_dir_getter
        self.log_callback = log_callback          # (kind, detail1, detail2, status, ok)
        self.status_callback = status_callback      # (running: bool, message: str)
        self.sock = None
        self.thread = None
        self.running = False

    def start(self):
        if self.running:
            return True, "سرور از قبل روشنه"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", TFTP_PORT))
        except PermissionError:
            msg = ("دسترسی رد شد: پورت 69 نیاز به دسترسی Administrator داره.\n"
                   "برنامه رو با «Run as Administrator» اجرا کنید.")
            self.status_callback(False, msg)
            return False, msg
        except OSError as e:
            msg = (f"پورت 69 در دسترس نیست ({e}).\n"
                   "احتمالا یک سرویس TFTP دیگه (مثل موبا ایکس‌ترم یا Tftpd32) "
                   "همین الان روی این پورت روشنه — اول اونو ببندید.")
            self.status_callback(False, msg)
            return False, msg

        self.sock = s
        self.running = True
        self.thread = threading.Thread(target=self._serve_loop, daemon=True)
        self.thread.start()
        self.status_callback(True, "سرور TFTP روشن است (پورت 69)")
        return True, "روشن شد"

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.status_callback(False, "سرور TFTP خاموش است")

    def _serve_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                break
            except Exception:
                continue
            threading.Thread(target=self._handle_request, args=(data, addr), daemon=True).start()

    def _find_file(self, filename):
        root = self.root_dir_getter()
        base = filename.replace("\\", "/").split("/")[-1].lower()
        if not os.path.isdir(root):
            return None
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.lower() == base:
                    return os.path.join(dirpath, f)
        return None

    def _handle_request(self, data, addr):
        try:
            opcode = struct.unpack("!H", data[0:2])[0]
        except Exception:
            return

        if opcode != OPCODE_RRQ:
            self._send_error(self.sock, addr, 4, "Only read requests are supported")
            return

        try:
            parts = data[2:].split(b"\x00")
            filename = parts[0].decode("utf-8", errors="replace")
        except Exception:
            self._send_error(self.sock, addr, 0, "Malformed request")
            return

        filepath = self._find_file(filename)
        client_ip = addr[0]

        if filepath is None:
            self._send_error(self.sock, addr, 1, "File not found")
            self.log_callback("TFTP", client_ip, filename, "فایل پیدا نشد", False)
            return

        try:
            with open(filepath, "rb") as f:
                content = f.read()
        except Exception as e:
            self._send_error(self.sock, addr, 0, str(e))
            self.log_callback("TFTP", client_ip, filename, f"خطا در خواندن فایل: {e}", False)
            return

        tsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tsock.settimeout(3.0)
        try:
            offset = 0
            block_num = 1
            while True:
                chunk = content[offset:offset + TFTP_BLOCK_SIZE]
                packet = struct.pack("!HH", OPCODE_DATA, block_num & 0xFFFF) + chunk
                acked = False
                for _attempt in range(5):
                    tsock.sendto(packet, addr)
                    try:
                        ack, _ = tsock.recvfrom(65536)
                    except socket.timeout:
                        continue
                    if len(ack) >= 4:
                        ack_op, ack_block = struct.unpack("!HH", ack[0:4])
                        if ack_op == OPCODE_ACK and ack_block == (block_num & 0xFFFF):
                            acked = True
                            break
                if not acked:
                    self.log_callback("TFTP", client_ip, filename,
                                       "ارتباط قطع شد (Timeout)", False)
                    return
                offset += TFTP_BLOCK_SIZE
                block_num += 1
                if len(chunk) < TFTP_BLOCK_SIZE:
                    break
            self.log_callback("TFTP", client_ip, filename,
                               f"ارسال شد ({len(content):,} بایت)", True)
        finally:
            tsock.close()

    @staticmethod
    def _send_error(sock, addr, code, msg):
        try:
            packet = struct.pack("!HH", OPCODE_ERROR, code) + msg.encode("ascii", "replace") + b"\x00"
            sock.sendto(packet, addr)
        except Exception:
            pass


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


# ============================================================ MAIN APP
class TftpConfiguratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("کانفیگ و سرور TFTP تلفن سیسکو")
        self.root.geometry("960x680")
        self.root.minsize(840, 560)
        self.root.configure(bg=COLOR_BG)

        self.root_path = tk.StringVar(value=r"D:\tftp")
        self.selected_model = tk.StringVar()
        self.barcode_value = tk.StringVar()
        self.status_text = tk.StringVar(value="آماده. پوشه ریشه و مدل رو انتخاب کن.")
        self.today_count = 0

        self.tftp_status_text = tk.StringVar(value="سرور TFTP: خاموش")
        self.local_ip_text = tk.StringVar(value="در حال تشخیص آی‌پی...")

        self.tftp_server = TftpServer(
            root_dir_getter=lambda: self.root_path.get().strip(),
            log_callback=self._server_log_threadsafe,
            status_callback=self._server_status_threadsafe,
        )

        self._setup_style()
        self._build_ui()
        self._refresh_models()
        self._refresh_ip()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # تلاش خودکار برای روشن کردن سرور TFTP هنگام اجرا (بی‌سروصدا، بدون پاپ‌آپ مزاحم)
        self.root.after(300, self._auto_start_server)

    # ---------------------------------------------------------- STYLE
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT,
                         font=("Segoe UI", 11))
        style.configure("Title.TLabel", background=COLOR_BG, foreground=COLOR_TEXT,
                         font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_MUTED,
                         font=("Segoe UI", 10))
        style.configure("Status.TLabel", background=COLOR_BG, foreground=COLOR_TEXT,
                         font=("Segoe UI", 13, "bold"))
        style.configure("Panel.TLabelframe", background=COLOR_PANEL, foreground=COLOR_TEXT,
                         font=("Segoe UI", 11, "bold"), borderwidth=0)
        style.configure("Panel.TLabelframe.Label", background=COLOR_BG,
                         foreground=COLOR_MUTED, font=("Segoe UI", 10, "bold"))

        style.configure("TEntry", fieldbackground=COLOR_ENTRY_BG, foreground=COLOR_TEXT,
                         insertcolor=COLOR_TEXT, borderwidth=1, padding=6)
        style.configure("Big.TEntry", fieldbackground=COLOR_ENTRY_BG, foreground=COLOR_TEXT,
                         insertcolor=COLOR_TEXT, borderwidth=2, padding=14)

        style.configure("TCombobox", fieldbackground=COLOR_ENTRY_BG, background=COLOR_ENTRY_BG,
                         foreground=COLOR_TEXT, arrowcolor=COLOR_TEXT, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", COLOR_ENTRY_BG)],
                   foreground=[("readonly", COLOR_TEXT)])

        style.configure("TButton", background=COLOR_ACCENT, foreground="white",
                         font=("Segoe UI", 10, "bold"), padding=8, borderwidth=0)
        style.map("TButton", background=[("active", "#2563eb")])

        style.configure("Server.TButton", background=COLOR_OK, foreground="white",
                         font=("Segoe UI", 10, "bold"), padding=8, borderwidth=0)
        style.map("Server.TButton", background=[("active", "#16a34a")])

        style.configure("Treeview", background=COLOR_ENTRY_BG, fieldbackground=COLOR_ENTRY_BG,
                         foreground=COLOR_TEXT, rowheight=28, font=("Consolas", 10),
                         borderwidth=0)
        style.configure("Treeview.Heading", background=COLOR_PANEL, foreground=COLOR_TEXT,
                         font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Treeview", background=[("selected", COLOR_ACCENT)])

    # ---------------------------------------------------------- UI BUILD
    def _build_ui(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True, padx=16, pady=14)

        ttk.Label(outer, text="کانفیگ و سرور TFTP تلفن سیسکو", style="Title.TLabel").pack(
            anchor="e", pady=(0, 2)
        )
        ttk.Label(
            outer, text="پوشه رو انتخاب کن، مدل رو بزن، بارکد رو بزن — سرور TFTP هم همینجا روشنه.",
            style="Muted.TLabel"
        ).pack(anchor="e", pady=(0, 12))

        # ------ TFTP server panel ------
        tftp_frame = ttk.Labelframe(outer, text="سرور TFTP", style="Panel.TLabelframe")
        tftp_frame.pack(fill="x", pady=(0, 10))
        tftp_inner = ttk.Frame(tftp_frame, style="TFrame")
        tftp_inner.pack(fill="x", padx=12, pady=10)

        self.tftp_toggle_btn = ttk.Button(
            tftp_inner, text="روشن کردن سرور", style="Server.TButton",
            command=self._toggle_server
        )
        self.tftp_toggle_btn.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="ns")

        ttk.Label(tftp_inner, textvariable=self.tftp_status_text,
                  style="Status.TLabel").grid(row=0, column=1, sticky="e")
        self.tftp_status_widget = tftp_inner.grid_slaves(row=0, column=1)[0]

        ip_row = ttk.Frame(tftp_inner, style="TFrame")
        ip_row.grid(row=1, column=1, sticky="e", pady=(4, 0))
        ttk.Button(ip_row, text="بروزرسانی آی‌پی", command=self._refresh_ip).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(ip_row, textvariable=self.local_ip_text, style="Muted.TLabel").pack(side="left")
        ttk.Label(ip_row, text="این آی‌پی رو باید توی DHCP option 66 میکروتیک ست کنید:  ",
                  style="Muted.TLabel").pack(side="left")

        tftp_inner.columnconfigure(1, weight=1)

        # ------ Folder / model panel ------
        top = ttk.Frame(outer, style="TFrame")
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="پوشه ریشه TFTP:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        entry_path = ttk.Entry(top, textvariable=self.root_path, font=("Consolas", 11))
        entry_path.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(top, text="انتخاب پوشه...", command=self._browse_root).grid(
            row=0, column=0, padx=6, pady=6
        )
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="مدل تلفن:").grid(row=1, column=2, sticky="e", padx=6, pady=6)
        self.model_combo = ttk.Combobox(
            top, textvariable=self.selected_model, state="readonly", font=("Segoe UI", 12)
        )
        self.model_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)
        ttk.Button(top, text="بروزرسانی لیست مدل‌ها", command=self._refresh_models).grid(
            row=1, column=0, padx=6, pady=6
        )

        # ------ Barcode input ------
        scan_frame = ttk.Labelframe(outer, text="اسکن بارکد MAC", style="Panel.TLabelframe")
        scan_frame.pack(fill="x", pady=(4, 10))

        self.barcode_entry = ttk.Entry(
            scan_frame, textvariable=self.barcode_value,
            font=("Consolas", 24, "bold"), justify="center", style="Big.TEntry",
        )
        self.barcode_entry.pack(fill="x", padx=16, pady=16)
        self.barcode_entry.bind("<Return>", self._on_scan)
        self.barcode_entry.focus_set()

        status_lbl = ttk.Label(outer, textvariable=self.status_text, style="Status.TLabel")
        status_lbl.pack(fill="x", pady=(0, 2))
        self.status_label_widget = status_lbl

        self.count_lbl = ttk.Label(outer, text="تعداد امروز: 0", style="Muted.TLabel")
        self.count_lbl.pack(anchor="e", pady=(0, 10))

        # ------ Log table ------
        log_frame = ttk.Labelframe(outer, text="گزارش (ساخت فایل + درخواست‌های TFTP)",
                                    style="Panel.TLabelframe")
        log_frame.pack(fill="both", expand=True)

        tree_holder = ttk.Frame(log_frame, style="TFrame")
        tree_holder.pack(fill="both", expand=True, padx=8, pady=8)

        cols = ("time", "kind", "detail1", "detail2", "status")
        self.tree = ttk.Treeview(tree_holder, columns=cols, show="headings", height=14)
        headers = {
            "time": "زمان", "kind": "نوع",
            "detail1": "MAC / آی‌پی کلاینت", "detail2": "مدل / نام فایل",
            "status": "نتیجه",
        }
        widths = {"time": 85, "kind": 90, "detail1": 150, "detail2": 260, "status": 220}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.tag_configure("ok", foreground=COLOR_OK)
        self.tree.tag_configure("err", foreground=COLOR_ERR)
        self.tree.pack(fill="both", expand=True, side="left")

        scrollbar = ttk.Scrollbar(tree_holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        tree_holder.bind("<Button-1>", self._refocus_soon)
        log_frame.bind("<Button-1>", self._refocus_soon)
        outer.bind("<Button-1>", self._refocus_soon)

    # ---------------------------------------------------------- TFTP SERVER GLUE
    def _auto_start_server(self):
        ok, msg = self.tftp_server.start()
        if not ok:
            # فقط توی status نشون بده، پاپ‌آپ مزاحم نزن هنگام استارت خودکار
            self.status_text.set("سرور TFTP روشن نشد — پایین صفحه رو ببین")
            self.status_label_widget.configure(foreground=COLOR_ERR)

    def _toggle_server(self):
        if self.tftp_server.running:
            self.tftp_server.stop()
        else:
            ok, msg = self.tftp_server.start()
            if not ok:
                messagebox.showerror("سرور TFTP", msg)

    def _server_status_threadsafe(self, running, message):
        def apply():
            if running:
                self.tftp_status_text.set(f"● {message}")
                self.tftp_status_widget.configure(foreground=COLOR_OK)
                self.tftp_toggle_btn.configure(text="خاموش کردن سرور")
            else:
                self.tftp_status_text.set(f"○ {message}")
                self.tftp_status_widget.configure(foreground=COLOR_ERR)
                self.tftp_toggle_btn.configure(text="روشن کردن سرور")
        self.root.after(0, apply)

    def _server_log_threadsafe(self, kind, detail1, detail2, status, ok):
        self.root.after(0, lambda: self._log_row(kind, detail1, detail2, status, ok))

    def _refresh_ip(self):
        ip = get_local_ip()
        self.local_ip_text.set(f"آی‌پی این سیستم: {ip}")

    def _on_close(self):
        self.tftp_server.stop()
        self.root.destroy()

    # ---------------------------------------------------------- FOCUS HELPERS
    def _on_model_selected(self, _event=None):
        self.status_text.set(f"مدل انتخاب شد: {self.selected_model.get()} — آماده اسکن")
        self.status_label_widget.configure(foreground=COLOR_TEXT)
        self._refocus_soon()

    def _refocus_soon(self, _event=None):
        self.root.after(120, lambda: self.barcode_entry.focus_set())

    # ---------------------------------------------------------- SOUND
    def _beep_ok(self):
        if HAS_WINSOUND:
            try:
                winsound.Beep(1500, 120)
                return
            except Exception:
                pass
        self.root.bell()

    def _beep_err(self):
        if HAS_WINSOUND:
            try:
                winsound.Beep(400, 180)
                winsound.Beep(400, 180)
                return
            except Exception:
                pass
        self.root.bell()
        self.root.bell()

    # ---------------------------------------------------------- FILE HELPERS
    def _browse_root(self):
        path = filedialog.askdirectory(title="انتخاب پوشه ریشه TFTP")
        if path:
            self.root_path.set(path)
            self._refresh_models()

    def _refresh_models(self):
        root = self.root_path.get().strip()
        models = []
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                full = os.path.join(root, name)
                if os.path.isdir(full):
                    models.append(name)
        self.model_combo["values"] = models
        if models and self.selected_model.get() not in models:
            self.selected_model.set(models[0])
        if not models:
            self.selected_model.set("")
            self.status_text.set("پوشه ریشه معتبر نیست یا زیرپوشه‌ای پیدا نشد.")
            self.status_label_widget.configure(foreground=COLOR_ERR)

    def _log_row(self, kind, detail1, detail2, status, ok):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        tag = "ok" if ok else "err"
        self.tree.insert("", 0, values=(now, kind, detail1, detail2, status), tags=(tag,))
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, datetime.date.today().strftime("%Y-%m-%d") + ".csv")
            is_new = not os.path.exists(log_file)
            with open(log_file, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if is_new:
                    w.writerow(["time", "kind", "detail1", "detail2", "status"])
                w.writerow([now, kind, detail1, detail2, status])
        except Exception:
            pass

    # ---------------------------------------------------------- CORE SCAN LOGIC
    def _on_scan(self, _event=None):
        raw = self.barcode_value.get().strip()
        self.barcode_value.set("")

        if not raw:
            return

        model = self.selected_model.get().strip()
        root = self.root_path.get().strip()

        if not model:
            self._fail("مدل تلفن انتخاب نشده", raw, "-")
            return

        model_dir = os.path.join(root, model)
        if not os.path.isdir(model_dir):
            self._fail(f"پوشه مدل پیدا نشد: {model_dir}", raw, model)
            return

        mac = self._normalize_mac(raw)
        if mac is None:
            self._fail(f"فرمت مک‌آدرس نامعتبره: {raw}", raw, model)
            return

        template_path = self._find_template(model_dir)
        if template_path is None:
            self._fail(f"فایل قالب {TEMPLATE_NAME} توی پوشه {model} پیدا نشد", mac, model)
            return

        new_filename = f"SEP{mac}.cnf.xml"
        new_path = os.path.join(model_dir, new_filename)

        if os.path.exists(new_path):
            overwrite = messagebox.askyesno(
                "فایل تکراری",
                f"فایل {new_filename} از قبل توی پوشه {model} وجود داره.\nرونویسی بشه؟",
            )
            if not overwrite:
                self._fail("رد شد توسط کاربر (تکراری)", mac, model)
                return

        try:
            self._write_config(template_path, new_path, mac)
        except Exception as e:
            self._fail(f"خطا در ساخت فایل: {e}", mac, model)
            return

        self.today_count += 1
        self.count_lbl.config(text=f"تعداد امروز: {self.today_count}")
        self.status_text.set(f"✔ ساخته شد: {new_filename}")
        self.status_label_widget.configure(foreground=COLOR_OK)
        self._log_row("ساخت فایل", mac, model, "موفق", True)
        self._beep_ok()
        self._refocus_soon()

    def _fail(self, status_msg, mac, model):
        self.status_text.set("✘ " + status_msg)
        self.status_label_widget.configure(foreground=COLOR_ERR)
        self._log_row("ساخت فایل", mac, model, status_msg, False)
        self._beep_err()
        self._refocus_soon()

    @staticmethod
    def _normalize_mac(raw):
        cleaned = re.sub(r"[:\-\.\s]", "", raw)
        if MAC_RE.match(cleaned):
            return cleaned.upper()
        return None

    @staticmethod
    def _find_template(model_dir):
        for name in os.listdir(model_dir):
            if name.lower() == TEMPLATE_NAME.lower():
                return os.path.join(model_dir, name)
        return None

    @staticmethod
    def _write_config(template_path, new_path, mac):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "MAC" in content:
                content = content.replace("MAC", mac)
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(content)
        except UnicodeDecodeError:
            with open(template_path, "rb") as f:
                data = f.read()
            with open(new_path, "wb") as f:
                f.write(data)


def main():
    root = tk.Tk()
    app = TftpConfiguratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
