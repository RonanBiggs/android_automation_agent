# Android AI Agent README

## Overview

This project is a local Android automation agent that controls an Android emulator through ADB.

It uses:

- A **text model** to plan what action should happen next
- **UIAutomator** to find normal Android UI elements by text/content description
- A **vision model** to inspect screenshots when UIAutomator cannot find the target
- ADB tools to tap, swipe, and take screenshots

The agent follows a cautious loop:

1. Read the user goal.
2. Ask the planner model what tool to use.
3. Validate the model’s JSON.
4. Run the requested tool.
5. Feed the tool result back to the planner.
6. Repeat until the task is complete.

The current default emulator target is:

```text
emulator-5554
```

The current configured screen size is:

```text
1080x2340
```

---

## File Layout

```text
agent/
├── main.py      # Main agent loop and planner validation
├── tools.py     # ADB, screenshot, tap, swipe, UIAutomator, vision tooling
├── prompts.py   # Large text prompts for planner and vision models
├── screenshots/ # Saved screenshots
└── debug/       # Debug images with bounding boxes
```

---

## What Tasks This Agent Can Do

The agent can currently handle tasks like:

```text
find and open chrome
open settings
tap a visible button
find a visible app icon
open an app from the launcher
tap a text field
tap a dialog button
swipe the screen
take screenshots
inspect the current screen
```

It works best on normal Android UI where UIAutomator exposes text, content descriptions, and bounds.

It can also use vision for cases where UIAutomator fails, such as:

```text
icons without useful text labels
custom app layouts
image-heavy screens
non-standard UI elements
```

Current limitations:

```text
vision coordinates may still be wrong
only one emulator is configured by default
screen size is currently hardcoded
no long-term memory of previous screen states
no direct package-name app launching yet
no multi-emulator orchestration yet
```

---

## Required Services

Start Ollama:

```bash
ollama serve
```

Make sure your models exist locally:

```bash
ollama run hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q5_K_M
ollama run llama3.2-vision:11b
```

Start your emulator:

```bash
emulator -avd agent_phone_1 -gpu host -no-metrics -no-boot-anim
```

Check ADB:

```bash
adb devices -l
```

Expected:

```text
emulator-5554    device
```

Run the agent:

```bash
python main.py
```

Example goal:

```text
find and open chrome
```

---

## Important Tunable Variables

### In `tools.py`

```python
ADB_DEVICE = "emulator-5554"
```

Change this if using a different emulator or physical phone.

```python
E_WIDTH = 1080
E_HEIGHT = 2340
```

Change these if your device resolution changes.

Check resolution with:

```bash
adb -s emulator-5554 shell wm size
```

```python
OLLAMA_URL = "http://localhost:11434/api/chat"
```

Change this if Ollama is running somewhere else.

```python
VISION_MODEL = "llama3.2-vision:11b"
```

Change this to test another vision model, for example:

```python
VISION_MODEL = "qwen2.5vl:7b"
```

```python
MAX_VISION_RETRIES = 2
```

Controls how many times the vision fallback retries after invalid JSON or invalid bounding boxes.

Increase if your vision model is unreliable.

Decrease if you want faster failure.

```python
SCREENSHOT_DIR = "screenshots"
DEBUG_DIR = "debug"
```

Change where screenshots and debug images are saved.

```python
"num_predict": 1200
```

Inside `ask_vision_model`.

Controls max output length from the vision model.

Increase if JSON gets cut off.

Decrease if responses are too slow.

```python
"temperature": 0
```

Keeps model output deterministic.

Usually leave this at `0` for tool use.

---

### In `main.py`

```python
max_steps = 15
```

Maximum number of planner/tool iterations before the agent stops.

Increase for longer tasks.

Decrease to prevent runaway loops.

```python
"num_predict": 700
```

Inside `ask_llm`.

Controls max output length from the planner model.

Increase if planner responses are getting cut off.

Decrease if you want faster responses.

```python
timeout=120
```

Text model request timeout.

Increase if your model is slow.

```python
time.sleep(0.3)
```

Delay after tool calls.

Increase if the emulator needs more time after taps/swipes.

---

### In `prompts.py`

Planner prompt controls:

```text
whether observe_screen must be used alone
whether tap uses x/y
whether placeholders are forbidden
whether the planner should avoid guessing
```

Vision prompt controls:

```text
how many targets vision returns
whether visible_text is capped
how bounding boxes should be formatted
whether vision should avoid normalized coordinates
```

If the model keeps making the same mistake, fix it in `prompts.py` and also enforce it in runtime validation.

---

## Main Control Flow

