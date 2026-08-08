"""
AgentFloat — 安装向导 (tkinter 轻量版)
"""
import sys, io, os, subprocess, shutil, threading, time

if sys.platform == 'win32':
    try:
        if sys.stdout and hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except: pass

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── 路径 ─────────────────────────────────
if getattr(sys, 'frozen', False):
    SETUP_DIR = sys._MEIPASS
else:
    SETUP_DIR = os.path.dirname(os.path.abspath(__file__))

EXE_NAME  = "AgentFloat.exe"
STARTUP_DIR = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
DESKTOP_DIR = os.path.join(os.environ["USERPROFILE"], "Desktop")
START_MENU  = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentFloat"
APP_NAME = "AgentFloat"

# 从 VERSION 文件读取版本号
def _get_version():
    for p in [os.path.join(SETUP_DIR, "VERSION"), os.path.join(os.path.dirname(__file__), "..", "VERSION")]:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
        except: pass
    return "1.0.0"
APP_VERSION = _get_version()

# ── 工具函数 ─────────────────────────────
def _safe_ps(cmd, **paths):
    """通过环境变量安全传递路径参数到 PowerShell，防止注入"""
    env = os.environ.copy()
    for k, v in paths.items():
        env[k] = v
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], env=env,
                          capture_output=True, text=True)

def create_shortcut(target, lnk_path, icon):
    """通过环境变量安全传递路径"""
    ps = (
        '$ws=New-Object -ComObject WScript.Shell;'
        '$sc=$ws.CreateShortcut($env:CC_LNK);'
        '$sc.TargetPath=$env:CC_TARGET;'
        '$sc.WindowStyle=7;'
        '$sc.IconLocation=$env:CC_ICON;'
        '$sc.WorkingDirectory=$env:CC_WORKDIR;'
        '$sc.Description="AgentFloat 桌面浮窗";'
        '$sc.Save()'
    )
    _safe_ps(ps, CC_LNK=lnk_path, CC_TARGET=target,
             CC_ICON=icon, CC_WORKDIR=os.path.dirname(target))

def create_uninstall_bat(install_dir):
    """在安装目录创建独立的卸载脚本（正确转义BAT特殊字符）"""
    bat_path = os.path.join(install_dir, "uninstall.bat")
    safe_dir = install_dir.replace("%", "%%")
    safe_name = APP_NAME.replace("%", "%%")
    bat_content = f'''@echo off
chcp 65001 >nul
title 卸载 {safe_name}
echo.
echo ╔══════════════════════════════════════════╗
echo ║   卸载 {safe_name}                  ║
echo ╚══════════════════════════════════════════╝
echo.
echo 正在关闭运行中的程序...
taskkill /f /im {EXE_NAME} >nul 2>&1
timeout /t 1 /nobreak >nul

echo 正在删除快捷方式...
del /q "%USERPROFILE%\\Desktop\\{safe_name}.lnk" 2>nul
del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{safe_name}.lnk" 2>nul
del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\{safe_name}.lnk" 2>nul

echo 正在清除注册表...
powershell -NoProfile -Command "Remove-Item -Path 'HKCU:{UNINSTALL_KEY}' -Recurse -Force -ErrorAction SilentlyContinue"

echo 正在删除程序文件...
cd /d "%USERPROFILE%"
rmdir /s /q "{safe_dir}" 2>nul

echo.
echo 卸载完成！
echo.
timeout /t 2 /nobreak >nul
'''
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    return bat_path


