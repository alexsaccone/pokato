"""Find and read cards without client identifiers, profiles or user-drawn ROIs."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from decimal import Decimal, InvalidOperation
import re
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .calibrated import normalized, similarity


@dataclass(frozen=True)
class Amount:
    raw: str
    value: str
    approximate: bool
    label: str = ''


@dataclass(frozen=True)
class Player:
    name: str
    stack: Amount
    box: tuple


@dataclass(frozen=True)
class AutoReading:
    board: tuple = ()
    hand: tuple = ()
    players: tuple = ()
    pots: tuple = ()
    hero_verified: bool = False
    issues: tuple = ()
    table_found: bool = False
    source: str = ''
    timestamp: float = 0.
    hand_views: tuple = ()
    image_size: tuple = ()
    hand_status: str = ''
    hand_held: bool = False


def amount(text, label=''):
    raw = text.strip()
    clean = re.sub(r'[\s$€£¥]', '', raw)
    if not re.fullmatch(r'\d+(?:,\d{3})*(?:\.\d+)?[kKmM]?', clean):
        return None
    abbreviated = clean[-1:].upper() in ('K', 'M')
    factor = 1000 if clean[-1:].upper() == 'K' else 1000000 if clean[-1:].upper() == 'M' else 1
    if abbreviated:
        clean = clean[:-1]
    try:
        value = Decimal(clean.replace(',', ''))*factor
        if value > 10**12:
            return None
        return Amount(raw, format(value, 'f'), abbreviated, label)
    except InvalidOperation:
        return None


def center(box):
    return (box[0]+box[2])/2, (box[1]+box[3])/2


def card_rows(cards):
    rows = []
    for card in sorted(cards, key=lambda c: center(c.box)[0]):
        h = card.box[3]-card.box[1]
        eligible = [row for row in rows if .6 < h/(row[-1].box[3]-row[-1].box[1]) < 1.7 and
                    abs(center(card.box)[1]-center(row[-1].box)[1]) < h*.4 and
                    0 < center(card.box)[0]-center(row[-1].box)[0] < (card.box[2]-card.box[0])*2.6]
        if eligible:
            eligible[0].append(card)
        else:
            rows.append([card])
    return tuple(tuple(row) for row in rows)


def hand_pairs(cards):
    return tuple(row for row in card_rows(cards) if len(row) == 2)


def arrange(cards):
    rows = card_rows(cards)
    boards = [row for row in rows if 3 <= len(row) <= 5 and sum(c.value is not None for c in row) >= 2]
    if len(boards) > 1:
        return (), (), ('Multiple possible boards; keep one table visible',)
    board = tuple(boards[0]) if boards else ()
    if board:
        # Preserve missed slots instead of turning a river into a valid turn.
        widths = sorted(c.box[2]-c.box[0] for c in board)
        width = widths[len(widths)//2]
        gaps = [center(b.box)[0]-center(a.box)[0] for a, b in zip(board, board[1:])]
        step = min(gaps)
        expanded = [board[0]]
        for prior, current, gap in zip(board, board[1:], gaps):
            missing = round(gap/step)-1 if gap > width*1.65 and step < width*1.5 else 0
            for slot in range(missing):
                x = center(prior.box)[0]+step*(slot+1)
                expanded.append(Card((x-width/2, prior.box[1], x+width/2, prior.box[3]), None, None, 0.))
            expanded.append(current)
        if len(expanded) > 5:
            return (), (), ('Board spacing is ambiguous; waiting for clearer cards',)
        board = tuple(expanded)
    pairs = [tuple(row) for row in rows if len(row) == 2]
    # A legible header pair is preferable to a larger, partly obscured pair.
    pairs.sort(key=lambda row: (sum(c.value is not None for c in row),
                               sum(c.score for c in row),
                               sum((c.box[2]-c.box[0])*(c.box[3]-c.box[1]) for c in row)), reverse=True)
    if not pairs:
        return board, (), ()
    hand = pairs[0]
    # Repeated mini cards are common. Different exposed pairs at showdown must
    # not be silently assigned to the hero.
    distinct = [row for row in pairs[1:] if all(c.value for c in row) and
                tuple(c.value for c in row) != tuple(c.value for c in hand)]
    return board, (() if distinct else hand), (('Several exposed hands; hero is ambiguous',) if distinct else ())


_NON_NAMES = {'pot', 'main pot', 'side pot', 'total pot', 'call', 'check', 'fold', 'folded', 'raise',
              'bet', 'all in', 'all in!', 'sitting out', 'waiting', 'home', 'lobby', 'store', 'play', 'free bonus'}


def player_amounts(texts):
    players = []
    for item in texts:
        stack = amount(item.text)
        if stack is None or item.score < .85:
            continue
        x, y = center(item.box)
        height = item.box[3]-item.box[1]
        above = [t for t in texts if t is not item and t.score >= .85 and
                 t.text.lower().strip() not in _NON_NAMES and len(t.text) <= 24 and
                 re.search('[A-Za-z]', t.text) and not amount(t.text) and
                 height*.35 < y-center(t.box)[1] < height*2.5 and
                 abs(center(t.box)[0]-x) < max(height*2, (item.box[2]-item.box[0])*.7)]
        if above:
            name = min(above, key=lambda t: item.box[1]-t.box[3])
            players.append(Player(name.text, stack, name.box))
    return tuple(players)


def pot_amounts(texts):
    pots = []
    for item in texts:
        if item.score < .8:
            continue
        label = re.fullmatch(r'((?:(?:main|side|total)\s+)?pot(?:\s*#?\d+)?)(?:\s*[:=]\s*(.+))?', item.text.strip(), re.I)
        if label is None:
            label = re.fullmatch(r'((?:(?:main|total)\s+)?pot)\s+([$€£¥]?\s*\d[\d,.]*\s*[kKmM]?)', item.text.strip(), re.I)
        if label is None:
            continue
        value = amount(label[2], label[1]) if label[2] else None
        if value is None:
            x, y = center(item.box)
            height = item.box[3]-item.box[1]
            nearby = [t for t in texts if t.score >= .85 and amount(t.text) and
                      -.3*height < t.box[1]-item.box[3] < height*2.5 and
                      abs(center(t.box)[0]-x) < max(height*2.5, (item.box[2]-item.box[0])*.8)]
            if nearby:
                number = min(nearby, key=lambda t: abs(center(t.box)[0]-x)+abs(t.box[1]-item.box[3]))
                value = amount(number.text, item.text)
        if value and value not in pots:
            pots.append(value)
    return tuple(pots)


class AutomaticReader:
    def __init__(self, ocr=None):
        self.ocr = ocr

    def read(self, frame):
        if self.ocr is None:
            from .ocr import LocalOCR
            self.ocr = LocalOCR()
        cards = detect_cards(frame.image, self.ocr)
        board, hand, issues = arrange(cards)
        texts = self.ocr.text(frame.image)
        players = player_amounts(texts)
        focused = ()
        if board:
            left, top = min(c.box[0] for c in board), min(c.box[1] for c in board)
            right, bottom = max(c.box[2] for c in board), max(c.box[3] for c in board)
            height = bottom-top
            cropbox = (max(0, int(left-height*2)), max(0, int(top-height*1.5)),
                       min(frame.image.width, int(right+height*2)), min(frame.image.height, int(bottom+height*2)))
            focused = self.ocr.text(frame.image.crop(cropbox))
        pots = pot_amounts(focused) or pot_amounts(texts)
        hero = False
        if len(hand) == 2 and all(c.value for c in hand):
            # Account name repeated at a seat provides an automatic hero anchor.
            for player in players:
                if sum(t.text.casefold() == player.name.casefold() for t in texts) >= 2:
                    x, y = center(player.box)
                    hx = sum(center(c.box)[0] for c in hand)/2
                    hy = sum(center(c.box)[1] for c in hand)/2
                    h = max(c.box[3]-c.box[1] for c in hand)
                    if abs(x-hx) < h*2 and abs(y-hy) < h*3:
                        hero = True
            if any(pair != hand and tuple(c.value for c in pair) == tuple(c.value for c in hand)
                   for pair in hand_pairs(cards)):
                hero = True
        known = [c.value for c in (*board, *hand) if c.value]
        if len(set(known)) != len(known):
            return AutoReading(issues=('Conflicting card readings; waiting for a clearer frame',),
                               source=frame.source, timestamp=frame.timestamp)
        poker_words = any(re.search(r'\b(pot|fold|folded|raise|blinds|check|call)\b', t.text, re.I) for t in texts)
        context = bool(pots) or len(players) >= 2 or poker_words
        found = bool((board or hand or (len(players) >= 2 and poker_words)) and context and not any('Multiple' in issue for issue in issues))
        return AutoReading(board, hand, players, pots, hero, issues, found, frame.source, frame.timestamp,
                           hand_pairs(cards), frame.image.size)


@dataclass(frozen=True)
class Card:
    box: tuple
    rank: object
    suit: object
    score: float
    visual: bytes = b''

    @property
    def value(self):
        return self.rank+self.suit if self.rank and self.suit else None


def ink(image):
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    neutral = rgb.max(axis=2)-rgb.min(axis=2) < 35
    background = np.percentile(rgb.max(axis=2)[neutral], 80) if neutral.any() else 225
    dark_limit = min(175, background-45)
    mask = ((rgb.max(axis=2) < dark_limit) | ((rgb.max(axis=2)-rgb.min(axis=2) > 65) &
             (rgb.min(axis=2) < 170))).astype('uint8')*255
    # Remove the card edge before extracting ink. A one-pixel bridge from a
    # shadow/chip to a suit must not erase the entire suit component.
    margin = max(2, round(min(image.size)*.045))
    mask[:margin] = mask[-margin:] = 0
    mask[:, :margin] = mask[:, -margin:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), 'uint8'))
    return mask


def card_parts(face):
    mask = ink(face)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    w, h = face.size
    parts = [(i, *stats[i]) for i in range(1, count) if stats[i, 4] >= 8]
    upper = [p for p in parts if p[2] < h*.45 and p[1] < w*.62 and
             h*.13 < p[4] < h*.65 and p[3] < w*.7]
    if not upper:
        return None, None
    # The rank is the upper glyph, not the tallest glyph. On fanned cards a
    # large heart can be taller than the A immediately above it.
    first = min(upper, key=lambda p: p[2]/h+.5*p[1]/w)
    rank = [p for p in upper if abs(p[2]-first[2]) < first[4]*.3 and p[4] >= first[4]*.8]
    # Small corner suits are shorter than rank glyphs, including a two-digit 10.
    x0, y0 = min(p[1] for p in rank), min(p[2] for p in rank)
    x1, y1 = max(p[1]+p[3] for p in rank), max(p[2]+p[4] for p in rank)
    rank_image = Image.new('RGB', (max(60, (x1-x0)*2+24), (y1-y0)*2+24), 'white')
    glyph = Image.fromarray(255-mask[y0:y1, x0:x1]).convert('RGB').resize(((x1-x0)*2, (y1-y0)*2))
    rank_image.paste(glyph, (12, 12))
    lower = [p for p in parts if p[0] not in {r[0] for r in rank} and
             p[2] >= y1-first[4]*.15 and p[4] > h*.08 and
             p[3] < w*.8 and p[4] < h*.65]
    if not lower:
        return rank_image, None
    # Choose the first suit under the rank. A FOLDED banner or central artwork
    # must not replace the small corner suit.
    suit = min(lower, key=lambda p: (p[2], -p[5]))
    main_suit = Image.fromarray((labels == suit[0]).astype('uint8')*255)
    main_suit = main_suit.crop(main_suit.getbbox())
    if read_suit(main_suit)[0] is not None:
        return rank_image, main_suit
    selected = {suit[0]}
    # A tiny disconnected stem can be shorter than the minimum size used to
    # choose the main suit. Include those pieces, but exclude rank glyphs and
    # full-height banner letters.
    for part in parts:
        if part[0] in {r[0] for r in rank}:
            continue
        horizontal_gap = max(0, max(part[1], suit[1])-min(part[1]+part[3], suit[1]+suit[3]))
        vertical_gap = max(0, max(part[2], suit[2])-min(part[2]+part[4], suit[2]+suit[4]))
        centered = abs(part[1]+part[3]/2-(suit[1]+suit[3]/2)) < suit[3]*.25
        if (horizontal_gap == 0 and centered and part[2] >= suit[2]+suit[4]-2 and
                vertical_gap <= max(2, suit[4]*.25) and
                part[4] < suit[4]*.5 and part[5] < suit[5]*.4):
            selected.add(part[0])
    suit_image = Image.fromarray(np.isin(labels, tuple(selected)).astype('uint8')*255)
    suit_image = suit_image.crop(suit_image.getbbox())
    return rank_image, suit_image


@lru_cache(maxsize=1)
def suit_templates():
    fonts = [p for p in (Path('C:/Windows/Fonts/seguisym.ttf'), Path('C:/Windows/Fonts/arial.ttf'),
             Path('C:/Windows/Fonts/segoeui.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.exists()]
    result = []
    for path in fonts:
        for size in (32, 52, 80):
            font = ImageFont.truetype(str(path), size)
            for suit, symbol in zip('cdhs', '♣♦♥♠'):
                im = Image.new('L', (130, 130))
                ImageDraw.Draw(im).text((12, 0), symbol, font=font, fill=255)
                im = im.point(lambda x: 255 if x >= 100 else 0)
                result.append((suit, *normalized(im)))
    return tuple(result)


def read_suit(mask):
    if mask is None:
        return None, 0.
    image, aspect = normalized(mask)
    scores = {}
    for label, template, ratio in suit_templates():
        scores[label] = max(scores.get(label, 0.), similarity(image, aspect, template, ratio))
    if not scores:
        return None, 0.
    array = cv2.morphologyEx(np.pad(np.asarray(mask), 3), cv2.MORPH_CLOSE, np.ones((3, 3), 'uint8'))
    contours, _ = cv2.findContours(array, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.
    contour = max(contours, key=cv2.contourArea)
    if len(contour) < 4 or cv2.contourArea(contour) < 4:
        return None, 0.
    defects = cv2.convexityDefects(contour, cv2.convexHull(contour, returnPoints=False))
    points = []
    if defects is not None:
        for _, _, far, depth in defects[:, 0, :]:
            if depth/256 >= max(mask.size)*.055:
                x, y = contour[far, 0]
                points.append(((x-3)/mask.width, (y-3)/mask.height))
    middle = [p for p in points if .15 < p[1] < .65]
    lower = [p for p in points if p[1] >= .65]
    label = None
    if any(x < .48 for x, y in middle) and any(x > .52 for x, y in middle):
        label = 'c'
    elif any(.25 < x < .75 and y < .3 for x, y in points):
        label = 'h'
    elif any(x < .5 for x, y in lower) and any(x > .5 for x, y in lower):
        label = 's'
    elif not points and len(cv2.approxPolyDP(contour, .04*cv2.arcLength(contour, True), True)) == 4:
        label = 'd'
    score = scores.get(label, 0.)
    return (label if score >= .78 else None), score


def face_variants(rgb, quad):
    """Keep glyph proportions; retry clipped faces below an overlaid banner."""
    width = (np.linalg.norm(quad[1]-quad[0])+np.linalg.norm(quad[2]-quad[3]))/2
    height = (np.linalg.norm(quad[3]-quad[0])+np.linalg.norm(quad[2]-quad[1]))/2
    variants = [quad]
    if width/height > .82:
        extended = quad.copy()
        factor = min(1.8, width/(height*.65))
        extended[2] = quad[1]+(quad[2]-quad[1])*factor
        extended[3] = quad[0]+(quad[3]-quad[0])*factor
        variants.append(extended)
    for points in variants:
        natural_height = (np.linalg.norm(points[3]-points[0])+np.linalg.norm(points[2]-points[1]))/2
        output_width = max(48, round(160*width/natural_height))
        transform = cv2.getPerspectiveTransform(points, np.array(
            [[0, 0], [output_width-1, 0], [output_width-1, 159], [0, 159]], dtype='float32'))
        yield Image.fromarray(cv2.warpPerspective(rgb, transform, (output_width, 160), borderValue=(255, 255, 255)))


def faces(image):
    rgb = np.asarray(image.convert('RGB'))
    scale = min(1., 1920/image.width)
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    found = []
    for threshold in (165, 190):
        array = small.astype(np.int16)
        mask = ((array.min(axis=2) >= threshold) & (array.max(axis=2)-array.min(axis=2) <= 55)).astype('uint8')*255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < small.shape[0]*small.shape[1]*.00007:
                continue
            polygon = cv2.approxPolyDP(contour, .035*cv2.arcLength(contour, True), True)
            if 5 <= len(polygon) <= 8:
                polygon = cv2.approxPolyDP(cv2.convexHull(contour), .055*cv2.arcLength(contour, True), True)
                if len(polygon) != 4:
                    polygon = cv2.boxPoints(cv2.minAreaRect(contour)).reshape(4, 1, 2)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            points = polygon[:, 0, :].astype('float32')/scale
            x, y, w, h = cv2.boundingRect(points)
            if not .4 <= w/h <= 1.15 or h < image.height*.018 or h > image.height*.3:
                continue
            if area/(w*h*scale*scale) < .6:
                continue
            box = (x, y, x+w, y+h)
            if any(intersection(box, prior[0]) > .65 for prior in found):
                continue
            sums, diffs = points.sum(axis=1), np.diff(points, axis=1)[:, 0]
            quad = np.array([points[sums.argmin()], points[diffs.argmin()], points[sums.argmax()], points[diffs.argmax()]], dtype='float32')
            if len(np.unique(quad, axis=0)) != 4:
                continue
            for face in face_variants(rgb, quad):
                pixels = np.asarray(face).astype(np.int16)
                if ((pixels.min(axis=2) > 150) & (pixels.max(axis=2)-pixels.min(axis=2) < 65)).mean() < .5:
                    continue
                rank, suit = card_parts(face)
                if rank is not None and suit is not None:
                    found.append((box, face, rank, suit))
    return found


def intersection(a, b):
    area = max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))
    return area/max(1, (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def detect_cards(image, ocr):
    candidates = faces(image)
    ranks = ocr.ranks([row[2] for row in candidates])
    cards = []
    for (box, face, rank_image, suit_image), (raw, confidence) in zip(candidates, ranks):
        rank = 'T' if raw == '10' else raw
        rank = rank if len(rank) == 1 and rank in '23456789TJQKA' and confidence >= .8 else None
        suit, score = read_suit(suit_image)
        rank_mask = rank_image.convert('L').point(lambda x: 255 if x < 128 else 0)
        visual = normalized(rank_mask)[0].tobytes()+normalized(suit_image)[0].tobytes()
        cards.append(Card(box, rank, suit, min(confidence, score), visual))
    grouped = []
    for card in cards:
        match = next((row for row in grouped if intersection(card.box, row[0].box) > .65), None)
        if match is None:
            grouped.append([card])
        else:
            match.append(card)
    result = []
    for group in grouped:
        values = {card.value for card in group if card.value}
        best = max(group, key=lambda c: (c.value is not None, (c.rank is not None)+(c.suit is not None), c.score))
        if len(values) > 1:
            best = Card(best.box, None, None, 0., best.visual)
        result.append(best)
    return tuple(result)
