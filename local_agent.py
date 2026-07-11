import json
import base64
import os
import time
import subprocess
import requests
from typing import Callable, Any

#emulator width/height
E_WIDTH = 1080
E_HEIGHT = 2340
OLLAMA_URL = "http://localhost:11434/api/chat"
#MODEL = "qwen3-coder:30b"
MODEL="hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q5_K_M"
VISION_MODEL = "llama3.2-vision:11b"
oldvmodel = "qwen2.5vl:7b"

def tool_get_time(_: dict) -> str:
    result = subprocess.run(
            ["date"],
            capture_output=True,
            text=True,
            check=True
            )
    return result.stdout.strip()

def tool_list_files(args: dict) -> str:
    path = args.get("path", ".")
    print(f"Path used: {path}")
    result = subprocess.run(
        ["ls", "-la", path],
        capture_output=True,
        text=True
    )
    return result.stdout or result.stderr

'''
args: x1 y1 x2 y2 duration_ms
'''
def tool_swipe(args: dict) -> str:
    x1 = int(args.get("x1", 0))
    y1 = int(args.get("y1", 0))
    x2 = int(args.get("x2", 0))
    y2 = int(args.get("y2", 0))
    duration_ms = int(args.get("duration_ms"))
    result = subprocess.run(
            [
                "adb",
                "-s",
                "emulator-5554",
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ],
            capture_output = True,
            text=True
        )
    print(f"stdout {result.stdout}")
    print(f"stderr {result.stderr}")
    return result.stdout or result.stderr or "Swipe complete"

def tool_tap(args: dict) -> str:
    x1 = int(args.get("x1", 0))
    y1 = int(args.get("y1", 0))
    result = subprocess.run(
            [
                "adb",
                "-s",
                "emulator-5554",
                "shell",
                "input",
                "tap",
                str(x1),
                str(y1),
            ],
            capture_output = True,
            text=True
        )
    return result.stdout or result.stderr or "Tap complete"

def tool_screenshot(args: dict) -> str:
    folder = "screenshots"
    os.makedirs(folder, exist_ok=True)
    timestamp = int(time.time())
    cap_result = subprocess.run(
            [
                "adb",
                "-s",
                "emulator-5554",
                "shell",
                "screencap",
                "-p",
                "/sdcard/screen.png",
            ],
            capture_output=True,
            text=True,
        )
    if cap_result.returncode != 0:
        return f"Screenshot failed: {cap_result.stderr}"
    local_path = f"./screenshots/screen_{timestamp}.png"
    pull_result = subprocess.run(
            [
                "adb",
                "-s",
                "emulator-5554",
                "pull",
                "/sdcard/screen.png",
                local_path,
            ],
            capture_output=True,
            text=True,
        )
    if pull_result.returncode != 0:
        return f"Screenshot pull failed: {pull_result.stderr}"
    return local_path

def encode_image_base64(path: str) -> str:
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

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
                 "temperature": 0
                }
            },
            timeout=120,
        )
    response.raise_for_status()
    data = response.json()
    return data["message"]["content"]

def bbox_check(center_x: int, center_y: int, bbox_l: int, bbox_r: int, bbox_t: int, bbox_b :int) -> bool:
    #check for valid box
    if bbox_b < 0 or bbox_b > E_HEIGHT or bbox_t < 0 or bbox_t > E_HEIGHT or bbox_l < 0 or bbox_l > E_WIDTH or bbox_r < 0 or bbox_r > E_WIDTH:
        return False
    if bbox_l >= bbox_r or bbox_t >= bbox_b:
        return False
    
    check_x = (bbox_l + bbox_r) // 2 
    check_y = (bbox_t + bbox_b) // 2
    #check that center given is within 10 of the actual bbox center
    if abs(center_x - check_x) < 10 or abs(center_y - check_y) < 10:
        return False
