import sys
import os
import re
import subprocess
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QTextEdit, QPushButton, QLabel, QLineEdit, QGridLayout, 
                               QMessageBox, QScrollArea, QCheckBox, QDialog, QDialogButtonBox)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QColor, QPalette, QTextOption, QIcon
import json

# Get the base directory for bundled files
base_dir = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys, '_MEIPASS'):
    base_dir = sys._MEIPASS

class PingThread(QThread):
    """PING测试线程类"""
    result_signal = Signal(str, dict)  # IP地址, 测试结果
    start_signal = Signal(str)  # 开始测试信号
    output_signal = Signal(str, str)  # IP地址, 输出内容
    progress_signal = Signal(str, int, int)  # IP地址, 当前进度, 总次数
    
    def __init__(self, ip, count=10, continuous=False):
        super().__init__()
        self.ip = ip
        self.count = count
        self.continuous = continuous
        self.is_running = True
    
    def run(self):
        """执行PING测试"""
        if not self.is_valid_ip(self.ip):
            self.result_signal.emit(self.ip, {
                'status': 'invalid',
                'latency': 0,
                'packet_loss': 0,
                'message': '无效IP格式'
            })
            return

        if not self.is_running:
            self.result_signal.emit(self.ip, {
                'status': 'stopped',
                'latency': 0,
                'packet_loss': 0,
                'message': '测试终止'
            })
            return

        # 发出开始测试信号
        self.start_signal.emit(self.ip)

        try:
            # 根据操作系统和模式生成不同的PING命令
            if platform.system() == 'Windows':
                if self.continuous:
                    cmd = ['ping', '-t', self.ip]
                else:
                    cmd = ['ping', '-n', str(self.count), self.ip]
            else:  # Linux/macOS
                if self.continuous:
                    cmd = ['ping', self.ip]
                else:
                    cmd = ['ping', '-c', str(self.count), self.ip]

            if self.continuous:
                # 持续PING模式，实时读取输出
                # 添加creationflags参数，确保在Windows窗口模式下不显示CMD窗口
                if platform.system() == 'Windows':
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                              universal_newlines=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                              bufsize=1)  # 添加bufsize=1参数，禁用缓冲
                else:
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                              universal_newlines=True, bufsize=1)  # 添加bufsize=1参数，禁用缓冲
                
                for line in iter(process.stdout.readline, ''):
                    if not self.is_running:
                        process.terminate()
                        self.result_signal.emit(self.ip, {
                            'status': 'stopped',
                            'latency': 0,
                            'packet_loss': 0,
                            'message': '测试终止'
                        })
                        return
                    
                    # 发送实时输出信号（只在持续PING模式下）
                    self.output_signal.emit(self.ip, line.strip())
                
                process.wait()
                self.result_signal.emit(self.ip, {
                    'status': 'stopped',
                    'latency': 0,
                    'packet_loss': 0,
                    'message': '测试终止'
                })
            else:
                # 普通模式，一次性执行
                # 添加creationflags参数，确保在Windows窗口模式下不显示CMD窗口
                if platform.system() == 'Windows':
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                              universal_newlines=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                              bufsize=1)  # 添加bufsize=1参数，禁用缓冲
                else:
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                              universal_newlines=True, bufsize=1)  # 添加bufsize=1参数，禁用缓冲
                
                # 实时读取输出并更新进度
                output = []
                current_count = 0
                for line in iter(process.stdout.readline, ''):
                    if not self.is_running:
                        process.terminate()
                        self.result_signal.emit(self.ip, {
                            'status': 'stopped',
                            'latency': 0,
                            'packet_loss': 0,
                            'message': '测试终止'
                        })
                        return
                    
                    output.append(line)
                    
                    # 检测是否完成一次ping
                    if platform.system() == 'Windows':
                        # 兼容中文和英文 Windows 系统
                        if ('来自' in line and '的回复' in line) or ('Reply from' in line):
                            current_count += 1
                            self.progress_signal.emit(self.ip, current_count, self.count)
                    else:
                        if 'bytes from' in line:
                            current_count += 1
                            self.progress_signal.emit(self.ip, current_count, self.count)
                
                process.wait()
                output = ''.join(output)
                
                if not self.is_running:
                    self.result_signal.emit(self.ip, {
                        'status': 'stopped',
                        'latency': 0,
                        'packet_loss': 0,
                        'message': '测试终止'
                    })
                    return

                # 解析PING结果
                result = self.parse_ping_output(output)
                self.result_signal.emit(self.ip, result)

        except subprocess.TimeoutExpired:
            self.result_signal.emit(self.ip, {
                'status': 'timeout',
                'latency': 0,
                'packet_loss': 100,
                'message': '测试超时'
            })
        except subprocess.CalledProcessError as e:
            self.result_signal.emit(self.ip, {
                'status': 'error',
                'latency': 0,
                'packet_loss': 100,
                'message': '网络异常'
            })
    
    def stop(self):
        """停止测试"""
        self.is_running = False
    
    def is_valid_ip(self, ip):
        """验证IP地址或域名格式"""
        # 检查是否为IP地址
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ip_pattern, ip):
            parts = ip.split('.')
            for part in parts:
                if not 0 <= int(part) <= 255:
                    return False
            return True
        
        # 检查是否为域名
        domain_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9](\.[a-zA-Z]{2,})+$'
        if re.match(domain_pattern, ip):
            return True
        
        return False
    
    def parse_ping_output(self, output):
        """解析PING命令输出"""
        if platform.system() == 'Windows':
            # Windows格式解析
            if '请求超时' in output or '无法访问目标主机' in output:
                return {
                    'status': 'error',
                    'latency': 0,
                    'min_latency': 0,
                    'max_latency': 0,
                    'packet_loss': 100,
                    'message': '连接失败'
                }
            
            # 提取延迟
            latency_match = re.search(r'平均 = (\d+)ms', output)
            if latency_match:
                latency = int(latency_match.group(1))
            else:
                latency = 0
            
            # 提取最小和最大延迟
            min_max_match = re.search(r'最短 = (\d+)ms，最长 = (\d+)ms', output)
            if min_max_match:
                min_latency = int(min_max_match.group(1))
                max_latency = int(min_max_match.group(2))
            else:
                min_latency = 0
                max_latency = 0
            
            # 提取丢包率
            packet_loss_match = re.search(r'丢失 = (\d+)', output)
            if packet_loss_match:
                packet_loss = int(packet_loss_match.group(1))
            else:
                packet_loss = 0
                
        else:
            # Linux/macOS格式解析
            if '100% packet loss' in output:
                return {
                    'status': 'error',
                    'latency': 0,
                    'min_latency': 0,
                    'max_latency': 0,
                    'packet_loss': 100,
                    'message': '连接失败'
                }
            
            # 提取延迟
            latency_match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', output)
            if latency_match:
                latency = float(latency_match.group(1))
            else:
                latency = 0
            
            # 提取最小和最大延迟
            min_max_match = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/[\d.]+/([\d.]+)/', output)
            if min_max_match:
                min_latency = float(min_max_match.group(1))
                max_latency = float(min_max_match.group(2))
            else:
                min_latency = 0
                max_latency = 0
            
            # 提取丢包率
            packet_loss_match = re.search(r'(\d+)% packet loss', output)
            if packet_loss_match:
                packet_loss = int(packet_loss_match.group(1))
            else:
                packet_loss = 0
        
        if packet_loss == 100:
            return {
                'status': 'error',
                'latency': latency,
                'min_latency': min_latency,
                'max_latency': max_latency,
                'packet_loss': packet_loss,
                'message': '连接失败'
            }
        else:
            return {
                'status': 'success',
                'latency': latency,
                'min_latency': min_latency,
                'max_latency': max_latency,
                'packet_loss': packet_loss,
                'message': '连接正常'
            }

