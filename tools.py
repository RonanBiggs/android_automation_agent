# tools.py

import base64
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

import requests

from prompts import build_vision_prompt


ADB_DEVICE = "emulator-5554"

E_WIDTH = 1080
E_HEIGHT = 2340

OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = "llama3.2-vision:11b"

SCREENSHOT_DIR = "screenshots"
DEBUG_DIR = "debug"

MAX_VISION_RETRIES = 2

TEXT_MODEL = "hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q5_K_M"

MAX_VISION_RETRIES = 2


def adb_cmd(args: list[str], *, timeout: int = 30, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", ADB_DEVICE] + args,
        capture_output=True,
        text=text,
        timeout=timeout,
    )


def clean_json_text(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        text = text.removeprefix("```").strip()

    if text.lower().startswith("json"):
        text = text[4:].strip()

    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    first = text.find("{")
    last = text.rfind("}")

    if first != -1 and last != -1 and last > first:
        return text[first:last + 1].strip()

    return text


def load_json_from_llm(text: str) -> dict[str, Any]:
    return json.loads(clean_json_text(text))


def encode_image_base64(path: str) -> str:
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def get_image_size(path: str) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError:
        return E_WIDTH, E_HEIGHT

    with Image.open(path) as img:
        return img.size


def clamp_int(value: Any, low: int, high: int) -> int:
    value = int(value)
    return max(low, min(high, value))

def adb_escape_text(text: str) -> str:
    """
    Escape text for: adb shell input text ...
    
    Android input text has awkward escaping:
    - spaces should usually be %s
    - some shell-sensitive characters need escaping
    """
    replacements = {
        " ": "%s",
        "&": r"\&",
        "|": r"\|",
        "<": r"\<",
        ">": r"\>",
        ";": r"\;",
        "(": r"\(",
        ")": r"\)",
        "'": r"\'",
        '"': r'\"',
        "\\": r"\\",
    }

    escaped = ""

    for char in text:
        escaped += replacements.get(char, char)

    return escaped


def tool_input_text(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return 'Input text failed: args must be {"text": "string"}.'

    if "text" not in args:
        return 'Input text failed: missing required field "text".'

    text = str(args["text"])

    if text == "":
        return "Input text failed: text was empty."

    escaped_text = adb_escape_text(text)

    result = adb_cmd(
        ["shell", "input", "text", escaped_text],
        timeout=15,
    )

    if result.returncode != 0:
        return f"Input text failed: {result.stderr.strip()}"

    return f"Input text complete: {text!r}"
def take_screenshot() -> str:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    timestamp = int(time.time() * 1000)
    local_path = os.path.join(SCREENSHOT_DIR, f"screen_{timestamp}.png")

    with open(local_path, "wb") as f:
        result = subprocess.run(
            ["adb", "-s", ADB_DEVICE, "exec-out", "screencap", "-p"],
            stdout=f,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"Screenshot failed: {stderr}")

    return local_path


def draw_bbox_debug(image_path: str, targets: list[dict[str, Any]]) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    os.makedirs(DEBUG_DIR, exist_ok=True)

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    for target in targets:
        try:
            l = int(target["bbox_left"])
            t = int(target["bbox_top"])
            r = int(target["bbox_right"])
            b = int(target["bbox_bottom"])
        except Exception:
            continue

        x = (l + r) // 2
        y = (t + b) // 2

        draw.rectangle((l, t, r, b), outline="red", width=5)
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), outline="blue", width=5)
        draw.line((x - 35, y, x + 35, y), fill="blue", width=3)
        draw.line((x, y - 35, x, y + 35), fill="blue", width=3)
        draw.text((l, max(0, t - 35)), str(target.get("label", "target")), fill="red")

    out_path = os.path.join(
        DEBUG_DIR,
        os.path.basename(image_path).replace(".png", "_bbox.png"),
    )
    img.save(out_path)
    return out_path


def parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)

    if not match:
        raise ValueError(f"Invalid bounds: {bounds}")

    left, top, right, bottom = map(int, match.groups())
    return left, top, right, bottom


