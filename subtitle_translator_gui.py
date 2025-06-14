import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QTextEdit, QComboBox, 
    QStatusBar, QToolBar, QMessageBox, QSplitter, QFrame,
    QDialog, QDialogButtonBox, QLineEdit, QSpinBox, QInputDialog, QStyle)
from PyQt6.QtCore import Qt, QSize, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction
import re
import json
import requests
import shutil
import subprocess
import tempfile
import shlex
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

class ApiTester(QThread):
    """Worker thread for testing API connection"""
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, api_url: str, api_key: str):
        super().__init__()
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
    
    def run(self):
        """Test the API connection"""
        try:
            # 根据填写的地址智能拼接 health 路径
            candidates = []
            base = self.api_url.rstrip('/')
            if base.endswith('/translate'):
                root = base.rsplit('/translate', 1)[0] or base  # 若用户直接填 /translate
                candidates.append(f"{root}/health")
                # 也尝试 /translate/health 以防万一
                candidates.append(f"{base}/health")
            else:
                candidates.append(f"{base}/health")
                # 备用：/translate/health
                candidates.append(f"{base}/translate/health")

            health_ok = False
            last_status = None
            for url in candidates:
                try:
                    response = requests.get(url, timeout=5)
                    last_status = response.status_code
                    if response.status_code == 200:
                        health_ok = True
                        break
                except requests.exceptions.RequestException:
                    continue

            if not health_ok:
                raise Exception(f"API returned status code: {last_status or 'N/A'}")

            # 如果需要验证 key，再用根路径 /models
            if self.api_key:
                # root 路径推导：去掉末尾的 '/translate'（若存在）
                root = base.rsplit('/translate', 1)[0] if base.endswith('/translate') else base
                models_url = f"{root}/models"
                response = requests.get(models_url, headers={"Authorization": self.api_key}, timeout=5)
                if response.status_code != 200:
                    raise Exception("API key verification failed")

            self.finished.emit(True, "Connection successful")
        except Exception as e:
            if isinstance(e, requests.exceptions.ConnectionError):
                self.finished.emit(False, "Failed to connect to API server")
            elif isinstance(e, requests.exceptions.Timeout):
                self.finished.emit(False, "Connection timed out")
            else:
                self.finished.emit(False, str(e))


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API设置")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # 创建表单布局
        layout = QVBoxLayout(self)
        
        # API URL
        url_layout = QHBoxLayout()
        url_label = QLabel("API地址:")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("例如: http://localhost:8989")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_edit)
        
        # API密钥
        key_layout = QHBoxLayout()
        key_label = QLabel("API密钥:")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("输入API密钥")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_edit)
        
        # 批量大小
        batch_layout = QHBoxLayout()
        batch_label = QLabel("批量大小:")
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 50)
        self.batch_spin.setValue(10)
        batch_layout.addWidget(batch_label)
        batch_layout.addWidget(self.batch_spin)
        
        # 测试连接按钮
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        
        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 按钮框
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        # 添加到主布局
        layout.addLayout(url_layout)
        layout.addLayout(key_layout)
        layout.addLayout(batch_layout)
        layout.addSpacing(10)
        layout.addWidget(self.test_btn)
        layout.addWidget(self.status_label)
        layout.addWidget(button_box)
        
        # 初始化状态
        self.update_status("", "black")
        
    def update_status(self, message: str, color: str):
        """Update status label with message and color"""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color};")
        
    def test_connection(self):
        """Test the API connection"""
        api_url = self.url_edit.text().strip()
        api_key = self.key_edit.text().strip()
        
        if not api_url:
            self.update_status("错误：请输入API地址", "red")
            return
            
        # 显示测试中状态
        self.update_status("正在测试连接...", "blue")
        self.test_btn.setEnabled(False)
        
        # 在后台线程中测试连接
        self.worker = ApiTester(api_url, api_key)
        self.worker.finished.connect(self.on_test_finished)
        self.worker.start()
    
    def on_test_finished(self, success: bool, message: str):
        """Handle test completion"""
        self.test_btn.setEnabled(True)
        if success:
            self.update_status("✓ 连接成功！", "green")
        else:
            self.update_status(f"✗ 连接失败: {message}", "red")
        
    def get_settings(self):
        return {
            "api_url": self.url_edit.text().strip().rstrip('/'),
            "api_key": self.key_edit.text().strip(),
            "batch_size": self.batch_spin.value()
        }
        
    def set_settings(self, api_url, api_key, batch_size):
        self.url_edit.setText(api_url)
        self.key_edit.setText(api_key)
        self.batch_spin.setValue(batch_size)

