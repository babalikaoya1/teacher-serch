"""在助手独立虚拟环境中构建安装包，不收集第三方测试模块。"""
from pathlib import Path
import os

import PyInstaller.__main__
from PyInstaller.utils.hooks import collect_submodules

os.chdir(Path(__file__).resolve().parent)
hidden = ["win32timezone", "win32crypt"]
for package in ("pywinauto", "comtypes"):
    hidden.extend(collect_submodules(package, filter=lambda name: not any(
        part in ("test", "tests", "linux") for part in name.split("."))))
arguments = ["--noconfirm", "--onefile", "--windowed", "--name", "微信同步助手",
             "--workpath", "build/windows", "--exclude-module", "comtypes.test",
             "--exclude-module", "pywinauto.tests"]
for module in sorted(set(hidden)):
    arguments.extend(["--hidden-import", module])
PyInstaller.__main__.run([*arguments, "main.py"])
