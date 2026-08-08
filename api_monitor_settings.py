"""
API 用量监控 — 设置对话框 Tab 页
端点增删改 + 字段映射编辑 + 测试连接
"""
import json
import logging
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QScrollArea, QMessageBox, QGroupBox, QDialog, QFileDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from api_monitor_config import (
    DEFAULTS, SAMPLE_ENDPOINT, validate_endpoint,
    resolve_template,
)

_logger = logging.getLogger("AgentFloat")


class FieldEditDialog(QDialog):
    """字段编辑弹窗"""
    def __init__(self, field=None, parent=None):
        super().__init__(parent)
        self.field = field or {"label": "", "jsonpath": "", "unit": "tokens", "display": "number"}
        self.result = None
        self.setWindowTitle("编辑字段")
        self.setMinimumWidth(280)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 标签
        layout.addWidget(QLabel("显示标签:"))
        self.label_edit = QLineEdit(self.field.get("label", ""))
        layout.addWidget(self.label_edit)

        # JSONPath
        layout.addWidget(QLabel("JSONPath:"))
        self.jsonpath_edit = QLineEdit(self.field.get("jsonpath", ""))
        self.jsonpath_edit.setPlaceholderText("$.data.total_usage")
        layout.addWidget(self.jsonpath_edit)

        # 单位
        row = QHBoxLayout()
        row.addWidget(QLabel("单位:"))
        self.unit_edit = QLineEdit(self.field.get("unit", ""))
        self.unit_edit.setPlaceholderText("tokens / 次 / ¥")
        self.unit_edit.setMaximumWidth(100)
        row.addWidget(self.unit_edit)
        row.addStretch()
        layout.addLayout(row)

        # 显示格式
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("格式:"))
        self.display_cb = QComboBox()
        self.display_cb.addItems(["number", "text", "percent"])
        self.display_cb.setCurrentText(self.field.get("display", "number"))
        row2.addWidget(self.display_cb)
        row2.addStretch()
        layout.addLayout(row2)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("确定")
        ok.clicked.connect(self._accept)
        ok.setDefault(True)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

    def _accept(self):
        self.result = {
            "label": self.label_edit.text().strip(),
            "jsonpath": self.jsonpath_edit.text().strip(),
            "unit": self.unit_edit.text().strip(),
            "display": self.display_cb.currentText(),
        }
        self.accept()


