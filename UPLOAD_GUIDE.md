# GTLeaderboard 1.0.0 업로드 안내

## 저장소에 올릴 내용

`GTLeaderboard-1.0.0` 폴더 **안의 파일과 하위 폴더**를
`GreenRiceCake/GTLeaderboard` 저장소의 **main 브랜치 루트**에 올립니다.
`GTLeaderboard-1.0.0`이라는 바깥 폴더 자체를 올리지 마세요.
숨김 파일 `.gitignore`와 `.github` 폴더도 포함합니다.

`update_manifest.json`이 이미 들어 있습니다. 버전은 `1.0.0`, 설명은
`최초 정식 배포입니다.`이며, 아래 full ZIP의 실제 크기와 SHA-256을 담고 있습니다.
최초 버전 앱이 같은 버전 매니페스트를 읽으면 새 업데이트 알림을 띄우지 않습니다.

개인 리그·PNG·CSV·게임 스크린샷·모델 바이너리·빌드 캐시는 제외했습니다.
모델은 소스 저장소에 넣지 않고 배포 ZIP에 포함합니다.

## Releases에 올릴 파일

저장소의 Releases에서 **v1.0.0** 태그로 릴리스를 만듭니다.
아래 경로는 작업 폴더 `GTLeaderboard`를 기준으로 합니다.

- 필수: `dist/GTLeaderboard-1.0.0-windows-x64-full.zip` — 사용자에게 안내할 배포 ZIP. EXE와 OCR 모델 포함, 86,092,003바이트(약 82.1 MiB).
- 선택: `dist/GTLeaderboard-1.0.0-windows-x64-update.zip` — 기존 모델을 재사용하는 수동 업데이트용.
- 권장: `dist/SHA256SUMS.txt` — 체크섬.
- 선택: `dist/update_manifest.json` — main 루트에 넣은 파일과 동일한 복사본.

ZIP을 그대로 첨부한 Release를 공개한 뒤, main 루트에 매니페스트를 올립니다.
ZIP 이름을 변경하거나 다시 압축하면 매니페스트와 불일치할 수 있습니다.
GitHub Actions에서 새로 빌드한 ZIP을 사용할 경우에는 **그 빌드에서 생성된 매니페스트와 체크섬**도 함께 사용하세요.

full ZIP SHA-256:

```text
b012d4eb8680fc14d3e6eab46dde241fe4dbfe162911e369323e0237ef9a784d
```

이 작업은 로컬 파일 준비까지 완료했으며 GitHub 업로드·공개는 수행하지 않았습니다.
