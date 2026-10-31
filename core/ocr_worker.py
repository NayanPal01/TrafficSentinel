"""Asynchronous ANPR — optimised for Indian number plates (BIS AIS-015 / MoRTH spec).

Indian plate format:
  [State (2L)] [District (1-2D)] [Series (1-3L)] [Serial (4D)]
  Examples: MH12AB1234  DL3CAB1234  UP80EJ5057  KA01MG8800

Plate background types (colour-aware preprocessing):
  White  BG + black text  → private vehicles           (most common)
  Yellow BG + black text  → commercial / taxi
  Green  BG + white text  → electric vehicles (EV)
  Black  BG + yellow text → tourist / rental
  Blue   BG + white text  → diplomatic corps

Plate detector model (models/license_plate_detector.pt):
  Supports both YOLOv8 and YOLO26 weights \u2014 the ultralytics API is identical.
  YOLO26 is recommended: NMS-free + DFL-removed = faster inference and
  cleaner ONNX/OpenVINO exports on CPU.

Full-frame pipeline (Stage 1 \u2014 main thread):
  YOLO26/v8 plate detector \u2192 crop \u2192 colour-detect \u2192 adaptive threshold \u2192 EasyOCR
  \u2192 Indian format validator + state-code check \u2192 get_car() containment

Async fallback pipeline (Stage 2 \u2014 background thread):
  Vehicle bumper crop \u2192 YOLO26/v8 plate isolate \u2192 multi-pass preprocessing
  \u2192 EasyOCR \u2192 Indian disambiguate + validate
"""

from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .helmet import enhance_crop


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OCRJob:
    track_id: int
    crop: np.ndarray


@dataclass
class OCRResult:
    track_id: int
    plate: Optional[str]
    confidence: float
    crop: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# Valid Indian state / UT codes (MoRTH official list)
# ---------------------------------------------------------------------------

INDIAN_STATE_CODES = {
    # States
    'AP', 'AR', 'AS', 'BR', 'CG', 'GA', 'GJ', 'HR', 'HP',
    'JK', 'JH', 'KA', 'KL', 'MP', 'MH', 'MN', 'ML', 'MZ',
    'NL', 'OD', 'PB', 'RJ', 'SK', 'TN', 'TS', 'TR', 'UP',
    'UA', 'WB',
    # Union territories
    'AN', 'CH', 'DL', 'DN', 'DD', 'LD', 'PY',
    # BH series (Bharat / National permit)
    'BH',
}

# ---------------------------------------------------------------------------
# Character disambiguation maps
# ---------------------------------------------------------------------------

# Digit positions: chars that look like digits → map to digit
_C2D = {
    'O': '0', 'D': '0', 'Q': '0',
    'I': '1', 'L': '1', 'T': '1',
    'Z': '2',
    'J': '3',
    'A': '4',
    'S': '5',
    'G': '6', 'C': '6',
    'B': '8',
}

# Letter positions: chars that look like letters → map to letter
_D2L = {
    '0': 'O',
    '1': 'I',
    '2': 'Z',
    '3': 'J',
    '4': 'A',
    '5': 'S',
    '6': 'G',
    '8': 'B',
}

# Keep legacy names for reference pipeline compatibility
dict_char_to_int = {'O': '0', 'I': '1', 'J': '3', 'A': '4', 'G': '6', 'S': '5'}
dict_int_to_char = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S'}
dict_char_to_int_ext = _C2D
dict_int_to_char_ext = _D2L


# ---------------------------------------------------------------------------
# Indian plate format validator & HSRP prefix handler
# ---------------------------------------------------------------------------

def strip_hsrp_prefix(text: str) -> str:
    """Strip leading 'IND' / '1ND' country identifier found on Indian HSRP plates."""
    if not text:
        return ""
    t = re.sub(r'[\s\-]', '', text.upper())
    t = re.sub(r'[^A-Z0-9]', '', t)
    if len(t) >= 10:
        for prefix in ('IND', '1ND', 'TND', 'LND', 'ND', 'IN'):
            if t.startswith(prefix) and len(t) - len(prefix) >= 8:
                remainder = t[len(prefix):]
                if remainder[:2] in INDIAN_STATE_CODES or remainder[:2] == 'DL':
                    return remainder
    return t


def sort_plate_detections(detections: list) -> list:
    """Sort OCR character/text boxes top-to-bottom, left-to-right with line binning.
    Prevents vertical jitter from swapping adjacent characters on the same line,
    and correctly handles two-line plates (motorcycles/trucks).
    """
    if not detections or len(detections) <= 1:
        return detections

    items = []
    for d in detections:
        bbox = d[0]
        pts = np.array(bbox, dtype=np.float32)
        min_x, min_y = float(pts[:, 0].min()), float(pts[:, 1].min())
        max_x, max_y = float(pts[:, 0].max()), float(pts[:, 1].max())
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        h = max(1.0, max_y - min_y)
        items.append({'det': d, 'cx': cx, 'cy': cy, 'h': h})

    # Sort primarily by vertical center
    items.sort(key=lambda it: it['cy'])

    lines = []
    for it in items:
        placed = False
        for line in lines:
            line_avg_cy = sum(m['cy'] for m in line) / len(line)
            line_avg_h = sum(m['h'] for m in line) / len(line)
            # If within 45% of average line height, group on the same line
            if abs(it['cy'] - line_avg_cy) < max(8.0, line_avg_h * 0.45):
                line.append(it)
                placed = True
                break
        if not placed:
            lines.append([it])

    # Sort each line left-to-right by cx
    sorted_dets = []
    for line in lines:
        line.sort(key=lambda it: it['cx'])
        for it in line:
            sorted_dets.append(it['det'])

    return sorted_dets


