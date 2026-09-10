# 随机文件选择器 / Random File Picker

一个轻量 Windows tkinter 工具：扫描根文件夹并按格式、范围、排除项和文件名过滤随机打开文件。

## 运行

需要 Python 3.10+；应用本身没有第三方依赖。

```powershell
python app.py
python -m unittest discover -s tests -v
```

设置会保存在 `%LOCALAPPDATA%\RandomFilePicker\config.json`。

## 打包 Windows 可执行文件

先安装 PyInstaller：

```powershell
python -m pip install pyinstaller
```

然后在项目目录运行：

```powershell
pyinstaller --onefile --windowed --name RandomFilePicker --add-data "locales;locales" app.py
```

生成的程序位于 `dist\RandomFilePicker.exe`。Windows 下打开文件和资源管理器定位使用系统原生关联程序。
