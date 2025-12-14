import sys
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFileDialog, QStackedWidget, QTableWidget, 
    QTableWidgetItem, QCheckBox, QDateEdit, QGroupBox, 
    QFormLayout, QSpinBox, QProgressBar, QTextEdit, QMessageBox,
    QHeaderView, QRadioButton, QButtonGroup, QComboBox
)
from PySide6.QtCore import Qt, QDate
from .workers import StatisticsWorker, AnalysisWorker
import json

class WizardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setup_ui()

    def setup_ui(self):
        pass

    def validate(self):
        return True

    def get_data(self):
        return {}


class PageOne(WizardPage):
    """File Selection"""
    def __init__(self, parent=None):
        self.file_path = ""
        super().__init__(parent)

    def setup_ui(self):
        self.layout.addWidget(QLabel("<h2>Step 1: 选择聊天记录</h2>"))
        
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("请选择导出的JSON文件...")
        self.path_edit.setReadOnly(True)
        
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self.browse_file)
        
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(btn_browse)
        
        self.layout.addLayout(file_layout)
        self.layout.addStretch()

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择JSON文件", "", "JSON Files (*.json)")
        if path:
            self.file_path = path
            self.path_edit.setText(path)

    def validate(self):
        if not self.file_path or not os.path.exists(self.file_path):
            QMessageBox.warning(self, "错误", "请选择有效的JSON文件")
            return False
        return True
    
    def get_data(self):
        return {'json_path': self.file_path}


