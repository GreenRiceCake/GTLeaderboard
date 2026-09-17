# GitHub 자동 업데이트 배포 — v1.0.0

앱은 시작 약 1초 후 백그라운드에서 다음 주소를 확인합니다.

```text
https://raw.githubusercontent.com/GreenRiceCake/GTLeaderboard/main/update_manifest.json
```

이 주소는 **GTLeaderboard 저장소의 main 브랜치 루트에 있는 파일**을 가리킵니다.
프로그램에 주소가 고정되어 있으며 사용자가 변경할 수 없습니다. 이전 버전에서 저장한
사용자 지정 주소도 무시합니다. 새 버전 배포 시 main의 같은 파일을 갱신합니다.

## 이번에 업로드할 파일

GitHub 저장소의 Releases → 새 Release에서 태그 **v1.0.0**을 만들고 ZIP을 먼저 첨부합니다.
ZIP은 다시 압축하거나 이름을 바꾸지 말고 그대로 첨부하세요.

| 파일 | 업로드 위치 | 역할 |
| --- | --- | --- |
| `dist/update_manifest.json` | **main 브랜치 루트의 update_manifest.json** | 필수. 최신 버전·설명·다운로드 URL·ZIP 크기·SHA-256 |
| `dist/GTLeaderboard-1.0.0-windows-x64-full.zip` | v1.0.0 Release 첨부 | 필수. EXE와 OCR 모델 포함 |
| `dist/GTLeaderboard-1.0.0-windows-x64-update.zip` | v1.0.0 Release 첨부 | 선택. 기존 모델을 재사용하는 수동 ZIP 업데이트용 |
| `dist/SHA256SUMS.txt` | v1.0.0 Release 첨부 | 권장. 파일 체크섬 확인 |

ZIP을 첨부한 Release를 먼저 공개하고 다운로드 가능한지 확인한 뒤,
**dist/update_manifest.json을 main 브랜치 루트의 update_manifest.json으로 업로드·갱신**합니다.
Release 첨부에만 JSON을 올리면 v0.8.3 이후 앱에는 전달되지 않습니다.
이전 버전(0.7.0부터 0.8.2까지)의 기본 확인 주소를 계속 지원하려면 같은 JSON을 Latest Release에도 첨부하세요.
앱은 GitHub 로그인 토큰을 사용하지 않으므로 로그인 없이 다운로드할 수 있어야 합니다.
이 작업에서는 저장소에 실제 업로드하거나 공개하지 않았습니다.

ZIP 안의 `release-manifest.json`은 내부 파일 검사용입니다. 따로 업로드하지 않습니다.
앱 소스 `SOURCE.zip`도 전체·수동 업데이트 ZIP 안에 이미 포함되어 있습니다.
사용자의 리그 PNG·GTLB·스크린샷은 업로드 대상이 아닙니다.

업데이트 창에서는 주소를 확인·복사할 수 있지만 수정할 수 없습니다.
시작 시 자동 확인과 ‘지금 업데이트 확인’은 모두 같은 고정 주소를 사용합니다.

## 앱의 동작

1. 처음에는 v1.0.0 전체 ZIP을 풀어 실행합니다. 0.6.x 사용자는 기존 로컬 ZIP 메뉴로도 이동할 수 있습니다.
2. **프로그램 시작 시 새 버전 자동 확인**이 기본으로 켜져 있습니다. 도움말에서 해제할 수 있습니다.
3. 최신/더 오래된 버전이면 시작 알림을 띄우지 않습니다. 새 버전이면 ‘업데이트 보기’를 안내합니다.
4. **도움말 → 버전 · 업데이트**에서 언제든 수동 확인하고 변경 사항을 읽을 수 있습니다.
5. **다운로드 · 업데이트 준비**를 누르고 새 버전 폴더를 만들 위치를 고릅니다.
6. HTTPS 다운로드 → ZIP 크기·SHA-256 검사 → 내부 버전·파일 해시·저장 형식·모델 검사 → 새 폴더 확정 순서로 진행합니다.
7. **현재 리그 저장 후 새 버전 실행**을 누르면 PNG 저장 후 새 앱에서 이어서 엽니다. 저장 취소·실패 또는 프로세스 시작 실패 시 현재 앱을 유지합니다. 폴더를 열어 직접 실행할 수도 있습니다.