def simplify_target_request(request: str) -> str:
    text = request.lower()

    junk_phrases = [
        "what are the coordinates of",
        "coordinates of",
        "find",
        "open",
        "tap",
        "click",
        "press",
        "where is",
        "locate",
        "the",
        "app",
        "icon",
        "button",
        "please",
        "screen",
        "on",
        "for",
    ]

    for phrase in junk_phrases:
        text = text.replace(phrase, " ")

    text = re.sub(r"[^a-z0-9_ .-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def dump_ui_xml() -> str | None:
    dump_result = adb_cmd(
        ["shell", "uiautomator", "dump", "/sdcard/window.xml"],
        timeout=20,
    )

    if dump_result.returncode != 0:
        return None

    cat_result = adb_cmd(
        ["exec-out", "cat", "/sdcard/window.xml"],
        timeout=20,
    )

    if cat_result.returncode != 0:
        return None

    xml_text = cat_result.stdout.strip()

    if not xml_text.startswith("<?xml") and "<hierarchy" not in xml_text:
        return None

    return xml_text


def find_ui_target(request: str) -> dict[str, Any] | None:
    query = simplify_target_request(request)

    if not query:
        return None

    xml_text = dump_ui_xml()

    if not xml_text:
        return None

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    query_tokens = [token for token in query.split() if token]

    if not query_tokens:
        return None

    candidates: list[dict[str, Any]] = []

    for node in root.iter("node"):
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        resource_id = node.attrib.get("resource-id", "")
        class_name = node.attrib.get("class", "")
        bounds = node.attrib.get("bounds", "")

        if not bounds:
            continue

        haystack = f"{text} {desc} {resource_id} {class_name}".lower()

        score = 0

        for token in query_tokens:
            if token in haystack:
                score += 10

        if query in haystack:
            score += 20

        if score <= 0:
            continue

        try:
            left, top, right, bottom = parse_bounds(bounds)
        except ValueError:
            continue

        box_w = right - left
        box_h = bottom - top

        if box_w <= 0 or box_h <= 0:
            continue

        label = text or desc or resource_id or "unknown"

        candidates.append(
            {
                "label": label,
                "type": "ui_element",
                "bbox_left": left,
                "bbox_top": top,
                "bbox_right": right,
                "bbox_bottom": bottom,
                "computed_center_x": (left + right) // 2,
                "computed_center_y": (top + bottom) // 2,
                "confidence": "high",
                "source": "uiautomator",
                "score": score,
                "evidence": f"text={text!r}, content-desc={desc!r}, resource-id={resource_id!r}",
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"], reverse=True)

    best = candidates[0]
    best.pop("score", None)

    return best


def ask_vision_model(image_path: str, prompt: str) -> str:
    image_b64 = encode_image_base64(image_path)

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                }
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 1200,
            },
        },
        timeout=300,
    )

    response.raise_for_status()

    data = response.json()
    content = data["message"]["content"]

    print("DEBUG vision raw:")
    print(content)

    return content


def validate_bbox(target: dict[str, Any], width: int, height: int) -> tuple[bool, str]:
    required = ["bbox_left", "bbox_top", "bbox_right", "bbox_bottom"]

    for key in required:
        if key not in target:
            return False, f"missing {key}"

    try:
        left = int(target["bbox_left"])
        top = int(target["bbox_top"])
        right = int(target["bbox_right"])
        bottom = int(target["bbox_bottom"])
    except (TypeError, ValueError):
        return False, "bbox fields must be integers"

    if not (0 <= left < right <= width):
        return False, f"x bounds out of range: {left}, {right}, width={width}"

    if not (0 <= top < bottom <= height):
        return False, f"y bounds out of range: {top}, {bottom}, height={height}"

    box_w = right - left
    box_h = bottom - top

    target_type = str(target.get("type", "unknown"))

    if target_type == "app_icon":
        if box_w < 50 or box_h < 50:
            return False, f"app_icon bbox too small: {box_w}x{box_h}"
    else:
        if box_w < 8 or box_h < 8:
            return False, f"bbox too small: {box_w}x{box_h}"

    if box_w > width * 0.85:
        return False, f"bbox too wide: {box_w}"

    if box_h > height * 0.85:
        return False, f"bbox too tall: {box_h}"

    return True, "ok"


def normalize_vision_json(raw_json: dict[str, Any]) -> dict[str, Any]:
    if raw_json.get("target_found") is False:
        return {
            "screen_summary": raw_json.get("screen_summary", ""),
            "visible_text": raw_json.get("visible_text", []),
            "target_found": False,
            "targets": [],
            "source": "vision",
        }

    target = raw_json.get("target")

    if target is None and isinstance(raw_json.get("targets"), list) and raw_json["targets"]:
        target = raw_json["targets"][0]

    if not isinstance(target, dict):
        return {
            "screen_summary": raw_json.get("screen_summary", ""),
            "visible_text": raw_json.get("visible_text", []),
            "target_found": False,
            "targets": [],
            "source": "vision",
            "error": "vision returned no usable target",
        }

    return {
        "screen_summary": raw_json.get("screen_summary", ""),
        "visible_text": raw_json.get("visible_text", []),
        "target_found": True,
        "targets": [target],
        "source": "vision",
    }


