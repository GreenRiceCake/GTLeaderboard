"""Refresh factual Korean track names from the public official page. No JS execution."""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

SOURCE = "https://www.gran-turismo.com/kr/gt7/tracklist/"


def read(url):
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def main():
    page = read(SOURCE)
    script = re.search(r'src="(/common/dist/gt7/tracklist/assets/index-[^"/]+\.js)"', page)
    if not script:
        raise RuntimeError("공식 페이지 구조가 변경되어 수동 확인이 필요합니다.")
    script_url = urljoin(SOURCE, script[1])
    app = read(script_url)
    module = re.search(r'\./tracks\.kr-[A-Za-z0-9_-]+\.js', app)
    if not module:
        raise RuntimeError("공식 한국어 코스 데이터 경로를 찾을 수 없습니다.")
    data_url = urljoin(script_url, module[0])
    source = read(data_url)
    tracks = []
    # Extract known string fields only. Never eval or import downloaded code.
    for block in re.findall(r'\{[^{}]*\}', source):
        values = {}
        for key in ("id", "baseId", "nameBase", "nameLong", "countryName"):
            match = re.search(r'\b' + key + r':("(?:\\.|[^"\\])*")', block)
            if match:
                values[key] = json.loads(match[1]).replace("\u200b", "").strip()
        if len(values) == 5:
            tracks.append({"id": values["id"], "base_id": values["baseId"], "circuit": values["nameBase"], "name": values["nameLong"], "country": values["countryName"]})
    if len(tracks) < 100 or len({t["id"] for t in tracks}) != len(tracks):
        raise RuntimeError("추출한 목록이 불완전하거나 중복되어 저장하지 않습니다.")
    tracks.sort(key=lambda t: (t["circuit"], t["name"]))
    document = {"source": SOURCE, "data_source": data_url, "retrieved_at": date.today().isoformat(), "tracks": tracks}
    target = Path(__file__).resolve().parents[1] / "gtleaderboard" / "data" / "tracks_kr.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(tracks)} layouts / {len({t['base_id'] for t in tracks})} base groups to {target}")


if __name__ == "__main__":
    main()