def validate_indian_plate(text: str) -> Tuple[bool, str]:
    """Validate and return (is_valid, reason) for an Indian plate string.

    Accepted formats (after stripping spaces/hyphens and HSRP prefix):
      Standard  : XX 00 XX 0000   (10 chars, e.g. MH12AB1234)
      Single-dist: XX 0 XX 0000   (9 chars,  e.g. DL3CAB1234, WB2AK1928)
      Short-series: XX 00 X 0000  (9 chars,  e.g. KA01M1234 — rare old plates)
      BH series : 00BH0000X       (defence/bharat series)

    Returns (True, plate) on success, (False, reason_string) on failure.
    """
    if not text:
        return False, "empty text"

    t = strip_hsrp_prefix(text)

    if len(t) < 8 or len(t) > 10:
        return False, f"length {len(t)} out of range [8,10]"

    # State code check (positions 0-1 must be letters forming a valid code)
    state = t[:2]
    if not state.isalpha():
        return False, f"state code '{state}' not alphabetic"
    if state not in INDIAN_STATE_CODES:
        return False, f"unknown state code '{state}'"

    # District digits (positions 2-3, or just 2 for 9-char plates)
    if state == 'DL' and len(t) == 10 and t[2].isdigit() and t[3].isalpha():
        series_start = 3        # DL 3 CAB 1234 (1-digit district + 3-letter series)
    elif t[2].isdigit():
        if t[3].isdigit():
            series_start = 4    # XX00...
        else:
            series_start = 3    # XX0...
    else:
        return False, f"position 2 '{t[2]}' should be a digit"

    # Last 4 must be digits (serial number)
    serial = t[-4:]
    if not serial.isdigit():
        return False, f"serial '{serial}' not all digits"

    # Series letters (between district and serial)
    series = t[series_start:-4]
    if not (1 <= len(series) <= 3):
        return False, f"series '{series}' length {len(series)} not in [1,3]"
    if not series.isalpha():
        return False, f"series '{series}' not all letters"

    return True, t


# ---------------------------------------------------------------------------
# Indian plate disambiguator — position-aware char correction
# ---------------------------------------------------------------------------

def disambiguate_indian_plate(text: str) -> str:
    """Correct common OCR confusions using positional rules for Indian plates.

    Position layout (10-char example  MH12AB1234):
      0,1   → letters  (state code)
      2,3   → digits   (district)
      4,5   → letters  (series — 2-char case)
      6-9   → digits   (serial)

    For 9-char (e.g. WB2AK1928, DL3AB1234):
      0,1   → letters  (state code)
      2     → digit    (district)
      3,4   → letters  (series)
      5-8   → digits   (serial)
    """
    if not text:
        return ""

    t = strip_hsrp_prefix(text)

    if len(t) < 6 or len(t) > 11:
        return t

    chars = list(t)
    n = len(chars)

    def to_letter(c: str) -> str:
        return _D2L.get(c, c)

    def to_digit(c: str) -> str:
        return _C2D.get(c, c)

    # --- Positions 0, 1: always letters (state code) ---
    chars[0] = to_letter(chars[0])
    chars[1] = to_letter(chars[1])

    # --- Position 2: always a digit (first district digit) ---
    chars[2] = to_digit(chars[2])

    # --- Last 4 positions: always digits (serial number) ---
    for i in range(n - 4, n):
        chars[i] = to_digit(chars[i])

    # --- Middle section: determine district vs series boundary ---
    if n == 10:
        # Check if 1-digit district with 3-letter series: e.g. DL 3 CAB 1234
        if chars[0] == 'D' and chars[1] == 'L' and chars[3].isalpha() and chars[4].isalpha() and chars[5].isalpha():
            chars[3] = to_letter(chars[3])
            chars[4] = to_letter(chars[4])
            chars[5] = to_letter(chars[5])
        else:
            # Standard: XX 00 XX 0000
            chars[3] = to_digit(chars[3])
            chars[4] = to_letter(chars[4])
            chars[5] = to_letter(chars[5])

    elif n == 9:
        # Single-district (vast majority of 9-char plates): XX 0 XX 0000 (e.g. WB2AK1928, DL3AB1234)
        # Position 3 is a series letter, NOT a digit! Do NOT apply broad _C2D check.
        if chars[3].isdigit():
            # Rare 1989 old format: XX 00 X 0000
            chars[3] = to_digit(chars[3])
            chars[4] = to_letter(chars[4])
        else:
            # Standard 9-char format: XX 0 XX 0000 — positions 3 and 4 are series letters
            chars[3] = to_letter(chars[3])
            chars[4] = to_letter(chars[4])

    elif n == 8:
        # Very short: XX 0 X 0000 — position 3 = letter (series)
        chars[3] = to_letter(chars[3])

    result = ''.join(chars)

    # --- Attempt state-code correction if first 2 chars aren't valid ---
    state = result[:2]
    if state not in INDIAN_STATE_CODES:
        for alt0 in [result[0], to_letter(result[0])]:
            for alt1 in [result[1], to_letter(result[1])]:
                candidate = alt0 + alt1
                if candidate in INDIAN_STATE_CODES:
                    result = candidate + result[2:]
                    break
            else:
                continue
            break

    return result


