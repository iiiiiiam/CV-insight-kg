"""Small installed desktop control window; the web application is unchanged."""
import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from console_ui import single_instance
from control import request_stop
from storage import state_directory

PAGE = 'http://127.0.0.1:8001/research/papers?tab=overview'


def supervisor_command(home, state):
    return [str(home / 'ResearchInsight.exe'), '--data-dir', str(state)]


class Controller:
    def __init__(self, root, home, state):
        self.root, self.home, self.state = root, home, state
        self.process = None
        self.stopping = self.stop_sent = self.ready = False
        self.messages = queue.Queue()
        self.error = ''
        root.title('Research Insight')
        root.geometry('460x210')
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Research Insight', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        self.status = tk.StringVar(value='正在启动，请稍候……')
        ttk.Label(frame, textvariable=self.status, wraplength=410).pack(anchor='w', pady=(14, 8))
        self.note = tk.StringVar(value='就绪后会自动打开浏览器。使用期间请保留此窗口。')
        ttk.Label(frame, textvariable=self.note, wraplength=410).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(16, 0))
        self.open_button = ttk.Button(buttons, text='打开页面', state='disabled', command=lambda: webbrowser.open(PAGE))
        self.open_button.pack(side='left')
        ttk.Button(buttons, text='查看日志', command=self.open_logs).pack(side='left', padx=8)
        self.exit_button = ttk.Button(buttons, text='退出软件', command=self.close)
        self.exit_button.pack(side='right')
        root.after(100, self.start)

    def open_logs(self):
        directory = self.state / 'logs'
        if directory.is_dir():
            os.startfile(directory)
        else:
            messagebox.showinfo('日志', '尚未生成日志。', parent=self.root)

    def start(self):
        try:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            self.process = subprocess.Popen(
                supervisor_command(self.home, self.state), cwd=self.home,
                creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace')
        except OSError as exc:
            self.status.set('启动失败，请检查程序文件及权限。')
            self.note.set(f'系统错误代码：{exc.winerror}')
            self.exit_button.configure(text='关闭')
            return
        threading.Thread(target=self.read_output, daemon=True).start()
        self.root.after(200, self.poll)

    def read_output(self):
        try:
            for line in self.process.stdout:
                self.messages.put(line.strip())
        finally:
            self.process.stdout.close()

    def poll(self):
        while True:
            try:
                line = self.messages.get_nowait()
            except queue.Empty:
                break
            if line.startswith('Ready:'):
                self.ready = True
                if not self.stopping:
                    self.status.set('软件正在运行')
                    self.open_button.configure(state='normal')
            elif line.startswith('ERROR:'):
                self.error = line
            elif line.startswith('Stopping ') or line == 'Stop requested.':
                self.stopping = True
                self.show_stopping()
        code = self.process.poll()
        if code is not None:
            if self.stopping and code == 0:
                self.root.destroy()
                return
            self.status.set('软件已停止' if code == 0 else '启动或运行失败')
            self.note.set(self.error or '请查看日志了解详情；可以关闭窗口后重新启动。')
            self.open_button.configure(state='disabled')
            self.exit_button.configure(text='关闭', state='normal')
            return
        if self.stopping and not self.stop_sent:
            # The per-process signal prevents closing a failed duplicate window
            # from stopping a different instance. Retry while initialization runs.
            try:
                self.stop_sent = request_stop(self.state, self.process.pid)
            except OSError:
                self.note.set('正在等待退出，请保留窗口；若长时间无响应可查看日志。')
        self.root.after(300, self.poll)

    def show_stopping(self):
        self.status.set('正在退出，请稍候……')
        self.note.set('正在保存并停止后台服务，完成后此窗口会自动关闭。')
        self.open_button.configure(state='disabled')
        self.exit_button.configure(state='disabled')

    def close(self):
        if self.process is None or self.process.poll() is not None:
            self.root.destroy()
            return
        self.stopping = True
        self.show_stopping()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    root = tk.Tk()
    home = Path(sys.executable).resolve().parent.parent
    try:
        state = state_directory(home, args.data_dir)
        with single_instance(Path(tempfile.gettempdir()) / 'ResearchInsight-window.lock'):
            Controller(root, home, state)
            root.mainloop()
    except (OSError, RuntimeError) as exc:
        messagebox.showerror('Research Insight', f'无法启动：{exc}', parent=root)
        root.destroy()


if __name__ == '__main__':
    main()
