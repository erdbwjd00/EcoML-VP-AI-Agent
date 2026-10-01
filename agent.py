# -*- coding: utf-8 -*-

import json
import os
import subprocess
from pathlib import Path
from openai import OpenAI


# ============================================================
# Local LLM
# ============================================================

QWEN_BASE_URL = os.environ.get(
    "QWEN_BASE_URL",
    "http://qwen-server:8080/v1",
)

client = OpenAI(
    base_url=QWEN_BASE_URL,
    api_key="local",
)

MODEL = "Qwen3-8B-Q4_K_M.gguf"


# ============================================================
# EcoML-VP tool
# ============================================================

ECOML_VP_DIR = Path(
    os.environ.get(
        "ECOML_VP_DIR",
        str(Path(__file__).resolve().parent / "EcoML-VP"),
    )
)

def run_ecoml_vp(fasta_path: str) -> str:
    """Run the existing EcoML-VP pipeline."""

    path = Path(fasta_path)

    if not path.exists():
        return f"ERROR: FASTA file not found: {fasta_path}"

    print(f"\n[Agent] Running EcoML-VP: {fasta_path}")

    try:
        result = subprocess.run(
            [
                "python",
                str(ECOML_VP_DIR / "main.py"),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(ECOML_VP_DIR),
        )

        if result.returncode != 0:
            return (
                "EcoML-VP execution failed.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        output = result.stdout.strip()

        print(f"[Agent] EcoML-VP result: {output}")

        return output

    except subprocess.TimeoutExpired:
        return "ERROR: EcoML-VP execution timed out."

def list_fasta_files(directory: str) -> str:
    """List FASTA files in a directory."""

    path = Path(directory)

    if not path.exists():
        return f"ERROR: Directory not found: {directory}"

    if not path.is_dir():
        return f"ERROR: Not a directory: {directory}"

    fasta_files = sorted(
        [
            str(p)
            for p in path.iterdir()
            if p.is_file()
            and p.suffix.lower() in [".fasta", ".fa", ".fna"]
        ]
    )

    if not fasta_files:
        return f"No FASTA files found in {directory}"

    return "\n".join(fasta_files)


# ============================================================
# Tool definition
# ============================================================

tools = [
    {
        "type": "function",
        "function": {
            "name": "list_fasta_files",
            "description": (
                "List FASTA files in a directory. "
                "Use this when the user asks to find or analyze "
                "FASTA files in a directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory containing FASTA files.",
                    }
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_ecoml_vp",
            "description": (
                "Run the existing EcoML-VP pipeline on an "
                "E. coli genomic FASTA file. "
                "Use this tool whenever the user asks to analyze "
                "an E. coli FASTA file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fasta_path": {
                        "type": "string",
                        "description": "Path to the FASTA file to analyze.",
                    }
                },
                "required": ["fasta_path"],
            },
        },
    },
]


# ============================================================
# Agent
# ============================================================

def run_agent(user_message: str):

    messages = [
        {
            "role": "system",
            "content": (
                "You are an AI assistant for EcoML-VP.\n"
                "\n"
                "When the user asks you to analyze an E. coli "
                "genomic FASTA file, you MUST use the "
                "run_ecoml_vp tool.\n"
                "\n"
                "If the user refers to FASTA files in a directory "
                "without specifying the exact filename, use "
                "list_fasta_files first.\n"
                "\n"
                "If the user asks to analyze all FASTA files in a "
                "directory, first use list_fasta_files, then analyze "
                "every FASTA file returned.\n"
                "\n"
                "Do not guess filenames.\n"
                "Do not guess prediction results.\n"
                "Do not infer or invent the meaning of an EcoML-VP "
                "output label.\n"
                "Report output labels exactly as returned by the "
                "program unless their meaning is explicitly documented.\n"
                "Use the actual EcoML-VP program and report its result.\n"
                "\n"
                "After analyzing multiple FASTA files, summarize each "
                "file and its exact EcoML-VP result separately.\n"
                "\n"
                "If a file analysis fails, report the actual error for "
                "that file and continue processing the other files."
            ),
        },
        {
            "role": "user",
            "content": user_message,
        },
    ]

    print("[Agent] Asking Qwen3...")

    while True:

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=512,
        )

        message = response.choices[0].message

        print("\n[DEBUG] Qwen3 response:")
        print(message)

        # ====================================================
        # 1. Qwen3가 정상적인 Tool call을 반환한 경우
        # ====================================================

        if message.tool_calls:

            messages.append(message)

            for tool_call in message.tool_calls:

                arguments = json.loads(
                    tool_call.function.arguments
                )

                tool_name = tool_call.function.name

                # --------------------------------------------
                # list_fasta_files
                # --------------------------------------------

                if tool_name == "list_fasta_files":

                    directory = arguments["directory"]

                    print(
                        f"[Agent] Tool call: "
                        f"list_fasta_files({directory})"
                    )

                    result = list_fasta_files(directory)

                # --------------------------------------------
                # run_ecoml_vp
                # --------------------------------------------

                elif tool_name == "run_ecoml_vp":

                    fasta_path = arguments["fasta_path"]

                    print(
                        f"[Agent] Tool call: "
                        f"run_ecoml_vp({fasta_path})"
                    )

                    result = run_ecoml_vp(fasta_path)

                # --------------------------------------------
                # Unknown tool
                # --------------------------------------------

                else:

                    result = (
                        f"ERROR: Unknown tool: {tool_name}"
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

            print(
                "[Agent] Tool result(s) sent back to Qwen3..."
            )

            continue

        # ====================================================
        # 2. Qwen3가 Tool call을 reasoning_content 안에
        #    <tool_call> 형태로 출력하는 경우
        # ====================================================

        reasoning = (
            getattr(message, "reasoning_content", "")
            or ""
        )

        if (
            "<tool_call>" in reasoning
            and "</tool_call>" in reasoning
        ):

            tool_text = reasoning.split(
                "<tool_call>", 1
            )[1].split(
                "</tool_call>", 1
            )[0].strip()

            try:

                tool_data = json.loads(tool_text)

                tool_name = tool_data["name"]
                arguments = tool_data["arguments"]

                print(
                    f"[Agent] Parsed tool call: "
                    f"{tool_name}({arguments})"
                )

                if tool_name == "list_fasta_files":

                    result = list_fasta_files(
                        arguments["directory"]
                    )

                elif tool_name == "run_ecoml_vp":

                    result = run_ecoml_vp(
                        arguments["fasta_path"]
                    )

                else:

                    result = (
                        f"ERROR: Unknown tool: {tool_name}"
                    )

                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                    }
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": "manual-tool-call",
                        "content": result,
                    }
                )

                print(
                    "[Agent] Tool result sent back to Qwen3..."
                )

                continue

            except (json.JSONDecodeError, KeyError) as e:

                print(
                    f"[Agent] Failed to parse tool call: {e}"
                )

        # ====================================================
        # 3. 일반적인 최종 답변
        # ====================================================

        return (
            message.content
            or "(No response)"
        )

# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("       EcoML-VP Local AI Agent")
    print("========================================")

    user_message = input("\nUser: ")

    answer = run_agent(user_message)

    print("\nAgent:")
    print(answer)
