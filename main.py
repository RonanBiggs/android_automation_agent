# main.py

import json
import time
from typing import Any

import requests

from prompts import build_system_prompt
from tools import E_HEIGHT, E_WIDTH, OLLAMA_URL, TEXT_MODEL, TOOLS, clean_json_text


def load_json_from_llm(text: str) -> dict[str, Any]:
    return json.loads(clean_json_text(text))


def ask_llm(messages: list[dict[str, str]]) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": TEXT_MODEL,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 700,
            },
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()
    return data["message"]["content"]


def validate_actions_or_feedback(actions: Any) -> tuple[bool, str]:
    if not isinstance(actions, list):
        return False, 'Invalid response. Return either {"final":"..."} or {"actions":[...]}.'

    if not actions:
        return False, "Invalid response. actions must not be empty."

    for action in actions:
        if not isinstance(action, dict):
            return False, "Invalid action. Each action must be an object."

        tool_name = action.get("tool")
        args = action.get("args", {})

        if tool_name not in TOOLS:
            return False, f"Unknown tool: {tool_name}"

        if not isinstance(args, dict):
            return False, f"Invalid args for {tool_name}. args must be an object."

    uses_observe = any(action.get("tool") == "observe_screen" for action in actions)

    if uses_observe and len(actions) > 1:
        return False, (
            "Invalid plan. observe_screen must be the only action in this step. "
            "Observe first, wait for the result, then decide whether to tap."
        )

    for action in actions:
        tool_name = action.get("tool")
        args = action.get("args", {})

        if tool_name == "tap":
            if "x" not in args or "y" not in args:
                return False, 'Invalid tap. Use {"x": integer, "y": integer}. Do not use x1/y1.'

            if not isinstance(args["x"], int) or not isinstance(args["y"], int):
                return False, "Invalid tap. x and y must be integers, not strings or placeholders."

            x = args["x"]
            y = args["y"]

            if not (0 <= x < E_WIDTH and 0 <= y < E_HEIGHT):
                return False, f"Invalid tap. Coordinates out of bounds for {E_WIDTH}x{E_HEIGHT}: ({x}, {y})"

        if tool_name == "swipe":
            required = ["x1", "y1", "x2", "y2", "duration_ms"]
            missing = [key for key in required if key not in args]

            if missing:
                return False, f"Invalid swipe. Missing fields: {missing}"

    return True, "ok"


def run_agent(user_goal: str, max_steps: int = 15) -> str:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(E_WIDTH, E_HEIGHT),
        },
        {
            "role": "user",
            "content": user_goal,
        },
    ]

    for step in range(max_steps):
        print(f"\n--- Agent step {step + 1} ---")

        try:
            llm_output = ask_llm(messages)
        except Exception as exc:
            return f"LLM request failed: {type(exc).__name__}: {exc}"

        print("LLM:", llm_output)

        try:
            response_obj = load_json_from_llm(llm_output)
        except json.JSONDecodeError:
            messages.append({"role": "assistant", "content": llm_output})
            messages.append(
                {
                    "role": "user",
                    "content": "Invalid JSON. Return exactly one JSON object and nothing else.",
                }
            )
            continue

        if "final" in response_obj:
            return str(response_obj["final"])

        actions = response_obj.get("actions")

        valid, feedback = validate_actions_or_feedback(actions)

        if not valid:
            print("Validation feedback:", feedback)

            messages.append({"role": "assistant", "content": llm_output})
            messages.append(
                {
                    "role": "user",
                    "content": feedback + " Return corrected JSON only.",
                }
            )
            continue

        assert isinstance(actions, list)

        messages.append({"role": "assistant", "content": llm_output})

        tool_results: list[dict[str, Any]] = []

        for action in actions:
            tool_name = action["tool"]
            args = action.get("args", {})

            print(f"Calling tool: {tool_name} {args}")

            tool_fn = TOOLS[tool_name]

            try:
                tool_result = tool_fn(args)
            except Exception as exc:
                tool_result = f"Tool error: {type(exc).__name__}: {exc}"

            print("Tool result:", tool_result)

            tool_results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": tool_result,
                }
            )

            time.sleep(0.3)

        messages.append(
            {
                "role": "user",
                "content": "Tool results:\n" + json.dumps(tool_results, indent=2),
            }
        )

    return "Agent stopped due to max step limit."


def main() -> None:
    goal = input("Goal: ").strip()

    if not goal:
        print("No goal provided.")
        return

    result = run_agent(goal)

    print("\nFinal Result:")
    print(result)


if __name__ == "__main__":
    main()