def tool_get_time(_: dict[str, Any]) -> str:
    result = subprocess.run(["date"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def tool_screenshot(_: dict[str, Any]) -> str:
    try:
        return take_screenshot()
    except Exception as exc:
        return f"Screenshot failed: {type(exc).__name__}: {exc}"


def tool_tap(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return 'Tap failed: args must be {"x": integer, "y": integer}.'

    if "x" not in args or "y" not in args:
        return 'Tap failed: tap requires {"x": integer, "y": integer}. Do not use x1/y1.'

    try:
        x = int(args["x"])
        y = int(args["y"])
    except (TypeError, ValueError):
        return "Tap failed: x and y must be integers."

    if not (0 <= x < E_WIDTH and 0 <= y < E_HEIGHT):
        return f"Tap failed: coordinate out of bounds for {E_WIDTH}x{E_HEIGHT}: ({x}, {y})"

    result = adb_cmd(["shell", "input", "tap", str(x), str(y)], timeout=10)

    if result.returncode != 0:
        return f"Tap failed: {result.stderr.strip()}"

    return f"Tap complete: ({x}, {y})"


def tool_swipe(args: dict[str, Any]) -> str:
    required = ["x1", "y1", "x2", "y2", "duration_ms"]

    for key in required:
        if key not in args:
            return f"Swipe failed: missing {key}"

    try:
        x1 = clamp_int(args["x1"], 0, E_WIDTH - 1)
        y1 = clamp_int(args["y1"], 0, E_HEIGHT - 1)
        x2 = clamp_int(args["x2"], 0, E_WIDTH - 1)
        y2 = clamp_int(args["y2"], 0, E_HEIGHT - 1)
        duration_ms = int(args["duration_ms"])
    except (TypeError, ValueError):
        return "Swipe failed: all coordinates and duration_ms must be integers."

    result = adb_cmd(
        [
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        ],
        timeout=15,
    )

    if result.returncode != 0:
        return f"Swipe failed: {result.stderr.strip()}"

    return f"Swipe complete: ({x1}, {y1}) -> ({x2}, {y2})"

def tool_keyevent(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return 'Keyevent failed: args must be {"key": "KEYCODE_NAME_OR_NUMBER"}.'

    if "key" not in args:
        return 'Keyevent failed: missing "key".'

    key = str(args["key"])

    result = adb_cmd(
        ["shell", "input", "keyevent", key],
        timeout=10,
    )

    if result.returncode != 0:
        return f"Keyevent failed: {result.stderr.strip()}"

    return f"Keyevent complete: {key}"

def tool_observe_screen(args: dict[str, Any]) -> str:
    request = str(args.get("request", "")).strip() or "Find the requested target"

    ui_target = find_ui_target(request)

    if ui_target is not None:
        observation = {
            "target_found": True,
            "targets": [ui_target],
            "message": "Target found using UIAutomator. Use computed_center_x and computed_center_y for tap.",
        }

        return "Observation:\n" + json.dumps(observation, indent=2)

    last_error = ""

    for attempt in range(1, MAX_VISION_RETRIES + 1):
        try:
            screenshot_path = take_screenshot()
        except Exception as exc:
            return f"Observation failed: screenshot failed: {type(exc).__name__}: {exc}"

        width, height = get_image_size(screenshot_path)
        prompt = build_vision_prompt(request, width, height)

        try:
            raw_vision_text = ask_vision_model(screenshot_path, prompt)
            raw_vision_json = load_json_from_llm(raw_vision_text)
        except Exception as exc:
            last_error = f"vision JSON parse failed on attempt {attempt}: {type(exc).__name__}: {exc}"
            continue

        vision = normalize_vision_json(raw_vision_json)

        if not vision.get("target_found"):
            last_error = "vision did not find target"
            continue

        valid_targets: list[dict[str, Any]] = []

        for target in vision.get("targets", []):
            is_valid, reason = validate_bbox(target, width, height)

            target["bbox_valid"] = is_valid
            target["bbox_error"] = None if is_valid else reason

            if not is_valid:
                last_error = reason
                continue

            left = int(target["bbox_left"])
            top = int(target["bbox_top"])
            right = int(target["bbox_right"])
            bottom = int(target["bbox_bottom"])

            target["computed_center_x"] = (left + right) // 2
            target["computed_center_y"] = (top + bottom) // 2
            target["source"] = "vision"

            valid_targets.append(target)

        if valid_targets:
            debug_path = draw_bbox_debug(screenshot_path, valid_targets)

            observation = {
                "target_found": True,
                "targets": valid_targets,
                "screenshot_path": screenshot_path,
                "debug_bbox_path": debug_path,
                "message": "Target found using vision. Use computed_center_x and computed_center_y for tap.",
            }

            return "Observation:\n" + json.dumps(observation, indent=2)

    observation = {
        "target_found": False,
        "targets": [],
        "error": last_error or "No valid target found",
        "message": "Do not tap. Try a different request, swipe, or use another tool.",
    }

    return "Observation:\n" + json.dumps(observation, indent=2)


TOOLS: dict[str, Callable[[dict[str, Any]], str]] = {
    "get_time": tool_get_time,
    "screenshot": tool_screenshot,
    "tap": tool_tap,
    "swipe": tool_swipe,
    "observe_screen": tool_observe_screen,
    "input_text": tool_input_text,
    "keyevent": tool_keyevent,
}
