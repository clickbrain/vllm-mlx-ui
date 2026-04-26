# SPDX-License-Identifier: Apache-2.0
"""Quality benchmark runner — GSM8K, MMLU, HumanEval against the live server."""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

# ── Bundled question sets ─────────────────────────────────────────────────────

GSM8K_QUESTIONS: list[dict[str, str]] = [
    {"id": "gsm_01", "question": "A baker made 48 cookies and packed them equally into 6 bags. She then sold 3 bags. How many cookies does she have left?", "answer": "24"},
    {"id": "gsm_02", "question": "A train travels 60 miles per hour. How many miles will it travel in 2 hours and 30 minutes?", "answer": "150"},
    {"id": "gsm_03", "question": "A store has 120 apples. They sell 45 apples on Monday and 38 apples on Tuesday. How many apples are left?", "answer": "37"},
    {"id": "gsm_04", "question": "Sarah earns $12 per hour. If she works 8 hours a day for 5 days, how much does she earn in total?", "answer": "480"},
    {"id": "gsm_05", "question": "A rectangular garden is 15 meters long and 8 meters wide. What is the area of the garden in square meters?", "answer": "120"},
    {"id": "gsm_06", "question": "There are 32 students in a class. If 3/8 of them play soccer, how many students play soccer?", "answer": "12"},
    {"id": "gsm_07", "question": "A bottle contains 2 liters of juice. If you pour out 350 milliliters, how many milliliters remain?", "answer": "1650"},
    {"id": "gsm_08", "question": "Tom has 5 boxes of crayons. Each box has 24 crayons. He gives away 37 crayons. How many crayons does he have left?", "answer": "83"},
    {"id": "gsm_09", "question": "A car uses 8 liters of fuel every 100 km. How many liters does it need to travel 350 km?", "answer": "28"},
    {"id": "gsm_10", "question": "A pizza is cut into 8 equal slices. If 3 people each eat 2 slices, how many slices remain?", "answer": "2"},
    {"id": "gsm_11", "question": "A library has 240 books. 60 are checked out and 15 are lost. How many books are available?", "answer": "165"},
    {"id": "gsm_12", "question": "A shirt costs $25 and pants cost $40. If you buy 2 shirts and 1 pair of pants, how much do you spend?", "answer": "90"},
    {"id": "gsm_13", "question": "A pool holds 5000 liters. A pump fills it at 125 liters per minute. How many minutes does it take to fill the pool?", "answer": "40"},
    {"id": "gsm_14", "question": "There are 7 days in a week. How many days are in 13 weeks?", "answer": "91"},
    {"id": "gsm_15", "question": "A farmer has 4 fields. Each field produces 850 kg of wheat. He sells 1200 kg. How many kg of wheat does he have left?", "answer": "2200"},
    {"id": "gsm_16", "question": "A school bus can carry 36 students. If 145 students need to travel, how many buses are needed?", "answer": "5"},
    {"id": "gsm_17", "question": "Maria saves $15 every week. After 6 weeks she spends $40. How much money does she have left?", "answer": "50"},
    {"id": "gsm_18", "question": "A rope is 48 meters long. It is cut into pieces of 6 meters each. How many pieces are there?", "answer": "8"},
    {"id": "gsm_19", "question": "A bookstore sells 85 books on Saturday and 62 books on Sunday. Each book costs $12. What are total sales in dollars?", "answer": "1764"},
    {"id": "gsm_20", "question": "There are 12 eggs in a dozen. A restaurant uses 7 dozen eggs per day. How many eggs does it use in 3 days?", "answer": "252"},
    {"id": "gsm_21", "question": "A cyclist rides 18 km per hour. How far does she travel in 2 hours and 20 minutes?", "answer": "42"},
    {"id": "gsm_22", "question": "A box contains 6 rows of oranges with 9 oranges per row. 17 oranges are removed. How many oranges remain?", "answer": "37"},
    {"id": "gsm_23", "question": "A class has 30 students. 40% passed an exam. How many students failed?", "answer": "18"},
    {"id": "gsm_24", "question": "A warehouse stores 500 crates. 120 are shipped Monday and 85 are shipped Tuesday. How many remain?", "answer": "295"},
    {"id": "gsm_25", "question": "A recipe calls for 3 cups of flour for 12 cookies. How many cups of flour are needed to make 60 cookies?", "answer": "15"},
]