#have not yet added bbox_check in
def tool_observe_screen(args: dict) -> str:
    screenshot_path = tool_screenshot({})
    request = args.get("request", "No Request")
    if screenshot_path.startswith("Screenshot failed") or screenshot_path.startswith("Screenshot pull failed"):
        return "Screenshot Failed"
    sys_prompt: str = """
You are analyzing an Android emulator screenshot for an automation agent.

Your job:
- Inspect the screenshot carefully.
- Find visible UI elements relevant to the request.
- Return bounding boxes and tappable center coordinates.
- Return JSON only.

You are NOT controlling the emulator.
Do not say you tapped, swiped, opened, selected, clicked, or performed any action.
Only describe what is visible and where it is.

User/agent request:
{request}

Screen and coordinate system:
- The screenshot width is 1080 pixels.
- The screenshot height is 2340 pixels.
- x=0 is the left edge.
- y=0 is the top edge.
- x increases left to right.
- y increases top to bottom.
- Return physical screenshot pixel coordinates only.
- Do not return dp coordinates.
- Do not return normalized coordinates.
- Do not return fractions.
- Do not use default coordinates.
- Do not use placeholder coordinates.
- Do not copy coordinates from the schema.
- The screen center is approximately x=540, y=1170. Do not return the screen center unless the target is actually centered there.

Target rules:
- Search the entire screenshot.
- The target may be an app icon, button, menu item, tab, text field, checkbox, link, popup, dialog button, navigation control, or icon.
- The target may be represented by text, an icon, or both.
- If the request asks for an app, look for app icons and app labels.
- If multiple matching targets are visible, return all reasonable candidates sorted best-first.
- Do not invent invisible targets.
- If the target is not visible, set target_found to false.

Bounding box rules:
- bbox_left is the left edge of the visible target.
- bbox_top is the top edge of the visible target.
- bbox_right is the right edge of the visible target.
- bbox_bottom is the bottom edge of the visible target.
- All box coordinates must be inside the screenshot.
- bbox_left must be less than bbox_right.
- bbox_top must be less than bbox_bottom.
- For app icons, box the icon itself, not the text label underneath.
- For text buttons, box the visible button/tappable region.
- For icon-only buttons, box the visible icon or its tappable region.
- center_x should be approximately halfway between bbox_left and bbox_right.
- center_y should be approximately halfway between bbox_top and bbox_bottom.

Return JSON only.
Do not use Markdown.
Do not include prose before or after JSON.
Do not include comments.

If matching targets are visible, return this exact shape:

{
  "screen_summary": "brief description of the screen",
  "visible_text": ["text visible on screen"],
  "target_found": true,
  "targets": [
    {
      "label": "best name for the target",
      "type": "app_icon|button|text_field|menu_item|tab|checkbox|link|dialog|navigation|icon|unknown",
      "bbox_left": 0,
      "bbox_top": 0,
      "bbox_right": 1,
      "bbox_bottom": 1,
      "center_x": 0,
      "center_y": 0,
      "confidence": "low|medium|high",
      "evidence": "visible text, icon, or position that supports this target"
    }
  ]
}

The numbers in the schema are placeholders only.
Replace them with actual pixel coordinates from the screenshot.

If no matching target is visible, return this exact shape:

{
  "screen_summary": "brief description of the screen",
  "visible_text": ["text visible on screen"],
  "target_found": false,
  "targets": []
}
"""
    prompt = sys_prompt + request 
    vision_result = ask_vision_model(screenshot_path, prompt) 
    return(
        f"Vision analysis:\n{vision_result}"
    )
    
TOOLS: dict[str, Callable[[dict], str]] = {
        "get_time": tool_get_time,
        "list_files": tool_list_files,
        "swipe": tool_swipe,
        "tap": tool_tap,
        "screenshot": tool_screenshot,
        "observe_screen": tool_observe_screen
    }
