"""Chinese desktop UI. Run with python app.py or Launch.cmd."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from bridge import Library, human


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SkillBridge · Codex × WorkBuddy 共享技能库")
        self.root.geometry("1120x740")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.config = Path(__file__).with_name("settings.json")
        settings = json.loads(self.config.read_text(encoding="utf-8")) if self.config.exists() else {}
        self.lib = Library(store=Path(settings["store"]) if settings.get("store") else None,
                           codex=Path(settings["codex"]) if settings.get("codex") else None,
                           workbuddy=Path(settings["workbuddy"]) if settings.get("workbuddy") else None)
        self.events = queue.Queue()
        self.busy = False
        self.buttons = []
        self.rows = []
        self.records = []
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6fa")
        style.configure("TLabel", background="#f4f6fa", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        style.configure("Treeview", font=("Microsoft YaHei UI", 10), rowheight=36)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=8)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="SkillBridge", font=("Segoe UI", 24, "bold"), foreground="#142844").pack(anchor="w")
        ttk.Label(outer, text="一份技能文件 · 两端原生发现 · 无后台常驻", foreground="#53647d").pack(anchor="w", pady=(2, 14))
        self.paths = ttk.Label(outer, wraplength=1000, foreground="#53647d")
        self.paths.pack(anchor="w", pady=(0, 12))
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 14))
        self.button(bar, "导入文件夹", self.import_skill)
        self.button(bar, "共享到两端", self.mount)
        self.button(bar, "合并副本", self.consolidate)
        self.button(bar, "取消共享", self.detach)
        self.button(bar, "刷新 / 检查", self.refresh)
        self.button(bar, "目录设置", self.settings)
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        skills = ttk.Frame(tabs, padding=10)
        backups = ttk.Frame(tabs, padding=10)
        tabs.add(skills, text="  技能库  ")
        tabs.add(backups, text="  合并备份  ")
        searchbar = ttk.Frame(skills)
        searchbar.pack(fill="x", pady=(0, 10))
        ttk.Label(searchbar, text="搜索技能  ").pack(side="left")
        self.query = tk.StringVar()
        ttk.Entry(searchbar, textvariable=self.query).pack(side="left", fill="x", expand=True)
        self.query.trace_add("write", lambda *_: self.render())
        self.tree = self.table(skills, [("name", "名称", 220), ("store", "共享库", 100),
                                       ("codex", "Codex", 160), ("workbuddy", "WorkBuddy", 160), ("size", "文件大小", 100)])
        self.tree.bind("<<TreeviewSelect>>", self.details)
        self.detail = tk.Text(skills, height=5, wrap="word", font=("Microsoft YaHei UI", 10),
                              bg="#ffffff", fg="#253958", relief="flat", padx=12, pady=10)
        self.detail.pack(fill="x", pady=(10, 0))
        self.backtree = self.table(backups, [("id", "事务编号", 310), ("name", "技能", 240), ("bytes", "备份大小", 130)])
        backupbar = ttk.Frame(backups)
        backupbar.pack(fill="x", pady=12)
        self.button(backupbar, "还原选中备份", self.restore)
        self.button(backupbar, "清理选中备份，释放空间", self.purge)
        ttk.Label(backups, text="合并时保留原副本用于还原；验证两端可以调用后，清理备份才真正释放磁盘空间。",
                  wraplength=900).pack(anchor="w")
        self.summary = ttk.Label(outer, text="读取中…", foreground="#246951")
        self.summary.pack(anchor="w", pady=(12, 4))
        ttk.Label(outer, text="文件共享不合并两个软件的运行内存。专属 MCP、脚本环境、登录权限仍需在每端配置。",
                  foreground="#53647d", wraplength=1000).pack(anchor="w")
        self.root.after(100, self.poll)
        self.refresh()

    def close(self):
        if self.busy:
            messagebox.showinfo("正在处理", "请等待当前操作完成后关闭，以免中断文件操作。")
            return
        self.root.destroy()

    def button(self, parent, text, command):
        b = ttk.Button(parent, text=text, command=command)
        b.pack(side="left", padx=(0, 8))
        self.buttons.append(b)

    def table(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=75)
        return tree

    def run(self, action, success=None):
        if self.busy:
            return
        self.busy = True
        for b in self.buttons:
            b.configure(state="disabled")
        self.summary.configure(text="处理中…")
        def worker():
            try:
                value = action()
                self.events.put((True, value, success))
            except Exception as e:
                self.events.put((False, str(e), None))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            ok, value, callback = self.events.get_nowait()
            self.busy = False
            for b in self.buttons:
                b.configure(state="normal")
            if ok:
                if callback:
                    callback(value)
            else:
                self.summary.configure(text="操作失败；请查看提示。")
                messagebox.showerror("操作未完成", value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def refresh(self):
        self.paths.configure(text=f"共享库：{self.lib.store}\nCodex：{self.lib.hosts['codex']}     WorkBuddy：{self.lib.hosts['workbuddy']}")
        self.run(lambda: (self.lib.rows(), self.lib.transactions()), self.loaded)

    def loaded(self, value):
        self.rows, self.records = value
        self.render()
        self.backtree.delete(*self.backtree.get_children())
        for row in self.records:
            label = row["name"] + ("（中断，需检查日志）" if row.get("status") == "pending" else "")
            self.backtree.insert("", "end", iid=row["transaction"], values=(row["transaction"], label, human(row["backup_bytes"])))
        shared = sum(r["codex"] == r["workbuddy"] == "已共享" for r in self.rows)
        issues = sum(bool(r["error"]) or any(r[h] in ("断链", "独立副本", "链接到其他位置", "同名文件冲突") for h in self.lib.hosts) for r in self.rows)
        self.summary.configure(text=f"{len(self.rows)} 个技能 · {shared} 个已共享到两端 · {issues} 个需检查 · {len(self.records)} 份合并记录")

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.query.get().casefold()
        for row in self.rows:
            if query not in (row["name"] + " " + row["description"]).casefold():
                continue
            self.tree.insert("", "end", iid=row["name"], values=(row["name"], "有" if row["in_store"] else "未收录",
                                                                   row["codex"], row["workbuddy"], human(row["bytes"])))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def chosen(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("选择技能", "请先选中一个技能。")
            return None
        return selected[0]

    def details(self, _event=None):
        selected = self.tree.selection()
        row = next((r for r in self.rows if selected and r["name"] == selected[0]), None)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if row:
            self.detail.insert("end", f"{row['name']}\n{row['description']}\n共享文件路径：{self.lib.store / row['name']}\n{row['error']}")
        self.detail.configure(state="disabled")

    def completed(self, text):
        def callback(_value):
            messagebox.showinfo("已完成", text)
            self.refresh()
        return callback

    def import_skill(self):
        folder = filedialog.askdirectory(title="选择直接包含 SKILL.md 的技能文件夹")
        if folder:
            self.run(lambda: self.lib.import_skill(Path(folder)), self.completed("已导入共享库。选中技能后点击「共享到两端」。源目录保留不变。"))

    def mount(self):
        name = self.chosen()
        if name:
            self.run(lambda: self.lib.mount(name), self.completed("已建立两端目录链接。请在两个软件的技能列表检查；未显示时重新打开软件。"))

    def consolidate(self):
        name = self.chosen()
        if not name:
            return
        def preview(plan):
            text = f"技能：{name}\n主副本：{plan['source']}\n原副本备份大小：{human(plan['backup_bytes'])}\n\n会逐文件核对完整内容，只合并完全相同的副本。建议先关闭两个软件中的相关任务，避免并发更新。\n\n是否执行合并？"
            if messagebox.askyesno("合并预览", text):
                self.run(lambda: self.lib.consolidate(name), self.completed("已合并并共享。原副本保存在「合并备份」中，可还原。验证两端可调用后，可清理备份释放空间。"))
            else:
                self.refresh()
        self.run(lambda: self.lib.plan(name), preview)

    def detach(self):
        name = self.chosen()
        if not name:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("选择取消共享的端")
        dialog.transient(self.root)
        ttk.Label(dialog, text="只移除所选端的目录链接，保留共享库文件。", padding=16).pack()
        for host, label in (("codex", "Codex"), ("workbuddy", "WorkBuddy")):
            def apply(h=host):
                dialog.destroy()
                self.run(lambda: self.lib.detach(name, h), self.completed("已移除目录链接。软件的技能缓存可能需要刷新或重新打开。"))
            ttk.Button(dialog, text=label, command=apply).pack(fill="x", padx=16, pady=8)
        dialog.grab_set()

    def backup_id(self):
        selected = self.backtree.selection()
        if not selected:
            messagebox.showinfo("选择备份", "请在合并备份页选中一条记录。")
            return None
        return selected[0]

    def restore(self):
        ident = self.backup_id()
        if ident and messagebox.askyesno("还原", "撤销这次合并，将原副本放回原目录？共享技能或原路径已变化时会拒绝还原。"):
            self.run(lambda: self.lib.restore(ident), self.completed("已还原到合并前的目录结构。"))

    def purge(self):
        ident = self.backup_id()
        if ident and messagebox.askyesno("永久清理备份", "请先确认两个软件都能调用该技能。\n\n永久删除此记录中的旧副本并释放磁盘空间，保留共享技能。清理后不能撤销这次合并。继续？"):
            self.run(lambda: self.lib.purge(ident), lambda n: (messagebox.showinfo("已清理", f"已释放原副本文件大小：{human(n)}（实际磁盘块大小可能不同）。"), self.refresh()))

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("目录设置")
        dialog.transient(self.root)
        variables = {}
        for key, label, path in (("store", "共享库", self.lib.store), ("codex", "Codex 目录", self.lib.hosts["codex"]),
                                 ("workbuddy", "WorkBuddy 目录", self.lib.hosts["workbuddy"])):
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill="x")
            ttk.Label(frame, text=label, width=15).pack(side="left")
            variable = tk.StringVar(value=str(path))
            variables[key] = variable
            ttk.Entry(frame, textvariable=variable, width=70).pack(side="left")
        ttk.Label(dialog, text="更改目录只切换管理视图，不迁移旧文件和链接。", padding=12).pack(anchor="w")
        def save():
            try:
                data = {k: v.get().strip() for k, v in variables.items()}
                if not all(data.values()) or not all(Path(p).is_absolute() for p in data.values()):
                    raise ValueError("请填写完整的绝对目录。")
                lib = Library(store=Path(data["store"]), codex=Path(data["codex"]), workbuddy=Path(data["workbuddy"]))
                self.config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self.lib = lib
                dialog.destroy()
                self.refresh()
            except Exception as e:
                messagebox.showerror("设置失败", str(e))
        ttk.Button(dialog, text="保存", command=save).pack(pady=12)
        dialog.grab_set()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        App(root)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("SkillBridge 启动失败", str(exc))
        raise