class EndpointEditDialog(QDialog):
    """端点编辑弹窗"""
    def __init__(self, endpoint=None, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint or SAMPLE_ENDPOINT.copy()
        self.result = None
        self.setWindowTitle("编辑 API 端点")
        self.setMinimumWidth(420)
        self.setMinimumHeight(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 名称
        layout.addWidget(QLabel("端点名称:"))
        self.name_edit = QLineEdit(self.endpoint.get("name", ""))
        self.name_edit.setPlaceholderText("如: OpenAI / DeepSeek")
        layout.addWidget(self.name_edit)

        # URL
        layout.addWidget(QLabel("API URL (支持 {{today}} / {{env:KEY}} 模板):"))
        self.url_edit = QLineEdit(self.endpoint.get("url", ""))
        self.url_edit.setPlaceholderText("https://api.example.com/v1/usage?date={{today}}")
        layout.addWidget(self.url_edit)

        # 方法
        row = QHBoxLayout()
        row.addWidget(QLabel("HTTP 方法:"))
        self.method_cb = QComboBox()
        self.method_cb.addItems(["GET", "POST"])
        self.method_cb.setCurrentText(self.endpoint.get("method", "GET"))
        row.addWidget(self.method_cb)
        row.addStretch()
        layout.addLayout(row)

        # Headers
        layout.addWidget(QLabel("请求 Headers (JSON):"))
        headers_json = json.dumps(self.endpoint.get("headers", {}), indent=2, ensure_ascii=False)
        self.headers_edit = QTextEdit()
        self.headers_edit.setPlaceholderText(
            '{\n  "Authorization": "Bearer {{env:API_KEY}}",\n  "Content-Type": "application/json"\n}'
        )
        self.headers_edit.setPlainText(headers_json)
        self.headers_edit.setMaximumHeight(70)
        layout.addWidget(self.headers_edit)

        # 字段列表
        layout.addWidget(QLabel("显示字段:"))
        self._field_list = QVBoxLayout()
        self._field_widgets = []
        self._refresh_fields()
        layout.addLayout(self._field_list)

        add_field_btn = QPushButton("+ 添加字段")
        add_field_btn.clicked.connect(self._add_field)
        layout.addWidget(add_field_btn)

        # 进度条字段（可选）
        layout.addWidget(QLabel("进度条映射 (可选):"))
        pf_row = QHBoxLayout()
        pf_row.addWidget(QLabel("已用:"))
        self.pf_used = QLineEdit(self.endpoint.get("progress_field", {}).get("used", ""))
        self.pf_used.setPlaceholderText("$.usage.used")
        pf_row.addWidget(self.pf_used)
        pf_row.addWidget(QLabel("总量:"))
        self.pf_total = QLineEdit(self.endpoint.get("progress_field", {}).get("total", ""))
        self.pf_total.setPlaceholderText("$.usage.limit")
        pf_row.addWidget(self.pf_total)
        layout.addLayout(pf_row)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("确定")
        ok.clicked.connect(self._accept)
        ok.setDefault(True)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

    def _refresh_fields(self):
        # 清空
        while self._field_list.count():
            item = self._field_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._field_widgets.clear()

        for i, f in enumerate(self.endpoint.get("fields", [])):
            row = QHBoxLayout()
            lbl = QLabel(f"{f.get('label', '?')} — {f.get('jsonpath', '?')}")
            lbl.setStyleSheet("color: #666; font-size: 11px;")
            row.addWidget(lbl)
            row.addStretch()
            edit_btn = QPushButton("编辑")
            edit_btn.clicked.connect(lambda checked, idx=i: self._edit_field(idx))
            row.addWidget(edit_btn)
            del_btn = QPushButton("✕")
            del_btn.setFixedWidth(28)
            del_btn.clicked.connect(lambda checked, idx=i: self._delete_field(idx))
            row.addWidget(del_btn)
            self._field_list.addLayout(row)
            self._field_widgets.append(row)

    def _add_field(self):
        dlg = FieldEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.result:
            self.endpoint.setdefault("fields", []).append(dlg.result)
            self._refresh_fields()

    def _edit_field(self, idx):
        dlg = FieldEditDialog(self.endpoint["fields"][idx], parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.result:
            self.endpoint["fields"][idx] = dlg.result
            self._refresh_fields()

    def _delete_field(self, idx):
        del self.endpoint["fields"][idx]
        self._refresh_fields()

    def _accept(self):
        # 解析 headers
        try:
            headers = json.loads(self.headers_edit.toPlainText())
        except json.JSONDecodeError:
            QMessageBox.warning(self, "格式错误", "Headers 不是合法的 JSON")
            return

        self.result = {
            "name": self.name_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "method": self.method_cb.currentText(),
            "headers": headers,
            "body": self.endpoint.get("body"),
            "fields": self.endpoint.get("fields", []),
        }
        if self.pf_used.text().strip() and self.pf_total.text().strip():
            self.result["progress_field"] = {
                "used": self.pf_used.text().strip(),
                "total": self.pf_total.text().strip(),
            }
        errors = validate_endpoint(self.result)
        if errors:
            QMessageBox.warning(self, "配置错误", "\n".join(errors))
            return
        self.accept()


class ApiMonitorSettingsTab(QWidget):
    """API 用量监控设置页"""

    config_changed = pyqtSignal(dict)  # 发出新的 api_monitor 配置

    def __init__(self, api_monitor_config=None, parent=None, theme="light"):
        super().__init__(parent)
        self._config = (api_monitor_config or DEFAULTS).copy()
        self._endpoints = self._config.get("endpoints", [])
        self._theme = theme
        self._hint = None
        self._ep_labels = []
        self._setup_ui()
        self.set_theme(theme)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        # 启用开关
        row = QHBoxLayout()
        self._enabled_cb = QCheckBox("启用 API 余额监控（浮窗角标）")
        self._enabled_cb.setChecked(self._config.get("enabled", False))
        self._enabled_cb.toggled.connect(self._emit_config)
        row.addWidget(self._enabled_cb)
        row.addStretch()
        layout.addLayout(row)

        # 监控设置
        mon_group = QGroupBox("监控设置")
        mon_layout = QVBoxLayout(mon_group)
        mon_layout.setSpacing(6)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("刷新间隔 (秒):"))
        self._interval_sb = QSpinBox()
        self._interval_sb.setRange(10, 3600)
        self._interval_sb.setValue(self._config.get("poll_interval_seconds", 60))
        self._interval_sb.valueChanged.connect(self._emit_config)
        r2.addWidget(self._interval_sb)
        r2.addStretch()
        r2.addWidget(QLabel("低余额警告:"))
        self._warn_sb = QDoubleSpinBox()
        self._warn_sb.setRange(0, 100000)
        self._warn_sb.setDecimals(2)
        self._warn_sb.setValue(float(self._config.get("low_balance_warn", 5.0)))
        self._warn_sb.setToolTip("余额低于此值时角标变红，0 表示禁用警告")
        self._warn_sb.valueChanged.connect(self._emit_config)
        r2.addWidget(self._warn_sb)
        mon_layout.addLayout(r2)

        layout.addWidget(mon_group)

        # 端点列表
        ep_group = QGroupBox("API 端点")
        ep_layout = QVBoxLayout(ep_group)
        ep_layout.setSpacing(6)

        self._ep_list_layout = QVBoxLayout()
        ep_layout.addLayout(self._ep_list_layout)
        self._refresh_endpoint_list()

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ 添加端点")
        add_btn.clicked.connect(self._add_endpoint)
        btn_row.addWidget(add_btn)

        # Claude 辅助配置按钮
        claude_btn = QPushButton("🧠 Claude 帮我配置")
        claude_btn.setToolTip(
            "启动 Claude Code 对话，让 AI 帮你找出正确的 API 端点和 JSONPath 映射"
        )
        claude_btn.clicked.connect(self._launch_claude_assist)
        btn_row.addWidget(claude_btn)
        btn_row.addStretch()
        ep_layout.addLayout(btn_row)

        layout.addWidget(ep_group)

        # 导入/导出
        io_row = QHBoxLayout()
        export_btn = QPushButton("导出配置")
        export_btn.clicked.connect(self._export_config)
        io_row.addWidget(export_btn)
        import_btn = QPushButton("导入配置")
        import_btn.clicked.connect(self._import_config)
        io_row.addWidget(import_btn)
        io_row.addStretch()
        layout.addLayout(io_row)

        # 说明
        hint = QLabel(
            "💡 URL 支持模板变量: {{today}} {{now_iso}} {{timestamp}} {{env:VAR_NAME}}\n"
            "Headers 中的 {{env:API_KEY}} 会被自动替换为环境变量值"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8E8E93; font-size: 10px;")
        layout.addWidget(hint)
        self._hint = hint

        layout.addStretch()

    def _label_css(self, kind):
        """按当前主题返回标签样式（endpoint / hint）"""
        if self._theme == "dark":
            tx = "#EBEBF5"
            hi = "#98989F"
        else:
            tx = "#1C1C1E"
            hi = "#8E8E93"
        if kind == "hint":
            return f"color: {hi}; font-size: 10px;"
        return f"color: {tx}; font-size: 11px;"

    def set_theme(self, theme):
        """切换整个 API 监控设置页的主题（含子对话框继承）"""
        self._theme = theme
        if theme == "dark":
            tx = "#EBEBF5"
            hi = "#98989F"
            card = "#333336"
            bd = "#48484A"
            ac = "#0A84FF"
        else:
            tx = "#1C1C1E"
            hi = "#8E8E93"
            card = "#FFFFFF"
            bd = "#E5E5EA"
            ac = "#007AFF"
        self.setStyleSheet(
            f"QGroupBox {{ color: {tx}; background: {card}; border: 1px solid {bd};"
            f" border-radius: 8px; margin-top: 8px; padding-top: 12px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
            f"QLabel {{ color: {tx}; }}"
            f"QCheckBox {{ color: {tx}; spacing: 6px; }}"
            f"QPushButton {{ color: {ac}; background: {card}; border: 1px solid {bd};"
            f" border-radius: 6px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ background: {bd}; }}"
            f"QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QComboBox {{ color: {tx};"
            f" background: {card}; border: 1px solid {bd}; border-radius: 4px; padding: 2px 6px; }}"
        )
        if self._hint is not None:
            self._hint.setStyleSheet(self._label_css("hint"))
        for lbl in self._ep_labels:
            lbl.setStyleSheet(self._label_css("endpoint"))

    def _refresh_endpoint_list(self):
        while self._ep_list_layout.count():
            item = self._ep_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._ep_labels = []

        for i, ep in enumerate(self._endpoints):
            row = QHBoxLayout()
            lbl = QLabel(f"{ep.get('name', '?')} — {ep.get('url', '?')[:50]}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(self._label_css("endpoint"))
            row.addWidget(lbl, 1)
            self._ep_labels.append(lbl)
            edit_btn = QPushButton("编辑")
            edit_btn.clicked.connect(lambda checked, idx=i: self._edit_endpoint(idx))
            row.addWidget(edit_btn)
            del_btn = QPushButton("✕")
            del_btn.setFixedWidth(28)
            del_btn.clicked.connect(lambda checked, idx=i: self._delete_endpoint(idx))
            row.addWidget(del_btn)
            self._ep_list_layout.addLayout(row)

    def _add_endpoint(self):
        dlg = EndpointEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.result:
            self._endpoints.append(dlg.result)
            self._refresh_endpoint_list()
            self._emit_config()

    def _edit_endpoint(self, idx):
        dlg = EndpointEditDialog(self._endpoints[idx], parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.result:
            self._endpoints[idx] = dlg.result
            self._refresh_endpoint_list()
            self._emit_config()

    def _delete_endpoint(self, idx):
        del self._endpoints[idx]
        self._refresh_endpoint_list()
        self._emit_config()

    def _launch_claude_assist(self):
        """启动 Claude Code 辅助用户配置 API 端点"""
        import subprocess, shutil, os

        claude_path = shutil.which("claude")
        if not claude_path:
            QMessageBox.warning(self, "Claude 未安装",
                "未检测到 Claude Code。\n请先运行: npm install -g @anthropic-ai/claude-code")
            return

        prompt = (
            "请帮我配置 API 用量监控端点。\n\n"
            "我需要你输出一个或多个 API 端点的配置 JSON，用于定时查询 API 使用量。\n\n"
            "请先问我以下问题（逐个问，不要一次问完）：\n"
            "1. 我使用的是哪个 API 平台？（OpenAI / Anthropic / DeepSeek / 通义千问 / 其他）\n"
            "2. 我的 API Key 存储在哪？（环境变量名 / 直接提供）\n"
            "3. 我想监控哪些指标？（已用 token 数 / 剩余额度 / 调用次数 / 费用）\n\n"
            "了解清楚后，请输出严格遵循以下格式的纯 JSON（不要 ```json 包裹，不要其他文字）：\n"
            '{"endpoints": [{"name": "平台名", "url": "https://...", "method": "GET", '
            '"headers": {"Authorization": "Bearer {{env:VAR}}"}, '
            '"fields": [{"label": "已用量", "jsonpath": "$.data.usage", "unit": "tokens", "display": "number"}], '
            '"progress_field": {"used": "$.data.usage", "total": "$.data.limit"}}]}\n\n'
            "如果该平台没有公开的 usage API，请诚实告知并建议替代方案。"
        )

        try:
            # 将 prompt 通过 stdin 传给 claude
            subprocess.Popen(
                ["wt", "--", claude_path, "-p", prompt],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            QMessageBox.information(self, "Claude 已启动",
                "Claude Code 已在 Windows Terminal 中启动。\n\n"
                "请按照 AI 引导描述你的 API 平台，\n"
                "然后将输出的 JSON 配置复制到设置中。")
        except Exception:
            # fallback
            subprocess.Popen(
                ["cmd", "/c", "start", "Claude Code", claude_path, "-p", prompt],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            QMessageBox.information(self, "Claude 已启动",
                "Claude Code 已在命令提示符中启动。")

    def _export_config(self):
        import os
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 API 监控配置", "api_monitor_config.json",
            "JSON 文件 (*.json)"
        )
        if path:
            export_data = {
                "enabled": self._enabled_cb.isChecked(),
                "panel_side": self._side_cb.currentText(),
                "panel_width": self._width_sb.value(),
                "panel_opacity": self._opacity_sl.value() / 100.0,
                "poll_interval_seconds": self._interval_sb.value(),
                "endpoints": self._endpoints,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "导出成功", f"配置已保存到:\n{path}")

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 API 监控配置", "",
            "JSON 文件 (*.json)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config.update(data)
                self._endpoints = self._config.get("endpoints", [])
                self._enabled_cb.setChecked(self._config.get("enabled", False))
                self._side_cb.setCurrentText(self._config.get("panel_side", "left"))
                self._width_sb.setValue(self._config.get("panel_width", 220))
                self._opacity_sl.setValue(int(self._config.get("panel_opacity", 0.82) * 100))
                self._interval_sb.setValue(self._config.get("poll_interval_seconds", 60))
                self._refresh_endpoint_list()
                self._emit_config()
                QMessageBox.information(self, "导入成功", f"已导入 {len(self._endpoints)} 个端点")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"无法解析配置文件:\n{e}")

    def _emit_config(self):
        config = {
            "enabled": self._enabled_cb.isChecked(),
            "poll_interval_seconds": self._interval_sb.value(),
            "low_balance_warn": self._warn_sb.value(),
            "endpoints": self._endpoints,
        }
        self._config = config
        self.config_changed.emit(config)

    def get_config(self):
        return self._config