"""
REMOVED:
    2. list_files
   Description: List files in a directory.
   Arguments: {"path": "directory path"}

1. get_time
   Description: Get the current local date and time.
   Arguments: {}


"""
SYSTEM_PROMPT = """
You are a local Android automation agent.

You control a phone using tools. You must be careful and minimal.

CRITICAL RULES:
- Return exactly one JSON object and nothing else.
- Do not use Markdown.
- Do not include comments inside JSON.
- Do not use placeholders like "{{x}}" or "replace with actual coordinate".
- All coordinates must be real integers.
- Never guess coordinates for a specific app/button unless you have already observed the screen.
- If you need to know what is visible, use observe_screen by itself.
- Do not combine observe_screen with tap or swipe in the same response.
- After observe_screen returns, use the observation result in the next step.
- Do not tap or swipe needlessly.
- Prefer observe_screen before any tap when the target location is unknown.
- Use tap only when you have a specific coordinate from observation.
- Use swipe only if the target is not visible and scrolling/searching is necessary.
- If using observe_screen do not attempt other tool calls in that iteration, wait for results.

Response format when using tools:

{
  "actions": [
    {
      "tool": "tool_name",
      "args": {}
    }
  ]
}

Response format when done:

{
  "final": "Done."
}


Valid tools are listed below.
"""
TOOL_DESCRIPTIONS = """
You have access to these tools:

1. swipe
   Description: Swipe on the phone screen. Valid X coordinates are in the range 0 to 719 and valid Y coordinates are in the range 0 to 1599. 
   Arguments: {
     "x1": Integer - starting x coordinate,
     "y1": Integer - starting y coordinate,
     "x2": Integer - ending x coordinate,
     "y2": Integer - ending y coordinate,
     "duration_ms": Integer - swipe duration in milliseconds
   }

1. tap
   Description: Tap on the phone screen. Valid X coordinates are in the range 0 to 719 and valid Y coordinates are in the range 0 to 1599. 
   Arguments: {
   "x1": Integer - x coordinate,
   "y1": Integer - y coordinate
  } 

4. screenshot
   Description: Save a screenshot of the phone screen.
   Arguments: {}
   Returns: Local screenshot path

5. observe_screen
    Description: Take a screenshot and ask a local vision model to describe visible screen elements, possible buttons, and approximate coordinates.
    Arguments: {
    "request": "Your request for analysis i.e. what are the coordinates of the calculator app" 
    }
    Returns: JSON-like visual analysis.

Rules:
- Return exactly one JSON object.
- Do not return Markdown.
- DO NOT precede any json replies with labels such as json or LLM.
- Do not return two JSON objects.
- If you need multiple actions, put them inside one "actions" array.
- Every action must have "tool" and "args".
- Only use tools listed above.

When you want to use tools, respond only like this:

{
  "actions": [
    {
      "tool": "swipe",
      "args": {
        "x1": 0,
        "y1": 500,
        "x2": 500,
        "y2": 500,
        "duration_ms": 300
      }
    }
  ]
}

When you are done, respond only like this:

{
  "final": "Done."
}
"""

def center_from_bbox(target: dict) -> tuple[int, int]:
    left = int(target["bbox_left"])
    top = int(target["bbox_top"])
    right = int(target["bbox_right"])
    bottom = int(target["bbox_bottom"])

    x = (left + right) // 2
    y = (top + bottom) // 2

    return x, y

def ask_llm(messages: list[dict]) -> str:
    response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0
                }
                },
            timeout=60,
    )
    response.raise_for_status()
    response_data = response.json()
    llm_text = response_data["message"]["content"]
    return llm_text

def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```").strip()
    if text.startswith("json"):
        text = text.removeprefix("json").strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()
    return text

def run_agent(user_goal: str, max_steps: int = 15) -> str:
    messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n\n" + TOOL_DESCRIPTIONS
                
            },
            {
                "role": "user",
                "content": user_goal,
            },
        ]
    for step in range(max_steps):
        print(f"\n--- Agent step {step + 1} ---")
        llm_output = ask_llm(messages)
        print("LLM:", llm_output)
        try:
            cleaned_output = clean_json_text(llm_output)
            response_obj = json.loads(cleaned_output)
        except json.JSONDecodeError:
            return f"LLM returned invalid json:\n{llm_output}"
        if "final" in response_obj:
            return response_obj["final"]

        actions = response_obj.get("actions")
        uses_observe = any(action.get("tool") == "observe_screen" for action in actions)

        if uses_observe and len(actions) > 1:
            messages.append({
                "role": "assistant",
                "content": "Invalid plan step skipped: observe_screen must be the only action in a step. You must observe first, wait for the result, then decide whether to tap."
                }) 
            continue
        for action in actions:
            if not isinstance(action, dict):
                return f"Each action must be a JSON object:\n{llm_output}"
            tool_name = action.get("tool")
            args = action.get("args", {})
            if tool_name not in TOOLS:
                return f"Unknown tool requested: {tool_name}"
            tool_function = TOOLS[tool_name]
            tool_result = tool_function(args)
            #time.sleep(.2)
            print("Tool result:", tool_result)
            messages.append({
                "role": "assistant",
                "content": llm_output,
                })
            messages.append({
                "role": "tool",
                "content": tool_result,
                })
    return "Agent stopped due to max step limit"
if __name__ == "__main__":
    goal = input("Goal: ")
    result = run_agent(goal)
    print("\nFinal Result:")
    print(result)