# ---------------------------------------------------------------------------
# Plate background colour detection
# ---------------------------------------------------------------------------

_PLATE_TYPES = {
    # (name, bg_lower_hsv, bg_upper_hsv, text_is_dark)
    'white':  ((0,   0, 150), (180,  40, 255), True),
    'yellow': ((15,  80,  80), (35, 255, 255), True),
    'green':  ((40,  60,  60), (90, 255, 255), False),
    'black':  ((0,   0,   0), (180,  50,  80), False),
    'blue':   ((95,  80,  80), (135, 255, 255), False),
}


def detect_plate_background(crop: np.ndarray) -> Tuple[str, bool]:
    """Detect dominant background colour of a plate crop.

    Returns (plate_type, text_is_dark).
    text_is_dark=True  → black text on bright bg → use THRESH_BINARY
    text_is_dark=False → white/yellow text on dark bg → use THRESH_BINARY_INV
    """
    if crop is None or crop.size == 0:
        return 'white', True

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    total = crop.shape[0] * crop.shape[1]
    best_type, best_ratio, best_dark = 'white', 0.0, True

    for ptype, (lo, hi, dark) in _PLATE_TYPES.items():
        mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
        ratio = float(np.count_nonzero(mask)) / max(total, 1)
        if ratio > best_ratio:
            best_type, best_ratio, best_dark = ptype, ratio, dark

    return best_type, best_dark


# ---------------------------------------------------------------------------
# 4-point contour deskew and perspective warp
# ---------------------------------------------------------------------------