MMLU_QUESTIONS: list[dict[str, Any]] = [
    # Elementary science (5)
    {"id": "mmlu_01", "subject": "science", "question": "What is the chemical symbol for water?", "choices": {"A": "CO2", "B": "H2O", "C": "NaCl", "D": "O2"}, "answer": "B"},
    {"id": "mmlu_02", "subject": "science", "question": "Which planet is known as the Red Planet?", "choices": {"A": "Venus", "B": "Jupiter", "C": "Mars", "D": "Saturn"}, "answer": "C"},
    {"id": "mmlu_03", "subject": "science", "question": "What force pulls objects toward Earth?", "choices": {"A": "Magnetism", "B": "Friction", "C": "Gravity", "D": "Tension"}, "answer": "C"},
    {"id": "mmlu_04", "subject": "science", "question": "What is the powerhouse of the cell?", "choices": {"A": "Nucleus", "B": "Ribosome", "C": "Mitochondria", "D": "Vacuole"}, "answer": "C"},
    {"id": "mmlu_05", "subject": "science", "question": "Which gas do plants absorb during photosynthesis?", "choices": {"A": "Oxygen", "B": "Nitrogen", "C": "Carbon Dioxide", "D": "Hydrogen"}, "answer": "C"},
    # World history (5)
    {"id": "mmlu_06", "subject": "history", "question": "In which year did World War II end?", "choices": {"A": "1943", "B": "1944", "C": "1945", "D": "1946"}, "answer": "C"},
    {"id": "mmlu_07", "subject": "history", "question": "Who was the first President of the United States?", "choices": {"A": "John Adams", "B": "Thomas Jefferson", "C": "Benjamin Franklin", "D": "George Washington"}, "answer": "D"},
    {"id": "mmlu_08", "subject": "history", "question": "The French Revolution began in which year?", "choices": {"A": "1776", "B": "1789", "C": "1804", "D": "1815"}, "answer": "B"},
    {"id": "mmlu_09", "subject": "history", "question": "Which ancient wonder was located in Alexandria, Egypt?", "choices": {"A": "Colossus of Rhodes", "B": "Hanging Gardens", "C": "Lighthouse of Alexandria", "D": "Statue of Zeus"}, "answer": "C"},
    {"id": "mmlu_10", "subject": "history", "question": "The Berlin Wall fell in which year?", "choices": {"A": "1987", "B": "1988", "C": "1989", "D": "1991"}, "answer": "C"},
    # Common sense reasoning (5)
    {"id": "mmlu_11", "subject": "reasoning", "question": "If all roses are flowers and some flowers fade quickly, which must be true?", "choices": {"A": "All roses fade quickly", "B": "Some roses may fade quickly", "C": "No roses fade quickly", "D": "Roses are not flowers"}, "answer": "B"},
    {"id": "mmlu_12", "subject": "reasoning", "question": "A bat and a ball cost $1.10 in total. The bat costs $1 more than the ball. How much does the ball cost?", "choices": {"A": "10 cents", "B": "5 cents", "C": "15 cents", "D": "20 cents"}, "answer": "A"},
    {"id": "mmlu_13", "subject": "reasoning", "question": "If you overtake the second-place runner in a race, what place are you in?", "choices": {"A": "First", "B": "Second", "C": "Third", "D": "Last"}, "answer": "B"},
    {"id": "mmlu_14", "subject": "reasoning", "question": "A doctor gives you 3 pills and says take one every half hour. How long until all pills are taken?", "choices": {"A": "90 minutes", "B": "60 minutes", "C": "30 minutes", "D": "120 minutes"}, "answer": "B"},
    {"id": "mmlu_15", "subject": "reasoning", "question": "What comes next in the sequence: 2, 4, 8, 16, ?", "choices": {"A": "24", "B": "18", "C": "32", "D": "20"}, "answer": "C"},
    # Computer science basics (5)
    {"id": "mmlu_16", "subject": "computer_science", "question": "What does CPU stand for?", "choices": {"A": "Central Processing Unit", "B": "Core Processing Utility", "C": "Central Program Unit", "D": "Computer Processing Unit"}, "answer": "A"},
    {"id": "mmlu_17", "subject": "computer_science", "question": "In binary, what is the decimal value of 1010?", "choices": {"A": "8", "B": "10", "C": "12", "D": "14"}, "answer": "B"},
    {"id": "mmlu_18", "subject": "computer_science", "question": "Which data structure uses LIFO (Last In First Out) ordering?", "choices": {"A": "Queue", "B": "Stack", "C": "Linked List", "D": "Tree"}, "answer": "B"},
    {"id": "mmlu_19", "subject": "computer_science", "question": "What is the time complexity of binary search?", "choices": {"A": "O(n)", "B": "O(n²)", "C": "O(log n)", "D": "O(1)"}, "answer": "C"},
    {"id": "mmlu_20", "subject": "computer_science", "question": "Which of these is NOT a programming paradigm?", "choices": {"A": "Object-oriented", "B": "Functional", "C": "Procedural", "D": "Alphabetical"}, "answer": "D"},
    # General knowledge (5)
    {"id": "mmlu_21", "subject": "general", "question": "What is the capital of Japan?", "choices": {"A": "Osaka", "B": "Kyoto", "C": "Tokyo", "D": "Hiroshima"}, "answer": "C"},
    {"id": "mmlu_22", "subject": "general", "question": "How many sides does a hexagon have?", "choices": {"A": "5", "B": "6", "C": "7", "D": "8"}, "answer": "B"},
    {"id": "mmlu_23", "subject": "general", "question": "What is the largest ocean on Earth?", "choices": {"A": "Atlantic", "B": "Indian", "C": "Arctic", "D": "Pacific"}, "answer": "D"},
    {"id": "mmlu_24", "subject": "general", "question": "Which element has the atomic number 1?", "choices": {"A": "Helium", "B": "Oxygen", "C": "Hydrogen", "D": "Carbon"}, "answer": "C"},
    {"id": "mmlu_25", "subject": "general", "question": "How many continents are there on Earth?", "choices": {"A": "5", "B": "6", "C": "7", "D": "8"}, "answer": "C"},
]

