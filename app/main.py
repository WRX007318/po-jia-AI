from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from runtime import Runtime
from store import Store
from bootstrap import check_model_dir, download as download_model, install_llama

APP = "破甲 AI"
ROOT = Path(os.environ.get("POJIA_HOME", Path.home() / "PoJiaAI"))
MODELS = ROOT / "models" / "inkling2mini"
DATA = ROOT / "data"
REPO = Path(__file__).resolve().parent.parent


class Workbench(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("1240x820")
        self.minsize(960, 650)
        self.configure(bg="#f6f7fb")
        self.store = Store(DATA)
        self.runtime = Runtime(ROOT, MODELS)
        self.session = None
        self.image = None
        self.worker_proc = None
        self.cancel = threading.Event()
        self._style()
        self._layout()
        self.new_session()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(1200, self.refresh)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background="#f6f7fb")
        s.configure("Card.TFrame", background="white")
        s.configure("TLabel", background="#f6f7fb", foreground="#18202b", font=("Microsoft YaHei UI", 10))
        s.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        s.configure("Sub.TLabel", foreground="#677184")
        s.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        s.configure("Accent.TButton", background="#3c67e8", foreground="white")
        s.map("Accent.TButton", background=[("active", "#2e54cb")])
        s.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 9))

    def _layout(self):
        shell = ttk.Frame(self); shell.pack(fill="both", expand=True)
        self.nav = tk.Frame(shell, bg="#172033", width=220); self.nav.pack(side="left", fill="y"); self.nav.pack_propagate(False)
        tk.Label(self.nav, text="破甲 AI", fg="white", bg="#172033", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", padx=22, pady=(24, 2))
        tk.Label(self.nav, text="本地智能工作台", fg="#aeb8cd", bg="#172033", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=(0, 24))
        self.pages = {}
        for key, label in [("chat", "AI 对话"), ("code", "编程工作台"), ("vision", "视觉工作台"), ("tasks", "视觉任务"), ("db", "视觉数据库"), ("models", "模型管理"), ("monitor", "资源监控"), ("settings", "设置与日志")]:
            b = tk.Button(self.nav, text="  " + label, anchor="w", relief="flat", fg="#e6eaf2", bg="#172033", activebackground="#2a3650", activeforeground="white", font=("Microsoft YaHei UI", 10), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2, ipady=7)
        foot = tk.Frame(self.nav, bg="#172033"); foot.pack(side="bottom", fill="x", padx=16, pady=18)
        self.status_dot = tk.Label(foot, text="● 未连接", fg="#f0bc55", bg="#172033", anchor="w"); self.status_dot.pack(fill="x")
        self.content = ttk.Frame(shell, padding=24); self.content.pack(side="left", fill="both", expand=True)
        for key, builder in [("chat",self.page_chat),("code",self.page_code),("vision",self.page_vision),("tasks",self.page_tasks),("db",self.page_db),("models",self.page_models),("monitor",self.page_monitor),("settings",self.page_settings)]:
            frame=ttk.Frame(self.content); self.pages[key]=frame; builder(frame)
        self.show("chat")

    def header(self, parent, title, desc):
        ttk.Label(parent,text=title,style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent,text=desc,style="Sub.TLabel").pack(anchor="w",pady=(5,16))

    def page_chat(self, f):
        self.header(f,"AI 对话","所有对话在本机处理并保存在本地。")
        bar=ttk.Frame(f);bar.pack(fill="x",pady=(0,10))
        ttk.Button(bar,text="新建对话",command=self.new_session).pack(side="left")
        ttk.Button(bar,text="上传图片",command=self.chat_image).pack(side="left",padx=8)
        self.chat_log=tk.Text(f,wrap="word",bg="white",bd=0,padx=18,pady=16,font=("Microsoft YaHei UI",10),state="disabled")
        self.chat_log.pack(fill="both",expand=True)
        bottom=ttk.Frame(f);bottom.pack(fill="x",pady=(12,0))
        self.prompt=tk.Text(bottom,height=4,wrap="word",font=("Microsoft YaHei UI",10),bd=1,relief="solid")
        self.prompt.pack(side="left",fill="both",expand=True)
        btns=ttk.Frame(bottom);btns.pack(side="left",padx=(10,0),fill="y")
        ttk.Button(btns,text="发送",style="Accent.TButton",command=self.send).pack(fill="x")
        ttk.Button(btns,text="停止",command=self.stop_generation).pack(fill="x",pady=6)

    def page_code(self,f):
        self.header(f,"编程工作台","生成的差异先进入审阅区；命令须由你手动确认运行。")
        row=ttk.Frame(f);row.pack(fill="x")
        self.project_var=tk.StringVar(value="未选择项目")
        ttk.Label(row,textvariable=self.project_var).pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="选择项目",command=self.pick_project).pack(side="right")
        self.code_prompt=tk.Text(f,height=5,font=("Microsoft YaHei UI",10));self.code_prompt.pack(fill="x",pady=12)
        ttk.Button(f,text="分析项目 / 生成补丁",style="Accent.TButton",command=self.code_task).pack(anchor="e")
        self.diff=tk.Text(f,bg="#101827",fg="#dbe4f3",font=("Consolas",10),wrap="none");self.diff.pack(fill="both",expand=True,pady=12)
        self.code_project=None
        actions=ttk.Frame(f);actions.pack(fill="x")
        ttk.Button(actions,text="应用所示统一 Diff",command=self.apply_patch).pack(side="left")
        ttk.Button(actions,text="回滚最近一次应用",command=self.rollback_patch).pack(side="left",padx=8)

    def page_vision(self,f):
        self.header(f,"视觉工作台","识别普通页面截图；检测到安全验证时请人工处理，不会分析或保存挑战页面。")
        bar=ttk.Frame(f);bar.pack(fill="x")
        ttk.Button(bar,text="选择截图",command=self.pick_image).pack(side="left")
        ttk.Button(bar,text="识别图片",style="Accent.TButton",command=self.recognize).pack(side="left",padx=8)
        self.img_label=ttk.Label(f,text="尚未选择图片",style="Sub.TLabel");self.img_label.pack(anchor="w",pady=10)
        self.vision_result=tk.Text(f,bg="white",font=("Microsoft YaHei UI",10),wrap="word",bd=0);self.vision_result.pack(fill="both",expand=True)
        self.image=None

    def page_tasks(self,f):
        self.header(f,"视觉任务","独立本地调度进程；任务只读取你明确授权的本地截图文件夹。")
        row=ttk.Frame(f);row.pack(fill="x")
        ttk.Button(row,text="创建本地导入任务",style="Accent.TButton",command=self.create_task).pack(side="left")
        ttk.Button(row,text="暂停",command=lambda:self.worker_action("pause")).pack(side="left",padx=6)
        ttk.Button(row,text="继续",command=lambda:self.worker_action("resume")).pack(side="left")
        ttk.Button(row,text="停止调度器",command=self.stop_worker).pack(side="right")
        self.task_tree=ttk.Treeview(f,columns=("source","state","count","updated"),show="headings")
        for col,text,w in [("source","来源",330),("state","状态",100),("count","已处理",100),("updated","更新时间",180)]:self.task_tree.heading(col,text=text);self.task_tree.column(col,width=w)
        self.task_tree.pack(fill="both",expand=True,pady=14)
        self.ensure_worker()

    def page_db(self,f):
        self.header(f,"视觉数据库","SHA256 去重；人工复核后保存分类和标签。原图保存在本机数据目录。")
        row=ttk.Frame(f);row.pack(fill="x")
        self.search_var=tk.StringVar();e=ttk.Entry(row,textvariable=self.search_var);e.pack(side="left",fill="x",expand=True);e.bind("<Return>",lambda _:self.refresh_samples())
        ttk.Button(row,text="检索",command=self.refresh_samples).pack(side="left",padx=6)
        ttk.Button(row,text="导出 JSON",command=self.export_samples).pack(side="left")
        self.sample_tree=ttk.Treeview(f,columns=("id","category","size","reviewed","source"),show="headings",selectmode="browse")
        for col,text,w in [("id","样本 ID",190),("category","页面分类",180),("size","分辨率",120),("reviewed","审核",90),("source","来源",180)]:self.sample_tree.heading(col,text=text);self.sample_tree.column(col,width=w)
        self.sample_tree.pack(fill="both",expand=True,pady=12)
        row=ttk.Frame(f);row.pack(fill="x")
        ttk.Button(row,text="预览 / 编辑审核",command=self.review_sample).pack(side="left")

    def page_models(self,f):
        self.header(f,"模型管理","本机独立存储；运行时仅绑定 127.0.0.1。")
        self.model_info=tk.Text(f,height=10,bg="white",bd=0,font=("Microsoft YaHei UI",10));self.model_info.pack(fill="x")
        self.model_info.insert("end",f"模型目录：{MODELS}\n运行时：{ROOT / 'runtime'}\n模型：Inkling-2-Mini AD-IQ3_S\n视觉组件：mmproj F16\n状态：按启动检查结果更新\n")
        row=ttk.Frame(f);row.pack(fill="x",pady=12)
        ttk.Button(row,text="启动模型服务",style="Accent.TButton",command=lambda:self.background(self.start_runtime)).pack(side="left")
        ttk.Button(row,text="停止并释放资源",command=self.runtime.stop).pack(side="left",padx=8)
        ttk.Button(row,text="下载并校验模型",command=lambda:self.background(self.bootstrap_all)).pack(side="left")
        ttk.Button(row,text="打开模型目录",command=lambda:os.startfile(MODELS) if MODELS.exists() else None).pack(side="left")
        self.model_log=tk.Text(f,bg="white",bd=0);self.model_log.pack(fill="both",expand=True)

    def bootstrap_all(self):
        try:
            self.after(0,lambda:self.model_log.insert("end","\n校验或下载模型中…\n"))
            ok=check_model_dir()
            if not ok:
                def progress(name,done,total):
                    pct=(done/total*100) if total else 0
                    self.after(0,lambda:self.model_log.insert("end",f"\r{name}: {done/1024**3:.2f}/{total/1024**3:.2f} GiB ({pct:.1f}%)"))
                download(progress=progress)
            exe=install_llama(progress=lambda n,d,t:self.after(0,lambda:self.model_log.insert("end",f"\n运行时 {n}: {d/1024**2:.1f}/{t/1024**2:.1f} MiB")))
            self.after(0,lambda:messagebox.showinfo(APP,f"模型、SHA-256 校验和运行时已完成。\n{exe}"))
        except Exception as e:self.after(0,lambda:messagebox.showerror(APP,f"安装失败：{e}"))

    def page_monitor(self,f):
        self.header(f,"资源监控","读取 Windows 性能计数和 NVIDIA SMI。")
        ttk.Button(f,text="刷新",command=self.refresh_monitor).pack(anchor="e")
        self.monitor=tk.Text(f,bg="white",bd=0,font=("Consolas",11));self.monitor.pack(fill="both",expand=True,pady=12)

    def page_settings(self,f):
        self.header(f,"设置与日志","应用设置及会话数据仅写入本机用户目录。")
        ttk.Label(f,text=f"数据目录：{DATA}").pack(anchor="w",pady=4)
        ttk.Label(f,text=f"运行时目录：{ROOT}").pack(anchor="w",pady=4)
        ttk.Button(f,text="打开数据目录",command=lambda:os.startfile(DATA)).pack(anchor="w",pady=8)
        ttk.Label(f,text="安全边界：仅本地推理；不自动操作大麦账号、交易或安全验证页面。",wraplength=780).pack(anchor="w",pady=12)
        self.log=tk.Text(f,bg="white",bd=0);self.log.pack(fill="both",expand=True)

    def show(self,key):
        for p in self.pages.values():p.pack_forget()
        self.pages[key].pack(fill="both",expand=True)
        if key=="db":self.refresh_samples()
        if key=="tasks":self.refresh_tasks()
        if key=="models":self.refresh()
        if key=="monitor":self.refresh_monitor()

    def logline(self,text):
        if hasattr(self,"log"):
            self.log.insert("end",f"{time.strftime('%H:%M:%S')} {text}\n");self.log.see("end")

    def background(self,fn): threading.Thread(target=fn,daemon=True).start()

    def start_runtime(self):
        try:
            self.runtime.start();self.after(0,lambda:messagebox.showinfo(APP,"本地模型服务已就绪。"))
        except Exception as e:self.after(0,lambda:messagebox.showerror(APP,str(e)))

    def refresh(self):
        state=self.runtime.status();color={"ready":"#39b778","loading":"#e6aa38","stopped":"#e6aa38"}.get(state,"#e05252")
        text={"ready":"● 模型就绪","loading":"● 模型加载中","stopped":"● 模型未启动"}.get(state,"● 模型异常")
        self.status_dot.configure(text=text,fg=color)
        if hasattr(self,"model_log") and self.pages["models"].winfo_ismapped():
            self.model_log.delete("1.0","end");self.model_log.insert("end",f"服务状态：{state}\n回环地址：{self.runtime.base}\n模型已存在：{(MODELS/'Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf').exists()}\n视觉组件已存在：{(MODELS/'mmproj-Inkling-2-Mini-Uncensored-F16.gguf').exists()}\n")
        self.after(2500,self.refresh)

    def new_session(self):
        self.session=self.store.new_session();self.render_messages()

    def render_messages(self):
        if not hasattr(self,"chat_log"):return
        self.chat_log.configure(state="normal");self.chat_log.delete("1.0","end")
        for m in self.store.messages(self.session):self.chat_log.insert("end",("你" if m["role"]=="user" else "破甲 AI")+"\n"+m["content"]+"\n\n")
        self.chat_log.configure(state="disabled");self.chat_log.see("end")

    def chat_image(self):
        p=filedialog.askopenfilename(filetypes=[("图片","*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:self.image=Path(p);messagebox.showinfo(APP,f"已附加：{self.image.name}")

    def send(self):
        prompt=self.prompt.get("1.0","end").strip()
        if not prompt:return
        if self.runtime.status()!="ready":messagebox.showwarning(APP,"请先在模型管理中启动已安装的本地推理服务。");return
        self.prompt.delete("1.0","end");self.store.add_message(self.session,"user",prompt);self.render_messages();self.cancel.clear()
        def run():
            try:
                result=self.runtime.chat(self.store.messages(self.session),self.image)
                self.store.add_message(self.session,"assistant",result)
                self.after(0,self.render_messages)
            except Exception as e:self.after(0,lambda:messagebox.showerror(APP,str(e)))
            self.image=None
        self.background(run)

    def stop_generation(self):
        try:
            req=__import__("urllib.request",fromlist=["Request"]).Request(self.runtime.base+"/slots/0?action=cancel",method="POST")
            __import__("urllib.request",fromlist=["urlopen"]).urlopen(req,timeout=2).close()
        except Exception:pass

    def pick_image(self):
        p=filedialog.askopenfilename(filetypes=[("图片","*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:self.image=Path(p);self.img_label.configure(text=self.image.name)

    def recognize(self):
        if not self.image:return messagebox.showinfo(APP,"请先选择图片。")
        if self.runtime.status()!="ready":return messagebox.showwarning(APP,"本地模型服务尚未就绪。")
        self.vision_result.delete("1.0","end");self.vision_result.insert("end","识别中…")
        def run():
            try:
                out=self.runtime.chat([{"role":"user","content":"识别这张普通业务页面截图。只返回 JSON：{page_type, elements, visible_text, needs_human_review}。若含安全验证/验证码/登录挑战，needs_human_review=true，且不要描述挑战内容。"}],self.image)
                self.after(0,lambda:(self.vision_result.delete("1.0","end"),self.vision_result.insert("end",out)))
            except Exception as e:self.after(0,lambda:messagebox.showerror(APP,str(e)))
        self.background(run)

    def pick_project(self):
        p=filedialog.askdirectory()
        if p:self.code_project=Path(p);self.project_var.set(p)

    def code_task(self):
        if not self.code_project:return messagebox.showwarning(APP,"请先选择本地项目目录。")
        if self.runtime.status()!="ready":return messagebox.showwarning(APP,"模型服务尚未就绪。")
        prompt=self.code_prompt.get("1.0","end").strip()
        if not prompt:return
        files=[]
        for p in self.code_project.rglob("*"):
            blocked={".git","node_modules",".venv","venv","__pycache__",".env","secrets","credentials"}
            if p.is_file() and not any(part.lower() in blocked for part in p.parts) and p.name.lower() not in {".env","id_rsa","id_ed25519","credentials.json"} and len(files)<30 and p.stat().st_size<100_000:
                try:files.append(f"\n--- {p.relative_to(self.code_project)} ---\n"+p.read_text(encoding="utf-8"))
                except Exception:pass
        messages=[{"role":"user","content":f"基于以下只读项目文件完成请求：{prompt}\n请给出统一 diff，不要执行命令。\n"+"".join(files)}]
        self.diff.delete("1.0","end");self.diff.insert("end","正在分析…")
        def run():
            try:
                out=self.runtime.chat(messages);self.after(0,lambda:(self.diff.delete("1.0","end"),self.diff.insert("end",out)))
            except Exception as e:self.after(0,lambda:messagebox.showerror(APP,str(e)))
        self.background(run)

    def apply_patch(self):
        if not self.code_project:return messagebox.showwarning(APP,"请先选择项目目录。")
        raw=self.diff.get("1.0","end").strip()
        if "*** Begin Patch" not in raw:return messagebox.showwarning(APP,"目前只支持 Codex patch 格式；未识别补丁，不做写入。")
        # Application is intentionally limited to files beneath the selected project.
        import re
        changes=[];current=None;mode=None;lines=[]
        for line in raw.splitlines():
            if line.startswith("*** Add File: "):
                if current:changes.append((current,mode,lines))
                current=line[len("*** Add File: "):].strip();mode="add";lines=[]
            elif line.startswith("*** Update File: "):
                if current:changes.append((current,mode,lines))
                current=line[len("*** Update File: "):].strip();mode="update";lines=[]
            elif line.startswith("*** Delete File: "):
                if current:changes.append((current,mode,lines))
                current=line[len("*** Delete File: "):].strip();mode="delete";lines=[]
            elif line.startswith("*** End Patch"):
                if current:changes.append((current,mode,lines));current=None
            elif current and line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
        if current:changes.append((current,mode,lines))
        if not changes:return messagebox.showwarning(APP,"补丁中没有可安全识别的文件变更。")
        resolved=[]
        for rel,mode,lines in changes:
            target=(self.code_project/rel).resolve()
            try:target.relative_to(self.code_project.resolve())
            except ValueError:return messagebox.showerror(APP,"补丁路径超出所选项目目录，已拒绝。")
            if mode=="delete":return messagebox.showwarning(APP,"删除文件补丁暂不开放。")
            if mode=="update":return messagebox.showwarning(APP,"更新文件请先使用新文件补丁或手工应用；避免不完整 Diff 覆盖。")
            if target.exists():return messagebox.showwarning(APP,f"目标文件已存在：{rel}")
            resolved.append((target,mode,lines))
        if not messagebox.askyesno(APP,f"将在所选项目中新建 {len(resolved)} 个文件。确认前会备份，继续？"):return
        backup=DATA/"patch-backups"/time.strftime("%Y%m%d-%H%M%S");backup.mkdir(parents=True,exist_ok=True)
        created=[]
        try:
            for target,mode,lines in resolved:
                target.parent.mkdir(parents=True,exist_ok=True);target.write_text("\n".join(lines)+"\n",encoding="utf-8");created.append(str(target))
            (backup/"manifest.json").write_text(json.dumps({"created":created},indent=2),encoding="utf-8")
            messagebox.showinfo(APP,f"已写入 {len(created)} 个新文件。\n备份记录：{backup}")
        except Exception:
            for name in created:Path(name).unlink(missing_ok=True)
            raise

    def rollback_patch(self):
        folders=sorted((DATA/"patch-backups").glob("*"),reverse=True) if (DATA/"patch-backups").exists() else []
        if not folders:return messagebox.showinfo(APP,"没有可回滚的应用记录。")
        manifest=folders[0]/"manifest.json"
        data=json.loads(manifest.read_text(encoding="utf-8"))
        if not messagebox.askyesno(APP,f"移除最近一次应用所创建的 {len(data['created'])} 个文件？"):
            return
        for name in data["created"]:
            path=Path(name)
            try:path.resolve().relative_to(self.code_project.resolve())
            except Exception:continue
            path.unlink(missing_ok=True)
        messagebox.showinfo(APP,"最近一次应用已回滚。")

    def ensure_worker(self):
        if self.worker_proc and self.worker_proc.poll() is None:return
        command=[sys.executable,str(REPO/"app"/"vision_worker.py"),"--data-dir",str(DATA)]
        self.worker_proc=subprocess.Popen(command,cwd=REPO/"app",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def create_task(self):
        folder=filedialog.askdirectory(title="选择已授权的本地截图目录")
        if not folder:return
        limit=simpledialog.askinteger("采集上限","本任务最多处理多少张图片？",initialvalue=50,minvalue=1,maxvalue=10000)
        if not limit:return
        self.store.create_task(folder,limit);self.ensure_worker();self.refresh_tasks()

    def worker_action(self,action):
        state=DATA/"worker.json";state.write_text(json.dumps({"action":action}),encoding="utf-8")
        if action=="resume": self.ensure_worker()
        messagebox.showinfo(APP,"调度器已收到控制请求。")

    def stop_worker(self):
        (DATA/"worker.json").write_text(json.dumps({"action":"stop"}),encoding="utf-8")
        if self.worker_proc and self.worker_proc.poll() is None:self.worker_proc.terminate()
        self.worker_proc=None

    def refresh_tasks(self):
        if not hasattr(self,"task_tree"):return
        for i in self.task_tree.get_children():self.task_tree.delete(i)
        for t in self.store.tasks():self.task_tree.insert("","end",values=(Path(t["source"]).name,t["status"],t["processed"],time.strftime("%Y-%m-%d %H:%M",time.localtime(t["updated"]))))

    def refresh_samples(self):
        if not hasattr(self,"sample_tree"):return
        for i in self.sample_tree.get_children():self.sample_tree.delete(i)
        for s in self.store.samples(self.search_var.get()):self.sample_tree.insert("","end",iid=s["id"],values=(s["id"],s["category"],f"{s['width'] or '?'}×{s['height'] or '?'}","已审核" if s["reviewed"] else "待审核",s["source"]))

    def review_sample(self):
        sel=self.sample_tree.selection()
        if not sel:return
        s=next((x for x in self.store.samples() if x["id"]==sel[0]),None)
        if not s:return
        category=simpledialog.askstring("页面分类","请输入页面分类",initialvalue=s["category"])
        if category is None:return
        labels=simpledialog.askstring("标签","逗号分隔标签",initialvalue=",".join(json.loads(s["labels"])))
        if labels is None:return
        self.store.update_sample(s["id"],category,[x.strip() for x in labels.split(",") if x.strip()],True);self.refresh_samples()

    def export_samples(self):
        dest=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")])
        if not dest:return
        rows=[dict(x) for x in self.store.samples()]
        Path(dest).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8");messagebox.showinfo(APP,"导出完成")

    def refresh_monitor(self):
        if not hasattr(self,"monitor"):return
        try:gpu=subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu","--format=csv,noheader"],text=True,timeout=5).strip()
        except Exception as e:gpu=f"nvidia-smi 不可用：{e}"
        try:mem=subprocess.check_output(["powershell.exe","-NoProfile","-Command","(Get-CimInstance Win32_OperatingSystem | Select-Object @{n='TotalGB';e={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}},@{n='FreeGB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}} | ConvertTo-Json -Compress)"],text=True,timeout=8).strip()
        except Exception as e:mem=f"RAM 查询失败：{e}"
        self.monitor.delete("1.0","end");self.monitor.insert("end",f"GPU\n{gpu}\n\nRAM\n{mem}\n\n运行时状态\n{self.runtime.status()}\n")

    def close(self):
        self.runtime.stop();self.stop_worker();self.destroy()


if __name__=="__main__":
    Workbench().mainloop()