class ConfigDialog(QDialog):
    """配置对话框类"""
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle('配置')
        self.setGeometry(200, 200, 400, 300)
        
        layout = QVBoxLayout(self)
        
        # 结果展示布局
        layout_group = QWidget()
        layout_layout = QVBoxLayout(layout_group)
        layout_layout.setSpacing(8)
        layout_layout.setContentsMargins(8, 8, 8, 8)
        layout_group.setStyleSheet('''
            QWidget {
                background-color: #ffffff;
                border-radius: 6px;
                border: 1px solid #e9ecef;
            }
        ''')
        
        layout_label = QLabel('结果展示布局')
        layout_label.setFont(QFont('Arial', 10, QFont.Bold))
        layout_label.setStyleSheet('color: #495057; margin-bottom: 3px;')
        layout_layout.addWidget(layout_label)
        
        rows_cols_layout = QHBoxLayout()
        rows_cols_layout.setSpacing(15)
        
        rows_group = QWidget()
        rows_layout = QVBoxLayout(rows_group)
        rows_layout.setSpacing(2)
        
        rows_label = QLabel('行数:')
        rows_label.setFont(QFont('Arial', 11, QFont.Bold))
        rows_label.setStyleSheet('color: #000000; font-weight: bold;')
        rows_layout.addWidget(rows_label)
        
        self.rows_input = QLineEdit(str(config.get('rows', 5)))
        self.rows_input.setPlaceholderText('行数')
        self.rows_input.setFixedWidth(90)
        self.rows_input.setFixedHeight(24)
        self.rows_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        rows_layout.addWidget(self.rows_input)
        
        cols_group = QWidget()
        cols_layout = QVBoxLayout(cols_group)
        cols_layout.setSpacing(2)
        
        cols_label = QLabel('列数:')
        cols_label.setFont(QFont('Arial', 11, QFont.Bold))
        cols_label.setStyleSheet('color: #000000; font-weight: bold;')
        cols_layout.addWidget(cols_label)
        
        self.cols_input = QLineEdit(str(config.get('cols', 5)))
        self.cols_input.setPlaceholderText('列数')
        self.cols_input.setFixedWidth(90)
        self.cols_input.setFixedHeight(24)
        self.cols_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        cols_layout.addWidget(self.cols_input)
        
        rows_cols_layout.addWidget(rows_group)
        rows_cols_layout.addWidget(cols_group)
        layout_layout.addLayout(rows_cols_layout)
        
        # 界面大小设置
        window_size_group = QWidget()
        window_size_layout = QVBoxLayout(window_size_group)
        window_size_layout.setSpacing(8)
        window_size_layout.setContentsMargins(8, 8, 8, 8)
        window_size_group.setStyleSheet('''
            QWidget {
                background-color: #ffffff;
                border-radius: 6px;
                border: 1px solid #e9ecef;
            }
        ''')
        
        window_size_label = QLabel('界面大小')
        window_size_label.setFont(QFont('Arial', 10, QFont.Bold))
        window_size_label.setStyleSheet('color: #495057; margin-bottom: 3px;')
        window_size_layout.addWidget(window_size_label)
        
        width_height_layout = QHBoxLayout()
        width_height_layout.setSpacing(15)
        
        width_group = QWidget()
        width_layout = QVBoxLayout(width_group)
        width_layout.setSpacing(2)
        
        width_label = QLabel('宽度:')
        width_label.setFont(QFont('Arial', 11, QFont.Bold))
        width_label.setStyleSheet('color: #000000; font-weight: bold;')
        width_layout.addWidget(width_label)
        
        self.width_input = QLineEdit(str(config.get('width', 1600)))
        self.width_input.setPlaceholderText('宽度')
        self.width_input.setFixedWidth(90)
        self.width_input.setFixedHeight(24)
        self.width_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        width_layout.addWidget(self.width_input)
        
        height_group = QWidget()
        height_layout = QVBoxLayout(height_group)
        height_layout.setSpacing(2)
        
        height_label = QLabel('高度:')
        height_label.setFont(QFont('Arial', 11, QFont.Bold))
        height_label.setStyleSheet('color: #000000; font-weight: bold;')
        height_layout.addWidget(height_label)
        
        self.height_input = QLineEdit(str(config.get('height', 700)))
        self.height_input.setPlaceholderText('高度')
        self.height_input.setFixedWidth(90)
        self.height_input.setFixedHeight(24)
        self.height_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        height_layout.addWidget(self.height_input)
        
        width_height_layout.addWidget(width_group)
        width_height_layout.addWidget(height_group)
        window_size_layout.addLayout(width_height_layout)
        
        # 添加到主布局
        layout.addWidget(layout_group)
        layout.addWidget(window_size_group)
        
        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_config(self):
        """获取配置"""
        try:
            rows = int(self.rows_input.text())
            cols = int(self.cols_input.text())
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            
            if rows <= 0 or cols <= 0:
                raise ValueError('行数和列数必须为正整数')
            
            if width <= 0 or height <= 0:
                raise ValueError('宽度和高度必须为正整数')
            
            return {
                'rows': rows,
                'cols': cols,
                'width': width,
                'height': height
            }
        except ValueError as e:
            QMessageBox.warning(self, '输入错误', str(e))
            return None

