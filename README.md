# GTLeaderboard

그란 투리스모 7 리그의 라운드 결과와 종합 순위를 관리하는 Windows용 프로그램입니다.

- 순위별 배점, 출전 상태, 예선 폴·패스티스트랩 보너스를 설정합니다.
- 결과를 직접 입력하거나 스크린샷을 로컬 OCR로 읽고 검토해 반영합니다.
- 라운드 수정·삭제·순서 변경 및 변경 이력을 지원합니다.
- 종합 순위를 PNG로 저장하며, PNG 안에 전체 리그 데이터를 함께 보관합니다.
- 저장한 PNG를 다시 열어 편집하거나 GTLB·CSV로 내보낼 수 있습니다.
- 총점은 종합 순위 오른쪽에 고정되며 세로 스크롤바는 그 오른쪽에 있습니다.

## 다운로드와 실행

[GitHub Releases](https://github.com/GreenRiceCake/GTLeaderboard/releases)에서
`GTLeaderboard-1.0.0-windows-x64-full.zip`을 받아 압축을 풀고 `GTLeaderboard.exe`를 실행합니다.
Python을 따로 설치할 필요가 없습니다. OCR 모델은 함께 제공되는 `models` 폴더에 있습니다.
EXE와 models 폴더를 함께 보관하세요.

업데이트 정보는 이 저장소 main 브랜치의 `update_manifest.json`에서 확인합니다.
자세한 배포 절차는 [UPDATING.md](UPDATING.md)를 참고하세요.

## 소스에서 실행

Windows x64와 Python 3.13 x64를 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/setup_ocr.py
.\.venv\Scripts\python.exe run.pyw
```

모델이 없어도 직접 입력과 리그 저장은 가능합니다. OCR을 사용할 때 모델이 필요합니다.
모델 출처와 검증 값은 [models/README.md](models/README.md)에 있습니다.

```powershell
python -m unittest discover -s tests
```

개인 리그와 원본 스크린샷, 해당 개인 자료에 의존하는 테스트는 공개 소스에 포함하지 않습니다.
원본 스크린샷이 필요한 OCR 검사는 자료가 없으면 건너뜁니다.
예시 리그는 `examples/demo.gtlb`를 열어 확인할 수 있습니다.

재빌드는 [BUILDING.md](BUILDING.md), 포함 라이브러리의 라이선스는
[packaging/licenses/THIRD_PARTY.md](packaging/licenses/THIRD_PARTY.md)를 참고하세요.
