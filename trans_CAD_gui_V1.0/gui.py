#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD文件翻译处理系统 - 图形用户界面（线程安全重构版）

重构目标：
1. 修复线程安全问题：所有UI更新通过主线程的after方法执行
2. 统一子进程管理：增加超时控制和错误处理
3. 优化用户体验：添加取消功能和更好的进度反馈
4. 启动时依赖检查：避免运行时错误
5. 集成日志功能：记录用户操作和程序状态

作者: AI Assistant
日期: 2024
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import subprocess
import sys
from pathlib import Path
import queue
import os
import time
import signal
from typing import Optional, List, Callable, Tuple

# 导入日志配置
try:
    from logger_config import get_logger
except ImportError:
    # 如果日志模块不可用，创建一个简单的替代
    import logging
    def get_logger(name="cad_translator"):
        return logging.getLogger(name)

# 内置依赖检查
def _check_deps() -> Tuple[bool, List[str]]:
    """检查必要依赖是否已安装"""
    required = ['ezdxf', 'pandas', 'openpyxl']
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    return len(missing) == 0, missing

# 已移除Aspose.CAD相关依赖，现在使用AutoCAD转换器

# 配置管理 - 现在通过命令行参数传递给回填.py
def get_translation_config():
    """获取翻译配置（保留兼容性）"""
    return {'mode': 'replace', 'font_size_reduction': 4}

def set_translation_mode(mode):
    """设置翻译模式（已废弃，现在通过命令行参数传递）"""
    # 此函数已废弃，配置现在通过命令行参数传递给回填.py
    pass

def set_font_size_reduction(value):
    """设置字体减少值（已废弃，现在通过命令行参数传递）"""
    # 此函数已废弃，配置现在通过命令行参数传递给回填.py
    pass

def get_current_font():
    """获取当前字体（从font_config.py读取）"""
    try:
        from font_config import get_current_font as get_font
        return get_font()
    except ImportError:
        return 'Times New Roman'

def set_font(font):
    """设置字体（通过font_config.py）"""
    try:
        from font_config import set_font as set_font_config
        return set_font_config(font)
    except ImportError:
        # 如果font_config.py不可用，直接返回True（GUI会通过命令行参数传递）
        return True

# 使用导入的依赖检查函数
check_dependencies = _check_deps

class CADTranslationApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CAD文件翻译处理系统 v2.1")
        self.geometry("950x750")
        
        # 初始化日志记录器
        self.logger = get_logger("cad_gui")
        self.logger.info("CAD翻译工具启动")
        
        # 工作状态（线程安全）
        self._processing = False
        self._current_process: Optional[subprocess.Popen] = None
        self._cancel_requested = False
        self.selected_files: List[str] = []
        self.working_dir: Optional[Path] = None
        
        # 线程安全的消息队列
        self.ui_queue = queue.Queue()  # UI更新队列
        self.log_queue = queue.Queue()  # 日志消息队列
        
        # 布局权重
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        
        # 构建UI
        self._create_widgets()
        
        # 启动UI更新循环
        self._process_ui_queue()
        
        # 启动时检查依赖
        self.after(100, self._check_startup_dependencies)
        
        # 欢迎语
        self._log("欢迎使用CAD翻译工具，只支持DXF文件，如果是DWG文件需先转换为DXF文件。先选择工作文件夹或DWG文件开始吧~ ✨")
    
    def _check_startup_dependencies(self) -> None:
        """启动时检查依赖"""
        self.logger.info("开始检查启动依赖")
        all_ok, missing = check_dependencies()
        if not all_ok:
            msg = f"缺少必要依赖：{', '.join(missing)}\n\n请运行以下命令安装：\npip install {' '.join(missing)}"
            self.logger.error(f"依赖检查失败，缺少：{missing}")
            messagebox.showerror("依赖检查失败", msg)
            self._log(f"❌ 依赖检查失败：{missing}")
            return
        
        self.logger.info("所有必要依赖检查通过")
        self._log("✅ 所有依赖检查通过")
        
        # 使用AutoCAD转换器，无需额外依赖检查
        self.logger.info("使用AutoCAD转换器")
        self._log("✅ AutoCAD转换器已集成")
    
    def _process_ui_queue(self) -> None:
        """处理UI更新队列（主线程安全）"""
        try:
            while True:
                action, *args = self.ui_queue.get_nowait()
                
                if action == 'update_buttons':
                    processing = args[0]
                    self._update_buttons_state(processing)
                elif action == 'update_progress':
                    value, text = args
                    self.progress_bar.set(value)
                    self.progress_label.configure(text=text)
                elif action == 'log_message':
                    message = args[0]
                    self._append_log_safe(message)
                elif action == 'show_error':
                    title, message = args
                    messagebox.showerror(title, message)
                elif action == 'show_info':
                    title, message = args
                    messagebox.showinfo(title, message)
                elif action == 'ask_question':
                    title, message, callback = args
                    result = messagebox.askyesno(title, message)
                    if callback:
                        callback(result)
        except queue.Empty:
            pass
        finally:
            self.after(50, self._process_ui_queue)  # 更频繁的UI更新
    
    def _update_buttons_state(self, processing: bool) -> None:
        """更新按钮状态（主线程安全）"""
        state = "disabled" if processing else "normal"
        
        # 文件选择按钮
        self.btn_select_dwg.configure(state=state)
        self.btn_select_dir.configure(state=state)
        
        # 操作按钮
        self.btn_convert.configure(state=state)
        self.btn_extract.configure(state=state)
        self.btn_open_excel.configure(state=state)
        self.btn_apply.configure(state=state)
        self.btn_auto.configure(state=state)
        
        # 取消按钮状态相反
        self.btn_cancel.configure(state="normal" if processing else "disabled")
    
    def _append_log_safe(self, message: str) -> None:
        """线程安全的日志追加"""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")
    
    def _safe_ui_call(self, action: str, *args) -> None:
        """线程安全的UI调用"""
        self.ui_queue.put((action, *args))
    
    def _on_cancel(self) -> None:
        """取消当前操作"""
        if not self.processing:
            return
        
        self._cancel_requested = True
        self._safe_ui_call('log_message', "🛑 正在取消操作...")
        
        # 终止当前子进程
        if self._current_process and self._current_process.poll() is None:
            try:
                if os.name == 'nt':
                    # Windows
                    self._current_process.terminate()
                else:
                    # Unix-like
                    self._current_process.send_signal(signal.SIGTERM)
                
                # 等待进程结束
                try:
                    self._current_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._current_process.kill()
                    self._safe_ui_call('log_message', "⚠️ 强制终止进程")
                
                self._safe_ui_call('log_message', "✅ 操作已取消")
            except Exception as e:
                self._safe_ui_call('log_message', f"❌ 取消操作失败: {e}")
        
        # 重置状态
        self._set_processing(False)
        self._cancel_requested = False
        self._current_process = None
        self._safe_ui_call('update_progress', 0, "操作已取消")
    
    @property
    def processing(self) -> bool:
        """线程安全的处理状态获取"""
        return self._processing
    
    def _set_processing(self, value: bool) -> None:
        """线程安全的处理状态设置"""
        self._processing = value
        # 通过UI队列更新按钮状态
        self.ui_queue.put(('update_buttons', value))

    # -------------------------- UI 构建 --------------------------
    def _create_widgets(self):
        # 标题
        title_frame = ctk.CTkFrame(self)
        title_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        ctk.CTkLabel(title_frame, text="🔧 CAD文件翻译处理系统", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=12)

        # 文件/目录选择
        file_frame = ctk.CTkFrame(self)
        file_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(file_frame, text="📁 文件选择:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.btn_select_dwg = ctk.CTkButton(file_frame, text="选择DWG文件", command=self._select_dwg_files, width=140)
        self.btn_select_dwg.grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.btn_select_dir = ctk.CTkButton(file_frame, text="选择工作文件夹", command=self._select_folder, width=140)
        self.btn_select_dir.grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.file_info_label = ctk.CTkLabel(file_frame, text="尚未选择文件/文件夹", anchor="w")
        self.file_info_label.grid(row=1, column=1, rowspan=2, padx=10, pady=5, sticky="ew")

        # 配置区
        config_frame = ctk.CTkFrame(self)
        config_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        config_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(config_frame, text="⚙️ 翻译配置:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        # 模式
        mode_frame = ctk.CTkFrame(config_frame)
        mode_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        ctk.CTkLabel(mode_frame, text="翻译模式:").pack(side="left", padx=8)
        self.trans_mode = ctk.StringVar(value="add")  # add/replace
        ctk.CTkRadioButton(mode_frame, text="在下方添加翻译", variable=self.trans_mode, value="add").pack(side="left", padx=6)
        ctk.CTkRadioButton(mode_frame, text="替换原文", variable=self.trans_mode, value="replace").pack(side="left", padx=6)

        # 字体
        font_frame = ctk.CTkFrame(config_frame)
        font_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        ctk.CTkLabel(font_frame, text="字体:").pack(side="left", padx=8)
        self.font_menu = ctk.CTkOptionMenu(font_frame, values=[
            "Times New Roman", "Arial", "SimSun", "SimHei", "Microsoft YaHei", "Calibri", "Verdana"
        ], command=self._on_font_changed)
        # 从font_config.py读取当前字体设置，如果失败则使用默认字体
        current_font = get_current_font()
        if current_font is None:
            current_font = "Times New Roman"  # 默认字体
        self.font_menu.set(current_font)
        self.font_menu.pack(side="left", padx=6)
        ctk.CTkLabel(font_frame, text="字号减少:").pack(side="left", padx=(18, 6))
        # 从配置读取字体减少值，默认为4
        config = get_translation_config()
        self.font_reduce_var = ctk.StringVar(value=str(config.get('font_size_reduction', 4)))
        self.font_reduce_entry = ctk.CTkEntry(font_frame, textvariable=self.font_reduce_var, width=60)
        self.font_reduce_entry.pack(side="left", padx=6)
        ctk.CTkLabel(font_frame, text="单位").pack(side="left", padx=4)

        # 操作按钮
        btn_frame = ctk.CTkFrame(self)
        btn_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.btn_convert = ctk.CTkButton(btn_frame, text="1️⃣ 转换DWG至dxf", command=self._on_convert, height=40)
        self.btn_extract = ctk.CTkButton(btn_frame, text="2️⃣ 提取文本", command=self._on_extract, height=40, state="disabled")
        self.btn_open_excel = ctk.CTkButton(btn_frame, text="3️⃣ 打开翻译表", command=self._on_open_excel, height=40, state="disabled")
        self.btn_apply = ctk.CTkButton(btn_frame, text="4️⃣ 应用翻译", command=self._on_apply, height=40, state="disabled")
        self.btn_convert.grid(row=0, column=0, padx=6, pady=10, sticky="ew")
        self.btn_extract.grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        self.btn_open_excel.grid(row=0, column=2, padx=6, pady=10, sticky="ew")
        self.btn_apply.grid(row=0, column=3, padx=6, pady=10, sticky="ew")

        self.btn_auto = ctk.CTkButton(btn_frame, text="🚀 一键处理 (转换+提取+打开翻译表)", command=self._on_auto, height=40,
                                      fg_color="#2fa572", hover_color="#106A43")
        self.btn_auto.grid(row=1, column=0, columnspan=3, padx=6, pady=(0, 8), sticky="ew")
        
        # 取消按钮
        self.btn_cancel = ctk.CTkButton(btn_frame, text="❌ 取消", command=self._on_cancel, height=40,
                                        fg_color="#d32f2f", hover_color="#b71c1c", state="disabled")
        self.btn_cancel.grid(row=1, column=3, padx=6, pady=(0, 8), sticky="ew")

        # 进度
        prog_frame = ctk.CTkFrame(self)
        prog_frame.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.progress_label = ctk.CTkLabel(prog_frame, text="准备就绪")
        self.progress_label.pack(pady=(10, 4))
        self.progress_bar = ctk.CTkProgressBar(prog_frame)
        self.progress_bar.pack(padx=16, pady=(0, 12), fill="x")
        self.progress_bar.set(0)

        # 日志
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=5, column=0, padx=20, pady=(0, 20), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_frame, text="📋 处理日志:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")
        self.log_textbox = ctk.CTkTextbox(log_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

    def _on_font_changed(self, selected_font: str):
        """字体选择改变时的回调函数"""
        self.logger.info(f"用户选择字体：{selected_font}")
        # 同步更新font_config.py中的字体设置
        if set_font(selected_font):
            self.logger.info(f"字体设置已更新：{selected_font}")
            self._log(f"✅ 字体已更新为：{selected_font}")
        else:
            self.logger.warning(f"字体设置更新失败：{selected_font}")
            self._log(f"⚠️ 字体设置更新失败：{selected_font}")

    # -------------------------- 工具方法 --------------------------
    def _ensure_working_dir(self) -> Optional[Path]:
        if self.working_dir and self.working_dir.exists():
            return self.working_dir
        if self.selected_files:
            # 若选择了文件，取其所在目录
            return Path(self.selected_files[0]).parent
        messagebox.showwarning("提示", "请先选择工作文件夹或DWG文件")
        return None

    def _set_buttons(self, converting=False, extracting=False, applying=False):
        """兼容性方法 - 使用新的线程安全机制"""
        processing = converting or extracting or applying
        self._safe_ui_call('update_buttons', processing)

    def _log(self, message: str):
        self._safe_ui_call('log_message', message)
    
    def _get_script_path(self, script_name: str) -> str:
        """获取项目根目录中指定脚本的完整路径"""
        script_dir = Path(__file__).parent
        return str(script_dir / script_name)

    def _stream_subprocess(self, cmd: List[str], cwd: Path, timeout: int = 300) -> int:
        """启动子进程并实时读取输出，返回退出码"""
        self._log(f"执行命令: {' '.join(cmd)}  (cwd={cwd})")
        try:
            self._current_process = subprocess.Popen(
                cmd, cwd=str(cwd), stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            
            start_time = time.time()
            for line in self._current_process.stdout:  # type: ignore
                if self._cancel_requested:
                    self._current_process.terminate()
                    return -1
                
                # 检查超时
                if time.time() - start_time > timeout:
                    self._log(f"⚠️ 操作超时 ({timeout}s)，正在终止...")
                    self._current_process.terminate()
                    return -2
                
                self._log(line.rstrip())
            
            self._current_process.wait()
            return self._current_process.returncode or 0
            
        except FileNotFoundError:
            self._log("错误：找不到可执行文件，请检查Python/脚本路径。")
            return 1
        except Exception as e:
            self._log(f"子进程执行失败: {e}")
            return 1
        finally:
            self._current_process = None

    def _count_files_text(self, directory: Path) -> str:
        dwg_count = sum(1 for p in directory.glob('*.dwg')) + sum(1 for p in directory.glob('*.DWG'))
        dxf_count = sum(1 for p in directory.glob('*.dxf')) + sum(1 for p in directory.glob('*.DXF'))
        return f"目录: {directory} | DWG: {dwg_count} | DXF: {dxf_count}"

    # -------------------------- 选择操作 --------------------------
    def _select_dwg_files(self):
        self.logger.info("用户开始选择DWG文件")
        files = filedialog.askopenfilenames(title="选择DWG文件", filetypes=(("DWG files", "*.dwg;*.DWG"), ("All files", "*.*")))
        if not files:
            self.logger.info("用户取消了文件选择")
            return
        self.selected_files = list(files)
        self.working_dir = Path(self.selected_files[0]).parent
        self.logger.info(f"用户选择了 {len(files)} 个DWG文件：{files}")
        self.file_info_label.configure(text=f"已选择 {len(self.selected_files)} 个DWG | {self._count_files_text(self.working_dir)}")
        # 启用后续按钮
        self.btn_extract.configure(state="normal")
        self.btn_open_excel.configure(state="normal")
        self.btn_apply.configure(state="normal")

    def _select_folder(self):
        self.logger.info("用户开始选择工作文件夹")
        folder = filedialog.askdirectory(title="选择工作文件夹")
        if not folder:
            self.logger.info("用户取消了文件夹选择")
            return
        self.working_dir = Path(folder)
        self.selected_files = []
        self.logger.info(f"用户选择了工作文件夹：{folder}")
        self.file_info_label.configure(text=self._count_files_text(self.working_dir))
        # 允许提取/回填（如果用户已有DXF）
        self.btn_extract.configure(state="normal")
        self.btn_open_excel.configure(state="normal")
        self.btn_apply.configure(state="normal")

    # -------------------------- 按钮事件 --------------------------
    def _on_convert(self):
        self.logger.info("用户点击转换DWG至DXF按钮")
        workdir = self._ensure_working_dir()
        if not workdir:
            return
        if self.processing:
            self.logger.warning("转换操作被拒绝：已有任务在运行")
            messagebox.showinfo("提示", "当前已有任务在运行，请稍候…")
            return
        self.logger.info(f"开始转换操作，工作目录：{workdir}")
        threading.Thread(target=self._convert_worker, args=(workdir,), daemon=True).start()

    def _on_extract(self):
        self.logger.info("用户点击提取文本按钮")
        workdir = self._ensure_working_dir()
        if not workdir:
            return
        if self.processing:
            self.logger.warning("提取操作被拒绝：已有任务在运行")
            messagebox.showinfo("提示", "当前已有任务在运行，请稍候…")
            return
        self.logger.info(f"开始提取操作，工作目录：{workdir}")
        threading.Thread(target=self._extract_worker, args=(workdir,), daemon=True).start()

    def _on_open_excel(self):
        workdir = self._ensure_working_dir()
        if not workdir:
            return
        excel_path = workdir / 'extracted_texts.xlsx'
        if not excel_path.exists():
            messagebox.showwarning("未找到", f"未找到翻译表: {excel_path}\n请先执行‘提取文本’生成翻译表。")
            return
        try:
            if os.name == 'nt':
                os.startfile(str(excel_path))  # type: ignore
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(excel_path)])
            self._log(f"已尝试打开: {excel_path}")
        except Exception as e:
            self._log(f"无法打开Excel: {e}")

    def _on_apply(self):
        self.logger.info("用户点击应用翻译按钮")
        workdir = self._ensure_working_dir()
        if not workdir:
            return
        if self.processing:
            self.logger.warning("应用操作被拒绝：已有任务在运行")
            messagebox.showinfo("提示", "当前已有任务在运行，请稍候…")
            return
        self.logger.info(f"开始应用翻译操作，工作目录：{workdir}")
        threading.Thread(target=self._apply_worker, args=(workdir,), daemon=True).start()

    def _on_auto(self):
        self.logger.info("用户点击一键处理按钮")
        workdir = self._ensure_working_dir()
        if not workdir:
            return
        if self.processing:
            self.logger.warning("一键处理被拒绝：已有任务在运行")
            messagebox.showinfo("提示", "当前已有任务在运行，请稍候…")
            return
        self.logger.info(f"开始一键处理操作，工作目录：{workdir}")
        threading.Thread(target=self._auto_worker, args=(workdir,), daemon=True).start()

    # -------------------------- 工作线程 --------------------------
    def _convert_worker(self, workdir: Path):
        """转换DWG到DXF的工作线程 - 使用优化的AutoCAD转换器"""
        self.logger.info(f"开始DWG转换工作线程，工作目录：{workdir}")
        self._set_processing(True)
        self._safe_ui_call('update_progress', 0.05, "正在转换DWG → DXF …")
        
        try:
            # 导入优化的AutoCAD转换器
            try:
                from autocad_converter import AutoCADConverter
                self.logger.info("成功导入优化的AutoCAD转换器")
            except ImportError as e:
                self.logger.error(f"无法导入优化转换器: {e}")
                self._log("错误：无法导入AutoCAD转换器模块")
                return
            
            # 如果需要使用浩辰CAD转换器，请取消以下注释并注释掉上面的AutoCADConverter导入
            """
            try:
                from haochen_optimized_converter import OptimizedHaoChenCADConverter
                self.logger.info("成功导入优化的浩辰CAD转换器")
                # 注意：使用浩辰转换器时，需要将下面的实例化代码改为：
                # converter = OptimizedHaoChenCADConverter()
            except ImportError as e:
                self.logger.error(f"无法导入浩辰转换器: {e}")
                self._log("错误：无法导入浩辰转换器模块")
                return
            """

            
            # 扫描DWG文件
            dwg_files = list(workdir.glob('*.dwg')) + list(workdir.glob('*.DWG'))
            self.logger.info(f"扫描到 {len(dwg_files)} 个DWG文件")
            
            if not dwg_files:
                self.logger.warning("未找到DWG文件")
                self._log("未找到DWG文件，跳过转换。")
                return
            
            self._log(f"找到 {len(dwg_files)} 个DWG文件，开始转换…")
            
            # 创建输出目录
            output_dir = workdir / 'converted_dxf'
            output_dir.mkdir(exist_ok=True)
            
            # 初始化转换器
            converter = AutoCADConverter()
            # 如果使用浩辰转换器，请将上面一行改为：
            # converter = OptimizedHaoChenCADConverter()
            
            # 设置进度回调
            def progress_callback(current, total, message=""):
                if not self._cancel_requested:
                    progress = 0.05 + (current / total) * 0.3  # 转换占30%进度
                    self._safe_ui_call('update_progress', progress, f"转换中 ({current}/{total}) {message}")
            
            converter.set_progress_callback(progress_callback)
            
            # 连接CAD
            if not converter.connect_to_cad():
                self.logger.error("无法连接到AutoCAD")
                self._log("错误：无法连接到AutoCAD，请确保已安装AutoCAD")
                return
            
            self._log("[成功] 已连接到AutoCAD")
            
            # 转换文件
            converted_count = 0
            failed_count = 0
            
            for i, dwg_file in enumerate(dwg_files):
                if self._cancel_requested:
                    self.logger.info("用户取消转换")
                    break
                
                try:
                    # 更新进度
                    progress_callback(i, len(dwg_files), f"处理 {dwg_file.name}")
                    
                    # 打开DWG文件
                    if not converter.open_dwg_file(str(dwg_file)):
                        self.logger.error(f"无法打开文件: {dwg_file}")
                        self._log(f"[错误] 无法打开: {dwg_file.name}")
                        failed_count += 1
                        continue
                    
                    # 生成输出文件名，添加 'trans_DXF_' 前缀
                    output_file = output_dir / f"trans_DXF_{dwg_file.stem}.dxf"
                    
                    # 转换为DXF
                    if converter.convert_to_dxf_optimized(str(output_file)):
                        converted_count += 1
                        self.logger.info(f"转换成功: {dwg_file.name} -> {output_file.name}")
                        self._log(f"[成功] 转换成功: {dwg_file.name}")
                    else:
                        failed_count += 1
                        self.logger.error(f"转换失败: {dwg_file.name}")
                        self._log(f"[错误] 转换失败: {dwg_file.name}")
                    
                    # 关闭文档
                    converter.close_document()
                    
                except Exception as e:
                    failed_count += 1
                    self.logger.error(f"处理文件 {dwg_file} 时出错: {e}")
                    self._log(f"[错误] 处理 {dwg_file.name} 时出错: {e}")
            
            # 断开连接
            converter.disconnect()
            
            # 显示结果
            if converted_count > 0:
                self.logger.info(f"转换完成: 成功 {converted_count} 个，失败 {failed_count} 个")
                self._log(f"转换完成: 成功 {converted_count} 个，失败 {failed_count} 个。输出: {output_dir}")
            else:
                self.logger.warning("没有文件转换成功")
                self._log("没有文件转换成功，请检查CAD软件和文件格式")
                
        except Exception as e:
            self.logger.error(f"转换过程出错: {e}", exc_info=True)
            self._log(f"转换过程出错: {e}")
        finally:
            if not self._cancel_requested:
                self._safe_ui_call('update_progress', 0.4, "转换步骤完成")
            self._set_processing(False)
            self.logger.info("DWG转换工作线程结束")

    def _extract_worker(self, workdir: Path):
        """提取文本的工作线程"""
        self.logger.info(f"开始文本提取工作线程，工作目录：{workdir}")
        self._set_processing(True)
        self._safe_ui_call('update_progress', 0.45, "正在提取文本…")
        try:
            # 使用新的模块化提取脚本
            extract_script = self._get_script_path('extract_texts.py')
            self.logger.info(f"执行提取脚本：{extract_script}")
            code = self._stream_subprocess([sys.executable, extract_script, '-d', str(workdir), '-v'], cwd=workdir)
            if code != 0:
                self.logger.error(f"文本提取失败，退出码：{code}")
                self._log("提取文本失败，请检查DXF文件与依赖库。")
                return
            self.logger.info("文本提取成功完成")
        finally:
            if not self._cancel_requested:
                self._safe_ui_call('update_progress', 0.7, "文本提取完成")
            self._set_processing(False)
            self.logger.info("文本提取工作线程结束")

    def _apply_worker(self, workdir: Path):
        """应用翻译的工作线程"""
        self.logger.info(f"开始应用翻译工作线程，工作目录：{workdir}")
        self._set_processing(True)
        self._safe_ui_call('update_progress', 0.75, "正在回填翻译…")
        try:
            # 使用内置配置处理
            self.logger.info("使用内置配置处理")

            mode = self.trans_mode.get()
            reduce_val = self.font_reduce_var.get().strip()
            self.logger.info(f"翻译模式：{mode}，字体减少值：{reduce_val}")
            try:
                reduce_int = int(reduce_val)
            except ValueError:
                reduce_int = 2
                self.logger.warning(f"字体减少值无效：{reduce_val}，回退为2")
                self._log("字体减少值无效，已回退为 2")

            # 准备命令行参数
            font_name = self.font_menu.get()
            if font_name is None or font_name.strip() == "":
                font_name = "Times New Roman"  # 安全默认值
                self.logger.warning(f"字体名称为空，使用默认字体: {font_name}")
            mode_arg = 'replace' if mode == 'replace' else 'add'
            
            # 构建回填命令，包含字体和模式参数
            apply_script = self._get_script_path('回填.py')
            cmd_args = [
                sys.executable, apply_script,
                '--font', font_name,
                '--mode', mode_arg,
                '--font-size-reduction', str(reduce_int)
            ]
            
            self.logger.info(f"执行回填脚本：{apply_script}")
            self.logger.info(f"命令行参数：字体={font_name}, 模式={mode_arg}, 字体减少={reduce_int}")
            
            # 执行回填
            code = self._stream_subprocess(cmd_args, cwd=workdir)
            if code != 0:
                self.logger.error(f"回填失败，退出码：{code}")
                self._log("回填失败，请检查日志与翻译表。")
                return
            self.logger.info("回填成功完成")
        finally:
            if not self._cancel_requested:
                self._safe_ui_call('update_progress', 1.0, "回填完成 ✅")
            self._set_processing(False)
            self.logger.info("应用翻译工作线程结束")

    def _auto_worker(self, workdir: Path):
        """一键处理的工作线程"""
        self.logger.info(f"开始一键处理工作线程，工作目录：{workdir}")
        self._set_processing(True)
        self._safe_ui_call('update_progress', 0.05, "一键处理进行中…")
        try:
            # 转换
            self.logger.info("开始执行DWG转换步骤")
            self._convert_worker(workdir)
            # 提取
            self.logger.info("开始执行文本提取步骤")
            self._extract_worker(workdir)
            # 打开翻译表
            excel_path = workdir / 'extracted_texts.xlsx'
            self.logger.info(f"检查翻译表文件：{excel_path}")
            if excel_path.exists():
                try:
                    if os.name == 'nt':
                        os.startfile(str(excel_path))  # type: ignore
                    else:
                        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(excel_path)])
                    self.logger.info(f"成功打开翻译表：{excel_path}")
                    self._log(f"已尝试打开: {excel_path}")
                except Exception as e:
                    self.logger.error(f"无法自动打开Excel：{str(e)}", exc_info=True)
                    self._log(f"无法自动打开Excel: {e}")
            else:
                self.logger.warning("未找到翻译表文件")
                self._log("未找到翻译表，请确认'提取文本'步骤成功。")
            self.logger.info("一键处理完成，等待用户填写翻译")
            self._log("请在Excel中填写翻译后，点击'应用翻译'完成回填～")
        finally:
            if not self._cancel_requested:
                self._safe_ui_call('update_progress', 0.9, "一键处理完成（待回填）")
            self._set_processing(False)
            self.logger.info("一键处理工作线程结束")


if __name__ == "__main__":
    ctk.set_appearance_mode("System")  # 可选: "System"/"Light"/"Dark"
    ctk.set_default_color_theme("blue")
    app = CADTranslationApp()
    app.mainloop()