def order_quad_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 (x, y) points in clockwise order: [top-left, top-right, bottom-right, bottom-left]."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    rect = np.zeros((4, 2), dtype=np.float32)

    # Top-left has smallest sum (x + y), bottom-right has largest sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # Top-right has smallest diff (y - x), bottom-left has largest diff
    diff = np.diff(pts, axis=1).reshape(4)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> Optional[np.ndarray]:
    """Perform perspective transform given 4 quadrilateral points on an image."""
    try:
        rect = order_quad_points(pts)
        tl, tr, br, bl = rect

        # Compute widths of top and bottom edges
        w_b = np.hypot(br[0] - bl[0], br[1] - bl[1])
        w_t = np.hypot(tr[0] - tl[0], tr[1] - tl[1])
        max_w = max(int(round(w_b)), int(round(w_t)))

        # Compute heights of right and left edges
        h_r = np.hypot(tr[0] - br[0], tr[1] - br[1])
        h_l = np.hypot(tl[0] - bl[0], tl[1] - bl[1])
        max_h = max(int(round(h_r)), int(round(h_l)))

        if max_w < 20 or max_h < 12:
            return None

        # Validate aspect ratio: Indian plates range from ~1.0 (square two-line) to ~6.0 (single-line)
        aspect = float(max_w) / float(max_h)
        if aspect < 1.0 or aspect > 6.5:
            return None

        dst = np.array([
            [0, 0],
            [max_w - 1, 0],
            [max_w - 1, max_h - 1],
            [0, max_h - 1]
        ], dtype=np.float32)

        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(
            image, M, (max_w, max_h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        return warped
    except Exception:
        return None


def find_plate_contour_quadrilateral(crop: np.ndarray) -> Optional[np.ndarray]:
    """Detect 4-point quadrilateral contour of a license plate within the crop.

    Searches across Canny edge detection and Otsu/adaptive threshold masks for
    a 4-corner convex polygon matching plate aspect ratio and area constraints.
    """
    if crop is None or crop.size == 0:
        return None

    h, w = crop.shape[:2]
    if h < 16 or w < 30:
        return None

    total_area = float(h * w)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()
    blur = cv2.bilateralFilter(gray, 7, 50, 50)

    # Strategy 1: Canny edge detection with dilation
    edges = cv2.Canny(blur, 35, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated_edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated_edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours[:8]:
        area = cv2.contourArea(c)
        if area < 0.12 * total_area or area > 0.98 * total_area:
            continue
        peri = cv2.arcLength(c, True)
        for eps in (0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(c, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                pts = approx.reshape(4, 2).astype(np.float32)
                rect = order_quad_points(pts)
                tl, tr, br, bl = rect
                w_cand = max(np.hypot(br[0] - bl[0], br[1] - bl[1]), np.hypot(tr[0] - tl[0], tr[1] - tl[1]))
                h_cand = max(np.hypot(tr[0] - br[0], tr[1] - br[1]), np.hypot(tl[0] - bl[0], tl[1] - bl[1]))
                if h_cand > 0 and 1.1 <= (w_cand / h_cand) <= 6.0:
                    return pts

    # Strategy 2: Contrast-based thresholding (for plates on contrasting bumpers)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresh_morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    contours_t, _ = cv2.findContours(thresh_morph, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours_t = sorted(contours_t, key=cv2.contourArea, reverse=True)

    for c in contours_t[:6]:
        area = cv2.contourArea(c)
        if area < 0.15 * total_area or area > 0.98 * total_area:
            continue
        peri = cv2.arcLength(c, True)
        for eps in (0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(c, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                pts = approx.reshape(4, 2).astype(np.float32)
                rect = order_quad_points(pts)
                tl, tr, br, bl = rect
                w_cand = max(np.hypot(br[0] - bl[0], br[1] - bl[1]), np.hypot(tr[0] - tl[0], tr[1] - tl[1]))
                h_cand = max(np.hypot(tr[0] - br[0], tr[1] - br[1]), np.hypot(tl[0] - bl[0], tl[1] - bl[1]))
                if h_cand > 0 and 1.1 <= (w_cand / h_cand) <= 6.0:
                    return pts

    return None


def deskew_plate_crop(crop: np.ndarray) -> np.ndarray:
    """Deskew a license plate crop using minAreaRect angle detection.

    Effective for tightly-cropped plates where the outer 4-corner border
    is partially cut off, but the plate text / characters are tilted.
    """
    if crop is None or crop.size == 0:
        return crop

    h, w = crop.shape[:2]
    if h < 16 or w < 30:
        return crop

    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()
        blur = cv2.GaussianBlur(gray, (3, 3), 0)

        # Adaptive threshold to isolate characters / text lines
        thresh = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 6
        )

        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 50:
            return crop

        # Points as (x, y)
        pts_xy = np.fliplr(coords).astype(np.float32)
        (cx, cy), (rect_w, rect_h), angle = cv2.minAreaRect(pts_xy)

        # Standardize angle so text orientation is horizontal
        if rect_w < rect_h:
            rect_w, rect_h = rect_h, rect_w
            angle += 90.0

        if angle > 45.0:
            angle -= 90.0
        elif angle < -45.0:
            angle += 90.0

        # Only deskew if tilt is meaningful and within reasonable limits
        if abs(angle) < 1.8 or abs(angle) > 38.0:
            return crop

        # Rotate around center
        center = (w / 2.0, h / 2.0)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        cos_val = abs(rot_mat[0, 0])
        sin_val = abs(rot_mat[0, 1])
        new_w = int((h * sin_val) + (w * cos_val))
        new_h = int((h * cos_val) + (w * sin_val))
        rot_mat[0, 2] += (new_w / 2.0) - center[0]
        rot_mat[1, 2] += (new_h / 2.0) - center[1]

        deskewed = cv2.warpAffine(
            crop, rot_mat, (new_w, new_h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        return deskewed
    except Exception:
        return crop


def correct_plate_perspective(crop: np.ndarray) -> np.ndarray:
    """Master plate rectification pipeline: 4-point perspective warp + contour deskew.

    1. Attempts 4-point quadrilateral detection and cv2.warpPerspective
       (handles trapezoidal perspective distortion from angled cameras).
    2. If no full quadrilateral is found, attempts minAreaRect character deskew
       (handles in-plane rotation and tilted plates).
    3. If plate is already horizontal/straight or deskew fails, returns crop intact.
    """
    if crop is None or crop.size == 0:
        return crop

    h, w = crop.shape[:2]
    if h < 16 or w < 30:
        return crop

    try:
        # Step 1: Try 4-point contour perspective warp
        quad_pts = find_plate_contour_quadrilateral(crop)
        if quad_pts is not None:
            rect = order_quad_points(quad_pts)
            tl, tr, br, bl = rect
            top_angle = abs(np.degrees(np.arctan2(tr[1] - tl[1], tr[0] - tl[0])))
            bot_angle = abs(np.degrees(np.arctan2(br[1] - bl[1], br[0] - bl[0])))
            width_ratio = max(np.hypot(tr[0] - tl[0], tr[1] - tl[1]), 1.0) / max(np.hypot(br[0] - bl[0], br[1] - bl[1]), 1.0)

            # If noticeable tilt (> 1.5 deg) or perspective divergence (> 6% difference in edge width)
            if top_angle > 1.5 or bot_angle > 1.5 or abs(width_ratio - 1.0) > 0.06:
                warped = four_point_transform(crop, quad_pts)
                if warped is not None and warped.size > 0:
                    return warped

        # Step 2: Fallback to minAreaRect character-level deskew
        return deskew_plate_crop(crop)
    except Exception:
        return crop


# ---------------------------------------------------------------------------
# Multi-variant plate preprocessor (colour-aware + adaptive)
# ---------------------------------------------------------------------------

def _generate_plate_variants(crop: np.ndarray) -> List[np.ndarray]:
    """Generate thresholded variants for a single image crop."""
    if crop is None or crop.size == 0:
        return []

    h, w = crop.shape[:2]

    # --- 1. Upscale small crops for better OCR ---
    target_h = max(64, min(180, h * 3))
    scale = target_h / max(h, 1)
    upscaled = cv2.resize(crop, (max(1, int(w * scale)), target_h),
                          interpolation=cv2.INTER_CUBIC)
    upscaled = enhance_crop(upscaled)  # CLAHE on L channel

    # --- 2. Detect plate colour type ---
    plate_type, text_is_dark = detect_plate_background(upscaled)

    # --- 3. Grayscale base ---
    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)

    # --- 4. Denoising variants ---
    bilateral = cv2.bilateralFilter(gray, 9, 75, 75)
    gaussian  = cv2.GaussianBlur(gray, (3, 3), 0)

    # --- 5. CLAHE for uneven illumination ---
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    clahe_gray = clahe.apply(bilateral)

    # --- 6. Threshold variants ---
    # 6a. Adaptive Gaussian threshold (handles shadows/glare)
    adapt_gauss = cv2.adaptiveThreshold(
        bilateral, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY if text_is_dark else cv2.THRESH_BINARY_INV,
        blockSize=15, C=8)

    # 6b. Adaptive mean threshold
    adapt_mean = cv2.adaptiveThreshold(
        bilateral, 255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY if text_is_dark else cv2.THRESH_BINARY_INV,
        blockSize=13, C=6)

    # 6c. Otsu's threshold (global, works well for bimodal plate histograms)
    _, otsu = cv2.threshold(clahe_gray, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if not text_is_dark:
        otsu = cv2.bitwise_not(otsu)

    # 6d. Fixed binary inverse (fallback)
    _, fixed_inv = cv2.threshold(gray, 64, 255, cv2.THRESH_BINARY_INV)
    if not text_is_dark:
        fixed_inv = cv2.bitwise_not(fixed_inv)

    # --- 7. Morphological cleanup on best adaptive result ---
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph_close = cv2.morphologyEx(adapt_gauss, cv2.MORPH_CLOSE, kernel)
    morph_open  = cv2.morphologyEx(adapt_gauss, cv2.MORPH_OPEN,  kernel)

    # --- 8. Assemble ordered list (best-first for detected plate type) ---
    if plate_type in ('yellow', 'black'):
        return [adapt_gauss, otsu, morph_close, adapt_mean,
                clahe_gray, morph_open, fixed_inv]
    elif plate_type == 'green':
        return [adapt_gauss, morph_close, otsu, adapt_mean,
                clahe_gray, fixed_inv]
    else:
        return [morph_close, adapt_gauss, adapt_mean, otsu,
                clahe_gray, morph_open, fixed_inv]


def preprocess_indian_plate(crop: np.ndarray) -> List[np.ndarray]:
    """Generate multiple preprocessed image variants optimised for Indian plates.

    Implements:
      1. 4-point perspective warp & contour deskew for angled/tilted plates.
      2. Adaptive thresholding recommendations for Indian illumination/plates.
      3. Colour-aware inversion for yellow/green/black plates.

    Returns a list of single-channel (grayscale) images to try for OCR,
    ordered best-first for the detected plate type.
    """
    if crop is None or crop.size == 0:
        return []

    rectified = correct_plate_perspective(crop)
    variants = _generate_plate_variants(rectified)

    # If perspective transform modified the crop, append raw variants as fallback
    if rectified is not crop and crop is not None and crop.size > 0:
        raw_variants = _generate_plate_variants(crop)
        for v in raw_variants[:3]:
            variants.append(v)

    return variants


# ---------------------------------------------------------------------------
# Reference pipeline helpers (kept for backward compat with engine.py)
# ---------------------------------------------------------------------------

def license_complies_format(text: str) -> bool:
    """Check Indian plate format (replaces the old 7-char international check)."""
    ok, _ = validate_indian_plate(text)
    return ok


def format_license(text: str) -> str:
    """Disambiguate using Indian rules (replaces old positional mapping)."""
    return disambiguate_indian_plate(text)


def read_license_plate_ref(reader, license_plate_crop) -> Tuple[Optional[str], float]:
    """Read plate from a (pre-thresholded) crop image via EasyOCR.

    Updated to validate against Indian format rather than the 7-char
    international format used in the original reference project.
    """
    try:
        detections = reader.readtext(
            license_plate_crop,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            detail=1, paragraph=False,
            text_threshold=0.18, low_text=0.12)
    except Exception:
        return None, 0.0

    if not detections:
        return None, 0.0

    # Sort top-to-bottom, left-to-right with line binning
    detections = sort_plate_detections(detections)
    raw = re.sub(r'[^A-Z0-9]', '',
                 ''.join(d[1] for d in detections).upper())
    raw = strip_hsrp_prefix(raw)
    conf = float(np.mean([d[2] for d in detections]))

    if len(raw) < 4:
        return None, 0.0

    corrected = disambiguate_indian_plate(raw)
    ok, _ = validate_indian_plate(corrected)
    if ok:
        return corrected, max(conf, 0.85)

    ok, _ = validate_indian_plate(raw)
    if ok:
        return raw, max(conf, 0.80)

    # Return raw text for foreign/non-standard plates if at least 4 alphanumeric chars
    return raw, max(conf, 0.60)


def get_car(license_plate_bbox, vehicle_bboxes_with_ids):
    """Retrieve the vehicle coordinates and ID that overlap with or contain the plate bbox."""
    px1, py1, px2, py2 = license_plate_bbox
    pcx = (px1 + px2) / 2.0
    pcy = (py1 + py2) / 2.0
    plate_area = max(1.0, float((px2 - px1) * (py2 - py1)))

    best_car = (-1, -1, -1, -1, -1)
    best_score = 0.0

    for vbox in vehicle_bboxes_with_ids:
        xcar1, ycar1, xcar2, ycar2, car_id = vbox
        # 1. Direct center containment (with slight vertical bumper tolerance)
        pad_y = 0.20 * max(10, (ycar2 - ycar1))
        pad_x = 0.08 * max(10, (xcar2 - xcar1))
        if (xcar1 - pad_x) <= pcx <= (xcar2 + pad_x) and (ycar1 - pad_y) <= pcy <= (ycar2 + pad_y):
            # Compute intersection area
            ix1 = max(px1, xcar1)
            iy1 = max(py1, ycar1)
            ix2 = min(px2, xcar2)
            iy2 = min(py2, ycar2)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            score = 1.0 + (inter / plate_area)
            if score > best_score:
                best_score = score
                best_car = (xcar1, ycar1, xcar2, ycar2, car_id)
        else:
            # 2. Overlap fallback
            ix1 = max(px1, xcar1)
            iy1 = max(py1, ycar1)
            ix2 = min(px2, xcar2)
            iy2 = min(py2, ycar2)
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2 - ix1) * (iy2 - iy1)
                overlap = inter / plate_area
                if overlap > 0.20 and overlap > best_score:
                    best_score = overlap
                    best_car = (xcar1, ycar1, xcar2, ycar2, car_id)

    # 3. Proximity fallback: nearest vehicle bounding box within 75px
    if best_car[4] == -1 and vehicle_bboxes_with_ids:
        min_dist = 75.0
        for vbox in vehicle_bboxes_with_ids:
            xcar1, ycar1, xcar2, ycar2, car_id = vbox
            dx = max(xcar1 - pcx, 0, pcx - xcar2)
            dy = max(ycar1 - pcy, 0, pcy - ycar2)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_dist:
                min_dist = dist
                best_car = (xcar1, ycar1, xcar2, ycar2, car_id)

    return best_car


# ---------------------------------------------------------------------------
# PlateReader — full Indian-optimised pipeline
# ---------------------------------------------------------------------------

class PlateReader:
    """YOLOv8 plate localizer + EasyOCR reader, fully optimised for Indian plates.

    Two modes:
    - Stage 1 (detect_plates_in_frame): full-frame YOLO detect → colour-aware
      adaptive threshold → Indian-format EasyOCR
    - Stage 2 (read): vehicle bumper crop → YOLO isolate → multi-pass OCR
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.regex = re.compile(cfg.plate_regex)
        self._reader = None
        self._plate_detector = None
        self._init_detector()

    def _init_detector(self):
        model_path = getattr(self.cfg, 'plate_model_path',
                             'models/license_plate_detector.pt')
        from pathlib import Path
        if model_path and Path(model_path).exists():
            try:
                import torch
                from ultralytics import YOLO
                self._plate_detector = YOLO(model_path)
                device = "cuda:0" if (torch.cuda.is_available() and getattr(self.cfg, 'gpu', True)) else "cpu"
                self.device = device
                self._plate_detector.to(device)
                if device != "cpu":
                    try:
                        self._plate_detector.model.half()
                    except Exception:
                        pass
                print(f'[anpr] loaded plate detector on {device}: {model_path}')
            except Exception as exc:
                print(f'[anpr] warning: could not load plate detector: {exc}')
        else:
            print('[anpr] no plate detector model found — Stage 1 disabled. '
                  'Place a YOLOv8/v11 plate detector at '
                  'models/license_plate_detector.pt for best ANPR results.')

    def _lazy(self):
        """Lazy-init EasyOCR (heavy import, only once)."""
        if self._reader is None:
            import easyocr
            import torch
            use_gpu = torch.cuda.is_available() and getattr(self.cfg, 'gpu', True)
            self._reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
        return self._reader

    # ------------------------------------------------------------------ #
    # Stage 1: Full-frame plate detection
    # ------------------------------------------------------------------ #

    def detect_plate_boxes(self, frame: np.ndarray) -> List[dict]:
        """Ultra-fast YOLO inference on GPU to locate plate bounding boxes in ~3ms without blocking OCR."""
        if self._plate_detector is None or frame is None or frame.size == 0:
            return []

        try:
            conf_thresh = getattr(self.cfg, 'plate_detector_conf', 0.25)
            results = self._plate_detector.predict(
                frame, conf=conf_thresh, verbose=False, device=getattr(self, 'device', 'cpu')
            )
            if not results or len(results[0].boxes) == 0:
                return []
        except Exception:
            return []

        plates = []
        h_img, w_img = frame.shape[:2]
        for box in results[0].boxes:
            x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].cpu().numpy()]
            det_score = float(box.conf)

            # 4% padding for clean characters
            pad_x = max(2, int((x2 - x1) * 0.04))
            pad_y = max(2, int((y2 - y1) * 0.04))
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y)
            cx2 = min(w_img, x2 + pad_x)
            cy2 = min(h_img, y2 + pad_y)

            plate_crop = frame[cy1:cy2, cx1:cx2]
            if plate_crop.size > 0:
                plates.append({
                    'bbox': [cx1, cy1, cx2, cy2],
                    'crop': plate_crop,
                    'conf': det_score,
                })
        return plates

    def detect_plates_in_frame(self, frame: np.ndarray) -> List[dict]:
        """Run YOLOv8 plate detector on the FULL FRAME.

        For each detected plate bbox:
          1. Crop the plate region
          2. Detect plate background colour
          3. Apply colour-aware adaptive threshold (replaces fixed-64 threshold)
          4. EasyOCR with Indian format validation
          5. Fallback to multi-pass Indian pipeline if needed

        Returns list of dicts:
          {bbox, bbox_score, text, text_score}
        """
        if self._plate_detector is None or frame is None or frame.size == 0:
            return []

        try:
            conf_thresh = getattr(self.cfg, 'plate_detector_conf', 0.20)
            results = self._plate_detector.predict(frame, conf=conf_thresh,
                                                   verbose=False)
            if not results or len(results[0].boxes) == 0:
                return []
        except Exception:
            return []

        reader = self._lazy()
        plates = []
        h_img, w_img = frame.shape[:2]

        for box in results[0].boxes:
            x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].cpu().numpy()]
            det_score = float(box.conf)

            cx1 = max(0, x1)
            cy1 = max(0, y1)
            cx2 = min(w_img, x2)
            cy2 = min(h_img, y2)
            plate_crop = frame[cy1:cy2, cx1:cx2]

            if plate_crop.size == 0:
                continue

            plate_crop = correct_plate_perspective(plate_crop)

            # --- Colour-aware adaptive threshold (paper recommendation) ---
            plate_type, text_is_dark = detect_plate_background(plate_crop)
            gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
            denoised = cv2.bilateralFilter(gray, 7, 55, 55)

            thresh_mode = (cv2.THRESH_BINARY if text_is_dark
                           else cv2.THRESH_BINARY_INV)
            adaptive_thresh = cv2.adaptiveThreshold(
                denoised, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                thresh_mode, blockSize=15, C=8)

            # --- Try Indian-aware EasyOCR on adaptive threshold ---
            plate_text, plate_score = read_license_plate_ref(
                reader, adaptive_thresh)

            # --- Fallback: try Otsu threshold ---
            if plate_text is None:
                _, otsu = cv2.threshold(denoised, 0, 255,
                                        cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                if not text_is_dark:
                    otsu = cv2.bitwise_not(otsu)
                plate_text, plate_score = read_license_plate_ref(reader, otsu)

            # --- Fallback: full multi-pass Indian pipeline ---
            if plate_text is None:
                plate_text, plate_score = self._read_indian(plate_crop)

            plates.append({
                'bbox':       [cx1, cy1, cx2, cy2],
                'bbox_score': det_score,
                'text':       plate_text,
                'text_score': plate_score or 0.0,
            })

        return plates

    # ------------------------------------------------------------------ #
    # Stage 2: Per-crop OCR (async worker fallback)
    # ------------------------------------------------------------------ #

    def isolate_plate(self, vehicle_crop: np.ndarray) -> np.ndarray:
        """Run YOLOv8-plate on a vehicle crop to get a tight plate bounding box."""
        if (self._plate_detector is None
                or vehicle_crop is None or vehicle_crop.size == 0):
            return vehicle_crop

        h, w = vehicle_crop.shape[:2]
        if h < 20 or w < 20:
            return vehicle_crop

        try:
            conf_thresh = getattr(self.cfg, 'plate_detector_conf', 0.20)
            results = self._plate_detector.predict(
                vehicle_crop, imgsz=320, conf=conf_thresh, verbose=False)
            if not results or len(results[0].boxes) == 0:
                return vehicle_crop

            boxes = results[0].boxes
            best_idx = int(boxes.conf.cpu().numpy().argmax())
            x1, y1, x2, y2 = [int(round(v))
                                for v in boxes.xyxy[best_idx].cpu().numpy()]

            pad_x = max(2, int((x2 - x1) * 0.06))
            pad_y = max(2, int((y2 - y1) * 0.08))
            px1 = max(0, x1 - pad_x)
            py1 = max(0, y1 - pad_y)
            px2 = min(w, x2 + pad_x)
            py2 = min(h, y2 + pad_y)

            if px2 > px1 and py2 > py1:
                sub = vehicle_crop[py1:py2, px1:px2]
                if sub.size > 0:
                    return correct_plate_perspective(sub)
        except Exception:
            pass
        return vehicle_crop

    def _read_indian(self, crop: np.ndarray) -> Tuple[Optional[str], float]:
        """Multi-pass OCR fully optimised for Indian plate structure.

        Tries every preprocessed image variant returned by
        preprocess_indian_plate() and keeps the best result that passes
        the Indian format validator.
        """
        if crop is None or crop.size == 0:
            return None, 0.0

        reader = self._lazy()
        best_text, best_conf = None, 0.0
        variants = preprocess_indian_plate(crop)

        for image in variants:
            if image is None or image.size == 0:
                continue
            try:
                raw_detections = reader.readtext(
                    image,
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    detail=1, paragraph=False,
                    text_threshold=0.15, low_text=0.10)
            except Exception:
                continue
            if not raw_detections:
                continue

            # Sort top-to-bottom, left-to-right with line binning (handles two-line plates)
            raw_detections = sort_plate_detections(raw_detections)
            raw = re.sub(r'[^A-Z0-9]', '',
                         ''.join(d[1] for d in raw_detections).upper())
            raw = strip_hsrp_prefix(raw)
            conf = float(np.mean([d[2] for d in raw_detections]))

            if len(raw) < 6:
                continue

            corrected = disambiguate_indian_plate(raw)

            # Validate against Indian format
            ok, _ = validate_indian_plate(corrected)
            if ok:
                return corrected, max(conf, 0.88)

            ok, _ = validate_indian_plate(raw)
            if ok:
                return raw, max(conf, 0.82)

            # Also check against config regex (catch partial matches)
            if self.regex.match(corrected) and conf > best_conf:
                best_text, best_conf = corrected, conf
            elif self.regex.match(raw) and conf > best_conf:
                best_text, best_conf = raw, conf
            elif len(corrected) >= 8 and conf > best_conf:
                best_text, best_conf = corrected, conf

        # Return best partial result with lower confidence
        if best_text and len(best_text) >= 8:
            final = disambiguate_indian_plate(best_text)
            ok, _ = validate_indian_plate(final)
            if ok:
                return final, max(best_conf, 0.82)
            return final, max(best_conf, 0.65)

        return None, 0.0

    def read(self, crop: np.ndarray) -> Tuple[Optional[str], float]:
        """Read a plate from a vehicle bumper crop (called by async OCR worker).

        Step 1: Try to isolate tight plate region using YOLOv8.
        Step 2: Multi-pass Indian OCR on the isolated crop.
        Step 3: If isolation failed / returned nothing, try on full vehicle crop.
        """
        if crop is None or crop.size == 0:
            return None, 0.0

        # Step 1: Isolate plate
        plate_img = self.isolate_plate(crop)

        # Step 2: Multi-pass Indian OCR on isolated plate
        text, score = self._read_indian(plate_img)
        if text is not None:
            return text, score

        # Step 3: If isolation returned the full crop, we already tried it.
        # If it returned a sub-crop, try the full vehicle crop as a last resort.
        if plate_img is not crop:
            text, score = self._read_indian(crop)
            if text is not None:
                return text, score

        return None, 0.0

    def read_fast(self, crop: np.ndarray) -> Tuple[Optional[str], float]:
        """High-speed single-pass OCR for video batch processing.
        Returns (plate, conf) if valid, or (None, 0.0) on failure to trigger multi-pass fallback.
        """
        if crop is None or crop.size == 0:
            return None, 0.0
        try:
            crop = correct_plate_perspective(crop)
            reader = self._lazy()
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            res = reader.readtext(enhanced, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                                  detail=1, paragraph=False, text_threshold=0.20, low_text=0.15)
            if not res:
                return None, 0.0

            # Sort using line-binning to prevent character swapping
            res = sort_plate_detections(res)
            raw = "".join(r[1].upper().replace(" ", "") for r in res)
            raw = strip_hsrp_prefix(raw)
            conf = float(sum(r[2] for r in res) / len(res))

            if len(raw) < 7:
                return None, 0.0

            corrected = disambiguate_indian_plate(raw)
            ok, valid_plate = validate_indian_plate(corrected)
            if ok:
                return valid_plate, round(conf, 2)

            ok_raw, valid_raw = validate_indian_plate(raw)
            if ok_raw:
                return valid_raw, round(conf, 2)

            # Check against regex config
            if self.regex.match(corrected):
                return corrected, round(conf, 2)
            if self.regex.match(raw):
                return raw, round(conf, 2)

            # Not a valid plate: return None so the full multi-pass pipeline runs!
            return None, 0.0
        except Exception:
            return None, 0.0

    def is_valid(self, plate: Optional[str]) -> bool:
        """True if plate passes both the regex and the Indian format validator."""
        if not plate:
            return False
        ok, _ = validate_indian_plate(plate)
        return ok or bool(self.regex.match(plate))


# ---------------------------------------------------------------------------
# Async OCR worker thread
# ---------------------------------------------------------------------------

class OCRWorker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reader = PlateReader(cfg)
        self._q: queue.Queue[OCRJob] = queue.Queue(maxsize=cfg.queue_size)
        self._results: Dict[int, OCRResult] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.processed = 0

    def start(self) -> 'OCRWorker':
        if not self.cfg.enabled:
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            target_crop = job.crop
            try:
                # If bumper or vehicle crop, isolate tight plate bounding box
                if job.crop.shape[0] > 70 or job.crop.shape[1] > 200:
                    isolated = self.reader.isolate_plate(job.crop)
                    if isolated is not None and isolated.size > 0:
                        target_crop = isolated
                target_crop = correct_plate_perspective(target_crop)
                plate, conf = self.reader.read_fast(target_crop)
                if not plate:
                    plate, conf = self.reader.read(target_crop)
            except Exception:
                plate, conf = None, 0.0
            self.processed += 1
            with self._lock:
                prev = self._results.get(job.track_id)
                if plate and (prev is None or conf > prev.confidence):
                    self._results[job.track_id] = OCRResult(
                        job.track_id, plate, conf, crop=target_crop)
                elif prev is None:
                    self._results[job.track_id] = OCRResult(
                        job.track_id, None, 0.0, crop=target_crop)

    def submit(self, track_id: int, crop: np.ndarray) -> bool:
        """Non-blocking submit. Drops oldest job if queue is full."""
        if not self.cfg.enabled or crop is None or crop.size == 0:
            return False
        job = OCRJob(track_id, crop.copy())
        try:
            self._q.put_nowait(job)
            return True
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(job)
                return True
            except Exception:
                return False

    def result(self, track_id: int) -> Optional[OCRResult]:
        with self._lock:
            return self._results.get(track_id)

    @property
    def backlog(self) -> int:
        return self._q.qsize()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)


# ---------------------------------------------------------------------------
# Utility: vehicle bumper crop  (used by engine.py)
# ---------------------------------------------------------------------------

def plate_crop(frame: np.ndarray, bbox, min_h: int) -> Optional[np.ndarray]:
    """Crop the bumper / plate-bearing region of a vehicle.

    For tall vehicles (cars, trucks): focuses on the lower 55% where
    both front and rear Indian plates are typically located.
    For motorcycles / bicycles (small bbox): uses full vehicle height
    since the plate is often near the centre or top of the rear.
    """
    h_img, w_img = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1

    if w < 24 or h < 24:
        return None

    if h < 90:
        # Small vehicle / motorcycle — use full bbox with slight padding
        y1_crop = max(0, int(y1 - 0.05 * h))
        y2_crop = min(h_img, int(y2 + 0.05 * h))
    else:
        # Car / truck / bus — lower 55% contains the plate
        y1_crop = max(0, int(y1 + 0.45 * h))
        y2_crop = min(h_img, int(y2 + 0.08 * h))

    x1_crop = max(0, int(x1 - 0.06 * w))
    x2_crop = min(w_img, int(x2 + 0.06 * w))

    if y2_crop <= y1_crop or x2_crop <= x1_crop:
        return None

    crop = frame[y1_crop:y2_crop, x1_crop:x2_crop]
    return crop if crop.size > 0 else None