설정은 Windows 사용자별 QSettings에 보관되어 다른 버전 폴더로 이동해도 유지됩니다.
앱 실행을 기다리게 하지 않도록 네트워크 검사는 별도 스레드에서 진행합니다.
확인 실패나 오프라인 상태에서는 기존 기능을 계속 사용할 수 있습니다.
다운로드 중 취소하면 임시 ZIP을 정리합니다. 파일 준비가 이미 시작되었다면 그 작업을 마친 뒤 닫습니다.

기존 폴더와 리그 파일을 덮어쓰지 않으므로 검증 실패 시 기존 앱을 그대로 쓸 수 있습니다.
준비가 완료된 뒤에도 이전 EXE로 돌아갈 수 있습니다. 현재 방식은 별도 버전 폴더 준비이며,
설치된 EXE는 제자리에서 교체하지 않습니다. 사용자가 실행 버튼을 누르면 새 프로세스를 시작하고 현재 창을 닫습니다.
네트워크 검사는 업데이트 정보·패키지만 요청하며 리그나 스크린샷을 전송하지 않습니다.

## 매니페스트 규격

실제 업로드할 JSON은 **dist/update_manifest.json**입니다. 예시의 GTMate 버전·해시를 복사하지 않고
완성된 GTLeaderboard ZIP에서 실제 값을 생성합니다.

- `app`: `GTLeaderboard`
- `schema_version`: `1`
- `version`: 앱과 ZIP 내부의 버전, 예: `1.0.0` (숫자 세 부분)
- `title`, `changelog`: 변경 사항. 앱은 HTML로 해석하지 않고 일반 텍스트로 표시합니다.
- `update_type`: `zip`
- `download_url`: **실제 HTTPS 주소 문자열**. `[설명](주소)` 같은 Markdown 문법을 넣지 않습니다.
- `min_updater_protocol`: `1`. GTLeaderboard의 프로토콜 번호이며 다른 앱의 번호와 호환을 의미하지 않습니다.
- `transactional_package`: `type`, `url`, `size`(바이트), `sha256`, `package_manifest`.
- `transactional_package.package_manifest`: `release-manifest.json`.

온라인 자동 업데이트에는 **full ZIP**을 사용합니다. 모델 누락이나 모델 버전 변경에도
동일한 절차로 준비할 수 있게 하기 위해서입니다. 같은 앱 버전 이하의 재설치는 막습니다.
SHA-256은 매니페스트가 신뢰할 수 있다는 전제에서 다운로드 파일을 검증합니다. 전자서명 기능은 아닙니다.

## 다음 버전 배포

1. `gtleaderboard/__init__.py`의 버전과 `RELEASE_NOTES.md` 맨 위 설명을 수정합니다.
2. `python -m unittest discover -s tests` 후 `python tools/build_release.py`를 실행합니다.
3. 빌드 도구가 두 ZIP, **실제 크기·해시를 넣은 update_manifest.json**, SHA256SUMS.txt를 함께 만듭니다.
4. 새 버전 태그의 Release에 ZIP을 업로드하고 공개한 뒤 main 루트의 update_manifest.json을 갱신합니다. 기존 앱 지원용으로 Latest Release에도 같은 JSON을 첨부할 수 있습니다.
5. 이전 앱의 ‘지금 업데이트 확인’으로 새 버전 발견 → 다운로드 → 새 폴더 실행을 확인합니다.

ZIP만 변경했다면 반드시 매니페스트도 다시 만드세요. 버전 숫자만 임의로 올리면
ZIP 내부 버전 검사에서 거부됩니다. 매니페스트만 다시 생성하는 명령은 다음과 같습니다.

```powershell
python tools/make_update_manifest.py dist/GTLeaderboard-1.0.0-windows-x64-full.zip
```

개별 생성 후에는 SHA256SUMS.txt의 매니페스트 체크섬도 새 값으로 갱신해야 합니다.
보통은 `python tools/build_release.py --repackage`로 ZIP·매니페스트·체크섬을 함께 생성하세요.

`.github/workflows/release.yml`도 매니페스트를 생성하고 ZIP들과 함께 초안 Release에 첨부합니다.
공개는 운영자가 검토 후 수행합니다. **workflow가 main의 JSON을 자동 커밋하지는 않습니다.** Release 공개 후 main 루트의 파일은 운영자가 갱신해야 합니다. 이 작업에서는 원격 GitHub Actions를 실행하지 않았습니다.