HUMANEVAL_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "he_01",
        "prompt": "Write a Python function `sum_evens(numbers: list[int]) -> int` that returns the sum of all even numbers in the list.",
        "entry_point": "sum_evens",
        "test_code": "assert sum_evens([1, 2, 3, 4]) == 6\nassert sum_evens([]) == 0\nassert sum_evens([1, 3, 5]) == 0",
    },
    {
        "id": "he_02",
        "prompt": "Write a Python function `reverse_string(s: str) -> str` that returns the reverse of the given string.",
        "entry_point": "reverse_string",
        "test_code": "assert reverse_string('hello') == 'olleh'\nassert reverse_string('') == ''\nassert reverse_string('a') == 'a'",
    },
    {
        "id": "he_03",
        "prompt": "Write a Python function `count_vowels(s: str) -> int` that returns the count of vowels (a, e, i, o, u, case-insensitive) in the string.",
        "entry_point": "count_vowels",
        "test_code": "assert count_vowels('hello') == 2\nassert count_vowels('AEIOU') == 5\nassert count_vowels('xyz') == 0",
    },
    {
        "id": "he_04",
        "prompt": "Write a Python function `is_palindrome(s: str) -> bool` that returns True if the string is a palindrome (reads the same forwards and backwards), False otherwise. Ignore case.",
        "entry_point": "is_palindrome",
        "test_code": "assert is_palindrome('racecar') == True\nassert is_palindrome('hello') == False\nassert is_palindrome('Madam') == True",
    },
    {
        "id": "he_05",
        "prompt": "Write a Python function `factorial(n: int) -> int` that returns the factorial of n. Assume n >= 0.",
        "entry_point": "factorial",
        "test_code": "assert factorial(0) == 1\nassert factorial(1) == 1\nassert factorial(5) == 120\nassert factorial(10) == 3628800",
    },
    {
        "id": "he_06",
        "prompt": "Write a Python function `flatten(lst: list) -> list` that takes a list of lists and returns a single flat list with all elements.",
        "entry_point": "flatten",
        "test_code": "assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]\nassert flatten([[], [1], [2, 3]]) == [1, 2, 3]\nassert flatten([]) == []",
    },
    {
        "id": "he_07",
        "prompt": "Write a Python function `remove_duplicates(lst: list) -> list` that removes duplicate elements from a list while preserving order.",
        "entry_point": "remove_duplicates",
        "test_code": "assert remove_duplicates([1, 2, 2, 3, 1]) == [1, 2, 3]\nassert remove_duplicates([]) == []\nassert remove_duplicates([1]) == [1]",
    },
    {
        "id": "he_08",
        "prompt": "Write a Python function `is_prime(n: int) -> bool` that returns True if n is a prime number, False otherwise. Assume n >= 2.",
        "entry_point": "is_prime",
        "test_code": "assert is_prime(2) == True\nassert is_prime(3) == True\nassert is_prime(4) == False\nassert is_prime(17) == True\nassert is_prime(100) == False",
    },
    {
        "id": "he_09",
        "prompt": "Write a Python function `celsius_to_fahrenheit(c: float) -> float` that converts Celsius to Fahrenheit using the formula F = C * 9/5 + 32.",
        "entry_point": "celsius_to_fahrenheit",
        "test_code": "assert celsius_to_fahrenheit(0) == 32.0\nassert celsius_to_fahrenheit(100) == 212.0\nassert celsius_to_fahrenheit(-40) == -40.0",
    },
    {
        "id": "he_10",
        "prompt": "Write a Python function `word_count(text: str) -> dict[str, int]` that counts the occurrences of each word in the string. Words are case-insensitive and separated by spaces.",
        "entry_point": "word_count",
        "test_code": "assert word_count('the cat sat on the mat') == {'the': 2, 'cat': 1, 'sat': 1, 'on': 1, 'mat': 1}\nassert word_count('') == {}",
    },
    {
        "id": "he_11",
        "prompt": "Write a Python function `max_subarray_sum(nums: list[int]) -> int` that returns the maximum sum of any contiguous subarray. If the list is empty, return 0.",
        "entry_point": "max_subarray_sum",
        "test_code": "assert max_subarray_sum([-2, 1, -3, 4, -1, 2, 1, -5, 4]) == 6\nassert max_subarray_sum([1]) == 1\nassert max_subarray_sum([]) == 0",
    },
    {
        "id": "he_12",
        "prompt": "Write a Python function `rotate_list(lst: list, k: int) -> list` that rotates the list to the right by k positions.",
        "entry_point": "rotate_list",
        "test_code": "assert rotate_list([1, 2, 3, 4, 5], 2) == [4, 5, 1, 2, 3]\nassert rotate_list([1, 2, 3], 0) == [1, 2, 3]\nassert rotate_list([], 3) == []",
    },
    {
        "id": "he_13",
        "prompt": "Write a Python function `title_case(s: str) -> str` that converts each word in the string to title case (first letter uppercase, rest lowercase).",
        "entry_point": "title_case",
        "test_code": "assert title_case('hello world') == 'Hello World'\nassert title_case('PYTHON IS FUN') == 'Python Is Fun'\nassert title_case('') == ''",
    },
    {
        "id": "he_14",
        "prompt": "Write a Python function `gcd(a: int, b: int) -> int` that returns the greatest common divisor of two positive integers.",
        "entry_point": "gcd",
        "test_code": "assert gcd(12, 8) == 4\nassert gcd(7, 13) == 1\nassert gcd(100, 75) == 25",
    },
    {
        "id": "he_15",
        "prompt": "Write a Python function `chunk_list(lst: list, size: int) -> list[list]` that splits a list into chunks of the given size. The last chunk may be smaller.",
        "entry_point": "chunk_list",
        "test_code": "assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\nassert chunk_list([], 3) == []\nassert chunk_list([1, 2, 3], 5) == [[1, 2, 3]]",
    },
]


