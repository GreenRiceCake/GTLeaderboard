"""Deterministic, complete season sheets, independent of the editor viewport."""

from dataclasses import dataclass
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from .domain import ValidationError, standings, validate_league
from .storage import atomic_write
from .sheet_content import bonus_description, footer_note, round_display, season_caption, stack_description

NAVY = "#142638"
INK = "#203449"
MUTED = "#607587"
TEAL = "#007f78"
WRAP = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter


def font(size, bold=False):
    value = QFont("Malgun Gothic")
    value.setPixelSize(size)
    value.setBold(bold)
    return value


def text_height(text, width, size, bold=False):
    return QFontMetricsF(font(size, bold)).boundingRect(QRectF(0, 0, width, 10000), int(WRAP), str(text)).height()


@dataclass
class SheetLayout:
    width: int
    height: int
    columns: list[int]
    title_height: int
    header_height: int
    row_heights: list[int]
    rows: list[dict]
    footer_height: int


def measure_sheet(league):
    validate_league(league)
    rows = standings(league)
    name_width = min(330, max(230, int(max((QFontMetricsF(font(17, True)).horizontalAdvance(d.name) for d in league.drivers), default=0)) + 32))
    round_width = max(132, (1280 - 64 - 60 - name_width - 116) // max(1, len(league.rounds)))
    columns = [60, name_width] + [round_width] * len(league.rounds) + [116]
    if not league.rounds:
        columns[1] = max(columns[1], 1040)
    width = sum(columns) + 64
    title_height = max(118, int(text_height(league.name, width - 100, 30, True)) + 76)
    header_height = max([84] + [int(text_height(r.name, round_width - 20, 16, True) + text_height(r.track_name, round_width - 20, 13)) + 34 for r in league.rounds])
    row_heights = [max(36, int(text_height(r["name"], name_width - 28, 17, True)) + 14) for r in rows]
    footer_height = 218
    return SheetLayout(width, title_height + header_height + sum(row_heights) + footer_height + 64, columns, title_height, header_height, row_heights, rows, footer_height)


def render_sheet(league, scale=2):
    """One image contains every driver/round; never truncate to fit a viewport."""
    layout = measure_sheet(league)
    if scale not in (1, 2):
        raise ValidationError("PNG 해상도 배율은 1 또는 2여야 합니다.")
    if layout.width * layout.height * scale * scale > 60_000_000:
        raise ValidationError("전체 표가 이미지 크기 한도를 넘습니다. 기본 해상도를 선택하거나 드라이버·라운드 수를 줄여 주세요.")
    image = QImage(layout.width * scale, layout.height * scale, QImage.Format.Format_RGB32)
    if image.isNull():
        raise ValidationError("이미지를 만들 메모리가 부족합니다.")
    image.fill(QColor("#edf2f6"))
    p = QPainter(image)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.scale(scale, scale)

        def rect(x, y, w, h, color):
            p.fillRect(QRectF(x, y, w, h), QColor(color))

        def text(x, y, w, h, value, size=16, color=INK, bold=False, align=LEFT):
            p.setFont(font(size, bold))
            p.setPen(QColor(color))
            p.drawText(QRectF(x, y, w, h), int(align | WRAP), str(value))

        width = layout.width
        content = width - 64
        rect(0, 0, width, layout.title_height, NAVY)
        rect(32, 26, 34, 4, "#40d0b5")
        text(78, 17, content - 46, 24, "GT LEAGUE  /  SEASON STANDINGS", 12, "#9cb6c8", True)
        text(32, 43, content, layout.title_height - 77, league.name, 30, "#ffffff", True)
        confirmed = sum(r.confirmed for r in league.rounds)
        text(32, layout.title_height - 32, content, 22, season_caption(league), 13, "#b6cbd6")

        y = layout.title_height
        x = 32
        for index, col_width in enumerate(layout.columns):
            total = index == len(layout.columns) - 1
            rect(x, y, col_width, layout.header_height, TEAL if total else "#e4ecf2")
            if index == 0:
                text(x, y, col_width, layout.header_height, "순위", 14, bold=True, align=CENTER)
            elif index == 1:
                text(x + 14, y, col_width - 28, layout.header_height, "드라이버", 15, bold=True)
            elif total:
                text(x, y, col_width, layout.header_height, "총 포인트", 15, "#ffffff", True, CENTER)
            else:
                rnd = league.rounds[index - 2]
                name_height = int(text_height(rnd.name, col_width - 20, 16, True)) + 4
                text(x + 10, y + 10, col_width - 20, name_height, rnd.name, 16, TEAL if rnd.confirmed else MUTED, True, CENTER)
                text(x + 10, y + 14 + name_height, col_width - 20, layout.header_height - name_height - 24, rnd.track_name, 13, MUTED, align=CENTER)
            x += col_width

        y += layout.header_height
        for index, (row, height) in enumerate(zip(layout.rows, layout.row_heights)):
            rect(32, y, content, height, "#ffffff" if index % 2 == 0 else "#f5f8fa")
            rank = row["rank"]
            if confirmed and rank <= 3:
                rect(32, y, 3, height, ("#bc9135", "#8a9caa", "#ad8066")[rank - 1])
            x = 32
            text(x, y, layout.columns[0], height, rank if confirmed else "—", 17, TEAL if rank <= 3 and confirmed else MUTED, True, CENTER)
            x += layout.columns[0]
            text(x + 14, y, layout.columns[1] - 28, height, row["name"], 17, INK, True)
            x += layout.columns[1]
            for rnd, points, col_width in zip(league.rounds, row["points"], layout.columns[2:-1]):
                result = rnd.results.get(row["id"]) if rnd.confirmed else None
                value, color, size = round_display(rnd, row["id"], points), INK, 17
                if result is not None and result.status not in ("FINISHED", "POINTS"):
                    color, size = MUTED, 13
                if not rnd.confirmed:
                    rect(x, y, col_width, height, "#eff3f6")
                text(x + 6, y, col_width - 12, height, value, size, color, align=CENTER)
                x += col_width
            rect(x, y, layout.columns[-1], height, "#e4f3ef")
            text(x, y, layout.columns[-1], height, row["total"], 22, TEAL, True, CENTER)
            rect(32, y + height - 1, content, 1, "#e3eaf0")
            y += height

        y += 22
        gap = 20
        left_width = int(content * 0.63)
        right_x = 32 + left_width + gap
        right_width = content - left_width - gap
        rect(32, y, left_width, 172, "#ffffff")
        rect(right_x, y, right_width, 172, "#ffffff")
        text(48, y + 8, left_width - 32, 26, "순위별 배점", 15, INK, True)
        box_width = (left_width - 32) / 8
        for index, points in enumerate(league.rules.position_points):
            bx = 48 + (index % 8) * box_width
            by = y + 41 + (index // 8) * 45
            text(bx, by, box_width, 18, f"{index + 1}위", 12, MUTED, align=CENTER)
            text(bx, by + 18, box_width, 24, f"{points}", 17, INK, True, CENTER)
        status_line = "   ·   ".join(f"{s} {n}점" for s, n in league.rules.status_points.items())
        text(48, y + 139, left_width - 32, 24, status_line, 12, MUTED)
        text(right_x + 16, y + 8, right_width - 32, 26, "보너스 규정", 15, INK, True)
        for index, (name, rule) in enumerate((("예선 폴", league.rules.pole), ("패스티스트랩", league.rules.fastest))):
            by = y + 41 + index * 46
            text(right_x + 16, by, right_width - 142, 22, name, 14, INK, True)
            text(right_x + right_width - 130, by, 114, 22, f"+{rule.points}점" if rule.enabled else "미사용", 17, TEAL, True, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text(right_x + 16, by + 22, right_width - 32, 22, bonus_description(rule), 12, MUTED)
        stack = stack_description(league.rules)
        text(right_x + 16, y + 139, right_width - 32, 24, stack, 12, MUTED)
        note = footer_note(league)
        text(32, y + 183, content, 25, note, 12, MUTED)
        text(32, layout.height - 28, content, 18, "GTLeaderboard", 11, MUTED, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    finally:
        p.end()
    return image


def save_png(path, image, league_document=None):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValidationError("PNG 인코딩에 실패했습니다.")
    content = bytes(data)
    if league_document is not None:
        from .png_data import embed_document
        content = embed_document(content, league_document)
    atomic_write(path, content)
