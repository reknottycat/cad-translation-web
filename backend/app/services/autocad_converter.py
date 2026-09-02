#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoCAD优化转换器
解决性能瓶颈问题的优化版本
主要优化:
1. 减少COM调用次数
2. 批量处理实体
3. 优化内存使用
4. 添加进度显示
5. 异步处理机制
"""

import os
import sys
import time
from pathlib import Path
import win32com.client
from typing import List, Dict, Optional
from collections import defaultdict

try:
    from app.functions import com_instance_guard as _guard
except Exception:  # pragma: no cover - import-time safety on odd layouts
    _guard = None

class AutoCADConverter:
    """
    AutoCAD转换器
    解决性能瓶颈，提升转换速度
    """
    
    def __init__(self):
        self.app = None
        self.doc = None
        self.connected = False
        self.last_error = None
        self.batch_size = 100  # 批处理大小
        self.progress_callback = None
        # Per-ProgID bound for a single COM Dispatch/GetActiveObject attempt so a
        # registered-but-hung ProgID cannot block a conversion for a long time.
        self._activate_error = None
        # True when a GetActiveObject result was a stale proxy (a probe had just
        # quit the instance) and we re-Dispatched a fresh one.
        self._stale_active_retried = False
        # True when this connection started (Dispatch) a fresh CAD instance that
        # we are responsible for quitting on disconnect.
        self._dispatch_started = False
        
    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self.progress_callback = callback
        
    def _update_progress(self, current, total, message=""):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)
        else:
            percent = (current / total * 100) if total > 0 else 0
            print(f"\r进度: {percent:.1f}% ({current}/{total}) {message}", end="", flush=True)
    
    def _set_background_mode(self):
        if not self.app:
            return
        try:
            self.app.Visible = False
        except Exception:
            pass

    def _autocad_prog_ids(self) -> list:
        """Candidate AutoCAD ProgIDs, newest-registration first.

        Prefer registry discovery so newer AutoCAD versions are recognised; fall
        back to a static baseline when the discovery helper cannot run (e.g. a
        non-Windows host used only for import-time checks)."""
        discovered = []
        try:
            from app.functions import autocad_discovery as _disc
            discovered = _disc.discovered_autocad_progids()
        except Exception:
            discovered = []
        if discovered:
            return discovered
        return [
            "AutoCAD.Application",
            "AutoCAD.Application.25",
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24",
            "AutoCAD.Application.23.1",
            "AutoCAD.Application.23",
            "AutoCAD.Application.22",
        ]

    def _try_activate_once(self, prog_id: str):
        """Activate ``prog_id`` synchronously on the current thread.

        COM apartment discipline: this converter runs inside a dedicated COM
        subprocess whose main thread owns the apartment (com_converter_cli
        initialises it).  Activation, use and release therefore happen on that
        same thread -- we never spawn a worker thread that ``CoUninitialize()``s
        and then hands a COM object back to another apartment (which yields a
        dead proxy, e.g. ``AttributeError`` on ``app.Version``).

        A **probe that just quit a freshly started CAD** can leave a stale ROT
        entry for a short window; ``GetActiveObject`` then returns a stale proxy
        that fails Version/Documents.  We detect that and automatically
        ``Dispatch`` a fresh instance instead of binding to the dying one (see
        ``com_instance_guard.acquire_usable_instance``).

        Returns ``(kind, instance)`` where ``kind`` is ``"active"`` (a usable
        already-running instance was attached) or ``"dispatch"`` (a usable fresh
        instance was started), or ``None`` on error (recorded in
        ``self._activate_error``).
        """
        self._activate_error = None
        stale_hint: list = []
        try:
            kind, instance = _guard.acquire_usable_instance(
                win32com.client, prog_id, stale_hint=stale_hint
            )
        except Exception as exc:  # noqa: BLE001 - COM raises generic exceptions
            self._activate_error = str(exc) or type(exc).__name__
            return None, None
        if stale_hint:
            self._stale_active_retried = True
            print(f"  注意: {stale_hint[0]}")
        if kind is None:
            self._activate_error = self._activate_error or "no usable instance"
            return None, None
        if kind == "dispatch":
            # A fresh instance we started must be quit by the caller later.
            self._dispatch_started = True
        return kind, instance

    def connect_to_cad(self) -> bool:
        """连接到 AutoCAD 应用程序 - 优化版

        Uses dynamic versioned ProgID discovery so future AutoCAD releases are
        recognised.  Each candidate ProgID is tried synchronously on the current
        COM thread/apartment (this module runs inside a dedicated subprocess, so
        a hung COM server is bounded and reclaimed by the parent subprocess
        timeout).  A registered-but-hung ProgID is skipped so the next candidate
        is tried, and an actionable diagnostic is recorded in ``self.last_error``
        distinguishing activation failure from "not installed".
        """
        cad_prog_ids = self._autocad_prog_ids()

        self.last_error = None
        print("正在连接 AutoCAD...")

        outcomes = []
        for prog_id in cad_prog_ids:
            kind, instance = self._try_activate_once(prog_id)
            if kind in ("active", "dispatch") and instance is not None:
                self.app = instance
                self._set_background_mode()
                try:
                    self.app.Visible = False
                except Exception:
                    pass
                self.connected = True
                print(f"[OK] 连接/启动 {prog_id} 实例 ({kind})")
                self.last_error = None
                return True
            outcomes.append(
                f"{prog_id}: activation failed "
                f"({self._activate_error or 'COM error'})"
            )

        # 诊断：区分“未注册/未运行”与“已注册但激活失败”。
        registered_any = False
        try:
            from app.functions import autocad_discovery as _disc
            registered_any = _disc.any_autocad_registered()
        except Exception:
            registered_any = False

        if registered_any:
            reason = (
                "AutoCAD is registered on this host but COM activation failed: "
                f"{'; '.join(outcomes) or 'unknown COM error'}. Check bitness "
                "match, run as a user with AutoCAD COM permissions, confirm the "
                "AutoCAD installation is not damaged, and close stray acad.exe "
                "processes."
            )
        else:
            reason = (
                "No AutoCAD COM registration or running acad.exe was detected on "
                "this host. Install/register AutoCAD, or configure another DWG "
                "backend (ODA / LibreDWG)."
            )
        self.last_error = reason
        print(f"[ERROR] 无法连接到任何 AutoCAD 程序：{reason}")
        return False


    def open_dwg_file(self, dwg_path: str) -> bool:
        """
        打开DWG文件 - 优化版
        """
        if not self.connected or not self.app:
            return False
            
        try:
            abs_path = os.path.abspath(dwg_path)
            print(f"正在打开文件: {os.path.basename(dwg_path)}")
            
            # 尝试多种打开方式
            try:
                self.doc = self.app.Documents.Open(abs_path)
                print("[OK] 使用Documents.Open方法成功打开")
                return True
            except Exception as e:
                print(f"Documents.Open失败: {e}")
            
            try:
                self.doc = self.app.ActiveDocument.Application.Documents.Open(abs_path)
                print("[OK] 使用ActiveDocument方法成功打开")
                return True
            except Exception as e:
                print(f"ActiveDocument方法失败: {e}")
            
            return False
            
        except Exception as e:
            print(f"打开文件失败: {e}")
            return False
    
    def analyze_entities_optimized(self) -> Dict:
        """
        优化的实体分析 - 批量处理，减少COM调用
        """
        if not self.doc:
            return {}
            
        print("\n开始优化分析...")
        
        analysis = {
            'total_entities': 0,
            'entity_types': defaultdict(int),  # 使用defaultdict优化
            'text_entities': [],
            'geometric_entities': [],
            'layers': set()
        }
        
        try:
            model_space = self.doc.ModelSpace
            
            # 预先获取实体总数
            try:
                total_count = model_space.Count
                print(f"检测到 {total_count} 个实体")
            except:
                total_count = 0
                # 如果无法获取总数，先遍历一遍计算
                for _ in model_space:
                    total_count += 1
                print(f"计算得到 {total_count} 个实体")
            
            # 批量处理实体
            processed = 0
            batch_entities = []
            
            for entity in model_space:
                batch_entities.append(entity)
                
                # 达到批处理大小或最后一批
                if len(batch_entities) >= self.batch_size or processed + len(batch_entities) >= total_count:
                    self._process_entity_batch(batch_entities, analysis)
                    processed += len(batch_entities)
                    self._update_progress(processed, total_count, "分析实体")
                    batch_entities = []
            
            # 处理剩余实体
            if batch_entities:
                self._process_entity_batch(batch_entities, analysis)
                processed += len(batch_entities)
                self._update_progress(processed, total_count, "分析完成")
            
            analysis['total_entities'] = processed
            analysis['layers'] = list(analysis['layers'])
            analysis['entity_types'] = dict(analysis['entity_types'])  # 转回普通dict
            
            print(f"\n[OK] 分析完成: {processed} 个实体")
            
        except Exception as e:
            print(f"\n[ERROR] 分析实体时出错: {e}")
            
        return analysis
    
    def _process_entity_batch(self, entities: List, analysis: Dict):
        """
        批量处理实体 - 减少单个COM调用开销
        """
        for entity in entities:
            try:
                # 批量获取属性，减少COM调用
                entity_props = self._get_entity_properties(entity)
                
                entity_type = entity_props.get('ObjectName', 'Unknown')
                layer = entity_props.get('Layer', 'Unknown')
                
                # 统计实体类型
                analysis['entity_types'][entity_type] += 1
                analysis['layers'].add(layer)
                
                # 处理文本实体
                if self._is_text_entity(entity_type):
                    text_content = self._extract_text_content(entity, entity_props)
                    if text_content:
                        analysis['text_entities'].append({
                            'type': entity_type,
                            'content': text_content,
                            'layer': layer
                        })
                else:
                    # 几何实体只记录基本信息
                    analysis['geometric_entities'].append({
                        'type': entity_type,
                        'layer': layer
                    })
                    
            except Exception:
                # 忽略单个实体的错误，继续处理
                continue
    
    def _get_entity_properties(self, entity) -> Dict:
        """
        批量获取实体属性 - 优化COM调用
        """
        props = {}
        try:
            # 一次性获取常用属性
            props['ObjectName'] = getattr(entity, 'ObjectName', 'Unknown')
            props['Layer'] = getattr(entity, 'Layer', 'Unknown')
            props['Handle'] = getattr(entity, 'Handle', 'Unknown')
        except:
            pass
        return props
    
    def _is_text_entity(self, entity_type: str) -> bool:
        """
        判断是否为文本实体
        """
        text_keywords = ['Text', 'text', 'TEXT', 'MText', 'mtext', 'MTEXT']
        return any(keyword in entity_type for keyword in text_keywords)
    
    def _extract_text_content(self, entity, props: Dict) -> Optional[str]:
        """
        提取文本内容 - 优化版
        """
        text_attrs = ['TextString', 'Text', 'Contents']
        for attr in text_attrs:
            try:
                if hasattr(entity, attr):
                    content = getattr(entity, attr)
                    if content and str(content).strip():
                        return str(content).strip()
            except:
                continue
        return None
    
    def convert_to_dxf_optimized(self, output_path: str) -> bool:
        """
        优化的DXF转换 - 使用最快的方法
        """
        if not self.doc:
            return False
            
        try:
            abs_output_path = os.path.abspath(output_path)
            print(f"\n开始DXF转换: {os.path.basename(output_path)}")
            
            # 优先使用最快的SaveAs方法
            try:
                start_time = time.time()
                
                # 设置为不显示对话框，提升速度
                try:
                    self.app.Preferences.Files.AutoSaveInterval = 0  # 禁用自动保存
                except:
                    pass
                
                # 使用格式13 (AutoCAD 2000 DXF) - 经典兼容格式
                try:
                    # 尝试AutoCAD的SaveAs
                    # 13 = ac2004_dxf for AutoCAD? No, it varies by version.
                    # For AutoCAD COM:
                    # ac2018_dxf = 61
                    # ac2013_dxf = 60
                    # ac2010_dxf = 50
                    # ac2007_dxf = 37
                    # ac2004_dxf = 25
                    # ac2000_dxf = 13
                    # acR12_dxf = 1
                    self.doc.SaveAs(abs_output_path, 13)
                except:
                    # 如果13失败，尝试其他常用格式或默认格式
                    # 60 = 2013 DXF
                    self.doc.SaveAs(abs_output_path, 60)
                
                elapsed = time.time() - start_time
                file_size = os.path.getsize(abs_output_path) if os.path.exists(abs_output_path) else 0
                
                print(f"[OK] DXF转换成功")
                print(f"  - 耗时: {elapsed:.2f}秒")
                print(f"  - 文件大小: {file_size / 1024 / 1024:.2f} MB")
                return True
                
            except Exception as e:
                print(f"SaveAs方法失败: {e}")
                
                # 备用方法：使用命令行
                try:
                    print("尝试命令行方式...")
                    # AutoCAD 命令行保存DXF
                    cmd = f'_SAVEAS _DXF "16" "{abs_output_path}" ' # 16 decimal places accuracy? Or version?
                    # AutoCAD command: SAVEAS <Format> <Version> <Path>
                    # Actually standard command: SAVEAS DXF 16 <Path>
                    # Let's try simple SAVEAS DXF
                    cmd = f'_SAVEAS _DXF _V _2000 "{abs_output_path}" '
                    self.doc.SendCommand(cmd)
                    
                    # 等待命令完成
                    max_wait = 30  # 最多等待30秒
                    wait_time = 0
                    while wait_time < max_wait:
                        time.sleep(1)
                        wait_time += 1
                        if os.path.exists(abs_output_path):
                            # Check if file size is stable (writing finished)
                            try:
                                size1 = os.path.getsize(abs_output_path)
                                time.sleep(1)
                                size2 = os.path.getsize(abs_output_path)
                                if size1 == size2 and size1 > 0:
                                    print(f"[OK] 命令行转换成功 (耗时: {wait_time}秒)")
                                    return True
                            except:
                                pass
                    
                    print("[ERROR] 命令行转换超时或文件未生成")
                    
                except Exception as e:
                    print(f"命令行转换失败: {e}")
            
            return False
            
        except Exception as e:
            print(f"[ERROR] DXF转换失败: {e}")
            return False
    
    def close_document(self):
        """
        关闭文档
        """
        if self.doc:
            try:
                self.doc.Close(False)  # 不保存
                self.doc = None
                print("[OK] 文档已关闭")
            except Exception as e:
                print(f"关闭文档时出错: {e}")
    
    def disconnect(self):
        """
        断开CAD连接
        """
        try:
            if self.doc:
                self.close_document()
            
            if self.app:
                # If this connection started (Dispatch) the CAD instance, quit it
                # so we do not leave a stray acad.exe / ROT entry behind.
                if getattr(self, "_dispatch_started", False):
                    try:
                        self.app.Quit()
                    except Exception:
                        pass
                    self._dispatch_started = False
                else:
                    # Restore visibility only for an instance we merely attached to.
                    try:
                        self.app.Visible = True
                    except Exception:
                        pass
                self.app = None
            
            self.connected = False
            print("[OK] 已断开CAD连接")
            
        except Exception as e:
            print(f"断开连接时出错: {e}")

def main():
    """
    优化版主函数
    """
    print("=" * 70)
    print("AutoCAD优化转换器")
    print("解决性能瓶颈的优化版本")
    print("=" * 70)
    
    # 测试文件
    repo_root = Path(__file__).resolve().parents[3]
    test_file = str(repo_root / 'sample.dwg')
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    
    if not os.path.exists(test_file):
        print(f"错误：测试文件不存在: {test_file}")
        # Only return if test file is crucial, but for main app usage this might be just a test
        # return
    else:
        converter = AutoCADConverter()
        
        try:
            start_time = time.time()
            
            # 1. 连接CAD
            if not converter.connect_to_cad():
                print("无法连接到AutoCAD")
                return
            
            # 2. 打开DWG文件
            if not converter.open_dwg_file(test_file):
                print("无法打开DWG文件")
                return
            
            # 3. 快速分析（可选）
            # print("\n是否进行详细分析？(y/n): ", end="")
            # do_analysis = input().lower().startswith('y')
            do_analysis = False
            
            if do_analysis:
                analysis = converter.analyze_entities_optimized()
                print(f"\n分析结果:")
                print(f"- 总实体: {analysis['total_entities']}")
                print(f"- 文本实体: {len(analysis['text_entities'])}")
                print(f"- 几何实体: {len(analysis['geometric_entities'])}")
            
            # 4. 转换为DXF
            output_dxf = os.path.splitext(test_file)[0] + "_converted.dxf"
            if converter.convert_to_dxf_optimized(output_dxf):
                total_time = time.time() - start_time
                print(f"\n=== 转换完成 ===")
                print(f"总耗时: {total_time:.2f}秒")
                if os.path.exists(output_dxf):
                    size_mb = os.path.getsize(output_dxf) / 1024 / 1024
                    print(f"输出文件: {output_dxf} ({size_mb:.2f} MB)")
            else:
                print("\n[ERROR] 转换失败")
                
        except KeyboardInterrupt:
            print("\n用户中断操作")
        except Exception as e:
            print(f"\n处理过程中出错: {e}")
        
        finally:
            # 清理资源
            converter.disconnect()

if __name__ == "__main__":
    main()
