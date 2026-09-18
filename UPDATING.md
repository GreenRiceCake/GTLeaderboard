# 업데이트 배포 안내

앱은 다음 고정 주소의 매니페스트에서 새 버전을 확인합니다.

```text
https://raw.githubusercontent.com/GreenRiceCake/GTLeaderboard/main/update_manifest.json
```

매니페스트는 **main 브랜치 루트**에 있어야 합니다. Release 첨부 파일로만 올리면 앱이 읽을 수 없습니다.

## 버전 준비

1. `gtleaderboard/__init__.py`의 버전과 `RELEASE_NOTES.md` 맨 위 릴리스 설명을 수정합니다. README와 배포 안내문의 버전도 맞춥니다.
2. [BUILDING.md](BUILDING.md)에 따라 테스트, 빌드 및 EXE 자체 검사를 실행합니다.
3. `dist`에 생성된 ZIP·매니페스트·체크섬을 한 묶음으로 사용합니다.

아래는 `1.0.0`의 예시입니다. 다음 배포에서는 버전과 태그를 함께 바꿉니다.

| 파일 | 게시 위치 | 용도 |
| --- | --- | --- |
| `dist/GTLeaderboard-1.0.0-windows-x64-full.zip` | `v1.0.0` Release 첨부 | 필수. 사용자 다운로드와 온라인 업데이트 |
| `dist/GTLeaderboard-1.0.0-windows-x64-update.zip` | 같은 Release 첨부 | 선택. 기존 모델을 재사용하는 수동 업데이트 |
| `dist/SHA256SUMS.txt` | 같은 Release 첨부 | 권장. 파일 체크섬 |
| `dist/update_manifest.json` | main 루트의 `update_manifest.json` | 필수. 최신 버전 안내와 ZIP 검증 정보 |

## 게시 순서

1. 배포할 소스 커밋에 `v1.0.0` 형식의 태그를 지정합니다. 태그 버전과 앱 버전이 같아야 합니다.
2. 해당 태그의 Release에 full ZIP과 필요한 첨부 파일을 올립니다. ZIP 이름과 내용은 그대로 유지합니다.
3. Release를 공개하고 매니페스트의 다운로드 주소로 로그인 없이 ZIP을 받을 수 있는지 확인합니다.
4. **같은 빌드의** `dist/update_manifest.json`을 main 루트에 복사해 커밋하고 푸시합니다.
5. 이전 버전 앱에서 업데이트 확인 → 다운로드 → 새 폴더 실행을 확인합니다. 최초 배포는 같은 버전을 최신으로 판단하는지 확인합니다.

ZIP 안의 `release-manifest.json`은 내부 파일 검사용이므로 따로 게시하지 않습니다.
라이선스와 재빌드용 `SOURCE.zip`도 배포 ZIP에 포함됩니다.

## GitHub Actions 사용

`.github/workflows/release.yml`은 수동 실행 또는 `v*` 태그 푸시로 Windows 빌드·테스트·EXE 검사를 실행합니다.
태그 실행은 생성한 파일을 첨부한 **초안 Release**를 만듭니다. 검토 후 공개합니다.
main의 매니페스트는 자동으로 갱신하지 않으므로 게시 순서의 4번을 직접 수행합니다.

로컬 빌드와 Actions 빌드는 같은 버전이어도 ZIP 해시가 다를 수 있습니다.
실제 Release에 첨부한 ZIP과 **같은 빌드에서 생성된 매니페스트·체크섬**을 사용하세요.

## 매니페스트와 패키지 검증

빌드 도구가 실제 full ZIP의 크기와 SHA-256을 계산해 `dist/update_manifest.json`을 생성합니다.

- `app`: `GTLeaderboard`
- `schema_version`: `1`
- `version`: 앱과 ZIP 내부의 버전. 예: `1.0.0`
- `title`, `changelog`: 업데이트 제목과 설명. 일반 텍스트로 표시합니다.
- `update_type`: `zip`
- `download_url`: 해당 버전 Release의 full ZIP HTTPS 주소
- `min_updater_protocol`: `1`
- `transactional_package`: `type`, `url`, `size`, `sha256`, `package_manifest`
- `transactional_package.package_manifest`: `release-manifest.json`

다운로드 URL은 Markdown 링크가 아닌 URL 문자열이어야 합니다.
SHA-256은 파일의 손상·불일치를 확인하는 값이며 배포자 인증용 전자서명은 아닙니다.

ZIP을 다시 만들면 매니페스트와 체크섬도 함께 갱신해야 합니다.
기존 EXE를 유지하며 문서와 ZIP을 다시 구성할 때는 빌드 가상환경에서 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe tools/build_release.py --repackage
```

이미 공개한 릴리스는 가능하면 새 버전으로 배포합니다. 같은 버전 파일을 교체해도 기존 사용자는 새 버전 알림을 받지 않습니다.
저장 형식이 바뀌면 업데이터 호환 검사와 내부 매니페스트의 `leagueSchema`도 함께 점검합니다.
모델이 바뀌면 기존 모델 재사용을 거부하므로 full ZIP을 제공합니다.

## 앱의 업데이트 동작

시작 시 새 버전 확인은 기본으로 켜져 있으며 도움말에서 해제할 수 있습니다.
**도움말 → 버전 · 업데이트**에서 수동으로 확인할 수도 있습니다.
같거나 더 오래된 버전이면 시작 알림을 띄우지 않습니다.

사용자가 업데이트 준비를 실행하면 ZIP의 크기·해시와 내부 버전·파일·저장 형식·모델을 검증한 뒤 새 폴더에 준비합니다.
**현재 리그 저장 후 새 버전 실행**을 누르면 PNG를 저장하고 새 앱에서 이어서 엽니다.
저장 취소·실패 또는 새 앱 시작 실패 시 현재 앱을 유지합니다.

기존 앱과 리그 파일을 덮어쓰지 않으며, 설정은 Windows 사용자별로 유지됩니다.
네트워크 확인이 실패하거나 오프라인이어도 기존 기능을 사용할 수 있습니다.
업데이트 요청에는 리그나 스크린샷을 전송하지 않습니다.