class PingTestApp(QMainWindow):
    """主应用程序类"""
    def __init__(self):
        super().__init__()
        # 配置选项
        self.default_ping_count = 10  # 默认PING次数，改为10次
        self.default_window_width = 1600  # 默认窗口宽度
        self.default_window_height = 700  # 默认窗口高度
        self.default_rows = 5  # 默认结果展示行数
        self.default_cols = 5  # 默认结果展示列数
        
        # 颜色配置
        self.color_success = QColor(0, 128, 0)  # 成功绿色
        self.color_error = QColor(255, 0, 0)  # 错误红色
        self.color_running = QColor(255, 165, 0)  # 运行中橙色
        
        # 数据文件路径
        self.ip_file = os.path.join(base_dir, 'saved_ips.json')
        self.config_file = os.path.join(base_dir, 'config.json')
        
        # 统一输出窗口
        self.output_window = None
        
        # 设置窗口图标
        icon_path = os.path.join(base_dir, 'image.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.init_ui()
        self.threads = {}  # 存储运行中的线程
        self.load_saved_ips()  # 加载保存的IP地址
        self.load_config()  # 加载配置
        
    def get_local_ip(self):
        """获取本机IP地址"""
        import socket
        try:
            # 创建一个套接字连接
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 连接到一个外部服务器
            s.connect(('8.8.8.8', 80))
            # 获取本地IP地址
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "无法获取本机IP"
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle('IP网络连接速度测试工具')
        self.setGeometry(100, 100, self.default_window_width, self.default_window_height)  # 使用默认窗口大小
        
        # 设置全局样式，增加边框加黑效果
        self.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 4px;
            }
            QGroupBox {
                border: 1px solid #000000;
                border-radius: 6px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QPushButton {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:hover {
                border: 1px solid #000000;
                background-color: #e0e0e0;
            }
            QLineEdit {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px;
            }
            QTextEdit {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px;
            }
            QScrollArea {
                border: 1px solid #000000;
                border-radius: 4px;
            }
        ''')
        
        # 主布局 - 两列水平布局
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        self.setCentralWidget(central_widget)
        
        # 1. 第一列：IP输入区
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # 1.1 IP输入区
        ip_input_group = QWidget()
        ip_input_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 8px;
                background-color: #f8f9fa;
            }
        ''')
        ip_input_layout = QVBoxLayout(ip_input_group)
        ip_input_layout.setSpacing(8)
        ip_input_layout.setContentsMargins(15, 15, 15, 15)
        
        ip_input_label = QLabel('批量IP地址/域名')
        ip_input_label.setFont(QFont('Arial', 14, QFont.Bold))
        ip_input_label.setStyleSheet('color: #000000; font-weight: bold;')
        ip_input_layout.addWidget(ip_input_label)
        
        self.ip_text_edit = QTextEdit()
        self.ip_text_edit.setFont(QFont('Courier New', 11))
        self.ip_text_edit.setPlaceholderText('请输入IP地址或域名，每行一个')
        self.ip_text_edit.setMinimumHeight(400)  # 增大输入框高度
        self.ip_text_edit.setStyleSheet('''
            QTextEdit {
                border: 2px solid #000000;
                border-radius: 6px;
                padding: 10px;
                background-color: #ffffff;
            }
        ''')
        ip_input_layout.addWidget(self.ip_text_edit)
        
        # 1.2 操作按钮
        button_group = QWidget()
        button_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 8px;
                background-color: #f8f9fa;
            }
        ''')
        button_layout = QVBoxLayout(button_group)
        button_layout.setSpacing(10)
        button_layout.setContentsMargins(15, 15, 15, 15)
        
        self.start_test_btn = QPushButton('PING测试')
        self.start_test_btn.clicked.connect(self.start_test)
        self.start_test_btn.setMinimumHeight(40)
        self.start_test_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 6px;
                padding: 10px;
                background-color: #007bff;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0069d9;
            }
            QPushButton:pressed {
                background-color: #0056b3;
            }
        ''')
        
        self.stop_test_btn = QPushButton('停止测试')
        self.stop_test_btn.clicked.connect(self.stop_test)
        self.stop_test_btn.setEnabled(False)
        self.stop_test_btn.setMinimumHeight(40)
        self.stop_test_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 6px;
                padding: 10px;
                background-color: #dc3545;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:pressed {
                background-color: #a71e2a;
            }
        ''')
        
        button_layout.addWidget(self.start_test_btn)
        button_layout.addWidget(self.stop_test_btn)
        
        left_layout.addWidget(ip_input_group)
        left_layout.addWidget(button_group)
        
        main_layout.addWidget(left_column, 1)  # 第一列宽度比例
        
        # 2. 第二列：配置参数和测试结果（上方配置，下方结果）
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setSpacing(15)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # 2.1 PING参数设置
        config_group = QWidget()
        config_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 8px;
                background-color: #f8f9fa;
            }
        ''')
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)  # 减少配置组内的垂直间距
        config_layout.setContentsMargins(15, 15, 15, 15)  # 调整外边距
        
        # 添加配置和清空IP按钮
        button_group = QWidget()
        button_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 6px;
                background-color: #ffffff;
            }
        ''')
        button_layout = QHBoxLayout(button_group)
        button_layout.setSpacing(10)
        button_layout.setContentsMargins(10, 10, 10, 10)
        
        self.clear_ip_btn = QPushButton('清空IP')
        self.clear_ip_btn.clicked.connect(self.clear_ip)
        self.clear_ip_btn.setMinimumHeight(30)
        self.clear_ip_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px 12px;
                background-color: #6c757d;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #495057;
            }
        ''')
        
        self.config_btn = QPushButton('配置')
        self.config_btn.clicked.connect(self.show_config_dialog)
        self.config_btn.setMinimumHeight(30)
        self.config_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px 12px;
                background-color: #007bff;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0069d9;
            }
            QPushButton:pressed {
                background-color: #0056b3;
            }
        ''')
        
        self.help_btn = QPushButton('帮助')
        self.help_btn.clicked.connect(self.show_help_dialog)
        self.help_btn.setMinimumHeight(30)
        self.help_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px 12px;
                background-color: #28a745;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        ''')
        
        button_layout.addWidget(self.clear_ip_btn)
        button_layout.addWidget(self.config_btn)
        button_layout.addWidget(self.help_btn)
        config_layout.addWidget(button_group)
        
        # 2.1.1 结果展示布局
        layout_group = QWidget()
        layout_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 6px;
                background-color: #ffffff;
            }
        ''')
        layout_layout = QVBoxLayout(layout_group)
        layout_layout.setSpacing(8)  # 减少内部间距
        layout_layout.setContentsMargins(10, 10, 10, 10)  # 调整内边距
        
        layout_label = QLabel('结果展示布局')
        layout_label.setFont(QFont('Arial', 12, QFont.Bold))
        layout_label.setStyleSheet('color: #000000; font-weight: bold; margin-bottom: 3px;')  # 减少标签底部边距
        layout_layout.addWidget(layout_label)
        
        rows_cols_layout = QHBoxLayout()
        rows_cols_layout.setSpacing(15)
        rows_cols_layout.setContentsMargins(0, 0, 0, 0)  # 移除底部边距
        
        rows_group = QWidget()
        rows_layout = QVBoxLayout(rows_group)
        rows_layout.setSpacing(2)  # 减少标签和输入框之间的间距
        
        rows_label = QLabel('行数:')
        rows_label.setFont(QFont('Arial', 11, QFont.Bold))
        rows_label.setStyleSheet('color: #000000; font-weight: bold;')
        rows_layout.addWidget(rows_label)
        
        self.rows_input = QLineEdit(str(self.default_rows))
        self.rows_input.setPlaceholderText('行数')
        self.rows_input.setFixedWidth(90)
        self.rows_input.setFixedHeight(24)  # 固定输入框高度
        self.rows_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        rows_layout.addWidget(self.rows_input)
        
        cols_group = QWidget()
        cols_layout = QVBoxLayout(cols_group)
        cols_layout.setSpacing(2)  # 减少标签和输入框之间的间距
        
        cols_label = QLabel('列数:')
        cols_label.setFont(QFont('Arial', 11, QFont.Bold))
        cols_label.setStyleSheet('color: #000000; font-weight: bold;')
        cols_layout.addWidget(cols_label)
        
        self.cols_input = QLineEdit(str(self.default_cols))
        self.cols_input.setPlaceholderText('列数')
        self.cols_input.setFixedWidth(90)
        self.cols_input.setFixedHeight(24)  # 固定输入框高度
        self.cols_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        cols_layout.addWidget(self.cols_input)
        
        rows_cols_layout.addWidget(rows_group)
        rows_cols_layout.addWidget(cols_group)
        layout_layout.addLayout(rows_cols_layout)
        
        # 2.1.2 界面大小设置
        window_size_group = QWidget()
        window_size_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 6px;
                background-color: #ffffff;
            }
        ''')
        window_size_layout = QVBoxLayout(window_size_group)
        window_size_layout.setSpacing(8)  # 减少内部间距
        window_size_layout.setContentsMargins(10, 10, 10, 10)  # 调整内边距
        
        window_size_label = QLabel('界面大小')
        window_size_label.setFont(QFont('Arial', 12, QFont.Bold))
        window_size_label.setStyleSheet('color: #000000; font-weight: bold; margin-bottom: 3px;')  # 减少标签底部边距
        window_size_layout.addWidget(window_size_label)
        
        width_height_layout = QHBoxLayout()
        width_height_layout.setSpacing(15)
        width_height_layout.setContentsMargins(0, 0, 0, 0)  # 移除底部边距
        
        width_group = QWidget()
        width_layout = QVBoxLayout(width_group)
        width_layout.setSpacing(2)  # 减少标签和输入框之间的间距
        
        width_label = QLabel('宽度:')
        width_label.setFont(QFont('Arial', 11, QFont.Bold))
        width_label.setStyleSheet('color: #000000; font-weight: bold;')
        width_layout.addWidget(width_label)
        
        self.width_input = QLineEdit(str(self.default_window_width))
        self.width_input.setPlaceholderText('宽度')
        self.width_input.setFixedWidth(90)
        self.width_input.setFixedHeight(24)  # 固定输入框高度
        self.width_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        width_layout.addWidget(self.width_input)
        
        height_group = QWidget()
        height_layout = QVBoxLayout(height_group)
        height_layout.setSpacing(2)  # 减少标签和输入框之间的间距
        
        height_label = QLabel('高度:')
        height_label.setFont(QFont('Arial', 11, QFont.Bold))
        height_label.setStyleSheet('color: #000000; font-weight: bold;')
        height_layout.addWidget(height_label)
        
        self.height_input = QLineEdit(str(self.default_window_height))
        self.height_input.setPlaceholderText('高度')
        self.height_input.setFixedWidth(90)
        self.height_input.setFixedHeight(24)  # 固定输入框高度
        self.height_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #80bdff;
                outline: none;
            }
        ''')
        height_layout.addWidget(self.height_input)
        
        self.apply_size_btn = QPushButton('应用大小')
        self.apply_size_btn.setFixedWidth(90)
        self.apply_size_btn.setFixedHeight(24)  # 固定按钮高度
        self.apply_size_btn.clicked.connect(self.apply_window_size)
        self.apply_size_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                background-color: #6c757d;
                color: white;
                border-radius: 4px;
                padding: 0px 12px;
                font-size: 9pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #495057;
            }
        ''')
        
        width_height_layout.addWidget(width_group)
        width_height_layout.addWidget(height_group)
        width_height_layout.addWidget(self.apply_size_btn, 0, Qt.AlignBottom)
        window_size_layout.addLayout(width_height_layout)
        
        # 2.1.3 PING参数设置
        ping_group = QWidget()
        ping_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 6px;
                background-color: #ffffff;
            }
        ''')
        ping_layout = QVBoxLayout(ping_group)
        ping_layout.setSpacing(8)  # 减少内部间距
        ping_layout.setContentsMargins(10, 10, 10, 10)  # 调整内边距
        
        ping_label = QLabel('PING参数')
        ping_label.setFont(QFont('Arial', 12, QFont.Bold))
        ping_label.setStyleSheet('color: #000000; font-weight: bold; margin-bottom: 3px;')  # 减少标签底部边距
        ping_layout.addWidget(ping_label)
        
        ping_params_layout = QHBoxLayout()
        ping_params_layout.setSpacing(10)
        ping_params_layout.setContentsMargins(0, 0, 0, 0)  # 移除底部边距
        
        # 创建一个水平布局，包含PING次数标签、输入框和持续PING复选框
        count_continuous_layout = QHBoxLayout()
        count_continuous_layout.setSpacing(8)
        count_continuous_layout.setContentsMargins(0, 0, 0, 0)
        
        # PING次数标签
        count_label = QLabel('PING次数:')
        count_label.setFont(QFont('Arial', 11, QFont.Bold))
        count_label.setStyleSheet('color: #000000; font-weight: bold;')
        
        # PING次数输入框
        self.count_input = QLineEdit(str(self.default_ping_count))
        self.count_input.setPlaceholderText('次数')
        self.count_input.setFixedWidth(90)
        self.count_input.setFixedHeight(24)  # 固定输入框高度
        self.count_input.setStyleSheet('''
            QLineEdit {
                padding: 2px 8px;
                border: 1px solid #000000;
                border-radius: 4px;
                font-size: 9pt;
                font-weight: bold;
            }
            QLineEdit:focus {
                border-color: #000000;
                outline: none;
            }
        ''')
        
        # 持续PING复选框
        self.continuous_checkbox = QCheckBox('持续PING (-t)')
        self.continuous_checkbox.setToolTip('启用持续PING模式，需要手动停止')
        # 加粗复选框样式，使其更显眼
        self.continuous_checkbox.setStyleSheet('''
            QCheckBox {
                color: #000000;
                font-size: 11pt;
                font-weight: bold;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #000000;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #007bff;
            }
        ''')
        
        # 将元素添加到水平布局中
        count_continuous_layout.addWidget(count_label, 0, Qt.AlignVCenter)  # 垂直居中对齐
        count_continuous_layout.addWidget(self.count_input, 0, Qt.AlignVCenter)  # 垂直居中对齐
        count_continuous_layout.addWidget(self.continuous_checkbox, 0, Qt.AlignVCenter)  # 垂直居中对齐
        
        # 将水平布局添加到主布局中
        ping_params_layout.addLayout(count_continuous_layout)
        ping_layout.addLayout(ping_params_layout)
        
        config_layout.addWidget(ping_group)
        
        # 2.2 测试结果区（下方）
        result_group = QWidget()
        result_group.setStyleSheet('''
            QWidget {
                border: 1px solid #000000;
                border-radius: 8px;
                background-color: #f8f9fa;
            }
        ''')
        result_layout = QVBoxLayout(result_group)
        result_layout.setSpacing(8)
        result_layout.setContentsMargins(15, 15, 15, 15)
        
        result_label = QLabel('测试结果')
        result_label.setFont(QFont('Arial', 14, QFont.Bold))
        result_label.setStyleSheet("color: #000000; font-weight: bold; margin-bottom: 5px;")
        result_layout.addWidget(result_label)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet('''
            QScrollArea {
                border: 1px solid #000000;
                border-radius: 6px;
                background-color: #ffffff;
            }
        ''')
        
        self.result_widget = QWidget()
        self.result_widget.setStyleSheet('''
            QWidget {
                border: none;
            }
        ''')
        self.result_grid = QGridLayout(self.result_widget)
        self.result_grid.setSpacing(20)  # 大幅增加间距，减少拥挤感
        self.result_grid.setContentsMargins(10, 10, 10, 10)  # 增加外边距
        
        self.scroll_area.setWidget(self.result_widget)
        result_layout.addWidget(self.scroll_area)
        
        right_layout.addWidget(config_group)
        right_layout.addWidget(result_group, 1)  # 测试结果区占据更多空间
        
        main_layout.addWidget(right_column, 4)  # 第二列宽度比例，进一步加宽以显示5列结果
        
        # 添加本机IP显示在边框下
        status_bar = self.statusBar()
        status_bar.setStyleSheet('''
            QStatusBar {
                border: none;
                background-color: transparent;
            }
            QStatusBar::item {
                border: none;
            }
        ''')
        local_ip_label = QLabel(f'本机IP: {self.get_local_ip()}')
        local_ip_label.setFont(QFont('Arial', 10, QFont.Bold))
        local_ip_label.setStyleSheet('''
            QLabel {
                color: red;
                border: none;
                background-color: transparent;
            }
        ''')
        status_bar.addPermanentWidget(local_ip_label)
    
    def clear_ip(self):
        """清空IP输入框"""
        from PySide6.QtWidgets import QMessageBox
        import datetime
        import os
        
        # 显示确认对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('确认清空')
        msg_box.setText('确定要清空所有IP地址吗？')
        msg_box.setInformativeText('此操作将清空当前输入的所有IP地址，并备份原有的保存文件。')
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        
        # 设置对话框为模态，并在屏幕中间显示
        msg_box.setWindowModality(Qt.ApplicationModal)
        # 计算屏幕中心位置
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        msg_box_geometry = msg_box.geometry()
        x = (screen_geometry.width() - msg_box_geometry.width()) // 2
        y = (screen_geometry.height() - msg_box_geometry.height()) // 2
        msg_box.move(x, y)
        
        # 执行确认操作
        if msg_box.exec() == QMessageBox.Yes:
            # 备份原有的saved_ips.json文件
            if os.path.exists(self.ip_file):
                # 获取当前日期和时间
                now = datetime.datetime.now()
                date_str = now.strftime('%Y%m%d')
                
                # 生成备份文件名，添加序号以避免覆盖
                backup_count = 1
                while True:
                    backup_file = f'saved_ips_{date_str}_{backup_count}.json'
                    if not os.path.exists(backup_file):
                        break
                    backup_count += 1
                
                # 复制文件进行备份
                import shutil
                shutil.copy2(self.ip_file, backup_file)
                print(f"已备份IP地址到: {backup_file}")
            
            # 清空IP输入框
            self.ip_text_edit.clear()
    
    def apply_window_size(self):
        """应用窗口大小设置"""
        try:
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            
            if width <= 0 or height <= 0:
                raise ValueError('宽度和高度必须为正整数')
            
            self.resize(width, height)
            
        except ValueError as e:
            QMessageBox.warning(self, '输入错误', str(e))
    
    def start_test(self):
        """开始测试"""
        # 获取输入的IP地址
        ip_text = self.ip_text_edit.toPlainText()
        ip_list = []
        
        for line in ip_text.split('\n'):
            line = line.strip()
            if line and ' ' not in line:
                ip_list.append(line)
        
        if not ip_list:
            QMessageBox.warning(self, '输入错误', '请输入有效的IP地址或域名')
            return
        
        # 保存IP地址
        self.save_ips()
        
        # 获取配置参数
        try:
            rows = self.default_rows
            cols = self.default_cols
            count = int(self.count_input.text())
            
            if rows <= 0 or cols <= 0:
                raise ValueError('行数和列数必须为正整数')
            
            if not self.continuous_checkbox.isChecked() and count <= 0:
                raise ValueError('PING次数必须为正整数')
                
        except ValueError as e:
            QMessageBox.warning(self, '输入错误', str(e))
            return
        
        # 获取持续PING模式
        continuous = self.continuous_checkbox.isChecked()
        
        # 清空之前的结果
        self.clear_result_grid()
        
        # 创建结果展示网格
        self.create_result_grid(rows, cols)
        
        # 禁用按钮并设置背景色为灰色
        self.start_test_btn.setEnabled(False)
        self.start_test_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 6px;
                padding: 10px;
                background-color: #6c757d;
                color: white;
                font-weight: bold;
            }
        ''')
        self.stop_test_btn.setEnabled(True)
        
        # 只有在持续PING模式下才创建输出窗口
        if continuous:
            self.create_unified_output_window(rows, cols)
        
        # 开始测试
        self.test_ip_list(ip_list, count, continuous)
    
    def stop_test(self):
        """停止测试"""
        # 停止所有线程
        for ip, thread in self.threads.items():
            if thread.isRunning():
                thread.stop()
                thread.wait()
        
        # 关闭统一的输出窗口
        self.close_unified_output_window()
        
        # 更新按钮状态并恢复PING测试按钮的背景色
        self.start_test_btn.setEnabled(True)
        self.start_test_btn.setStyleSheet('''
            QPushButton {
                border: 1px solid #000000;
                border-radius: 6px;
                padding: 10px;
                background-color: #007bff;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0069d9;
            }
            QPushButton:pressed {
                background-color: #0056b3;
            }
        ''')
        self.stop_test_btn.setEnabled(False)
    
    def load_saved_ips(self):
        """加载保存的IP地址"""
        try:
            if os.path.exists(self.ip_file):
                with open(self.ip_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'ips' in data:
                        self.ip_text_edit.setPlainText('\n'.join(data['ips']))
        except Exception as e:
            print(f"加载保存的IP地址失败: {e}")
    
    def save_ips(self):
        """保存当前IP地址"""
        try:
            ip_text = self.ip_text_edit.toPlainText()
            ip_list = [line.strip() for line in ip_text.split('\n') if line.strip()]
            
            data = {'ips': ip_list}
            with open(self.ip_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存IP地址失败: {e}")
    
    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'rows' in data:
                        self.default_rows = data['rows']
                    if 'cols' in data:
                        self.default_cols = data['cols']
                    if 'width' in data:
                        self.default_window_width = data['width']
                        self.resize(data['width'], self.default_window_height)
                    if 'height' in data:
                        self.default_window_height = data['height']
                        self.resize(self.default_window_width, data['height'])
        except Exception as e:
            print(f"加载配置失败: {e}")
    
    def save_config(self, config):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def show_config_dialog(self):
        """显示配置对话框"""
        config = {
            'rows': self.default_rows,
            'cols': self.default_cols,
            'width': self.default_window_width,
            'height': self.default_window_height
        }
        
        dialog = ConfigDialog(self, config)
        # 设置对话框为模态，并在屏幕中间显示
        dialog.setWindowModality(Qt.ApplicationModal)
        # 计算屏幕中心位置
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        dialog_geometry = dialog.geometry()
        x = (screen_geometry.width() - dialog_geometry.width()) // 2
        y = (screen_geometry.height() - dialog_geometry.height()) // 2
        dialog.move(x, y)
        
        if dialog.exec():
            new_config = dialog.get_config()
            if new_config:
                self.default_rows = new_config['rows']
                self.default_cols = new_config['cols']
                self.default_window_width = new_config['width']
                self.default_window_height = new_config['height']
                self.resize(new_config['width'], new_config['height'])
                self.save_config(new_config)
    
    def show_help_dialog(self):
        """显示帮助对话框"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle('操作说明')
        dialog.resize(600, 400)
        
        # 设置对话框为模态，并在屏幕中间显示
        dialog.setWindowModality(Qt.ApplicationModal)
        # 计算屏幕中心位置
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        dialog_geometry = dialog.geometry()
        x = (screen_geometry.width() - dialog_geometry.width()) // 2
        y = (screen_geometry.height() - dialog_geometry.height()) // 2
        dialog.move(x, y)
        
        layout = QVBoxLayout(dialog)
        
        # 标题
        title_label = QLabel('操作说明')
        title_label.setFont(QFont('Arial', 12, QFont.Bold))
        title_label.setStyleSheet('color: #2c3e50; margin-bottom: 10px;')
        layout.addWidget(title_label)
        
        # 帮助内容
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setFont(QFont('Arial', 10))
        help_text.setStyleSheet('''
            QTextEdit {
                padding: 10px;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                background-color: #f8f9fa;
            }
        ''')
        
        help_content = '''
IP网络连接速度测试工具使用说明

一、功能概述
本工具用于批量测试多个IP地址或域名的网络连接状态和速度，支持普通测试模式和持续测试模式，提供实时测试结果和详细的统计数据。

二、操作流程
1. IP地址输入
   - 在左侧IP输入框中输入要测试的IP地址或域名，每行一个
   - 支持的格式：IPv4地址（如192.168.1.1）和域名（如www.baidu.com）
   - 系统会自动验证输入格式的有效性

2. 参数设置
   - PING次数：设置每个IP的测试次数，默认为10次
   - 持续PING模式：勾选后会持续测试，直到手动停止

3. 开始测试
   - 点击"PING测试"按钮开始执行测试
   - 测试过程中会显示实时进度
   - 持续模式下会弹出实时输出窗口

4. 查看结果
   - 测试结果会显示在下方的网格中
   - 每个结果包含IP地址、测试状态、平均延迟、最小/最大延迟和丢包率
   - 测试完成后会自动保存当前输入的IP地址，下次启动时可恢复

三、按钮功能说明
- 清空IP：清除当前输入的所有IP地址，操作前会自动备份原有数据
- 配置：打开配置对话框，可设置结果展示的行数、列数和窗口大小
- 帮助：显示本操作说明文档
- PING测试：开始执行PING测试，支持批量测试多个IP地址
- 停止测试：停止正在进行的测试，适用于普通模式和持续模式

四、测试模式详解
1. 普通模式
   - 根据设置的PING次数执行测试，完成后自动结束
   - 测试过程中显示实时进度（如3/10）
   - 测试完成后显示详细的统计结果

2. 持续PING模式
   - 持续执行PING测试，直到手动停止
   - 弹出实时输出窗口，显示每个IP的详细测试结果
   - 支持同时测试多个IP地址，每个IP有独立的输出区域
   - 关闭输出窗口或点击"停止测试"按钮可结束测试

五、结果状态说明
- 绿色背景：连接正常，测试成功
- 红色背景：连接失败，可能是网络问题或目标不可达
- 橙色背景：测试进行中，显示当前进度

六、高级功能
1. IP地址自动保存
   - 点击"PING测试"按钮时，系统会自动保存当前输入的IP地址
   - 保存文件为saved_ips.json，下次启动时自动加载
   - 清空IP时会自动备份原有数据，避免意外丢失

2. 配置管理
   - 通过"配置"按钮可调整界面布局和窗口大小
   - 配置会自动保存，下次启动时生效
   - 可根据测试IP数量调整网格布局的行数和列数

3. 实时输出
   - 持续模式下提供实时输出窗口
   - 每个IP有独立的输出区域，便于对比分析
   - 支持滚动查看历史输出记录

七、注意事项
1. 输入格式：请确保输入的IP地址或域名格式正确
2. 网络环境：测试结果受网络环境影响，建议在稳定网络环境下测试
3. 权限要求：在某些系统上可能需要管理员权限才能执行PING命令
4. 资源占用：测试大量IP时可能会占用较多系统资源，请合理设置测试数量
5. 防火墙：某些防火墙设置可能会影响PING测试结果

八、故障排查
- 测试失败：检查目标IP是否可达，网络连接是否正常
- 无响应：可能是目标设备防火墙阻止了PING请求
- 数据异常：可能是网络波动导致，建议多次测试取平均值
- 程序错误：请检查控制台输出的错误信息，或重启程序后重试
        '''
        
        help_text.setPlainText(help_content)
        layout.addWidget(help_text)
        
        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.exec()
    
    def handle_test_start(self, ip):
        """处理测试开始信号"""
        # 找到对应的单元格并显示"ping + IP"
        found = False
        
        # 首先检查是否已经有映射
        if ip in getattr(self, 'ip_to_cell', {}):
            cell_widget = self.ip_to_cell[ip]
            labels = cell_widget.findChildren(QLabel)
            if len(labels) >= 5:
                ip_label = labels[0]
                status_label = labels[1]
                status_label.setText(f'准备测试 {ip}')
                
                # 设置运行中颜色
                palette = cell_widget.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                status_label.setStyleSheet('color: orange;')
                cell_widget.setPalette(palette)
                cell_widget.setAutoFillBackground(True)
                found = True
            elif len(labels) >= 4:
                # 兼容旧的布局
                ip_label = labels[0]
                status_label = labels[1]
                status_label.setText(f'准备测试 {ip}')
                
                # 设置运行中颜色
                palette = cell_widget.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                status_label.setStyleSheet('color: orange;')
                cell_widget.setPalette(palette)
                cell_widget.setAutoFillBackground(True)
                found = True
        else:
            # 遍历查找空单元格
            for i in range(self.result_grid.rowCount()):
                for j in range(self.result_grid.columnCount()):
                    cell = self.result_grid.itemAtPosition(i, j)
                    if cell:
                        cell_widget = cell.widget()
                        labels = cell_widget.findChildren(QLabel)
                        if len(labels) >= 5:
                            ip_label = labels[0]
                            if ip_label.text() == '':
                                # 如果是新的测试，先设置IP地址
                                ip_label.setText(ip)
                                
                                # 存储映射
                                if not hasattr(self, 'ip_to_cell'):
                                    self.ip_to_cell = {}
                                self.ip_to_cell[ip] = cell_widget
                                
                                status_label = labels[1]
                                status_label.setText(f'准备测试 {ip}')
                                
                                # 设置运行中颜色
                                palette = cell_widget.palette()
                                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                                status_label.setStyleSheet('color: orange;')
                                cell_widget.setPalette(palette)
                                cell_widget.setAutoFillBackground(True)
                                found = True
                                break
                        elif len(labels) >= 4:
                            # 兼容旧的布局
                            ip_label = labels[0]
                            if ip_label.text() == '':
                                # 如果是新的测试，先设置IP地址
                                ip_label.setText(ip)
                                
                                # 存储映射
                                if not hasattr(self, 'ip_to_cell'):
                                    self.ip_to_cell = {}
                                self.ip_to_cell[ip] = cell_widget
                                
                                status_label = labels[1]
                                status_label.setText(f'准备测试 {ip}')
                                
                                # 设置运行中颜色
                                palette = cell_widget.palette()
                                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                                status_label.setStyleSheet('color: orange;')
                                cell_widget.setPalette(palette)
                                cell_widget.setAutoFillBackground(True)
                                found = True
                                break
                if found:
                    break
    
    def handle_progress(self, ip, current, total):
        """处理测试进度信号"""
        # 找到对应的单元格并更新进度
        found = False
        
        # 首先检查是否已经有映射
        if ip in getattr(self, 'ip_to_cell', {}):
            cell_widget = self.ip_to_cell[ip]
            labels = cell_widget.findChildren(QLabel)
            if len(labels) >= 5:
                status_label = labels[1]
                # 调整显示格式，减小字体大小，确保进度信息能够完全显示
                status_label.setText(f'测试中\n{current}/{total}')
                status_label.setFont(QFont('Arial', 12, QFont.Bold))  # 减小字体大小
                
                # 设置运行中颜色
                palette = cell_widget.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                status_label.setStyleSheet('color: orange; text-align: center;')
                cell_widget.setPalette(palette)
                cell_widget.setAutoFillBackground(True)
                found = True
            elif len(labels) >= 4:
                # 兼容旧的布局
                status_label = labels[1]
                status_label.setText(f'测试中\n{current}/{total}')
                status_label.setFont(QFont('Arial', 12, QFont.Bold))  # 减小字体大小
                
                # 设置运行中颜色
                palette = cell_widget.palette()
                palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                status_label.setStyleSheet('color: orange; text-align: center;')
                cell_widget.setPalette(palette)
                cell_widget.setAutoFillBackground(True)
                found = True
        else:
            # 遍历查找
            for i in range(self.result_grid.rowCount()):
                for j in range(self.result_grid.columnCount()):
                    cell = self.result_grid.itemAtPosition(i, j)
                    if cell:
                        cell_widget = cell.widget()
                        ip_label = cell_widget.findChild(QLabel)
                        if ip_label and ip_label.text() == ip:
                            # 存储映射
                            if not hasattr(self, 'ip_to_cell'):
                                self.ip_to_cell = {}
                            self.ip_to_cell[ip] = cell_widget
                            
                            labels = cell_widget.findChildren(QLabel)
                            if len(labels) >= 5:
                                status_label = labels[1]
                                status_label.setText(f'测试中\n{current}/{total}')
                                status_label.setFont(QFont('Arial', 12, QFont.Bold))
                                
                                # 设置运行中颜色
                                palette = cell_widget.palette()
                                palette.setColor(QPalette.Window, QColor(255, 255, 220))
                                status_label.setStyleSheet('color: orange; text-align: center;')
                                cell_widget.setPalette(palette)
                                cell_widget.setAutoFillBackground(True)
                                found = True
                                break
                            elif len(labels) >= 4:
                                # 兼容旧的布局
                                status_label = labels[1]
                                status_label.setText(f'测试中\n{current}/{total}')
                                status_label.setFont(QFont('Arial', 12, QFont.Bold))
                                
                                # 设置运行中颜色
                                palette = cell_widget.palette()
                                palette.setColor(QPalette.Window, QColor(255, 255, 220))
                                status_label.setStyleSheet('color: orange; text-align: center;')
                                cell_widget.setPalette(palette)
                                cell_widget.setAutoFillBackground(True)
                                found = True
                                break
                if found:
                    break
    
    def create_unified_output_window(self, rows, cols):
        """创建统一的输出窗口"""
        # 确保之前的窗口已完全关闭
        if self.output_window is not None:
            self.close_unified_output_window()
        
        self.output_window = QDialog(self)
        self.output_window.setWindowTitle('PING 实时输出')
        self.output_window.setGeometry(100, 100, 1700, 600)  # 增加窗口宽度，确保能显示5个IP框
        
        # 重写关闭事件
        def closeEvent(event):
            self.close_unified_output_window()
            event.accept()
        
        self.output_window.closeEvent = closeEvent
        
        layout = QVBoxLayout(self.output_window)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        # 创建网格布局的输出区域
        output_widget = QWidget()
        self.output_grid = QGridLayout(output_widget)
        self.output_grid.setSpacing(10)
        
        # 设置网格的行列数
        self.output_grid.setRowStretch(rows, 1)
        self.output_grid.setColumnStretch(cols, 1)
        
        # 存储每个IP对应的输出文本框
        self.ip_outputs = {}
        
        scroll_area.setWidget(output_widget)
        layout.addWidget(scroll_area)
        
        # 添加状态标签
        status_label = QLabel('就绪')
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setFont(QFont('Arial', 9))
        layout.addWidget(status_label)
        self.output_window.status_label = status_label
        
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.close_unified_output_window)
        layout.addWidget(close_btn)
        
        self.output_window.show()
    
    def close_unified_output_window(self):
        """关闭统一的输出窗口"""
        if self.output_window:
            try:
                # 显示关闭进度
                if hasattr(self.output_window, 'status_label'):
                    self.output_window.status_label.setText('正在停止测试...')
                    # 强制更新界面
                    QApplication.processEvents()
                
                # 停止所有正在运行的线程
                running_threads = [thread for thread in self.threads.values() if thread.isRunning()]
                total_threads = len(running_threads)
                
                if total_threads > 0 and hasattr(self.output_window, 'status_label'):
                    self.output_window.status_label.setText(f'正在停止测试... (0/{total_threads})')
                    QApplication.processEvents()
                
                for i, thread in enumerate(running_threads):
                    thread.stop()
                    thread.wait()
                    
                    # 更新进度
                    if hasattr(self.output_window, 'status_label'):
                        self.output_window.status_label.setText(f'正在停止测试... ({i+1}/{total_threads})')
                        QApplication.processEvents()
                
                # 更新按钮状态
                self.start_test_btn.setEnabled(True)
                self.stop_test_btn.setEnabled(False)
                
                # 关闭窗口
                self.output_window.close()
                
                # 等待窗口完全关闭
                QApplication.processEvents()
                
            except Exception as e:
                print(f"关闭窗口时出错: {e}")
            
            finally:
                # 强制清理所有资源
                self.output_window = None
                self.ip_outputs = {}
                # 清空网格布局引用
                if hasattr(self, 'output_grid'):
                    self.output_grid = None
    
    def handle_output(self, ip, line):
        """处理实时输出"""
        # 检查窗口是否存在且可见
        if self.output_window is None or not self.output_window.isVisible():
            return
        
        # 如果IP还没有对应的输出文本框，创建它
        if ip not in self.ip_outputs:
            # 跟踪下一个可用位置
            if not hasattr(self, 'next_output_position'):
                self.next_output_position = (0, 0)
            
            # 使用预计算的位置
            i, j = self.next_output_position
            cols = self.default_cols
            
            # 创建输出文本框
            output_group = QWidget()
            output_layout = QVBoxLayout(output_group)
            
            ip_label = QLabel(f'IP: {ip}')
            ip_label.setFont(QFont('Arial', 10, QFont.Bold))
            output_layout.addWidget(ip_label)
            
            output_text = QTextEdit()
            output_text.setReadOnly(True)
            output_text.setFont(QFont('Courier New', 9))
            output_text.setMinimumHeight(150)
            output_text.setMinimumWidth(300)  # 增加最小宽度
            output_text.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)  # 启用自动换行
            output_text.setLineWrapMode(QTextEdit.WidgetWidth)  # 按窗口宽度换行
            output_layout.addWidget(output_text)
            
            self.output_grid.addWidget(output_group, i, j)
            self.ip_outputs[ip] = output_text
            
            # 更新下一个位置
            j += 1
            if j >= cols:
                j = 0
                i += 1
            self.next_output_position = (i, j)
        
        # 添加输出内容
        if ip in self.ip_outputs and self.output_window and self.output_window.isVisible():
            # 使用缓存批量更新，减少UI重绘
            if not hasattr(self, 'output_buffers'):
                self.output_buffers = {}
                self.last_update_time = {}
            
            if ip not in self.output_buffers:
                self.output_buffers[ip] = []
                self.last_update_time[ip] = 0
            
            import time
            current_time = time.time()
            
            # 添加到缓冲区
            self.output_buffers[ip].append(line)
            
            # 每5行或100ms批量更新一次
            if len(self.output_buffers[ip]) >= 5 or current_time - self.last_update_time[ip] >= 0.1:
                # 批量更新
                text = '\n'.join(self.output_buffers[ip])
                self.ip_outputs[ip].append(text)
                self.output_buffers[ip] = []
                self.last_update_time[ip] = current_time
    
    def test_ip_list(self, ip_list, count, continuous=False):
        """测试IP列表"""
        self.threads = {}
        
        # 限制并发线程数
        max_threads = min(10, len(ip_list))  # 最多10个并发线程
        
        # 批量创建线程
        threads = []
        for i, ip in enumerate(ip_list):
            # 创建线程
            thread = PingThread(ip, count, continuous)
            thread.result_signal.connect(self.update_result)
            thread.start_signal.connect(self.handle_test_start)
            thread.output_signal.connect(self.handle_output)
            thread.progress_signal.connect(self.handle_progress)  # 连接进度信号
            self.threads[ip] = thread
            threads.append(thread)
        
        # 批量启动线程，控制并发数
        import threading
        semaphore = threading.Semaphore(max_threads)
        
        def start_thread_with_semaphore(thread):
            with semaphore:
                thread.start()
                # 给线程一些时间启动
                import time
                time.sleep(0.05)
        
        # 使用线程池启动测试线程
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(5, max_threads)) as executor:
            executor.map(start_thread_with_semaphore, threads)
    
    def create_result_grid(self, rows, cols):
        """创建结果展示网格"""
        # 清空现有布局
        self.clear_result_grid()
        
        # 添加IP到单元格的映射
        self.ip_to_cell = {}
        
        # 创建网格
        for i in range(rows):
            for j in range(cols):
                cell = QWidget()
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(8, 8, 8, 8)
                cell_layout.setSpacing(6)  # 减少内部间距
                
                # 设置默认背景色和边框
                palette = cell.palette()
                palette.setColor(QPalette.Window, QColor(220, 255, 220))  # 浅绿底色
                cell.setPalette(palette)
                cell.setAutoFillBackground(True)
                cell.setStyleSheet('border: 1px solid #000000; border-radius: 4px;')
                
                ip_label = QLabel('')
                ip_label.setFont(QFont('Courier New', 10, QFont.Bold))
                ip_label.setWordWrap(True)
                ip_label.setStyleSheet('color: #333333;')
                
                status_label = QLabel('')
                status_label.setFont(QFont('Arial', 9))
                status_label.setWordWrap(True)
                status_label.setStyleSheet('color: #666666;')
                
                latency_label = QLabel('')
                latency_label.setFont(QFont('Arial', 9))
                latency_label.setStyleSheet('color: #666666;')
                
                packet_loss_label = QLabel('')
                packet_loss_label.setFont(QFont('Arial', 9))
                packet_loss_label.setStyleSheet('color: #666666;')
                
                # 添加最小/最大延迟标签
                min_max_label = QLabel('')
                min_max_label.setFont(QFont('Arial', 9))
                min_max_label.setStyleSheet('color: #666666;')
                
                cell_layout.addWidget(ip_label)
                cell_layout.addWidget(status_label)
                cell_layout.addWidget(latency_label)
                cell_layout.addWidget(min_max_label)  # 添加最小/最大延迟标签
                cell_layout.addWidget(packet_loss_label)
                
                cell.setObjectName(f'cell_{i}_{j}')
                cell.setMinimumSize(140, 110)  # 增加最小尺寸，确保显示空间
                cell.setMaximumSize(220, 140)  # 设置最大尺寸，避免过大
                self.result_grid.addWidget(cell, i, j)
    
    def clear_result_grid(self):
        """清空结果网格"""
        while self.result_grid.count():
            item = self.result_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def update_result(self, ip, result):
        """更新测试结果"""
        # 确保result字典包含所有必要的键
        if 'min_latency' not in result:
            result['min_latency'] = 0
        if 'max_latency' not in result:
            result['max_latency'] = 0
        
        # 找到显示该IP地址的单元格
        for i in range(self.result_grid.rowCount()):
            for j in range(self.result_grid.columnCount()):
                cell = self.result_grid.itemAtPosition(i, j)
                if cell:
                    cell_widget = cell.widget()
                    ip_label = cell_widget.findChild(QLabel)
                    if ip_label and ip_label.text() == ip:
                        # 更新单元格内容
                        labels = cell_widget.findChildren(QLabel)
                        if len(labels) >= 5:  # 增加了一个标签，所以长度变为5
                            status_label = labels[1]
                            latency_label = labels[2]
                            min_max_label = labels[3]  # 新增的最小/最大延迟标签
                            packet_loss_label = labels[4]
                        else:
                            continue
                        
                        status_label.setText(result['message'])
                        latency_label.setText(f'平均延迟: {result["latency"]}ms')
                        min_max_label.setText(f'最小/最大: {result["min_latency"]}ms/{result["max_latency"]}ms')  # 显示最小/最大延迟
                        packet_loss_label.setText(f'丢包率: {result["packet_loss"]}%')
                        
                        # 增大字体，保持与进度显示的一致性
                        status_label.setFont(QFont('Arial', 12, QFont.Bold))
                        latency_label.setFont(QFont('Arial', 11))
                        min_max_label.setFont(QFont('Arial', 11))
                        packet_loss_label.setFont(QFont('Arial', 11))
                        
                        # 设置颜色
                        palette = cell_widget.palette()
                        if result['status'] == 'success':
                            palette.setColor(QPalette.Window, QColor(220, 255, 220))  # 浅绿底色
                            status_label.setStyleSheet('color: green; text-align: center;')
                        elif result['status'] == 'error' or result['status'] == 'timeout' or result['status'] == 'invalid':
                            palette.setColor(QPalette.Window, QColor(255, 220, 220))  # 浅红底色
                            status_label.setStyleSheet('color: red; text-align: center;')
                        else:
                            palette.setColor(QPalette.Window, QColor(255, 255, 220))  # 浅黄底色
                            status_label.setStyleSheet('color: orange; text-align: center;')
                        
                        cell_widget.setPalette(palette)
                        cell_widget.setAutoFillBackground(True)
                        
                        break
            else:
                continue
            break
        
        # 检查是否所有测试都已完成
        all_finished = True
        for thread in self.threads.values():
            if thread.isRunning():
                all_finished = False
                break
        
        if all_finished:
            self.start_test_btn.setEnabled(True)
            self.start_test_btn.setStyleSheet('''
                QPushButton {
                    border: 1px solid #000000;
                    border-radius: 6px;
                    padding: 10px;
                    background-color: #007bff;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0069d9;
                }
                QPushButton:pressed {
                    background-color: #0056b3;
                }
            ''')
            self.stop_test_btn.setEnabled(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PingTestApp()
    window.show()
    sys.exit(app.exec())