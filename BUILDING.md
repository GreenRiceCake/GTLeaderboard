# Windows 배포 · 재빌드

Windows x64, Python 3.13 x64에서 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools/setup_ocr.py
.\.venv\Scripts\python.exe tools/build_release.py
.\.venv\Scripts\python.exe tools/smoke_release.py dist/GTLeaderboard-1.0.0-windows-x64/GTLeaderboard.exe
```

소스 저장소의 테스트는 `python -m unittest discover -s tests`로 실행합니다.
개인 정보가 들어갈 수 있는 테스트 자료는 배포용 SOURCE.zip에서 제외합니다.
SOURCE.zip을 해제한 소스만으로도 앱을 재빌드할 수 있습니다.
Qt DLL을 직접 교체할 수 있는 디렉터리 빌드는 `--onedir`로 생성합니다.
라이브러리 수정 버전을 사용하려면 requirements의 해당 버전 고정을 조정해
같은 가상환경에 설치하고 재빌드합니다. 빌드에 사용한 버전은 BUILD_INFO.json에 기록됩니다.
공식 라이선스 텍스트를 다시 준비하려면 `python tools/fetch_release_licenses.py`를 실행합니다.

## 배포 파일

- `dist/GTLeaderboard-1.0.0-windows-x64-full.zip`: EXE, OCR 모델, 사용법, 라이선스, 앱 소스.
- `dist/GTLeaderboard-1.0.0-windows-x64-update.zip`: 같은 구성에서 OCR 모델 파일만 제외.
- `dist/update_manifest.json`: 자동 업데이트용 버전·변경 사항·전체 ZIP 주소·크기·SHA-256.
- `dist/SHA256SUMS.txt`: 두 ZIP과 업데이트 매니페스트의 SHA-256.
- `dist/GTLeaderboard-1.0.0-windows-x64/`: 바로 실행할 수 있는 전체 구성.

실행 파일은 PyInstaller onefile 형식이고 실행 시 내부 구성요소를 임시 폴더에
풀기 때문에 첫 화면이 나타나기까지 잠시 걸릴 수 있습니다.
([PyInstaller 공식 안내](https://pyinstaller.org/en/stable/operating-mode.html))
앱 소스, 코스 목록, 명시한 문서만 SOURCE.zip에 넣으며 개인 리그·PNG·스크린샷은 포함하지 않습니다.
현재 코드 서명은 없습니다. 이 PC의 EXE 검사와 별개로 최초 공개 전 다른 Windows PC에서도 실행을 확인하세요.
