# OCR 모델

현재 앱은 한국어 PP-OCRv5 인식 모델을 ONNX Runtime의 CPU 실행기로 사용합니다. 이미지나 인식 결과를 서버로 보내지 않습니다.

개발 중에는 프로젝트 루트의 이 폴더를 사용합니다. 배포본에서는 `GTLeaderboard.exe`와 같은 경로의 `models` 폴더를 사용합니다.

- 파일: `korean_PP-OCRv5_rec_mobile.onnx`
- 크기: 13,488,748바이트 (약 13.5 MB)
- SHA-256: `cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b`
- 준비 명령: 프로젝트 폴더에서 `python tools/setup_ocr.py`

준비 도구는 아래 모델을 내려받고 고정된 체크섬을 검사합니다. 앱도 로드 전에 체크섬을 검사합니다. 모델이 없는 경우 수동 기능은 그대로 사용할 수 있고, OCR 실행 시 준비 방법을 안내합니다.

출처는 [RapidAI의 모델 목록](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)과 [RapidAI가 배포한 한국어 ONNX 모델](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx)입니다. 원 모델 프로젝트는 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)입니다. 전처리·문자 해독의 입력 규격은 [RapidOCR 인식 코드](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/ch_ppocr_rec/main.py)를 참고했습니다. 재배포 시 [RapidOCR 라이선스](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE)와 [PaddleOCR 라이선스](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)를 함께 확인하세요.