def register_uninstall(install_dir, ico_path):
    """在控制面板注册卸载信息（安全 env-var 传参）"""
    bat_path = create_uninstall_bat(install_dir)
    ps = (
        '$k="HKCU:"+$env:CC_KEY;'
        'if(-not(Test-Path $k)){New-Item -Path $k -Force|Out-Null};'
        'Set-ItemProperty -Path $k -Name "DisplayName" -Value $env:CC_NAME;'
        'Set-ItemProperty -Path $k -Name "UninstallString" -Value $env:CC_BAT;'
        'Set-ItemProperty -Path $k -Name "DisplayIcon" -Value $env:CC_ICON;'
        'Set-ItemProperty -Path $k -Name "Publisher" -Value "AgentFloat";'
        f'Set-ItemProperty -Path $k -Name "DisplayVersion" -Value "{APP_VERSION}";'
        'Set-ItemProperty -Path $k -Name "NoModify" -Value 1;'
        'Set-ItemProperty -Path $k -Name "NoRepair" -Value 1'
    )
    _safe_ps(ps, CC_BAT=f'"{bat_path}"', CC_ICON=ico_path,
             CC_KEY=UNINSTALL_KEY, CC_NAME=APP_NAME)

# ── GUI ───────────────────────────────────
class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AgentFloat 安装向导")
        self.root.geometry("460x400")
        self.root.resizable(False, False)
        self.root.configure(bg="#F2F2F7")
        try:
            self.root.iconbitmap(os.path.join(SETUP_DIR, "agent_float_icon.ico"))
        except: pass

        # 居中
        self.root.update_idletasks()
        w, h = 460, 400
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self.install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AgentFloat")
        self._build_ui()

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg="#007AFF", height=90)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="AgentFloat", font=("Microsoft YaHei", 18, "bold"),
                 fg="white", bg="#007AFF").pack(anchor="w", padx=24, pady=(18, 0))
        tk.Label(header, text="AI Agent 桌面悬浮助手",
                 font=("Microsoft YaHei", 10), fg="white", bg="#007AFF").pack(anchor="w", padx=24)

        # Content
        content = tk.Frame(self.root, bg="#F2F2F7")
        content.pack(fill="both", expand=True, padx=24, pady=16)

        tk.Label(content, text="选择安装选项", font=("Microsoft YaHei", 10),
                 fg="#8E8E93", bg="#F2F2F7", anchor="w").pack(fill="x")

        # 安装路径
        pf = tk.Frame(content, bg="#F2F2F7")
        pf.pack(fill="x", pady=(12, 4))
        tk.Label(pf, text="安装位置:", font=("Microsoft YaHei", 11),
                 bg="#F2F2F7").pack(side="left")
        self.path_var = tk.StringVar(value=self.install_dir)
        tk.Label(pf, textvariable=self.path_var, font=("Microsoft YaHei", 9),
                 fg="#007AFF", bg="#F2F2F7").pack(side="left", padx=6)
        tk.Button(pf, text="更改...", font=("Microsoft YaHei", 9), bd=0,
                  bg="#F2F2F7", fg="#007AFF", activebackground="#E5E5EA",
                  command=self._browse).pack(side="right")

        # 选项
        self.cb_desktop = tk.BooleanVar(value=True)
        tk.Checkbutton(content, text="创建桌面快捷方式", variable=self.cb_desktop,
                       font=("Microsoft YaHei", 12), bg="#F2F2F7", fg="#1C1C1E",
                       activebackground="#F2F2F7", selectcolor="#F2F2F7",
                       pady=6).pack(anchor="w", pady=(16, 0))

        self.cb_startup = tk.BooleanVar(value=False)
        tk.Checkbutton(content, text="开机自动启动", variable=self.cb_startup,
                       font=("Microsoft YaHei", 12), bg="#F2F2F7", fg="#1C1C1E",
                       activebackground="#F2F2F7", selectcolor="#F2F2F7",
                       pady=6).pack(anchor="w")

        # 进度条
        self.progress = ttk.Progressbar(content, mode="determinate", length=400)
        self.progress.pack(fill="x", pady=(20, 4))

        self.status_var = tk.StringVar(value="")
        tk.Label(content, textvariable=self.status_var, font=("Microsoft YaHei", 9),
                 fg="#8E8E93", bg="#F2F2F7").pack(anchor="w")

        # 按钮
        bf = tk.Frame(self.root, bg="#F2F2F7")
        bf.pack(fill="x", padx=24, pady=(0, 20))

        tk.Button(bf, text="取消", font=("Microsoft YaHei", 11),
                  bg="#F2F2F7", fg="#007AFF", bd=1, relief="solid",
                  activebackground="#E5E5EA", padx=20, pady=6,
                  command=self.root.destroy).pack(side="left")

        self.install_btn = tk.Button(bf, text="立即安装", font=("Microsoft YaHei", 12, "bold"),
                                     bg="#007AFF", fg="white", bd=0,
                                     activebackground="#0066D6", padx=24, pady=8,
                                     command=self._do_install)
        self.install_btn.pack(side="right")

    def _browse(self):
        d = filedialog.askdirectory(title="选择安装位置", initialdir=self.install_dir)
        if d:
            self.install_dir = d
            self.path_var.set(d)

    def _do_install(self):
        self.install_btn.config(state="disabled", text="安装中...")
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        try:
            self._do_install_work()
        except Exception as e:
            self.root.after(0, self._install_failed, str(e))

    def _do_install_work(self):
        install_dir = self.install_dir
        exe_src = os.path.join(SETUP_DIR, EXE_NAME)
        ico_src = os.path.join(SETUP_DIR, "agent_float_icon.ico")
        png_src = os.path.join(SETUP_DIR, "agent_float_icon.png")

        self.root.after(0, self._update_progress, 10, "创建目录...")
        os.makedirs(install_dir, exist_ok=True)
        os.makedirs(os.path.join(install_dir, "资源素材"), exist_ok=True)

        self.root.after(0, self._update_progress, 30, "复制文件...")
        for src, dst in [(exe_src, EXE_NAME), (ico_src, "资源素材/agent_float_icon.ico"),
                          (png_src, "资源素材/agent_float_icon.png")]:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(install_dir, dst))

        exe_dst = os.path.join(install_dir, EXE_NAME)
        ico_dst = os.path.join(install_dir, "资源素材", "agent_float_icon.ico")
        self.root.after(0, self._update_progress, 55, "创建快捷方式...")

        create_shortcut(exe_dst, os.path.join(START_MENU, "AgentFloat.lnk"), ico_dst)
        if self.cb_desktop.get():
            create_shortcut(exe_dst, os.path.join(DESKTOP_DIR, "AgentFloat.lnk"), ico_dst)

        self.root.after(0, self._update_progress, 75, "配置启动选项...")
        startup_lnk = os.path.join(STARTUP_DIR, "AgentFloat.lnk")
        if self.cb_startup.get():
            create_shortcut(exe_dst, startup_lnk, ico_dst)
        elif os.path.exists(startup_lnk):
            try:
                os.remove(startup_lnk)
            except OSError:
                pass

        self.root.after(0, self._update_progress, 90, "注册信息...")
        register_uninstall(install_dir, ico_dst)

        self.root.after(0, self._update_progress, 100, "安装完成!")

        # 启动程序
        subprocess.Popen([exe_dst], cwd=install_dir, creationflags=subprocess.CREATE_NO_WINDOW)

        # 关闭窗口
        self.root.after(800, self.root.destroy)

    def _install_failed(self, error_msg):
        messagebox.showerror("安装失败", f"安装过程中发生错误：\n\n{error_msg}\n\n请检查磁盘空间和权限后重试。")
        self.install_btn.config(state="normal", text="立即安装")

    def _update_progress(self, val, msg):
        self.progress["value"] = val
        self.status_var.set(msg)

    def run(self):
        self.root.mainloop()


def main():
    if not os.path.exists(os.path.join(SETUP_DIR, EXE_NAME)):
        messagebox.showerror("错误", f"未找到 {EXE_NAME}\n请确保安装程序与程序文件在同一目录")
        return 1
    SetupWizard().run()
    return 0

if __name__ == "__main__":
    sys.exit(main())
