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

## 카페 · GitHub

GitHub Release에는 전체 ZIP을 첨부하고, 공개 후 update_manifest.json을 main 브랜치 루트에 갱신합니다. 이전 버전 지원을 위해 같은 JSON을 Latest Release에도 첨부할 수 있습니다. 업데이트 ZIP과 SHA256SUMS.txt도 함께 제공할 수 있습니다. 카페의 첨부 용량 제한 때문에
첨부가 불가능하면 GitHub Release 링크를 게시할 수 있습니다.
저장소 업로드 전 개인 파일이 추적되지 않는지 확인하고, 전체 작업 폴더를 올리지 마세요.
`.github/workflows/release.yml`은 수동 실행 또는 `v1.0.0` 같은 태그로
Windows 빌드·테스트·EXE 검사 후 산출물을 남깁니다. 태그 실행은 공개 전 검토할
**초안 Release**를 만듭니다. 현재 원격 저장소 생성·업로드·공개는 수행하지 않았습니다.

새 버전은 `gtleaderboard/__init__.py`와 릴리스 노트·안내문 버전을 함께 수정합니다.
ZIP 내부 release-manifest.json은 파일 목록/크기/SHA-256, 모델 해시, 지원 저장 형식을 기록합니다.
다음 버전이 저장 형식을 변경하면 updater의 호환 검사와 manifest의 leagueSchema도 같이 변경해야 합니다.
해시는 손상 검사용이며 배포자 인증용 전자서명은 아닙니다.
모델 버전이 바뀌면 기존 모델 재사용을 거부하므로 전체 패키지를 제공합니다.

빌드는 dist/update_manifest.json을 ZIP의 실제 버전·크기·해시로 생성합니다.
앱은 GreenRiceCake/GTLeaderboard의 main/update_manifest.json Raw 주소를 고정 사용합니다. 사용자 지정 주소 설정은 무시합니다.
업로드할 파일과 공개 순서는 UPDATING.md를 참고하세요. 기존 앱·리그는 덮어쓰지 않습니다.

## GitHub 업로드 폴더 준비

빌드 완료 후 `python tools/prepare_github_upload.py`를 실행하면
`github-upload/GTLeaderboard-1.0.0/`에 공개용 소스와 같은 빌드의 `update_manifest.json`을 모읍니다.
이 폴더 **안의 내용**을 main 브랜치 루트에 올립니다. `.github`와 `.gitignore`도 포함합니다.
개인 리그·원본 스크린샷·개인 자료에 의존하는 테스트·빌드 캐시·모델 바이너리는 제외합니다.
이미 파일이 있는 대상은 덮어쓰지 않습니다. 재준비 시 명령 뒤에 새 대상 폴더를 지정하세요.
GitHub Actions에서 다시 빌드했다면 그 빌드의 ZIP과 매니페스트를 함께 사용해야 합니다.