```text
+----------------------+
| User enters goal     |
+----------+-----------+
           |
           v
+----------------------+
| Text planner model   |
| decides next action  |
+----------+-----------+
           |
           v
+----------------------+
| main.py parses JSON  |
+----------+-----------+
           |
           v
+----------------------+
| Validate action      |
+-----+------------+---+
      |            |
      | invalid    | valid
      v            v
+------------+   +----------------------+
| Send error |   | Run requested tool   |
| feedback   |   +----------+-----------+
+-----+------+              |
      |                     v
      |          +----------------------+
      |          | Tool result returned |
      |          +----------+-----------+
      |                     |
      +----------<----------+
                 |
                 v
+----------------------+
| Send result back to  |
| planner model        |
+----------+-----------+
           |
           v
+----------------------+
| Done?                |
+-----+------------+---+
      |            |
      | no         | yes
      v            v
+------------+   +----------------------+
| Next step  |   | Print final result   |
+------------+   +----------------------+
```

---

## `observe_screen` Control Flow

```text
+------------------------------+
| observe_screen(request)      |
+--------------+---------------+
               |
               v
+------------------------------+
| Try UIAutomator XML lookup   |
+--------------+---------------+
               |
        +------+------+
        |             |
        | found       | not found
        v             v
+---------------+   +-------------------+
| Return exact  |   | Take screenshot   |
| UI bounds     |   +---------+---------+
+-------+-------+             |
        |                     v
        |           +-------------------+
        |           | Send screenshot   |
        |           | to vision model   |
        |           +---------+---------+
        |                     |
        |                     v
        |           +-------------------+
        |           | Parse JSON        |
        |           +---------+---------+
        |                     |
        |                     v
        |           +-------------------+
        |           | Validate bbox     |
        |           +----+----------+---+
        |                |          |
        |                | valid    | invalid
        |                v          v
        |        +---------------+  +-------------------+
        |        | Compute tap   |  | Retry or return   |
        |        | center        |  | target_found false|
        |        +-------+-------+  +-------------------+
        |                |
        v                v
+------------------------------+
| Return observation to planner|
+------------------------------+
```

---

## Tool Flow Summary

### `observe_screen`

Preferred target-finding path:

```text
observe_screen
   ↓
UIAutomator XML lookup
   ↓
if found: return exact bounds
   ↓
if not found: screenshot
   ↓
vision model
   ↓
JSON parse
   ↓
bbox validation
   ↓
computed tap center
```

### `tap`

```text
planner provides x/y
   ↓
runtime validates x/y
   ↓
ADB runs input tap
```

### `swipe`

```text
planner provides x1/y1/x2/y2/duration_ms
   ↓
runtime validates fields
   ↓
coordinates are clamped to screen bounds
   ↓
ADB runs input swipe
```

---

## Why UIAutomator Comes Before Vision

UIAutomator gives exact Android UI bounds when available.

Example:

```text
content-desc="Chrome" bounds="[800,1300][1000,1500]"
```

That is more reliable than asking a vision model to estimate coordinates.

Vision is only used when UIAutomator cannot find the requested target.

---

## Debugging

Screenshots are saved in:

```text
screenshots/
```

Vision debug images are saved in:

```text
debug/
```

Debug images show:

```text
red rectangle = bounding box
blue crosshair = computed tap point
```

Open a debug image with:

```bash
xdg-open debug/some_file_bbox.png
```

---

## Common Failure Modes

### Planner tries to observe and tap in one response

Bad:

```json
{
  "actions": [
    {
      "tool": "observe_screen",
      "args": {
        "request": "Find Chrome"
      }
    },
    {
      "tool": "tap",
      "args": {
        "x": 900,
        "y": 1500
      }
    }
  ]
}
```

This is rejected.

The planner must observe first, wait for results, then tap in the next step.

---

### Planner uses placeholders

Bad:

```json
{
  "tool": "tap",
  "args": {
    "x": "{{chrome_x}}",
    "y": "{{chrome_y}}"
  }
}
```

This is rejected.

Coordinates must be real integers.

---

### Planner uses `x1/y1` for tap

Bad:

```json
{
  "tool": "tap",
  "args": {
    "x1": 900,
    "y1": 1500
  }
}
```

Correct:

```json
{
  "tool": "tap",
  "args": {
    "x": 900,
    "y": 1500
  }
}
```

`x1/y1` are only for swipes.

---

### Vision returns wrong coordinates

Check:

```text
debug/
```

If the red box is wrong, the vision model misread the screen.

Possible fixes:

```text
improve the request text
increase MAX_VISION_RETRIES
try a different vision model
prefer UIAutomator when possible
add OCR later
```

---

## Good Next Improvements

```text
add command line args for --device, --width, --height
auto-detect screen size at startup
support multiple emulators
add direct app launching by package name
add OCR fallback
add a no-tap dry-run mode
add structured logs
add a task queue
add screenshot comparison after each action
```
