# -*- mode: python ; coding: utf-8 -*-
# AgentFloat — PyInstaller 参考配置（手动调试用）
# 注意：正式构建走 build_debug.py / build_exe.py（自动归档 + 版本写入）；
#       本 spec 与两者保持同构，便于 `pyinstaller AgentFloat.spec` 手动排查。

a = Analysis(
    ['agent_float.py'],
    pathex=['src'],
    binaries=[],
    datas=[('assets', 'assets'), ('VERSION', '.'), ('web', 'web')],
    hiddenimports=[
        # AgentFloat 包内（src 布局）动态/延迟导入兜底
        'agentfloat.app',
        'agentfloat.ui.floatball',
        'agentfloat.webshell.window',
        'agentfloat.webshell.server',
        'agentfloat.services.dsh',
        'agentfloat.services.installer',
        'agentfloat.services.update.updater',
        'agentfloat.services.skills.ai_service',
        # 第三方动态导入
        'fastapi', 'uvicorn', 'pydantic', 'webview', 'clr',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'QtWebEngine', 'QtWebEngineCore', 'QtWebEngineWidgets', 'QtWebChannel',
        'QtMultimedia', 'QtMultimediaWidgets',
        'QtSql', 'QtXml', 'QtTest',
        'QtNetwork', 'Qt3D', 'Qt3DCore', 'Qt3DRender', 'Qt3DInput', 'Qt3DLogic',
        'QtCharts', 'QtDataVisualization',
        'QtSensors', 'QtSerialPort', 'QtPositioning',
        'QtPrintSupport', 'QtQuick', 'QtQml', 'QtQmlModels', 'QtQuickWidgets',
        'QtSvg', 'QtSvgWidgets', 'QtBluetooth', 'QtNfc',
        'QtTextToSpeech', 'QtSpeech', 'QtLocation',
        'tkinter', '_tkinter', 'Tkinter', 'tcl', 'tk',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AgentFloat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\agent_float_icon.ico'],
)