class PageTwo(WizardPage):
    """Statistics & Filtering"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_data = [] # List of dicts
        self.start_ts = 0
        self.end_ts = 0

    def setup_ui(self):
        self.layout.addWidget(QLabel("<h2>Step 2: 用户统计与筛选</h2>"))

        # Filter Controls
        filter_group = QGroupBox("日期范围筛选")
        filter_layout = QHBoxLayout()
        
        self.date_start = QDateEdit()
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        
        self.date_end = QDateEdit()
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate())
        
        btn_refresh = QPushButton("刷新统计")
        btn_refresh.clicked.connect(self.refresh_stats)
        
        filter_layout.addWidget(QLabel("开始日期:"))
        filter_layout.addWidget(self.date_start)
        filter_layout.addWidget(QLabel("结束日期:"))
        filter_layout.addWidget(self.date_end)
        filter_layout.addWidget(btn_refresh)
        filter_group.setLayout(filter_layout)
        
        self.layout.addWidget(filter_group)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["选择", "排名", "用户名/显示名", "消息数"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.layout.addWidget(self.table)
        
        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("全选")
        btn_select_all.clicked.connect(self.select_all)
        btn_deselect_all = QPushButton("取消全选")
        btn_deselect_all.clicked.connect(self.deselect_all)
        
        self.lbl_info = QLabel("请点击刷新按钮加载数据")
        
        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_deselect_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.lbl_info)
        
        self.layout.addLayout(btn_layout)

    def load_data(self, json_path):
        self.current_json = json_path
        self.refresh_stats()

    def refresh_stats(self):
        start_str = self.date_start.date().toString("yyyy-MM-dd")
        end_str = self.date_end.date().toString("yyyy-MM-dd")
        
        # Convert to timestamps for passing to next step
        self.start_ts = datetime.strptime(start_str, "%Y-%m-%d").timestamp()
        # Add 1 day - 1 sec to include the end date fully
        self.end_ts = datetime.strptime(end_str, "%Y-%m-%d").timestamp() + 86399
        
        self.lbl_info.setText("正在分析数据...")
        self.table.setRowCount(0)
        
        self.worker = StatisticsWorker(self.current_json, start_str, end_str)
        self.worker.finished.connect(self.on_stats_ready)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_stats_ready(self, result):
        self.user_data = result['user_stats']
        group_name = result['group_name']
        
        self.lbl_info.setText(f"群名: {group_name} | 有效消息: {result['filtered_count']}")
        
        self.table.setRowCount(len(self.user_data))
        for i, user in enumerate(self.user_data):
            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            # Default check active users (>50 msgs)
            if user['count'] >= 50:
                chk_item.setCheckState(Qt.Checked)
            else:
                chk_item.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, chk_item)
            
            # Rank
            self.table.setItem(i, 1, QTableWidgetItem(str(i + 1)))
            
            # Name
            name = f"{user['display_name']} ({user['username']})"
            self.table.setItem(i, 2, QTableWidgetItem(name))
            
            # Count
            self.table.setItem(i, 3, QTableWidgetItem(str(user['count'])))

    def on_error(self, err):
        QMessageBox.critical(self, "错误", f"统计失败: {err}")
        self.lbl_info.setText("统计失败")

    def select_all(self):
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(Qt.Checked)

    def deselect_all(self):
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(Qt.Unchecked)

    def validate(self):
        selected = self.get_selected_users()
        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一个用户")
            return False
        return True

    def get_selected_users(self):
        users = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).checkState() == Qt.Checked:
                # user_data is sorted same as table
                users.append(self.user_data[i]['username'])
        return users

    def get_data(self):
        return {
            'users': self.get_selected_users(),
            'start_ts': self.start_ts,
            'end_ts': self.end_ts
        }


class PageThree(WizardPage):
    """Configuration & Execution"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_text = ""

    def setup_ui(self):
        self.layout.addWidget(QLabel("<h2>Step 3: 配置与执行</h2>"))
        
        # Output Config
        group_out = QGroupBox("输出设置")
        layout_out = QFormLayout()
        
        self.out_path_edit = QLineEdit()
        btn_out_browse = QPushButton("选择目录...")
        btn_out_browse.clicked.connect(self.browse_out)
        
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.out_path_edit)
        h_layout.addWidget(btn_out_browse)
        
        layout_out.addRow("输出目录:", h_layout)
        
        # Template Config
        self.out_template_edit = QLineEdit()
        self.out_template_edit.setPlaceholderText("（可选）选择Markdown模板文件...")
        btn_tpl_browse = QPushButton("选择模板...")
        btn_tpl_browse.clicked.connect(self.browse_template)
        
        h_layout_tpl = QHBoxLayout()
        h_layout_tpl.addWidget(self.out_template_edit)
        h_layout_tpl.addWidget(btn_tpl_browse)
        
        layout_out.addRow("报告模板:", h_layout_tpl)
        
        # Prompt Config
        self.out_prompt_edit = QLineEdit()
        self.out_prompt_edit.setPlaceholderText("（可选）选择提示词模板文件...")
        btn_prompt_browse = QPushButton("选择提示词...")
        btn_prompt_browse.clicked.connect(self.browse_prompt)
        
        h_layout_prompt = QHBoxLayout()
        h_layout_prompt.addWidget(self.out_prompt_edit)
        h_layout_prompt.addWidget(btn_prompt_browse)
        
        layout_out.addRow("提示词模板:", h_layout_prompt)
        
        group_out.setLayout(layout_out)
        self.layout.addWidget(group_out)

        # API Config
        group_api = QGroupBox("API 设置")
        layout_api = QFormLayout()
        
        self.api_url = QLineEdit("https://api.deepseek.com")
        self.api_url.setPlaceholderText("https://api.openai.com/v1")
        
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        
        self.model_name = QLineEdit("deepseek-chat")
        
        layout_api.addRow("API 地址:", self.api_url)
        layout_api.addRow("API Key:", self.api_key)
        layout_api.addRow("模型名称:", self.model_name)
        group_api.setLayout(layout_api)
        self.layout.addWidget(group_api)
        
        # Advanced Config
        group_adv = QGroupBox("高级参数 (通常保持默认)")
        layout_adv = QFormLayout()
        
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 20)
        self.spin_workers.setValue(10)
        
        self.spin_slices = QSpinBox()
        self.spin_slices.setRange(1, 100)
        self.spin_slices.setValue(30)
        self.spin_slices.setToolTip("每用户最大切片数")

        layout_adv.addRow("并发线程数:", self.spin_workers)
        layout_adv.addRow("最大切片数:", self.spin_slices)
        group_adv.setLayout(layout_adv)
        self.layout.addWidget(group_adv)
        
        # Log Area
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.layout.addWidget(QLabel("分析日志:"))
        self.layout.addWidget(self.txt_log)
        
        # Start Button
        self.btn_start = QPushButton("开始分析")
        self.btn_start.clicked.connect(self.start_analysis)
        self.layout.addWidget(self.btn_start)

    def browse_out(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.out_path_edit.setText(path)

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模板文件", "", "Markdown Files (*.md);;All Files (*.*)")
        if path:
            self.out_template_edit.setText(path)

    def browse_prompt(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择提示词文件", "", "Text/Markdown Files (*.txt *.md);;All Files (*.*)")
        if path:
            self.out_prompt_edit.setText(path)
            
    def set_defaults(self, json_path):
        # Default output dir to 'results' next to json
        if json_path:
            base = os.path.dirname(json_path)
            res = os.path.join(base, "results")
            self.out_path_edit.setText(res)
            
            # Try to auto-find template if exists
            tpl_path = os.path.join(base, "analysis_template.md")
            if os.path.exists(tpl_path):
                self.out_template_edit.setText(tpl_path)

    def start_analysis(self):
        if not self.out_path_edit.text():
            QMessageBox.warning(self, "提示", "请设置输出目录")
            return
        if not self.api_key.text():
            QMessageBox.warning(self, "提示", "请填写API Key")
            return

        self.btn_start.setEnabled(False)
        self.txt_log.clear()
        
        # Collect all config
        config = {
            'api_url': self.api_url.text(),
            'api_key': self.api_key.text(),
            'model_name': self.model_name.text(),
            'output_dir': self.out_path_edit.text(),
            'template_path': self.out_template_edit.text(),
            'prompt_template_path': self.out_prompt_edit.text(),
            'max_workers': self.spin_workers.value(),
            'max_slices': self.spin_slices.value(),
            # These come from global context passed via wizard
            'users': self.wizard_context.get('users', []),
            'json_path': self.wizard_context.get('json_path', ''),
            'start_ts': self.wizard_context.get('start_ts', 0),
            'end_ts': self.wizard_context.get('end_ts', 0)
        }
        
        self.worker = AnalysisWorker(config)
        self.worker.progress.connect(self.log_msg)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def log_msg(self, msg):
        self.txt_log.append(msg)
        # Scroll to bottom
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_finished(self, result):
        self.btn_start.setEnabled(True)
        QMessageBox.information(self, "完成", f"分析完成！\n报告已保存至: {self.out_path_edit.text()}")

    def on_error(self, err):
        self.btn_start.setEnabled(True)
        QMessageBox.critical(self, "出错", f"分析过程中出错: {err}")
        self.log_msg(f"ERROR: {err}")

    def set_wizard_context(self, context):
        self.wizard_context = context


class MainWizard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("微信聊天记录分析工具")
        self.resize(800, 600)
        
        self.context = {}
        
        self.layout_main = QVBoxLayout(self)
        
        # Stacked Widget
        self.stack = QStackedWidget()
        self.page1 = PageOne()
        self.page2 = PageTwo()
        self.page3 = PageThree()
        
        self.stack.addWidget(self.page1)
        self.stack.addWidget(self.page2)
        self.stack.addWidget(self.page3)
        
        self.layout_main.addWidget(self.stack)
        
        # Navigation
        self.nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("上一步")
        self.btn_next = QPushButton("下一步")
        
        self.btn_prev.clicked.connect(self.go_prev)
        self.btn_next.clicked.connect(self.go_next)
        
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_next)
        
        self.layout_main.addLayout(self.nav_layout)
        
        self.update_buttons()

    def update_buttons(self):
        idx = self.stack.currentIndex()
        self.btn_prev.setEnabled(idx > 0)
        
        if idx == 2:
            self.btn_next.setVisible(False)
        else:
            self.btn_next.setVisible(True)
            self.btn_next.setText("下一步")

    def go_next(self):
        idx = self.stack.currentIndex()
        current_page = self.stack.currentWidget()
        
        if not current_page.validate():
            return
            
        # Collect data
        data = current_page.get_data()
        self.context.update(data)
        
        if idx == 0:
            # Pass file to page 2
            self.page2.load_data(self.context['json_path'])
            
        if idx == 1:
            # Pass data to page 3
            self.page3.set_wizard_context(self.context)
            self.page3.set_defaults(self.context.get('json_path'))
        
        self.stack.setCurrentIndex(idx + 1)
        self.update_buttons()

    def go_prev(self):
        idx = self.stack.currentIndex()
        self.stack.setCurrentIndex(idx - 1)
        self.update_buttons()
