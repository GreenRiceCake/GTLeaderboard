# Third-party software

The application bundles Python and the following libraries. Their original
licenses and notices are included here. No Gran Turismo, PlayStation, or Naver
logos, user screenshots, or personal league results are bundled.

- Python 3.13: https://www.python.org/downloads/source/
- PySide6 / shiboken6 / Qt 6.9.1: LGPL v3 option; https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.9.1
- Qt 6.9.1 corresponding sources: https://download.qt.io/archive/qt/6.9/6.9.1/single/
- Qt third-party attributions: https://doc.qt.io/qt-6.9/licenses-used-in-qt.html
- NumPy 2.2.5: https://github.com/numpy/numpy/tree/v2.2.5
- Pillow 11.2.1: https://github.com/python-pillow/Pillow/tree/11.2.1
- ONNX Runtime 1.23.2: https://github.com/microsoft/onnxruntime/tree/v1.23.2
- PyInstaller 6.21.0 (bootloader exception): https://github.com/pyinstaller/pyinstaller/tree/v6.21.0
- Supporting Python modules (setuptools and its vendored helpers, packaging,
  charset-normalizer, typing-extensions): license texts are in the corresponding subfolders.
- Korean PP-OCRv5 recognition model: PaddleOCR / RapidAI ONNX conversion,
  Apache 2.0. Model distribution and digest are documented in models/README.md.

Qt is dynamically linked inside the one-file extraction directory. SOURCE.zip
contains the application Python source and build instructions so users can
rebuild with a modified compatible Qt/PySide6 library, including a directory
build using `python tools/build_release.py --onedir`. Debugging modifications
to LGPL-covered libraries and reverse engineering for that purpose are not
restricted by this distribution. Third-party license terms govern those components.

This notice does not assign a new open-source license to the application's own code.