class SubtitleTranslator(QMainWindow):
    def _setup_logging(self):
        """设置日志记录系统"""
        try:
            # 创建日志目录
            log_dir = os.path.join(os.path.expanduser('~'), '.subtitle_translator', 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # 设置日志文件名（按日期）
            log_file = os.path.join(log_dir, f"subtitle_translator_{datetime.now().strftime('%Y%m%d')}.log")
            
            # 配置日志
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8'),
                    logging.StreamHandler()
                ]
            )
            
            self.logger = logging.getLogger('SubtitleTranslator')
            self.logger.info('=' * 50)
            self.logger.info('字幕翻译工具启动')
            self.logger.info(f'日志文件位置: {log_file}')
            
        except Exception as e:
            # 如果日志初始化失败，使用基本的日志记录
            logging.basicConfig(level=logging.ERROR)
            self.logger = logging.getLogger('SubtitleTranslator')
            self.logger.error(f'初始化日志系统失败: {str(e)}')
    
    def _log_debug(self, message: str):
        """记录调试信息"""
        if hasattr(self, 'logger'):
            self.logger.debug(message)
        else:
            print(f"[DEBUG] {message}")
    
    def _log_info(self, message: str):
        """记录一般信息"""
        if hasattr(self, 'logger'):
            self.logger.info(message)
        else:
            print(f"[INFO] {message}")
    
    def _log_error(self, message: str, exc_info=None):
        """记录错误信息"""
        if hasattr(self, 'logger'):
            self.logger.error(message, exc_info=exc_info)
        else:
            print(f"[ERROR] {message}")
            if exc_info:
                import traceback
                traceback.print_exc()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("字幕翻译工具")
        self.setWindowIcon(QIcon("icons/app.png"))
        self.setGeometry(100, 100, 1200, 800)
        
        # 检测 ffmpeg 可用性
        ffmpeg_path = r"D:\software\ffmpeg\bin\ffmpeg.exe"
        self.ffmpeg_available = os.path.exists(ffmpeg_path)
        if not self.ffmpeg_available:
            self._log_error(f"未在 {ffmpeg_path} 找到 ffmpeg，可执行字幕提取将不可用")
        else:
            self.ffmpeg_path = ffmpeg_path  # 保存完整路径
        # 初始化日志系统
        self._setup_logging()
        
        # 添加翻译API配置
        self.api_url = "http://localhost:8989/translate"
        self.api_headers = {"Authorization": "your_token_here"}  # 替换为你的token
        self.batch_size = 10  # 每批翻译的行数
        
        # 当前打开的文件路径
        self.current_file_path = ""
        
        # 创建线程池
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.futures = []
        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QToolBar {
                background-color: #f8f8f8;
                border: none;
                border-bottom: 1px solid #d0d0d0;
                spacing: 5px;
                padding: 5px;
            }
            QToolButton {
                padding: 5px;
                border-radius: 4px;
            }
            QToolButton:hover {
                background-color: #e0e0e0;
            }
            QTextEdit {
                font-family: 'Consolas', 'Microsoft YaHei', monospace;
                font-size: 12px;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 5px;
            }
            QStatusBar {
                background-color: #f8f8f8;
                border-top: 1px solid #d0d0d0;
            }
        """)
        
        self._create_actions()
        self._create_menu_bar()
        self._create_tool_bars()
        self._create_status_bar()
        self._create_central_widget()

          # 加载设置
        self.settings = self._load_settings()
        
        # 更新API配置
        self.api_url = self.settings.get("api_url", "http://localhost:8989")
        self.api_headers = {"Authorization": self.settings.get("api_key", "")}
        self.batch_size = self.settings.get("batch_size", 10)

    def _load_settings(self):
        """从文件加载设置"""
        settings_file = Path("translator_settings.json")
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _save_settings(self):
        """保存设置到文件"""
        settings_file = Path("translator_settings.json")
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {str(e)}")
            return False
    
    def show_settings_dialog(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self)
        dialog.set_settings(
            self.api_url,
            self.api_headers.get("Authorization", ""),
            self.batch_size
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dialog.get_settings()
            self.api_url = settings["api_url"].rstrip('/')
            self.api_headers = {"Authorization": settings["api_key"]}
            self.batch_size = settings["batch_size"]
            
            # 保存设置
            self.settings.update(settings)
            self._save_settings()
            
            QMessageBox.information(self, "提示", "设置已保存，将在下次翻译时生效")


    def translate_subtitle(self):
        """执行字幕翻译并更新界面"""
        source_text = self.original_text.toPlainText()
        if not source_text.strip():
            QMessageBox.warning(self, "警告", "没有要翻译的文本")
            return

        self.status_bar.showMessage("正在翻译...")
        QApplication.processEvents()
        self._log_info("开始翻译字幕")

        # 简单格式判定：ASS 文件含有 Dialogue 或 [Script Info]
        is_ass = False
        if self.current_file_path.lower().endswith('.ass'):
            is_ass = True
        elif 'Dialogue:' in source_text or '[Script Info]' in source_text:
            is_ass = True

        if is_ass:
            success, result = self._translate_ass(source_text, 'en', 'zh')
        else:
            success, result = self._translate_plain_text(source_text, 'en', 'zh')

        if success:
            self.translated_text.setPlainText(result)
            self.status_bar.showMessage("翻译完成")
            self._log_info("翻译完成")
        else:
            self.status_bar.showMessage("翻译失败")
            self._log_error(f"翻译失败: {result}")
            QMessageBox.critical(self, "翻译失败", result)
    
    def _do_translate(self, text: str, source_lang: str, target_lang: str) -> Tuple[bool, str]:
        """执行实际的翻译工作"""
        try:
            # 1. 解析字幕
            if text.strip().startswith('Dialogue:'):  # ASS格式
                return self._translate_ass(text, source_lang, target_lang)
            else:  # 假设是SRT或其他格式
                return self._translate_plain_text(text, source_lang, target_lang)
        except Exception as e:
            return False, f"翻译过程中出错: {str(e)}"
    
    def _translate_ass(self, text: str, source_lang: str, target_lang: str) -> Tuple[bool, str]:
        """翻译ASS格式字幕"""
        try:
            lines = text.split('\n')
            dialogues = []
            
            # 收集所有需要翻译的对话行
            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith('Dialogue:'):
                    # 解析对话行
                    parts = line.split(',', 9)
                    if len(parts) >= 10:
                        # 保存原始行和需要翻译的文本
                        dialogue_text = parts[9]
                        # 保留原始文本中的换行符
                        clean_text = re.sub(r'\{.*?\}', '', dialogue_text).replace('\\N', '\n')
                        if clean_text.strip():  # 只添加非空文本
                            dialogues.append((i, clean_text, dialogue_text))
            
            total = len(dialogues)
            if total == 0:
                return True, text  # 没有需要翻译的内容
                
            # 批量翻译
            for i in range(0, total, self.batch_size):
                batch = dialogues[i:i+self.batch_size]
                texts_to_translate = [item[1] for item in batch]
                
                try:
                    # 调用翻译API
                    api_base = self._ensure_translate_base()
                    api_url = f"{api_base}/batch"
                    headers = self.api_headers.copy()
                    headers['Content-Type'] = 'application/json; charset=utf-8'
                    
                    # 记录调试信息
                    self._log_debug(f'发送翻译请求到: {api_url}')
                    self._log_debug(f'待翻译文本: {texts_to_translate}')
                    
                    response = requests.post(
                        api_url,
                        json={
                            "from": source_lang,
                            "to": target_lang,
                            "texts": texts_to_translate
                        },
                        headers=headers,
                        timeout=30
                    )
                    response.raise_for_status()
                    
                    # 确保响应使用utf-8编码
                    response.encoding = 'utf-8'
                    response_text = response.text
                    self._log_debug(f'API响应: {response_text}')
                    
                    # 解析响应
                    try:
                        response_data = response.json()
                    except ValueError as e:
                        error_msg = f"解析API响应失败: {response_text[:200]}..."
                        self._log_error(error_msg)
                        return False, error_msg
                    
                    # 获取翻译结果
                    if 'results' in response_data:
                        results = response_data['results']
                    elif 'data' in response_data and 'results' in response_data['data']:
                        results = response_data['data']['results']
                    else:
                        error_msg = f"无效的API响应格式: {response_data}"
                        self._log_error(error_msg)
                        return False, error_msg
                    
                    # 更新翻译结果
                    for (idx, _, original_dialogue), translated in zip(batch, results):
                        if not translated:
                            continue
                            
                        translated = self._clean_translated(translated)
                        # 在原文后添加翻译，使用较小的字体和不同颜色
                        # 保留原始对话行的格式，只修改文本部分
                        parts = lines[idx].split(',', 9)
                        if len(parts) >= 10:
                            # 去除原文中的换行符
                            original_single = parts[9].replace('\\N', ' ').strip()
                            parts[9] = f"{original_single}\\N{{\\fnSimHei\\fs12\\c&H3CF1F7&}}{translated}"
                            lines[idx] = ','.join(parts)
                        
                except requests.exceptions.RequestException as e:
                    error_msg = f"API请求失败: {str(e)}"
                    self._log_error(error_msg, exc_info=True)
                    return False, error_msg
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    error_msg = f"处理翻译时出错: {str(e)}"
                    self._log_error(error_msg, exc_info=True)
                    return False, error_msg
                
                # 更新进度
                progress = min(100, int((i + len(batch)) / total * 100))
                self.status_bar.showMessage(f"正在翻译... {progress}%")
                QApplication.processEvents()
                
            return True, '\n'.join(lines)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = f"处理字幕时出错: {str(e)}"
            self._log_error(error_msg, exc_info=True)
            return False, error_msg
    
    def _translate_plain_text(self, text: str, source_lang: str, target_lang: str) -> Tuple[bool, str]:
        """翻译普通文本"""
        try:
            api_base = self._ensure_translate_base()
            response = requests.post(
                api_base,
                json={
                    "from": source_lang,
                    "to": target_lang,
                    "text": text
                },
                headers=self.api_headers,
                timeout=30
            )
            response.raise_for_status()
            raw = response.json().get("result", "")
            return True, self._clean_translated(raw)
        except Exception as e:
            return False, f"翻译失败: {str(e)}"
    
    def _on_translation_done(self, future):
        """翻译完成后的回调"""
        try:
            success, result = future.result()
            if success:
                self.translated_text.setPlainText(result)
                self.status_bar.showMessage("翻译完成")
            else:
                QMessageBox.critical(self, "错误", result)
                self.status_bar.showMessage("翻译失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理翻译结果时出错: {str(e)}")
            self.status_bar.showMessage("处理翻译结果时出错")
        finally:
            self.translate_action.setEnabled(True)
    
    def closeEvent(self, event):
        """窗口关闭时清理资源"""
        self.executor.shutdown(wait=False)
        super().closeEvent(event)
        
    def _create_actions(self):
        # 文件操作
        style = self.style()
        self.open_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "打开", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_file)
        
        self.save_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "保存", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self.save_file)
        
        self.exit_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_BrowserStop), "退出", self)
        self.exit_action.triggered.connect(self.close)
        
        # 翻译操作
        self.translate_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), "翻译", self)
        self.translate_action.setShortcut("F5")
        self.translate_action.triggered.connect(self.translate_subtitle)
        # 设置操作
        self.settings_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "设置", self)
        self.settings_action.triggered.connect(self.show_settings_dialog)
    
    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        
        # 文件菜单
        file_menu = menu_bar.addMenu("文件")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        
        # 编辑菜单
        edit_menu = menu_bar.addMenu("编辑")
        edit_menu.addAction("查找...")
        edit_menu.addAction("替换...")
        
        # 工具菜单
        tools_menu = menu_bar.addMenu("工具")
        tools_menu.addAction(self.translate_action)

        # 设置菜单
        settings_menu = menu_bar.addMenu("设置")
        settings_action = QAction("API设置...", self)
        settings_action.triggered.connect(self.show_settings_dialog)
        settings_menu.addAction(settings_action)
    
        # 帮助菜单
        help_menu = menu_bar.addMenu("帮助")
        help_menu.addAction("关于")
        
    def _create_tool_bars(self):
        # 主工具栏
        main_toolbar = self.addToolBar("主工具栏")
        main_toolbar.setIconSize(QSize(24, 24))
        main_toolbar.setMovable(False)
        
        # 添加工具按钮
        main_toolbar.addAction(self.open_action)
        main_toolbar.addAction(self.save_action)
        main_toolbar.addSeparator()
        main_toolbar.addAction(self.translate_action)
        
        # 添加语言选择
        self.source_lang = QComboBox()
        self.source_lang.addItems(["英语", "日语", "韩语", "自动检测"])
        self.source_lang.setCurrentText("英语")
        self.source_lang.setMinimumWidth(100)
        
        self.target_lang = QComboBox()
        self.target_lang.addItems(["中文", "英文", "日语", "韩语"])
        self.target_lang.setCurrentText("中文")
        self.target_lang.setMinimumWidth(100)
        
        main_toolbar.addWidget(QLabel("从:"))
        main_toolbar.addWidget(self.source_lang)
        main_toolbar.addWidget(QLabel("到:"))
        main_toolbar.addWidget(self.target_lang)
        
    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
    def _create_central_widget(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 原始字幕区域
        self.original_text = QTextEdit()
        self.original_text.setPlaceholderText("原始字幕将显示在这里...")
        
        # 翻译后区域
        self.translated_text = QTextEdit()
        self.translated_text.setPlaceholderText("翻译后的字幕将显示在这里...")
        
        # 添加文本区域到分割器
        splitter.addWidget(self.original_text)
        splitter.addWidget(self.translated_text)
        splitter.setSizes([self.height()//2, self.height()//2])
        
        # 底部状态信息
        bottom_bar = QFrame()
        bottom_bar.setFrameShape(QFrame.Shape.StyledPanel)
        bottom_bar.setMaximumHeight(30)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(5, 0, 5, 0)
        
        self.status_label = QLabel("就绪")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch()
        
        # 添加所有到主布局
        main_layout.addWidget(splitter)
        main_layout.addWidget(bottom_bar)
        
    def open_file(self):
        # 使用 QFileDialog 打开文件，支持字幕和视频

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开字幕文件",
            "",
            "字幕/视频文件 (*.srt *.ass *.ssa *.mkv *.mp4);;所有文件 (*.*)"
        )
        
        if file_path:
            # 判断是否为视频，通过扩展名
            ext = os.path.splitext(file_path)[1].lower()
            if ext in [".mkv", ".mp4"]:
                if not self.ffmpeg_available:
                    QMessageBox.critical(self, "错误", "未检测到 ffmpeg，无法提取视频字幕")
                    return
                success, content = self._extract_subtitle_from_video(file_path)
                if not success:
                    QMessageBox.critical(self, "错误", content)
                    return
            else:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"无法打开文件: {str(e)}")
                    return
                    
            # 更新UI
            self.original_text.setPlainText(content)
            self.status_bar.showMessage(f"已加载: {file_path}")
            # 记录并保存当前文件路径
            self.current_file_path = file_path
            self._log_info(f"已加载文件: {file_path}")
            
    
    def _extract_subtitle_from_video(self, video_path: str):
        """使用 ffmpeg 解析字幕流并提取文本轨道，返回 (success, content or error)"""
        try:
            # 使用完整路径调用 ffmpeg 解析轨道
            cmd = [self.ffmpeg_path, "-i", video_path]
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            _, err = proc.communicate()
            # 提取含 "Subtitle:" 且包含可识别格式
            tracks = []
            stream_pattern = re.compile(r"Stream #\d:(\d+)(?:\((.*?)\))?: Subtitle: (\w+)")
            for line in err.splitlines():
                m = stream_pattern.search(line)
                if m:
                    idx, lang, fmt = m.group(1), m.group(2) or 'und', m.group(3).lower()
                    if fmt in ["ass", "ssa", "subrip", "srt"]:
                        if fmt == "subrip":
                            fmt = "srt"
                        tracks.append((idx, lang, fmt, line.strip()))
            if not tracks:
                return False, "视频中未找到文本字幕轨道 (ass/srt)"
            # 让用户选择轨道
            choices = [f"#{idx} {lang} [{fmt}]" for idx, lang, fmt, _ in tracks]
            selected, ok = QInputDialog.getItem(self, "选择字幕轨道", "请选择要提取的字幕流：", choices, 0, False)
            if not ok:
                return False, "用户取消选择"
            sel_idx = choices.index(selected)
            stream_idx, lang, fmt, _ = tracks[sel_idx]
            # 提取到临时文件
            suffix = ".ass" if fmt == "ass" else ".srt"
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(tmp_fd)
            
            # 构建提取命令 - 使用正确的流选择语法
            extract_cmd = [
                self.ffmpeg_path,
                "-y",  # 覆盖输出文件
                "-i", video_path,
                "-map", f"0:{stream_idx}",  # 使用绝对流索引
                "-c:s", "copy",  # 直接复制字幕流，不重新编码
                "-f", "ass" if fmt == "ass" else "srt",  # 强制指定输出格式
                "-loglevel", "warning",  # 减少日志输出
                tmp_path
            ]
            
            self._log_info(f"执行提取命令: {' '.join(extract_cmd)}")
            
            try:
                # 运行提取命令，设置超时30秒
                extract = subprocess.run(
                    extract_cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=30
                )
                
                # 记录完整的错误输出以便调试
                if extract.stderr:
                    self._log_error(f"FFmpeg 错误输出: {extract.stderr}")
                
                if extract.returncode != 0:
                    error_msg = f"提取字幕失败 (返回码 {extract.returncode}): {extract.stderr[:200]}"
                    self._log_error(error_msg)
                    return False, error_msg
                
                # 读取提取的字幕内容
                with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                
                if not content.strip():
                    return False, "提取的字幕文件为空"
                
                self._log_info(f"成功提取 {len(content)} 字符的字幕内容")
                return True, content
                
            except subprocess.TimeoutExpired:
                error_msg = "提取字幕超时，请重试"
                self._log_error(error_msg)
                return False, error_msg
                
            except Exception as e:
                error_msg = f"提取字幕时发生错误: {str(e)}"
                self._log_error(error_msg)
                return False, error_msg
                
            finally:
                # 确保删除临时文件
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception as e:
                    self._log_error(f"删除临时文件失败: {str(e)}")
        except Exception as e:
            return False, f"解析字幕失败: {str(e)}"

    def save_file(self):
        if not hasattr(self, 'current_file_path') or not self.current_file_path:
            # 如果没有当前文件路径，使用默认的保存对话框
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存翻译文件",
                "",
                "字幕文件 (*.srt *.ass);;所有文件 (*.*)"
            )
        else:
            # 从当前文件路径生成新的文件名
            base_path, ext = os.path.splitext(self.current_file_path)
            
            # 如果是从视频文件提取的字幕，使用视频文件名
            if self.current_file_path.lower().endswith(('.mkv', '.mp4')):
                # 如果已经有_cn后缀，不再添加
                if not base_path.lower().endswith('_cn'):
                    base_path += '_cn'
                # 使用.ass作为默认扩展名
                default_path = base_path + '.ass'
            else:
                # 普通字幕文件，添加_cn
                default_path = base_path + '_cn' + ext
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存翻译文件",
                default_path,
                "字幕文件 (*.srt *.ass);;所有文件 (*.*)"
            )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.translated_text.toPlainText())
                self.status_bar.showMessage(f"已保存到: {file_path}")
                self._log_info(f"已保存翻译文件: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存文件失败: {str(e)}")
    
    def _ensure_translate_base(self) -> str:
        """确保 self.api_url 以 /translate 结尾，返回标准化基础地址"""
        base = self.api_url.rstrip('/')
        if not base.endswith('/translate'):
            base = f"{base}/translate"
        return base

    def _clean_translated(self, text: str) -> str:
        """解码 \\uXXXX 以及 \\n，返回单行文本"""
        # 解码形如 \u4e2d 的转义序列
        def _decode_match(match):
            try:
                return chr(int(match.group(1), 16))
            except Exception:
                return match.group(0)

        # 先处理双反斜杠开头的转义 \\uXXXX
        text = re.sub(r"\\\\u([0-9a-fA-F]{4})", _decode_match, text)
        # 再处理单反斜杠开头的转义 \uXXXX
        text = re.sub(r"\\u([0-9a-fA-F]{4})", _decode_match, text)

        # 移除换行及多余空格
        text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        # 压缩多余空格
        text = re.sub(r"\s+", ' ', text).strip()
        return text

def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    # 创建并显示主窗口
    translator = SubtitleTranslator()
    translator.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()