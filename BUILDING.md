# Windows 빌드 안내

소스에서 Windows 실행 파일을 만드는 방법입니다. 프로그램 사용자는 배포 ZIP을 받아 실행하면 됩니다.

## 개발 환경과 빌드

Windows x64와 Python 3.13 x64가 필요합니다. 저장소 루트에서 PowerShell로 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools/setup_ocr.py
.\.venv\Scripts\python.exe tools/build_release.py
```

`setup_ocr.py`는 OCR 모델을 다운로드하고 해시를 검증합니다.
빌드에 사용한 Python과 라이브러리 버전은 `BUILD_INFO.json`에 기록됩니다.

## 검증

소스 저장소의 테스트와 빌드한 EXE의 자체 검사를 실행합니다.
아래 경로의 `1.0.0`은 빌드한 버전에 맞게 바꿉니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tools/smoke_release.py dist/GTLeaderboard-1.0.0-windows-x64/GTLeaderboard.exe
```

배포 ZIP에 포함된 `SOURCE.zip`은 재빌드용 소스이며 테스트 자료는 포함하지 않습니다.
테스트는 저장소 소스에서 실행하고, `SOURCE.zip`으로 재빌드한 경우에는 EXE 자체 검사를 실행합니다.

## 생성되는 파일

버전이 `1.0.0`일 때 `dist` 폴더에 다음 파일이 생성됩니다.

| 파일 | 내용 |
| --- | --- |
| `GTLeaderboard-1.0.0-windows-x64/` | EXE, 외부 OCR 모델, 사용법, 라이선스, 소스 등 실행 구성 |
| `GTLeaderboard-1.0.0-windows-x64-full.zip` | OCR 모델을 포함한 전체 배포 ZIP |
| `GTLeaderboard-1.0.0-windows-x64-update.zip` | OCR 모델 파일을 제외한 수동 업데이트 ZIP |
| `update_manifest.json` | 전체 ZIP의 버전·다운로드 주소·크기·SHA-256 |
| `SHA256SUMS.txt` | 두 ZIP과 업데이트 매니페스트의 체크섬 |

EXE는 PyInstaller onefile 방식이며, OCR 모델은 EXE 옆의 `models` 폴더에서 읽습니다.

## 라이브러리 교체와 재빌드

`requirements.txt`와 `requirements-build.txt`의 버전을 조정한 뒤 같은 가상환경에서 다시 설치하고 빌드합니다.
Qt DLL을 직접 교체할 수 있는 디렉터리 빌드는 다음 명령으로 생성합니다.
출력 경로는 명령 완료 시 표시되며, 이 옵션은 배포 ZIP을 만들지 않습니다.

```powershell
.\.venv\Scripts\python.exe tools/build_release.py --onedir
```

라이선스 텍스트를 다시 준비하려면 `tools/fetch_release_licenses.py`를 실행합니다.
포함 라이브러리 안내는 [THIRD_PARTY.md](packaging/licenses/THIRD_PARTY.md)를 참고하세요.

버전 변경과 GitHub 배포 절차는 [UPDATING.md](UPDATING.md)에 정리되어 있습니다.