# ── Grading functions ─────────────────────────────────────────────────────────

def grade_gsm8k(response: str, expected: str) -> bool:
    """Extract last number from response, compare to expected."""
    nums = re.findall(r"-?\d+\.?\d*", response)
    if not nums:
        return False
    got = nums[-1].rstrip(".")
    # Normalise: strip trailing zeros after decimal point
    try:
        return float(got) == float(expected)
    except ValueError:
        return got.strip() == expected.strip()


def grade_mmlu(response: str, expected: str) -> bool:
    """Find first standalone A/B/C/D in response, compare to expected."""
    m = re.search(r"\b([ABCD])\b", response.strip()[:200])
    if not m:
        return False
    return m.group(1).upper() == expected.upper()


def _extract_code(response: str) -> str:
    """Extract Python code block from markdown response, or return raw response."""
    # Try fenced code block with 'python' language tag first
    m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1)
    # Try any fenced code block
    m = re.search(r"```\w*\s*\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1)
    return response


def grade_humaneval(response: str, entry_point: str, test_code: str) -> tuple[bool, str]:
    """Run extracted code + test_code in subprocess. Return (passed, error_msg)."""
    code = _extract_code(response)
    full_script = code + "\n\n" + test_code + "\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = tmpdir + "/solution.py"
        with open(script_path, "w") as f:
            f.write(full_script)

        try:
            result = subprocess.run(
                ["python3", script_path],
                timeout=10,
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )
            if result.returncode == 0:
                return (True, "")
            err = (result.stderr or result.stdout or "non-zero exit").strip()
            return (False, err[:300])
        except subprocess.TimeoutExpired:
            return (False, "Timeout after 10s")
        except Exception as exc:
            return (False, str(exc)[:300])


# ── Main runner ───────────────────────────────────────────────────────────────

def _get_model_name(server_url: str) -> str:
    """Fetch the loaded model name from /v1/models."""
    try:
        resp = requests.get(f"{server_url}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        if models:
            return models[0].get("id", "unknown")
    except Exception:
        pass
    return "unknown"


def run_quality_benchmark(
    suites: list[str],
    server_url: str,
    num_questions: int = 20,
    output_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Run selected quality benchmark suites against the live server.
    Returns structured results dict with per-suite accuracy.
    """

    def _cb(line: str) -> None:
        if output_callback:
            output_callback(line)

    model_name = _get_model_name(server_url)
    suite_results: dict[str, Any] = {}

    for suite in suites:
        suite_upper = suite.upper()

        if suite == "gsm8k":
            questions = GSM8K_QUESTIONS[:num_questions]
            system_prompt = "Solve this math problem step by step. At the end, state your final answer as a single number."
            max_tokens = 512
        elif suite == "mmlu":
            questions = MMLU_QUESTIONS[:num_questions]
            system_prompt = "Answer this multiple choice question. Reply with just the letter (A, B, C, or D) followed by a brief explanation."
            max_tokens = 512
        elif suite == "humaneval":
            questions = HUMANEVAL_QUESTIONS[:num_questions]
            system_prompt = "Write a complete Python function. Respond with only the code in a Python code block."
            max_tokens = 1024
        else:
            _cb(f"[{suite_upper}] Unknown suite, skipping.\n")
            continue

        correct = 0
        total = len(questions)
        details: list[dict[str, Any]] = []

        for i, q in enumerate(questions, start=1):
            # Build user message
            if suite == "mmlu":
                choices_text = "\n".join(f"{k}. {v}" for k, v in q["choices"].items())
                user_msg = f"{q['question']}\n\n{choices_text}"
            elif suite == "humaneval":
                user_msg = q["prompt"]
            else:
                user_msg = q["question"]

            response_text = ""
            try:
                resp = requests.post(
                    f"{server_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.0,
                        "max_tokens": max_tokens,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                response_text = data["choices"][0]["message"]["content"]
            except Exception as exc:
                _cb(f"[{suite_upper} {i}/{total}] ✗ request error: {exc}\n")
                details.append({"id": q["id"], "correct": False, "error": str(exc)})
                continue

            # Grade
            if suite == "gsm8k":
                passed = grade_gsm8k(response_text, q["answer"])
                nums = re.findall(r"-?\d+\.?\d*", response_text)
                got_str = nums[-1] if nums else "?"
                if passed:
                    _cb(f"[{suite_upper} {i}/{total}] ✓ {got_str} (expected {q['answer']})\n")
                else:
                    _cb(f"[{suite_upper} {i}/{total}] ✗ got {got_str}, expected {q['answer']}\n")
                details.append({"id": q["id"], "correct": passed, "got": got_str, "expected": q["answer"]})

            elif suite == "mmlu":
                passed = grade_mmlu(response_text, q["answer"])
                m = re.search(r"\b([ABCD])\b", response_text.strip()[:200])
                got_str = m.group(1) if m else "?"
                if passed:
                    _cb(f"[{suite_upper} {i}/{total}] ✓ {got_str} (expected {q['answer']})\n")
                else:
                    _cb(f"[{suite_upper} {i}/{total}] ✗ got {got_str}, expected {q['answer']}\n")
                details.append({"id": q["id"], "correct": passed, "got": got_str, "expected": q["answer"]})

            elif suite == "humaneval":
                passed, err_msg = grade_humaneval(response_text, q["entry_point"], q["test_code"])
                if passed:
                    _cb(f"[{suite_upper} {i}/{total}] ✓ {q['entry_point']} passed\n")
                else:
                    short_err = err_msg.split("\n")[-1][:80] if err_msg else "failed"
                    _cb(f"[{suite_upper} {i}/{total}] ✗ {q['entry_point']}: {short_err}\n")
                details.append({"id": q["id"], "correct": passed, "error": err_msg if not passed else ""})

            if passed:
                correct += 1

        accuracy = correct / total if total > 0 else 0.0
        suite_results[suite] = {
            "correct": correct,
            "total": total,
            "accuracy": round(accuracy, 4),
            "details": details,
        }
        _cb(f"\n[{suite_upper}] Finished: {correct}/{total} ({accuracy:.0%})\n\n")

    # Overall score: weighted average across suites
    if suite_results:
        overall = sum(s["accuracy"] for s in suite_results.values()) / len(suite_results)
    else:
        overall = 0.0

    return {
        "suites": suite_results,
        "overall_score": round(overall, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "server_url": server_url,
    }
