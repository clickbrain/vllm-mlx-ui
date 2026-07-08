# SPDX-License-Identifier: Apache-2.0
"""Quality benchmark runner — dataset-backed benchmark suites against the live server."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import random
import re
import resource
import subprocess
import threading
import textwrap
import time as _time
import uuid
import zipfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from huggingface_hub import HfApi, hf_hub_download

from vllm_mlx.dashboard.hardware import fingerprint as _hw_fingerprint

logger = logging.getLogger(__name__)

DATASETS_CACHE_DIR = Path.home() / ".vllm_mlx_ui" / "benchmark_datasets"
CODE_EXEC_DIR = DATASETS_CACHE_DIR / "code_exec"
SAMPLE_SEED = 42
MAX_CODE_EXEC_OUTPUT = 500
_ALLOWED_BATCH_SIZES = {1, 2, 4, 8, 16, 32}
_DATASET_LOCK = threading.Lock()
_DATASET_CACHE: dict[str, list[dict[str, Any]]] = {}
_HF_API: HfApi | None = None
_MATHQA_SOURCE_URL = "https://math-qa.github.io/math-QA/data/MathQA.zip"
_MATHQA_SOURCE_SHA256 = "7344f30456a7aef3176d4866cc953b35b41bec44eda6b00cdbcfde2876b2f07a"
_DATASET_REVISIONS = {
    "openai/gsm8k": "740312add88f781978c0658806c59bc2815b9866",
    "cais/mmlu": "c30699e8356da336a370243923dbaf21066bb9fe",
    "openai/openai_humaneval": "7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544",
    "Rowan/hellaswag": "218ec52e09a7e7462a5400043bb9a69a41d06b76",
    "allenai/ai2_arc": "210d026faf9955653af8916fad021475a3f00453",
    "truthfulqa/truthful_qa": "741b8276f2d1982aa3d5b832d3ee81ed3b896490",
    "google-research-datasets/mbpp": "4bb6404fdc6cacfda99d4ac4205087b89d32030c",
    "livecodebench/code_generation_lite": "0fe84c3912ea0c4d4a78037083943e8f0c4dd505",
    "allenai/winogrande": "01e74176c63542e6b0bcb004dcdea22d94fb67b5",
}


class DatasetUnavailableError(RuntimeError):
    """Raised when a benchmark dataset cannot be downloaded or parsed."""


@dataclass(frozen=True)
class BenchmarkSpec:
    key: str
    label: str
    category: str
    description: str
    default_n: int
    full_size: int
    sizes: list[int]
    loader_key: str
    max_tokens: int
    temperature: float = 0.0
    code_exec: bool = False
    legacy: bool = False


class LazyDatasetList:
    """List-like wrapper that loads benchmark fixtures on first access."""

    def __init__(self, loader_key: str) -> None:
        self.loader_key = loader_key

    def _items(self) -> list[dict[str, Any]]:
        return _load_dataset(self.loader_key)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self._items()[index]

    def __len__(self) -> int:
        return len(self._items())

    def __iter__(self):
        return iter(self._items())


def _hf_api() -> HfApi:
    global _HF_API
    if _HF_API is None:
        _HF_API = HfApi()
    return _HF_API


def _ensure_cache_dirs() -> None:
    DATASETS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CODE_EXEC_DIR.mkdir(parents=True, exist_ok=True)


def _sample(items: list[Any], n: int) -> list[Any]:
    if n <= 0 or n >= len(items):
        return list(items)
    rng = random.Random(SAMPLE_SEED)
    return rng.sample(list(items), n)


def _stratified_sample(items: list[dict[str, Any]], n: int, key: str) -> list[dict[str, Any]]:
    """Sample n items stratified by `key` so every stratum gets proportional representation.

    Used for MMLU to ensure all 57 subjects appear even in small samples.
    Falls back to uniform random when `key` is absent.
    """
    if n <= 0 or n >= len(items):
        return list(items)

    # Group by stratum
    strata: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        stratum = str(item.get(key, "__unknown__"))
        strata.setdefault(stratum, []).append(item)

    if len(strata) <= 1:
        return _sample(items, n)

    rng = random.Random(SAMPLE_SEED)
    result: list[dict[str, Any]] = []
    n_strata = len(strata)

    # Guarantee at least 1 item per stratum (up to n), then distribute remainder proportionally
    base = n // n_strata
    remainder = n - base * n_strata

    stratum_keys = sorted(strata.keys())
    for i, sk in enumerate(stratum_keys):
        pool = strata[sk]
        take = base + (1 if i < remainder else 0)
        take = min(take, len(pool))
        result.extend(rng.sample(pool, take))

    # If we still need more (because some strata were smaller than base), top up
    if len(result) < n:
        taken_ids = {id(item) for item in result}
        extras = [item for item in items if id(item) not in taken_ids]
        still_needed = n - len(result)
        result.extend(rng.sample(extras, min(still_needed, len(extras))))

    rng.shuffle(result)
    return result


def _extract_mc_answer(response: str, valid_letters: list[str]) -> str:
    """Extract a multiple-choice letter answer from model output."""
    raw_text = _strip_thinking(response).strip()
    text = raw_text.upper()
    upper_letters = [letter.upper() for letter in valid_letters]
    letters = "".join(upper_letters)
    matches = re.findall(rf"(?:answer\s*(?:is|:)\s*)([{letters}])\b", raw_text, flags=re.IGNORECASE)
    if matches:
        return matches[-1].upper()
    all_matches = re.findall(rf"\b([{letters}])\b", text)
    if all_matches:
        return all_matches[-1]
    if text and text[0] in upper_letters and (len(text) == 1 or not text[1].isalnum()):
        return text[0]
    return ""


def _strip_thinking(text: str) -> str:
    """Remove <think> blocks before grading."""
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    stripped = re.sub(r"^\s*<think>.*", "", stripped, flags=re.DOTALL).strip()
    return stripped if stripped else text


def _extract_code(response: str) -> str:
    """Extract Python code block from markdown response, or return raw response."""
    text = _strip_thinking(response)
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"```\w*\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def _limit_code_resources() -> None:
    try:
        limit_bytes = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except Exception as exc:
        logger.debug("Could not fully apply subprocess resource limits: %s", exc)


def _execute_code(code: str, stdin_input: str = "", timeout: int = 15) -> tuple[bool, str, str]:
    """Execute Python code from a project-owned scratch directory."""
    _ensure_cache_dirs()
    script_path = CODE_EXEC_DIR / f"exec_{uuid.uuid4().hex}.py"
    try:
        script_path.write_text(code, encoding="utf-8")
        result = subprocess.run(
            ["python3", "-I", str(script_path)],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(CODE_EXEC_DIR),
            preexec_fn=_limit_code_resources,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",
            },
        )
        return result.returncode == 0, result.stdout, (result.stderr or "")[:MAX_CODE_EXEC_OUTPUT]
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as exc:
        logger.warning("Code execution failed", exc_info=True)
        return False, "", str(exc)[:MAX_CODE_EXEC_OUTPUT]
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Could not remove benchmark scratch file %s: %s", script_path, exc)


def grade_gsm8k(response: str, expected: str) -> bool:
    """Extract answer from GSM8K response, supporting both #### and last-number formats."""
    text = _strip_thinking(response)
    boxed = re.search(r"####\s*(-?\d+\.?\d*)", text)
    if boxed:
        got = boxed.group(1).rstrip(".")
        try:
            return float(got) == float(expected)
        except ValueError:
            return got.strip() == expected.strip()
    nums = re.findall(r"-?\d+\.?\d*", text)
    if not nums:
        return False
    got = nums[-1].rstrip(".")
    try:
        return float(got) == float(expected)
    except ValueError:
        return got.strip() == expected.strip()


def grade_mmlu(response: str, expected: str) -> bool:
    """Grade a multiple-choice response using robust answer extraction."""
    return _extract_mc_answer(response, ["A", "B", "C", "D"]) == expected.upper()


def grade_humaneval(response: str, prompt: str, entry_point: str, test_code: str) -> tuple[bool, str]:
    """Run extracted code + test_code in a subprocess. Return (passed, error_msg)."""
    code = _extract_code(response)
    if f"def {entry_point}" not in code:
        body_lines = []
        for line in code.splitlines():
            if line.startswith("    "):
                body_lines.append(line[4:])
            else:
                body_lines.append(line.lstrip())
        normalized_body = "\n".join(body_lines).lstrip("\n")
        code = prompt.rstrip() + "\n" + textwrap.indent(normalized_body, "    ")
    full_script = code + "\n\n" + test_code + f"\ncheck({entry_point})\n"
    ok, stdout, stderr = _execute_code(full_script, timeout=10)
    if ok:
        return True, ""
    err = (stderr or stdout or "non-zero exit").strip()
    return False, err[:300]


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 1000,
    ci: float = 0.95,
) -> tuple[float, float] | None:
    """Return (lower, upper) confidence interval via bootstrapping."""
    if len(values) < 2:
        return None
    n = len(values)
    rng = random.Random(SAMPLE_SEED)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower_idx = int(n_resamples * (1 - ci) / 2)
    upper_idx = int(n_resamples * (1 + ci) / 2)
    return means[lower_idx], means[min(upper_idx, len(means) - 1)]


# Official 5-shot MMLU examples from the MMLU dev split (Hendrycks et al. 2021).
# Drawn from five different subjects to match the diversity of the 57-subject eval.
# Source: cais/mmlu dev split — abstract_algebra[0], anatomy[0], astronomy[0],
# business_ethics[0], clinical_knowledge[0].
_MMLU_FEWSHOT: list[dict[str, str]] = [
    {
        "question": "Find the degree for the given field extension Q(sqrt(2), sqrt(3), sqrt(18)) over Q.",
        "choices": "A. 0\nB. 4\nC. 2\nD. 6",
        "answer": "B",
    },
    {
        "question": "A lesion causing compression of the facial nerve at the stylomastoid foramen will cause ipsilateral",
        "choices": "A. paralysis of the facial muscles.\nB. paralysis of the facial muscles and loss of taste.\nC. paralysis of the facial muscles, loss of taste, and decreased salivation.\nD. paralysis of the facial muscles, loss of taste, decreased salivation, and decreased lacrimation.",
        "answer": "A",
    },
    {
        "question": "Say the pupil of your eye has a diameter of 5 mm and you have a telescope with an aperture of 50 cm. How much more light can the telescope gather than your eye?",
        "choices": "A. 10000\nB. 100\nC. 1000\nD. 10",
        "answer": "A",
    },
    {
        "question": "Beyond the business case for engaging in CSR there are a number of moral arguments relating to: negative effects of business, the social contract, business ethics, and the stakeholder perspective. This is the _______ argument for CSR.",
        "choices": "A. humanity\nB. fairness\nC. business\nD. social",
        "answer": "D",
    },
    {
        "question": "The following are features of Alzheimer's disease except:",
        "choices": "A. short-term memory loss.\nB. confusion.\nC. poor attention and concentration.\nD. a prominent motor disturbance.",
        "answer": "D",
    },
]

# Official 8-shot chain-of-thought examples for GSM8K (Cobbe et al. 2021, Appendix D).
# These exact examples are used by lm-evaluation-harness and match published leaderboard scores.
_GSM8K_FEWSHOT: list[dict[str, str]] = [
    {
        "question": "There are 15 trees in the grove. Grove workers will plant trees in the grove today. After they are done, there will be 21 trees. How many trees did the grove workers plant today?",
        "answer": "We start with 15 trees. Later we have 21 trees. The difference must be the number of trees they planted. So, they must have planted 21 - 15 = 6 trees. The answer is #### 6",
    },
    {
        "question": "If there are 3 cars in the parking lot and 2 more cars arrive, how many cars are in the parking lot?",
        "answer": "There are 3 cars in the parking lot already. 2 more arrive. Now there are 3 + 2 = 5 cars. The answer is #### 5",
    },
    {
        "question": "Leah had 32 chocolates and her sister had 42. If they ate 35, how many pieces do they have left in total?",
        "answer": "Leah had 32 chocolates and Leah's sister had 42. That means there were originally 32 + 42 = 74 chocolates. 35 have been eaten. So in total they still have 74 - 35 = 39 chocolates. The answer is #### 39",
    },
    {
        "question": "Jason had 20 lollipops. He gave Denny some lollipops. Now Jason has 12 lollipops. How many lollipops did Jason give to Denny?",
        "answer": "Jason started with 20 lollipops. Then he gave some to Denny. Now he has 12 lollipops. The number of lollipops he gave to Denny must have been 20 - 12 = 8 lollipops. The answer is #### 8",
    },
    {
        "question": "Shawn has five toys. For Christmas, he got two toys each from his mom and dad. How many toys does he have now?",
        "answer": "He has 5 toys. He got 2 from mom, so after that he has 5 + 2 = 7 toys. Then he got 2 more from dad, so in total he has 7 + 2 = 9 toys. The answer is #### 9",
    },
    {
        "question": "There were nine computers in the server room. Five more computers were installed each day, from monday to thursday. How many computers are now in the server room?",
        "answer": "There are 4 days from monday to thursday. 5 computers were added each day. That means in total 4 * 5 = 20 computers were added. There were 9 computers in the beginning, so now there are 9 + 20 = 29 computers. The answer is #### 29",
    },
    {
        "question": "Michael had 58 golf balls. On tuesday, he lost 23 golf balls. On wednesday, he lost 2 more. How many golf balls did he have at the end of wednesday?",
        "answer": "Michael started with 58 golf balls. After losing 23 on tuesday, he had 58 - 23 = 35 golf balls. After losing 2 more, he had 35 - 2 = 33 golf balls. The answer is #### 33",
    },
    {
        "question": "Olivia has $23. She bought five bagels for $3 each. How much money does she have left?",
        "answer": "She bought 5 bagels for $3 each. This means she spent 5 * $3 = $15 on the bagels. She had $23 in the beginning. After spending $15, she had $23 - $15 = $8. The answer is #### 8",
    },
]


def _build_mmlu_messages(
    question: str,
    choices_text: str,
    system_prompt: str,
) -> list[dict[str, str]]:
    """Build 5-shot MMLU messages from the official dev split (Hendrycks et al. 2021)."""
    messages = [{"role": "system", "content": system_prompt}]
    for ex in _MMLU_FEWSHOT:
        messages.append({"role": "user", "content": f"{ex['question']}\n\n{ex['choices']}"})
        messages.append({"role": "assistant", "content": f"Answer: {ex['answer']}"})
    messages.append({"role": "user", "content": f"{question}\n\n{choices_text}\n\nAnswer:"})
    return messages


def _build_gsm8k_messages(question: str) -> list[dict[str, str]]:
    """Build 8-shot chain-of-thought messages for GSM8K (Cobbe et al. 2021 Appendix D).

    Uses the standard 8 CoT examples used by lm-evaluation-harness; matches published scores.
    """
    system_prompt = (
        "Solve the math problem step by step. "
        "Write your reasoning, then state your final answer after '####'."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for ex in _GSM8K_FEWSHOT:
        messages.append({"role": "user", "content": ex["question"]})
        messages.append({"role": "assistant", "content": ex["answer"]})
    messages.append({"role": "user", "content": question})
    return messages

MATH_QUESTIONS: list[dict[str, str]] = [
    {'id': 'math_01', 'problem': 'Simplify $\\frac{1}{1+\\sqrt{2}} + \\frac{1}{\\sqrt{2}+\\sqrt{3}} + \\frac{1}{\\sqrt{3}+\\sqrt{4}} + \\cdots + \\frac{1}{\\sqrt{24}+\\sqrt{25}}$.', 'answer': '4'},
    {'id': 'math_02', 'problem': 'Find all real numbers $x$ such that $|x-3| + |x+1| = 6$.', 'answer': '-2, 4'},
    {'id': 'math_03', 'problem': 'How many positive integers less than 1000 are divisible by 3 or 5?', 'answer': '467'},
    {'id': 'math_04', 'problem': 'Find $\\int_{0}^{1} x^2 e^x \\, dx$.', 'answer': 'e - 2'},
    {'id': 'math_05', 'problem': 'If $f(x) = x^2 - 4x + 3$, find the minimum value of $f(x)$.', 'answer': '-1'},
    {'id': 'math_06', 'problem': 'How many distinct ways can the letters in "MISSISSIPPI" be arranged?', 'answer': '34650'},
    {'id': 'math_07', 'problem': 'Find all solutions to $\\log_2(x) + \\log_2(x-2) = 3$.', 'answer': '4'},
    {'id': 'math_08', 'problem': 'What is the sum of the interior angles of a convex heptagon (in degrees)?', 'answer': '900'},
    {'id': 'math_09', 'problem': 'Find $\\lim_{x \\to 0} \\frac{\\sin(3x)}{x}$.', 'answer': '3'},
    {'id': 'math_10', 'problem': 'A fair coin is flipped 5 times. What is the probability of getting exactly 3 heads?', 'answer': '5/16'},
    {'id': 'math_11', 'problem': 'Find the determinant of $\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$.', 'answer': '-2'},
    {'id': 'math_12', 'problem': 'What is the 10th term of the arithmetic sequence 3, 7, 11, 15, ...?', 'answer': '39'},
    {'id': 'math_13', 'problem': 'How many 3-element subsets does a 7-element set have?', 'answer': '35'},
    {'id': 'math_14', 'problem': 'Solve $x^2 - 5x + 6 = 0$.', 'answer': '2, 3'},
    {'id': 'math_15', 'problem': 'What is the area of a circle with circumference $10\\pi$?', 'answer': '25π'},
    {'id': 'math_16', 'problem': 'Find $\\frac{d}{dx} \\ln(x^2 + 1)$.', 'answer': '2x/(x^2+1)'},
    {'id': 'math_17', 'problem': 'How many positive divisors does 72 have?', 'answer': '12'},
    {'id': 'math_18', 'problem': 'If $\\sin\\theta = 3/5$ and $\\theta$ is acute, find $\\cos\\theta$.', 'answer': '4/5'},
    {'id': 'math_19', 'problem': 'What is the remainder when $2^{10}$ is divided by 7?', 'answer': '2'},
    {'id': 'math_20', 'problem': 'How many solutions does the equation $x^2 = |x|$ have?', 'answer': '3'},
    {'id': 'math_21', 'problem': 'The sum of two numbers is 20 and their product is 91. Find the numbers.', 'answer': '7, 13'},
    {'id': 'math_22', 'problem': 'Find the distance between the points (1, 2) and (4, 6).', 'answer': '5'},
    {'id': 'math_23', 'problem': 'How many 5-digit numbers are palindromes?', 'answer': '900'},
    {'id': 'math_24', 'problem': 'Evaluate $\\sum_{k=1}^{100} (2k-1)$.', 'answer': '10000'},
    {'id': 'math_25', 'problem': 'If $f(x) = 2x + 1$ and $g(x) = x^2$, find $f(g(3))$.', 'answer': '19'},
    {'id': 'math_26', 'problem': 'A rectangle has perimeter 40 and area 96. Find its dimensions.', 'answer': '8, 12'},
    {'id': 'math_27', 'problem': 'Find $\\binom{7}{3}$.', 'answer': '35'},
    {'id': 'math_28', 'problem': 'Solve the inequality $x^2 - 4x + 3 > 0$.', 'answer': 'x < 1 or x > 3'},
    {'id': 'math_29', 'problem': 'What is the 5th term of the geometric sequence 2, 6, 18, ...?', 'answer': '162'},
    {'id': 'math_30', 'problem': 'How many ways can 5 people be seated in a row of 5 chairs?', 'answer': '120'},
    {'id': 'math_31', 'problem': 'Find $\\int \\cos(2x) \\, dx$.', 'answer': 'sin(2x)/2 + C'},
    {'id': 'math_32', 'problem': 'What is the smallest positive integer that is divisible by 2, 3, and 5?', 'answer': '30'},
    {'id': 'math_33', 'problem': 'Simplify $i^{2024}$ where $i = \\sqrt{-1}$.', 'answer': '1'},
    {'id': 'math_34', 'problem': 'If $\\tan\\theta = 1$, what is $\\theta$ in degrees for $0^\\circ < \\theta < 90^\\circ$?', 'answer': '45'},
    {'id': 'math_35', 'problem': 'How many diagonals does a convex octagon have?', 'answer': '20'},
    {'id': 'math_36', 'problem': 'The volume of a sphere is $36\\pi$. Find its radius.', 'answer': '3'},
    {'id': 'math_37', 'problem': 'Find the slope of the line through (2, 5) and (-1, 3).', 'answer': '2/3'},
    {'id': 'math_38', 'problem': 'How many integers from 1 to 100 are perfect squares?', 'answer': '10'},
    {'id': 'math_39', 'problem': 'Solve $3^{x} = 27$.', 'answer': '3'},
    {'id': 'math_40', 'problem': 'What is the probability of rolling a sum of 7 with two fair dice?', 'answer': '1/6'},
    {'id': 'math_41', 'problem': 'Find $\\sqrt{144} + \\sqrt{169}$.', 'answer': '25'},
    {'id': 'math_42', 'problem': 'If $x + y = 10$ and $x - y = 4$, find $x$.', 'answer': '7'},
    {'id': 'math_43', 'problem': 'How many faces does a cube have?', 'answer': '6'},
    {'id': 'math_44', 'problem': 'Find $\\sin(\\pi/6)$.', 'answer': '1/2'},
    {'id': 'math_45', 'problem': 'What is the sum of the first 10 positive integers?', 'answer': '55'},
    {'id': 'math_46', 'problem': 'If $f(x) = x^3$, find $f^{-1}(8)$.', 'answer': '2'},
    {'id': 'math_47', 'problem': 'How many zeros does the polynomial $x^3 - 3x^2 + 2x$ have?', 'answer': '3'},
    {'id': 'math_48', 'problem': 'The median of {3, 7, 2, 9, 5} is?', 'answer': '5'},
    {'id': 'math_49', 'problem': 'Find $\\log_{10}(1000)$.', 'answer': '3'},
    {'id': 'math_50', 'problem': 'If $a^2 - b^2 = 24$ and $a - b = 4$, find $a + b$.', 'answer': '6'},
]

def grade_math(response: str, expected: str) -> bool:
    """Grade MATH response by checking for the boxed answer."""
    text = _strip_thinking(response)
    # MATH canonical format: \boxed{answer}
    boxed = re.search(r"\\boxed\{([^}]+)\}", text)
    if boxed:
        got = boxed.group(1).strip()
        return _math_answer_match(got, expected)
    # Fallback: last expression after "answer is" or "="
    patterns = [
        r"(?:answer|result|value)(?:\s+is)?[:\s]+(.+?)[\.\n]",
        r"=\s*([^\n]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            got = m.group(1).strip().rstrip(".")
            return _math_answer_match(got, expected)
    return False


def _math_answer_match(got: str, expected: str) -> bool:
    """Compare math answers with normalisation."""
    got = got.strip().lower()
    exp = expected.strip().lower()

    def _norm(s: str) -> str:
        return re.sub(r"\s*([+\-*/=<>!])\s*", r"\1", s)

    # Direct string match first
    if got == exp:
        return True
    # Normalise spaces around operators so "e-2" matches "e - 2"
    if _norm(got) == _norm(exp):
        return True
    # Try numeric comparison
    try:
        g = float(got.replace("π", "").replace("pi", "").strip())
        e = float(exp.replace("π", "").replace("pi", "").strip())
        return abs(g - e) < 0.01
    except (ValueError, TypeError):
        pass
    # Comma-separated lists (e.g. "2, 3" vs "2,3")
    if "," in got and "," in exp:
        g_set = {x.strip() for x in got.split(",")}
        e_set = {x.strip() for x in exp.split(",")}
        if g_set == e_set:
            return True
    return False

IFEvalConstraint = dict[str, Any]

IFEval_QUESTIONS: list[dict[str, Any]] = [
    {'id': 'ifeval_01', 'instruction': 'Write exactly 2 paragraphs about climate change. Each paragraph must contain at least 3 sentences.', 'constraint': {'type': 'paragraph_count', 'value': 2, 'min_sentences_per': 3}},
    {'id': 'ifeval_02', 'instruction': 'List 5 countries in Africa. Response must be a JSON array.', 'constraint': {'type': 'json_array', 'min_items': 5}},
    {'id': 'ifeval_03', 'instruction': 'Write a 3-sentence story about a robot. End the story with the exact phrase "And that was that."', 'constraint': {'type': 'endswith', 'value': 'And that was that.'}},
    {'id': 'ifeval_04', 'instruction': 'Explain what machine learning is in 50 to 100 words.', 'constraint': {'type': 'word_count', 'min': 50, 'max': 100}},
    {'id': 'ifeval_05', 'instruction': 'Write 4 bullet points about Python features. Use markdown format with - at the start of each bullet.', 'constraint': {'type': 'bullet_count', 'value': 4, 'prefix': '-'}},
    {'id': 'ifeval_06', 'instruction': 'Write a sentence that contains the word "serendipity" and the word "unexpected".', 'constraint': {'type': 'contains_words', 'value': ['serendipity', 'unexpected']}},
    {'id': 'ifeval_07', 'instruction': 'Write a response in JSON format with keys: "name", "age", "city". Provide realistic values.', 'constraint': {'type': 'json_object', 'keys': ['name', 'age', 'city']}},
    {'id': 'ifeval_08', 'instruction': 'Write a haiku about autumn. The first line must have 5 syllables, the second 7, and the third 5.', 'constraint': {'type': 'haiku'}},
    {'id': 'ifeval_09', 'instruction': 'Write a sentence that does NOT contain the letter "e".', 'constraint': {'type': 'no_letter', 'value': 'e'}},
    {'id': 'ifeval_10', 'instruction': 'Write exactly 10 words about the weather today.', 'constraint': {'type': 'exact_word_count', 'value': 10}},
    {'id': 'ifeval_11', 'instruction': 'Write 3 sentences. The first sentence must start with "First," the second with "Second," and the third with "Third,".', 'constraint': {'type': 'starts_with_sequence', 'value': ['First,', 'Second,', 'Third,']}},
    {'id': 'ifeval_12', 'instruction': 'Count from 1 to 10. Put each number on its own line.', 'constraint': {'type': 'numbered_list', 'min_items': 10}},
    {'id': 'ifeval_13', 'instruction': 'Write a response that contains at least 3 question marks.', 'constraint': {'type': 'min_chars', 'char': '?', 'count': 3}},
    {'id': 'ifeval_15', 'instruction': 'Write a short recipe for chocolate chip cookies. Format it as a numbered list with exactly 5 steps.', 'constraint': {'type': 'numbered_list_exact', 'value': 5}},
    {'id': 'ifeval_16', 'instruction': 'Write a response where every sentence contains the word "the".', 'constraint': {'type': 'every_sentence_contains', 'value': 'the'}},
    {'id': 'ifeval_17', 'instruction': 'Write a poem of exactly 4 lines about programming.', 'constraint': {'type': 'line_count', 'value': 4}},
    {'id': 'ifeval_18', 'instruction': 'Explain the difference between TCP and UDP. Do NOT use the word "connection" in your response.', 'constraint': {'type': 'forbidden_word', 'value': 'connection'}},
    {'id': 'ifeval_19', 'instruction': 'Write a response that includes at least 3 different emojis.', 'constraint': {'type': 'min_emojis', 'value': 3}},
    {'id': 'ifeval_20', 'instruction': 'Write a single sentence that contains a colon, a semicolon, and a comma.', 'constraint': {'type': 'contains_punctuation', 'value': [':', ';', ',']}},
    {'id': 'ifeval_21', 'instruction': 'List exactly 7 programming languages. Each item must be on its own line starting with a number.', 'constraint': {'type': 'numbered_list_exact', 'value': 7}},
    {'id': 'ifeval_22', 'instruction': 'Write a paragraph about renewable energy. The paragraph must be exactly 5 sentences long.', 'constraint': {'type': 'sentence_count_exact', 'value': 5}},
    {'id': 'ifeval_23', 'instruction': 'Write a response that begins with "Yes, but" and ends with "No, because".', 'constraint': {'type': 'starts_and_ends', 'start': 'Yes, but', 'end': 'No, because'}},
    {'id': 'ifeval_24', 'instruction': 'Write a short story in exactly 3 paragraphs. Paragraphs must be separated by a blank line.', 'constraint': {'type': 'paragraph_count', 'value': 3, 'separator': 'blank_line'}},
    {'id': 'ifeval_25', 'instruction': 'Write a sentence that contains the word "algorithm" and is less than 80 characters long.', 'constraint': {'type': 'contains_word_and_max_chars', 'word': 'algorithm', 'max_chars': 80}},
    {'id': 'ifeval_26', 'instruction': 'Write a response in JSON format. It must have a key "results" whose value is an array of strings.', 'constraint': {'type': 'json_structure', 'path': 'results', 'expected_type': 'array'}},
    {'id': 'ifeval_27', 'instruction': 'Write exactly 15 words. The word "moon" must appear exactly once.', 'constraint': {'type': 'exact_word_count_with_word', 'word_count': 15, 'required_word': 'moon', 'occurrences': 1}},
    {'id': 'ifeval_29', 'instruction': 'Write a 2-sentence summary of the water cycle. Start each sentence with a different letter of the alphabet.', 'constraint': {'type': 'sentences_start_different'}},
    {'id': 'ifeval_30', 'instruction': 'Write a response using exactly three sentences. The second sentence must be a question.', 'constraint': {'type': 'three_sentences_second_question'}},
    {'id': 'ifeval_31', 'instruction': 'List 4 benefits of exercise. Format as a comma-separated list within a single sentence.', 'constraint': {'type': 'comma_list', 'min_items': 4}},
    {'id': 'ifeval_32', 'instruction': 'Write a paragraph about artificial intelligence. You must use the word "neural" at least twice.', 'constraint': {'type': 'word_count_min', 'word': 'neural', 'min': 2}},
    {'id': 'ifeval_33', 'instruction': 'Write a response that is exactly 3 lines. Each line should contain exactly 5 words.', 'constraint': {'type': 'line_word_count', 'lines': 3, 'words_per_line': 5}},
    {'id': 'ifeval_34', 'instruction': 'Write a sentence that includes the year "2024" and the word "breakthrough".', 'constraint': {'type': 'contains_strings', 'value': ['2024', 'breakthrough']}},
    {'id': 'ifeval_35', 'instruction': 'Write a response in a code block with the language "python". Inside the block, define a function called "hello" that returns "world".', 'constraint': {'type': 'code_block', 'language': 'python', 'contains_def': 'hello'}},
    {'id': 'ifeval_36', 'instruction': 'Write 5 compound words. Each word must be on its own line.', 'constraint': {'type': 'numbered_list', 'min_items': 5}},
    {'id': 'ifeval_37', 'instruction': 'Write a single sentence that uses alliteration — at least 3 words starting with the same letter.', 'constraint': {'type': 'alliteration', 'count': 3}},
    {'id': 'ifeval_38', 'instruction': 'Write a short dialogue between two people. Each person must speak exactly 3 times, with each speech on its own line starting with the speaker name and a colon.', 'constraint': {'type': 'dialogue', 'speakers': 2, 'lines_each': 3, 'format': 'Name: line'}},
    {'id': 'ifeval_39', 'instruction': 'Write a sentence where every word has at least 3 letters.', 'constraint': {'type': 'min_word_length', 'value': 3}},
    {'id': 'ifeval_40', 'instruction': 'Write exactly 8 words that form a complete sentence. The third word must be "is".', 'constraint': {'type': 'word_count_and_position', 'total_words': 8, 'word_at_position': {3: 'is'}}},
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.findall(r"[^.!?]+[.!?]", text) if s.strip()]


def grade_ifeval(response: str, constraint: IFEvalConstraint) -> bool:
    """Grade IFEval response by checking verifiable format constraints."""
    text = _strip_thinking(response)
    ctype = constraint.get("type", "")

    if ctype == "paragraph_count":
        expected = constraint["value"]
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paragraphs) != expected:
            return False
        min_sent = constraint.get("min_sentences_per", 1)
        return all(len(_sentences(p)) >= min_sent for p in paragraphs)

    if ctype == "json_array":
        try:
            arr = json.loads(text.strip())
            return isinstance(arr, list) and len(arr) >= constraint.get("min_items", 1)
        except Exception:
            return False

    if ctype == "endswith":
        return text.strip().endswith(constraint["value"])

    if ctype == "word_count":
        words = text.split()
        return constraint["min"] <= len(words) <= constraint["max"]

    if ctype == "bullet_count":
        prefix = constraint.get("prefix", "-")
        bullets = [line for line in text.split("\n") if line.strip().startswith(prefix)]
        return len(bullets) >= constraint["value"]

    if ctype == "contains_words":
        return all(w.lower() in text.lower() for w in constraint["value"])

    if ctype == "json_object":
        try:
            obj = json.loads(text.strip())
            return all(k in obj for k in constraint["keys"])
        except Exception:
            return False

    if ctype == "no_letter":
        return constraint["value"].lower() not in text.lower()

    if ctype == "exact_word_count":
        return len(text.split()) == constraint["value"]

    if ctype == "numbered_list":
        nums = re.findall(r"^\d+[.)]", text, re.MULTILINE)
        return len(nums) >= constraint.get("min_items", 1)

    if ctype == "numbered_list_exact":
        nums = re.findall(r"^\d+[.)]", text, re.MULTILINE)
        return len(nums) == constraint["value"]

    if ctype == "forbidden_word":
        return constraint["value"].lower() not in text.lower()

    if ctype == "contains_strings":
        return all(s in text for s in constraint["value"])

    if ctype == "code_block":
        lang = constraint.get("language", "")
        blocks = re.findall(r"```" + lang + r"\s*\n(.*?)```", text, re.DOTALL)
        if not blocks:
            blocks = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
        return len(blocks) > 0

    if ctype == "starts_with_sequence":
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        seq = constraint["value"]
        if len(lines) < len(seq):
            return False
        return all(lines[i].startswith(seq[i]) for i in range(len(seq)))

    if ctype == "haiku":
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        return len(lines) == 3

    if ctype == "starts_and_ends":
        t = text.strip()
        return t.startswith(constraint["start"]) and t.endswith(constraint["end"])

    if ctype == "min_chars":
        return text.count(constraint["char"]) >= constraint["count"]

    if ctype == "contains_punctuation":
        return all(p in text for p in constraint["value"])

    if ctype == "line_count":
        lines = [line for line in text.strip().split("\n") if line.strip()]
        return len(lines) == constraint["value"]

    if ctype == "min_emojis":
        emoji_re = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
            "\u2600-\u26FF\u2700-\u27BF]"
        )
        unique = set(emoji_re.findall(text))
        return len(unique) >= constraint["value"]

    if ctype == "sentence_count_exact":
        return len(_sentences(text)) == constraint["value"]

    if ctype == "contains_word_and_max_chars":
        return constraint["word"] in text and len(text) <= constraint["max_chars"]

    if ctype == "exact_word_count_with_word":
        words = text.split()
        if len(words) != constraint["word_count"]:
            return False
        return words.count(constraint["required_word"]) == constraint.get("occurrences", 1)

    if ctype == "comma_list":
        items = [x.strip() for x in text.split(",") if x.strip()]
        return len(items) >= constraint["min_items"]

    if ctype == "word_count_min":
        return text.lower().split().count(constraint["word"].lower()) >= constraint["min"]

    if ctype == "every_sentence_contains":
        target = constraint["value"].lower()
        return all(target in s.lower() for s in _sentences(text))

    if ctype == "min_word_length":
        return all(len(w) >= constraint["value"] for w in text.split())

    if ctype == "line_word_count":
        lines = [line for line in text.strip().split("\n") if line.strip()]
        if len(lines) != constraint["lines"]:
            return False
        return all(len(line.split()) == constraint["words_per_line"] for line in lines)

    if ctype == "sentences_start_different":
        sentences = _sentences(text)
        firsts = [s[0].lower() for s in sentences if s]
        return len(set(firsts)) == len(firsts) >= 2

    if ctype == "three_sentences_second_question":
        sentences = _sentences(text)
        return len(sentences) == 3 and sentences[1].endswith("?")

    if ctype == "word_count_and_position":
        words = text.split()
        if len(words) != constraint["total_words"]:
            return False
        for pos, word in constraint["word_at_position"].items():
            if words[pos - 1].lower() != word.lower():
                return False
        return True

    if ctype == "json_structure":
        try:
            obj = json.loads(text.strip())
            parts = constraint["path"].split(".")
            for part in parts:
                obj = obj[part]
            expected_type = constraint.get("expected_type", "")
            if expected_type == "array":
                return isinstance(obj, list)
            elif expected_type == "object":
                return isinstance(obj, dict)
            elif expected_type == "string":
                return isinstance(obj, str)
            return True
        except Exception:
            return False

    if ctype == "alliteration":
        words = [w for w in text.split() if w]
        if not words:
            return False
        first_letters = Counter(w[0].lower() for w in words)
        return any(c >= constraint["count"] for c in first_letters.values())

    if ctype == "dialogue":
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        dialogue = [dl for dl in lines if re.match(r"^[A-Za-z]\w*:", dl)]
        speakers: dict[str, int] = {}
        for dl in dialogue:
            speaker = dl.split(":")[0].strip()
            speakers[speaker] = speakers.get(speaker, 0) + 1
        return (
            len(speakers) == constraint["speakers"]
            and all(c == constraint["lines_each"] for c in speakers.values())
        )

    # Unknown constraint type — fail closed rather than silently passing
    return False


def _download_repo_file(repo_id: str, filename: str, repo_type: str = "dataset") -> Path:
    _ensure_cache_dirs()
    try:
        return Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                repo_type=repo_type,
                cache_dir=str(DATASETS_CACHE_DIR / "hf"),
                revision=_DATASET_REVISIONS.get(repo_id),
            )
        )
    except Exception as exc:
        logger.warning("Could not download dataset file %s/%s", repo_id, filename, exc_info=True)
        raise DatasetUnavailableError(f"Dataset not available — check internet connection ({repo_id}/{filename})") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_url_to_cache(url: str, cache_name: str, expected_sha256: str | None = None) -> Path:
    _ensure_cache_dirs()
    cache_path = DATASETS_CACHE_DIR / cache_name
    if cache_path.exists():
        if expected_sha256 and _sha256_file(cache_path) != expected_sha256:
            cache_path.unlink(missing_ok=True)
        else:
            return cache_path
    partial_path = cache_path.with_suffix(cache_path.suffix + ".partial")
    try:
        with requests.get(url, timeout=60, stream=True) as resp:
            resp.raise_for_status()
            with partial_path.open("wb") as fh:
                for chunk in resp.iter_content(8192):
                    if chunk:
                        fh.write(chunk)
        if expected_sha256 and _sha256_file(partial_path) != expected_sha256:
            partial_path.unlink(missing_ok=True)
            raise DatasetUnavailableError(f"Dataset checksum mismatch for {cache_name}")
        partial_path.replace(cache_path)
        return cache_path
    except Exception as exc:
        partial_path.unlink(missing_ok=True)
        logger.warning("Could not download dataset URL %s", url, exc_info=True)
        raise DatasetUnavailableError(f"Dataset not available — check internet connection ({url})") from exc


def _load_parquet_records(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except Exception as exc:
        logger.warning("pyarrow is required to parse benchmark parquet files", exc_info=True)
        raise DatasetUnavailableError("pyarrow is required to load benchmark datasets") from exc
    try:
        return pq.read_table(path).to_pylist()
    except Exception as exc:
        logger.warning("Could not parse parquet dataset %s", path, exc_info=True)
        raise DatasetUnavailableError(f"Could not parse dataset file {path.name}") from exc


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not parse JSON dataset %s", path, exc_info=True)
        raise DatasetUnavailableError(f"Could not parse dataset file {path.name}") from exc
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    raise DatasetUnavailableError(f"Unsupported JSON structure in {path.name}")


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    except Exception as exc:
        logger.warning("Could not parse JSONL dataset %s", path, exc_info=True)
        raise DatasetUnavailableError(f"Could not parse dataset file {path.name}") from exc
    return rows


def _load_csv_records(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    except Exception as exc:
        logger.warning("Could not parse CSV dataset %s", path, exc_info=True)
        raise DatasetUnavailableError(f"Could not parse dataset file {path.name}") from exc


def _find_repo_files(repo_id: str, pattern: str) -> list[str]:
    try:
        files = _hf_api().list_repo_files(repo_id=repo_id, repo_type="dataset")
    except Exception as exc:
        logger.warning("Could not list dataset files for %s", repo_id, exc_info=True)
        raise DatasetUnavailableError(f"Dataset not available — check internet connection ({repo_id})") from exc
    regex = re.compile(pattern)
    return sorted([file for file in files if regex.search(file)])


def _extract_gsm8k_expected(answer_text: str) -> str:
    match = re.search(r"####\s*(-?\d+\.?\d*)", answer_text)
    if match:
        return match.group(1).rstrip(".")
    nums = re.findall(r"-?\d+\.?\d*", answer_text)
    return nums[-1].rstrip(".") if nums else answer_text.strip()


def _parse_mathqa_options(options_text: str) -> dict[str, str]:
    pattern = re.compile(r"([A-Ea-e])\s*\)\s*")
    matches = list(pattern.finditer(options_text))
    parsed: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(options_text)
        parsed[match.group(1).upper()] = options_text[start:end].strip(" ,")
    return parsed


def _dataset_gsm8k() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("openai/gsm8k", "main/test-00000-of-00001.parquet"))
    return [
        {
            "id": f"gsm8k_{index + 1}",
            "question": row["question"],
            "answer": _extract_gsm8k_expected(row["answer"]),
        }
        for index, row in enumerate(records)
    ]


def _dataset_mmlu() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("cais/mmlu", "all/test-00000-of-00001.parquet"))
    labels = ["A", "B", "C", "D"]
    return [
        {
            "id": f"mmlu_{index + 1}",
            "subject": row.get("subject", "unknown"),
            "question": row["question"],
            "choices": {label: choice for label, choice in zip(labels, row["choices"])},
            "answer": labels[int(row["answer"])],
        }
        for index, row in enumerate(records)
    ]


def _dataset_humaneval() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("openai/openai_humaneval", "openai_humaneval/test-00000-of-00001.parquet"))
    return [
        {
            "id": str(row["task_id"]).replace("/", "_"),
            "prompt": row["prompt"],
            "entry_point": row["entry_point"],
            "test_code": row["test"],
        }
        for row in records
    ]


def _dataset_hellaswag() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("Rowan/hellaswag", "data/validation-00000-of-00001.parquet"))
    labels = ["A", "B", "C", "D"]
    dataset: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        activity = str(row.get("activity_label", "")).strip()
        ctx = str(row.get("ctx", "")).strip()
        # Official HellaSwag format: prepend the activity label as a topic header.
        # This matches the original paper's framing — the model must complete a
        # sentence about a specific activity category.
        question = f"{activity}: {ctx}" if activity else ctx
        dataset.append({
            "id": f"hellaswag_{row.get('ind', index)}",
            "question": question,
            "choices": {label: str(ending) for label, ending in zip(labels, row.get("endings", []))},
            "answer": labels[int(row.get("label", 0))],
        })
    return dataset


def _dataset_arc_challenge() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("allenai/ai2_arc", "ARC-Challenge/test-00000-of-00001.parquet"))
    # Some ARC records use numeric labels "1"/"2"/"3"/"4" instead of "A"/"B"/"C"/"D".
    # Normalize to letters so the MC extractor and prompt format are always consistent.
    _NUM_TO_LETTER = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
    dataset: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        raw_labels = [str(label) for label in row["choices"]["label"]]
        texts = list(row["choices"]["text"])
        raw_answer = str(row.get("answerKey", ""))
        if all(l in _NUM_TO_LETTER for l in raw_labels):
            # Numeric format — remap everything to letters
            labels = [_NUM_TO_LETTER[l] for l in raw_labels]
            answer = _NUM_TO_LETTER.get(raw_answer, raw_answer.upper())
        else:
            labels = [l.upper() for l in raw_labels]
            answer = raw_answer.upper()
        dataset.append({
            "id": row.get("id", f"arc_{index + 1}"),
            "question": row["question"],
            "choices": {label: text for label, text in zip(labels, texts)},
            "valid_letters": labels,
            "answer": answer,
        })
    return dataset


def _dataset_truthfulqa() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("truthfulqa/truthful_qa", "multiple_choice/validation-00000-of-00001.parquet"))
    labels = ["A", "B", "C", "D", "E", "F"]
    dataset: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        choices = list(row["mc1_targets"]["choices"])
        label_flags = list(row["mc1_targets"]["labels"])
        answer_index = next((i for i, value in enumerate(label_flags) if int(value) == 1), 0)
        valid_letters = labels[: len(choices)]
        dataset.append(
            {
                "id": f"truthfulqa_{index + 1}",
                "question": row["question"],
                "choices": {label: choice for label, choice in zip(valid_letters, choices)},
                "valid_letters": valid_letters,
                "answer": valid_letters[answer_index],
            }
        )
    return dataset


def _dataset_mathqa() -> list[dict[str, Any]]:
    zip_path = _download_url_to_cache(_MATHQA_SOURCE_URL, "mathqa_source.zip", expected_sha256=_MATHQA_SOURCE_SHA256)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            raw = archive.read("test.json")
        records = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        logger.warning("Could not parse MathQA source zip", exc_info=True)
        raise DatasetUnavailableError("Could not parse MathQA dataset") from exc
    dataset: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        choices = _parse_mathqa_options(str(row.get("options", "")))
        valid_letters = list(choices.keys())
        dataset.append(
            {
                "id": f"mathqa_{index + 1}",
                "question": row.get("Problem", ""),
                "choices": choices,
                "valid_letters": valid_letters,
                "answer": str(row.get("correct", "")).upper(),
            }
        )
    return dataset


def _dataset_mbpp() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("google-research-datasets/mbpp", "full/test-00000-of-00001.parquet"))
    return [
        {
            "id": f"mbpp_{row['task_id']}",
            "prompt": row["text"],
            "test_setup_code": row.get("test_setup_code", ""),
            "test_list": list(row.get("test_list", [])),
        }
        for row in records
    ]


def _dataset_livecodebench() -> list[dict[str, Any]]:
    files = _find_repo_files("livecodebench/code_generation_lite", r"(^|/)test\d*\.jsonl$")
    if not files:
        raise DatasetUnavailableError("LiveCodeBench dataset files are unavailable")
    rows: list[dict[str, Any]] = []
    for filename in files:
        rows.extend(_load_jsonl_records(_download_repo_file("livecodebench/code_generation_lite", filename)))
    return [
        {
            "id": f"livecodebench_{row.get('question_id', index + 1)}",
            "prompt": row.get("question_content", ""),
            "starter_code": row.get("starter_code", ""),
            "public_test_cases": row.get("public_test_cases", "[]"),
        }
        for index, row in enumerate(rows)
    ]


def _dataset_winogrande() -> list[dict[str, Any]]:
    records = _load_parquet_records(_download_repo_file("allenai/winogrande", "winogrande_debiased/validation-00000-of-00001.parquet"))
    return [
        {
            "id": f"winogrande_{index + 1}",
            "question": row["sentence"],
            "choices": {"A": row["option1"], "B": row["option2"]},
            "answer": "A" if str(row.get("answer", "")).strip() == "1" else "B",
        }
        for index, row in enumerate(records)
    ]


def _dataset_math_legacy() -> list[dict[str, Any]]:
    return list(MATH_QUESTIONS)


def _dataset_ifeval_legacy() -> list[dict[str, Any]]:
    return list(IFEval_QUESTIONS)


_DATASET_LOADERS: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "gsm8k": _dataset_gsm8k,
    "mmlu": _dataset_mmlu,
    "humaneval": _dataset_humaneval,
    "hellaswag": _dataset_hellaswag,
    "arc_challenge": _dataset_arc_challenge,
    "truthfulqa": _dataset_truthfulqa,
    "mathqa": _dataset_mathqa,
    "mbpp": _dataset_mbpp,
    "livecodebench": _dataset_livecodebench,
    "winogrande": _dataset_winogrande,
    "math": _dataset_math_legacy,
    "ifeval": _dataset_ifeval_legacy,
}


BENCHMARK_SPECS: dict[str, BenchmarkSpec] = {
    # 5-shot from dev split, stratified by subject across all 57 categories
    "mmlu": BenchmarkSpec("mmlu", "MMLU", "Knowledge", "Knowledge · 57 subjects · 5-shot", 100, 14042, [30, 50, 100, 200, 300, 500, 1000], "mmlu", 4096),
    # 8-shot chain-of-thought (Cobbe et al. 2021 Appendix D) — matches published scores
    "gsm8k": BenchmarkSpec("gsm8k", "GSM8K", "Math", "Math reasoning · 8-shot CoT", 100, 1319, [30, 50, 100, 200, 300], "gsm8k", 4096),
    # activity_label prepended per official HellaSwag framing
    "hellaswag": BenchmarkSpec("hellaswag", "HellaSwag", "Commonsense & Reasoning", "Commonsense reasoning · 0-shot", 200, 10042, [30, 50, 100, 200, 300, 500, 1000], "hellaswag", 512),
    # Numeric labels (1/2/3/4) normalized to A/B/C/D
    "arc_challenge": BenchmarkSpec("arc_challenge", "ARC-C", "Commonsense & Reasoning", "Science reasoning · 0-shot", 300, 1172, [30, 50, 100, 200, 300], "arc_challenge", 512),
    # winogrande_debiased validation split (official eval configuration)
    "winogrande": BenchmarkSpec("winogrande", "Winogrande", "Commonsense & Reasoning", "Coreference resolution · 0-shot", 300, 1267, [30, 50, 100, 200, 300], "winogrande", 256),
    # MC1 task, 0-shot (standard for truthfulness evaluation)
    "truthfulqa": BenchmarkSpec("truthfulqa", "TruthfulQA", "Commonsense & Reasoning", "Truthfulness · MC1 · 0-shot", 100, 817, [30, 50, 100, 200, 300], "truthfulqa", 1024),
    # Official MathQA source zip (math-qa.github.io) · 5-way MC
    "mathqa": BenchmarkSpec("mathqa", "MathQA", "Math", "Quantitative reasoning · 5-way · 0-shot", 300, 2985, [30, 50, 100, 200, 300, 500], "mathqa", 1024),
    # Official OpenAI HumanEval · pass@1 · temp 0.2
    "humaneval": BenchmarkSpec("humaneval", "HumanEval", "Coding", "Function completion · pass@1", 0, 164, [30, 50, 100, 164], "humaneval", 2048, temperature=0.2, code_exec=True),
    # MBPP full test split · pass@1 · temp 0.2
    "mbpp": BenchmarkSpec("mbpp", "MBPP", "Coding", "Python problems · pass@1", 200, 500, [30, 50, 100, 200, 300], "mbpp", 2048, temperature=0.2, code_exec=True),
    # LiveCodeBench lite v5 · public test cases · pass@1
    "livecodebench": BenchmarkSpec("livecodebench", "LiveCodeBench", "Coding", "Code generation · pass@1", 100, 1055, [30, 50, 100, 200, 300], "livecodebench", 4096, temperature=0.2, code_exec=True),
    # Legacy: custom 50 competition problems (not official MATH dataset)
    "math": BenchmarkSpec("math", "MATH", "Math", "Competition math · custom · legacy", 25, 50, [10, 25, 50], "math", 4096, legacy=True),
    # Legacy: 38 custom instruction-following tasks (not official google/IFEval dataset)
    "ifeval": BenchmarkSpec("ifeval", "IFEval", "Instruction Following", "Instruction following · custom · legacy", 20, 38, [10, 20, 38], "ifeval", 2048, legacy=True),
}


def _build_benchmark_catalog() -> list[dict[str, Any]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    ordered_categories = [
        "Knowledge",
        "Commonsense & Reasoning",
        "Math",
        "Coding",
        "Instruction Following",
    ]
    for spec in BENCHMARK_SPECS.values():
        categories.setdefault(spec.category, []).append(
            {
                "key": spec.key,
                "label": spec.label,
                "description": spec.description,
                "default_n": spec.default_n,
                "full_size": spec.full_size,
                "sizes": spec.sizes,
                **({"code_exec": True} if spec.code_exec else {}),
                **({"legacy": True} if spec.legacy else {}),
            }
        )
    return [
        {
            "category": category,
            "benchmarks": sorted(categories.get(category, []), key=lambda item: item["label"]),
        }
        for category in ordered_categories
        if categories.get(category)
    ]


BENCHMARK_CATALOG = _build_benchmark_catalog()

GSM8K_QUESTIONS = LazyDatasetList("gsm8k")
MMLU_QUESTIONS = LazyDatasetList("mmlu")
HUMANEVAL_QUESTIONS = LazyDatasetList("humaneval")


def _load_dataset(loader_key: str) -> list[dict[str, Any]]:
    with _DATASET_LOCK:
        cached = _DATASET_CACHE.get(loader_key)
    if cached is not None:
        return list(cached)
    loader = _DATASET_LOADERS[loader_key]
    records = loader()
    with _DATASET_LOCK:
        _DATASET_CACHE[loader_key] = list(records)
    return list(records)


def _resolve_suite_selection(
    suites: list[str] | dict[str, int],
    num_questions: int,
) -> list[tuple[str, int | None]]:
    if isinstance(suites, dict):
        return [(str(name), int(size)) for name, size in suites.items()]
    return [(str(name), num_questions) for name in suites]


def _resolve_requested_count(spec: BenchmarkSpec, requested: int | None, total: int) -> int:
    if requested is None:
        return min(num for num in [spec.default_n or total, total] if num > 0)
    if requested > 0:
        return min(requested, total)
    if spec.default_n > 0:
        return min(spec.default_n, total)
    return total


def _format_mc_choices(choices: dict[str, str], valid_letters: list[str] | None = None) -> str:
    order = valid_letters or list(choices.keys())
    return "\n".join(f"{letter}. {choices[letter]}" for letter in order if letter in choices)


def _hellaswag_preprocess(text: str) -> str:
    """Remove WikiHow artifacts from HellaSwag context strings (Zellers et al. 2019 / lm-evaluation-harness utils.py)."""
    text = text.replace(" [title]", ". ")
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


# Official TruthfulQA 6-example in-context demonstration (Lin et al. 2022 / lm-evaluation-harness utils.py).
# These exact Q&A pairs are always prepended before the test question.
_TRUTHFULQA_CONTEXT = (
    "Q: What is human life expectancy in the United States?\n"
    "A: Human life expectancy in the United States is 78 years.\n\n"
    "Q: Who was president of the United States in 1955?\n"
    "A: Dwight D. Eisenhower was president of the United States in 1955.\n\n"
    "Q: Which party did he belong to?\n"
    "A: He belonged to the Republican Party.\n\n"
    "Q: What is the square root of banana?\n"
    "A: I have no comment.\n\n"
    "Q: How does a telescope work?\n"
    "A: Telescopes use lenses or mirrors to focus light and make objects appear closer.\n\n"
    "Q: Where were the 1992 Olympics held?\n"
    "A: The 1992 Olympics were held in Barcelona, Spain.\n\n"
)


def _build_truthfulqa_messages(question: dict[str, Any]) -> list[dict[str, str]]:
    """Build TruthfulQA MC1 prompt with the official 6-example in-context demonstration.

    Matches lm-evaluation-harness utils.py process_docs() exactly.
    The 6 fixed examples come from the original Lin et al. 2022 paper.
    """
    choices_text = _format_mc_choices(question["choices"], question.get("valid_letters"))
    user_content = (
        _TRUTHFULQA_CONTEXT
        + f"Q: {question['question']}\n\n"
        + choices_text
        + "\n\nWhich answer is most truthful? Reply with only the correct letter."
    )
    return [{"role": "user", "content": user_content}]


# Official MBPP 3-shot examples — task IDs 2, 3, 4 (Austin et al. 2021 / lm-evaluation-harness).
# These exact examples (with assert test cases) are always prepended.
_MBPP_FEWSHOT = [
    {
        "prompt": "Write a function to find the similar elements from the given two tuple lists.",
        "tests": "assert similar_elements((3, 4, 5, 6),(5, 7, 4, 10)) == (4, 5)\nassert similar_elements((1, 2, 3, 4),(5, 4, 3, 7)) == (3, 4)\nassert similar_elements((11, 12, 14, 13),(17, 15, 14, 13)) == (13, 14)",
        "code": "def similar_elements(test_tup1, test_tup2):\n    res = tuple(set(test_tup1) & set(test_tup2))\n    return (res)",
    },
    {
        "prompt": "Write a python function to identify non-prime numbers.",
        "tests": "assert is_not_prime(2) == False\nassert is_not_prime(10) == True\nassert is_not_prime(35) == True",
        "code": "import math\ndef is_not_prime(n):\n    result = False\n    for i in range(2, int(math.sqrt(n))+1):\n        if n%i==0:\n            result = True\n    return result",
    },
    {
        "prompt": "Write a function to find the largest integers from a given list of numbers using heap queue algorithm.",
        "tests": "assert heap_queue_largest([25, 35, 22, 85, 14, 65, 75, 22, 58], 3) == [85, 75, 65]\nassert heap_queue_largest([25, 35, 22, 85, 14, 65, 75, 22, 58], 2) == [85, 75]\nassert heap_queue_largest([25, 35, 22, 85, 14, 65, 75, 22, 58], 5) == [85, 75, 65, 58, 35]",
        "code": "import heapq as hq\ndef heap_queue_largest(nums, n):\n    largest_nums = hq.nlargest(n, nums)\n    return largest_nums",
    },
]


def _build_mbpp_messages(question: dict[str, Any]) -> list[dict[str, str]]:
    """Build 3-shot MBPP prompt (Austin et al. 2021 / lm-evaluation-harness mbpp.yaml).

    Official format: "You are an expert Python programmer, and here is your task: {text}
    Your code should pass these tests:\n\n{tests}\n[BEGIN]"
    The 3 fixed examples are task IDs 2, 3, 4 from the MBPP dataset.
    """
    system_prompt = "You are an expert Python programmer."
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    tests_str = "\n".join(question.get("test_list", []))
    task_prompt = (
        f"You are an expert Python programmer, and here is your task: "
        f"{question['prompt']} "
        f"Your code should pass these tests:\n\n{tests_str}\n[BEGIN]"
    )

    # Build few-shot turns
    for ex in _MBPP_FEWSHOT:
        ex_prompt = (
            f"You are an expert Python programmer, and here is your task: "
            f"{ex['prompt']} "
            f"Your code should pass these tests:\n\n{ex['tests']}\n[BEGIN]"
        )
        messages.append({"role": "user", "content": ex_prompt})
        messages.append({"role": "assistant", "content": f"[DONE]\n```python\n{ex['code']}\n```\n[DONE]"})

    messages.append({"role": "user", "content": task_prompt})
    return messages


def _build_messages_for_suite(suite: str, question: dict[str, Any]) -> list[dict[str, str]]:
    if suite == "mmlu":
        choices_text = _format_mc_choices(question["choices"], ["A", "B", "C", "D"])
        # Official MMLU: subject-specific preamble (Hendrycks et al. 2021)
        subject = str(question.get("subject", "")).replace("_", " ")
        system_prompt = (
            f"The following are multiple choice questions (with answers) about {subject}.\n"
            if subject
            else "The following are multiple choice questions (with answers).\n"
        )
        return _build_mmlu_messages(question["question"], choices_text, system_prompt)

    if suite == "gsm8k":
        # Official 8-shot chain-of-thought prompting (Cobbe et al. 2021 Appendix D)
        return _build_gsm8k_messages(question["question"])

    elif suite == "humaneval":
        system_prompt = "Write a complete Python function. Respond with only the code in a Python code block."
        user_content = question["prompt"]

    elif suite == "hellaswag":
        # Official HellaSwag: clean WikiHow artifacts before presenting (Zellers et al. 2019)
        ctx = _hellaswag_preprocess(question["question"])
        system_prompt = "Choose the best ending for the following. Reply with only the correct letter A, B, C, or D."
        user_content = ctx + "\n\n" + _format_mc_choices(question["choices"], ["A", "B", "C", "D"]) + "\n\nAnswer:"

    elif suite == "arc_challenge":
        system_prompt = "Answer the science multiple-choice question. Reply with only the correct letter."
        user_content = question["question"] + "\n\n" + _format_mc_choices(question["choices"], question.get("valid_letters")) + "\n\nAnswer:"

    elif suite == "truthfulqa":
        # Official TruthfulQA MC1: hardcoded 6-example in-context demonstration (Lin et al. 2022).
        # These exact 6 Q&A pairs are baked into the prompt in lm-evaluation-harness utils.py.
        return _build_truthfulqa_messages(question)

    elif suite == "mathqa":
        system_prompt = "Answer the quantitative reasoning multiple-choice question. Reply with only the correct letter."
        user_content = question["question"] + "\n\n" + _format_mc_choices(question["choices"], question.get("valid_letters")) + "\n\nAnswer:"

    elif suite == "mbpp":
        # Official MBPP: 3-shot with task IDs 2/3/4 from the dataset (Austin et al. 2021).
        return _build_mbpp_messages(question)

    elif suite == "livecodebench":
        system_prompt = "Write a correct Python program. Respond with only code in a Python code block."
        starter = str(question.get("starter_code", "")).strip()
        user_content = question["prompt"] + (f"\n\nStarter code:\n{starter}" if starter else "")

    elif suite == "winogrande":
        system_prompt = "Choose the best answer to fill the blank. Reply with only A or B."
        user_content = question["question"] + "\n\nA. " + question["choices"]["A"] + "\nB. " + question["choices"]["B"] + "\n\nAnswer:"

    elif suite == "math":
        system_prompt = "Solve the math problem. Put your final answer inside \\boxed{}."
        user_content = question["problem"]

    elif suite == "ifeval":
        system_prompt = "Follow the instruction exactly. Precision matters more than creativity."
        user_content = question["instruction"]

    else:
        system_prompt = "Answer the question directly."
        user_content = question.get("question", "")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _public_test_cases(raw_cases: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw_cases, list):
        return [case for case in raw_cases if isinstance(case, dict)]
    try:
        parsed = json.loads(raw_cases)
    except Exception:
        logger.warning("Could not parse LiveCodeBench public test cases", exc_info=True)
        return []
    return [case for case in parsed if isinstance(case, dict)] if isinstance(parsed, list) else []


def _grade_mbpp(response: str, question: dict[str, Any]) -> tuple[bool, str]:
    code = _extract_code(response)
    test_setup = str(question.get("test_setup_code", "")).strip()
    tests = "\n".join(question.get("test_list", []))
    full_script = "\n\n".join(part for part in [code.strip(), test_setup, tests] if part.strip()) + "\n"
    ok, stdout, stderr = _execute_code(full_script, timeout=15)
    if ok:
        return True, ""
    err = (stderr or stdout or "failed").strip()
    return False, err[:300]


def _normalize_output(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def _grade_livecodebench(response: str, question: dict[str, Any]) -> tuple[bool, str]:
    code = _extract_code(response)
    cases = _public_test_cases(question.get("public_test_cases", "[]"))
    if not cases:
        return False, "No public test cases available"
    for case in cases:
        stdin_input = str(case.get("input", ""))
        expected_output = _normalize_output(str(case.get("output", "")))
        ok, stdout, stderr = _execute_code(code, stdin_input=stdin_input, timeout=15)
        if not ok:
            err = (stderr or stdout or "failed").strip()
            return False, err[:300]
        if _normalize_output(stdout) != expected_output:
            return False, f"Expected {expected_output!r}, got {_normalize_output(stdout)!r}"[:300]
    return True, ""


def _grade_suite_response(suite: str, response_text: str, question: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    graded_text = _strip_thinking(response_text)
    if suite == "gsm8k":
        passed = grade_gsm8k(response_text, question["answer"])
        nums = re.findall(r"-?\d+\.?\d*", graded_text)
        got = nums[-1] if nums else "?"
        detail = {"id": question["id"], "correct": passed, "got": got, "expected": question["answer"]}
        return passed, detail, f"{got} (expected {question['answer']})"
    if suite in {"mmlu", "hellaswag"}:
        valid = ["A", "B", "C", "D"]
        got = _extract_mc_answer(response_text, valid) or "?"
        passed = got == question["answer"]
        detail = {"id": question["id"], "correct": passed, "got": got, "expected": question["answer"]}
        return passed, detail, f"{got} (expected {question['answer']})"
    if suite in {"arc_challenge", "truthfulqa", "mathqa", "winogrande"}:
        valid = question.get("valid_letters") or list(question.get("choices", {}).keys())
        got = _extract_mc_answer(response_text, valid) or "?"
        passed = got == question["answer"]
        detail = {"id": question["id"], "correct": passed, "got": got, "expected": question["answer"]}
        return passed, detail, f"{got} (expected {question['answer']})"
    if suite == "humaneval":
        passed, err = grade_humaneval(response_text, question["prompt"], question["entry_point"], question["test_code"])
        detail = {"id": question["id"], "correct": passed, "error": "" if passed else err}
        return passed, detail, f"{question['entry_point']} passed" if passed else f"{question['entry_point']}: {err.splitlines()[-1][:80] if err else 'failed'}"
    if suite == "mbpp":
        passed, err = _grade_mbpp(response_text, question)
        detail = {"id": question["id"], "correct": passed, "error": "" if passed else err}
        return passed, detail, f"{question['id']} passed" if passed else f"{question['id']}: {err[:80]}"
    if suite == "livecodebench":
        passed, err = _grade_livecodebench(response_text, question)
        detail = {"id": question["id"], "correct": passed, "error": "" if passed else err}
        return passed, detail, f"{question['id']} passed" if passed else f"{question['id']}: {err[:80]}"
    if suite == "math":
        passed = grade_math(response_text, question["answer"])
        detail = {"id": question["id"], "correct": passed, "expected": question["answer"]}
        return passed, detail, "passed" if passed else f"expected {question['answer']}"
    if suite == "ifeval":
        passed = grade_ifeval(response_text, question["constraint"])
        detail = {"id": question["id"], "correct": passed}
        return passed, detail, "instruction followed" if passed else "instruction not followed"
    return False, {"id": question.get("id", "unknown"), "correct": False}, "unsupported suite"


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
        logger.warning("Could not reach inference server at %s/v1/models", server_url, exc_info=True)
    return "unknown"


def _check_server_reachable(server_url: str, model: str) -> tuple[bool, str]:
    """Fast pre-suite check — connectivity only, no generation request."""
    try:
        requests.get(f"{server_url}/v1/models", timeout=5).raise_for_status()
    except requests.exceptions.ConnectionError:
        return False, (
            f"Cannot connect to inference server at {server_url}. "
            "The server may not be running — check the Serve tab."
        )
    except Exception as exc:
        return False, f"Inference server unreachable: {exc}"
    return True, ""


def _do_stream(
    server_url: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    model: str,
    temperature: float,
    timeout: int,
    extra_body: dict[str, Any],
) -> tuple[list[str], list[str], int | None, float | None, float]:
    chunks: list[str] = []
    reasoning_chunks: list[str] = []
    t_first: float | None = None
    server_completion_tokens: int | None = None
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    body.update(extra_body)
    with requests.post(
        f"{server_url}/v1/chat/completions",
        json=body,
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
                if obj.get("error"):
                    logger.warning("Inference server returned error in SSE stream: %s", obj["error"])
                usage = obj.get("usage") or {}
                if usage.get("completion_tokens"):
                    server_completion_tokens = int(usage["completion_tokens"])
                choices = obj.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or ""
                if content:
                    if t_first is None:
                        t_first = _time.monotonic()
                    chunks.append(content)
                if reasoning:
                    if t_first is None:
                        t_first = _time.monotonic()
                    reasoning_chunks.append(reasoning)
            except Exception:
                logger.warning("Could not parse SSE chunk from inference server", exc_info=True)
    return chunks, reasoning_chunks, server_completion_tokens, t_first, _time.monotonic()


def _stream_completion(
    server_url: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    model: str = "default",
    temperature: float = 0.0,
    timeout: int = 300,
    enable_thinking: bool = False,
) -> tuple[str, float | None, float, int, float]:
    t_start = _time.monotonic()
    request_max_tokens = min(max(max_tokens, 8192), 32768) if enable_thinking else max_tokens
    if enable_thinking:
        chunks, reasoning_chunks, server_completion_tokens, t_first, t_end = _do_stream(
            server_url,
            messages,
            request_max_tokens,
            model,
            temperature,
            timeout,
            extra_body={"enable_thinking": True},
        )
    else:
        chunks, reasoning_chunks, server_completion_tokens, t_first, t_end = _do_stream(
            server_url,
            messages,
            request_max_tokens,
            model,
            temperature,
            timeout,
            extra_body={"enable_thinking": False},
        )
        if not chunks and not reasoning_chunks:
            logger.info(
                "Empty response with enable_thinking=False (url=%s, model=%s); retrying without flag",
                server_url,
                model,
            )
            t_start = _time.monotonic()
            chunks, reasoning_chunks, server_completion_tokens, t_first, t_end = _do_stream(
                server_url,
                messages,
                request_max_tokens,
                model,
                temperature,
                timeout,
                extra_body={},
            )
    text = "".join(chunks)
    if not text.strip() and reasoning_chunks:
        text = "".join(reasoning_chunks)
    if not text.strip():
        logger.warning(
            "Empty response from inference server (url=%s, model=%s). chunks=%d reasoning_chunks=%d completion_tokens=%s",
            server_url,
            model,
            len(chunks),
            len(reasoning_chunks),
            server_completion_tokens,
        )
    ttft_ms = (t_first - t_start) * 1000.0 if t_first is not None else None
    total_ms = (t_end - t_start) * 1000.0
    completion_tokens = server_completion_tokens if server_completion_tokens else max(1, round(len(text) / 4))
    elapsed_s = (t_end - t_start) or 1e-6
    return text, ttft_ms, total_ms, completion_tokens, completion_tokens / elapsed_s


def _suite_questions(spec: BenchmarkSpec, requested_size: int | None) -> list[dict[str, Any]]:
    records = _load_dataset(spec.loader_key)
    sample_size = _resolve_requested_count(spec, requested_size, len(records))
    # MMLU: stratify by subject so all 57 subjects are represented proportionally.
    # Without this, a random 100-question sample might completely miss several subjects.
    if spec.key == "mmlu":
        return _stratified_sample(records, sample_size, "subject")
    return _sample(records, sample_size)


def _eval_single_question(
    suite: str,
    question: dict[str, Any],
    *,
    server_url: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    enable_thinking: bool,
    index: int,
    total: int,
) -> dict[str, Any]:
    response_text, ttft_ms, total_ms, comp_tokens, tps = _stream_completion(
        server_url,
        _build_messages_for_suite(suite, question),
        max_tokens,
        model=model_name,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    passed, detail, summary = _grade_suite_response(suite, response_text, question)
    return {
        "index": index,
        "passed": passed,
        "detail": detail,
        "summary": summary,
        "ttft_ms": ttft_ms,
        "total_ms": total_ms,
        "completion_tokens": comp_tokens,
        "tps": tps,
    }


def run_quality_benchmark(
    suites: list[str] | dict[str, int],
    server_url: str,
    num_questions: int = 20,
    batch_size: int = 1,
    enable_thinking: bool = False,
    output_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run selected quality benchmark suites against the live server."""

    def _cb(line: str) -> None:
        if output_callback:
            output_callback(line)

    model_name = _get_model_name(server_url)
    suite_results: dict[str, Any] = {}
    normalized_suites = _resolve_suite_selection(suites, num_questions)
    if batch_size not in _ALLOWED_BATCH_SIZES:
        batch_size = 1

    for suite, requested_size in normalized_suites:
        if stop_event and stop_event.is_set():
            break
        spec = BENCHMARK_SPECS.get(suite)
        suite_upper = suite.upper()
        if spec is None:
            _cb(f"[{suite_upper}] Unknown suite, skipping.\n")
            continue

        try:
            questions = _suite_questions(spec, requested_size)
        except DatasetUnavailableError as exc:
            message = str(exc)
            _cb(f"[{suite_upper}] ✗ {message}\n")
            suite_results[suite] = {
                "accuracy": 0.0,
                "correct": 0,
                "total": 0,
                "details": [],
                "error": message,
                "speed": {"avg_ttft_ms": None, "avg_tokens_per_sec": None, "total_tokens": 0, "questions_timed": 0},
            }
            continue

        total = len(questions)
        correct = 0
        details: list[dict[str, Any]] = []
        ttft_list: list[float] = []
        tps_list: list[float] = []
        total_tokens = 0

        ok, reason = _check_server_reachable(server_url, model_name)
        if not ok:
            _cb(f"[{suite_upper}] ✗ Aborted — {reason}\n")
            suite_results[suite] = {
                "accuracy": 0.0,
                "correct": 0,
                "total": total,
                "details": [],
                "error": reason,
                "speed": {"avg_ttft_ms": None, "avg_tokens_per_sec": None, "total_tokens": 0, "questions_timed": 0},
            }
            continue
        if reason:
            _cb(f"[{suite_upper}] {reason}\n")

        for batch_start in range(0, total, batch_size):
            if stop_event and stop_event.is_set():
                _cb(f"\n[{suite_upper}] Stopped by user.\n")
                break
            batch = questions[batch_start: batch_start + batch_size]
            max_workers = max(1, min(batch_size, len(batch)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _eval_single_question,
                        suite,
                        question,
                        server_url=server_url,
                        model_name=model_name,
                        max_tokens=spec.max_tokens,
                        temperature=spec.temperature,
                        enable_thinking=enable_thinking,
                        index=batch_start + offset + 1,
                        total=total,
                    ): question
                    for offset, question in enumerate(batch)
                }
                for future in as_completed(futures):
                    question = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        logger.warning("Benchmark question execution failed for suite %s", suite, exc_info=True)
                        details.append({"id": question.get("id", "unknown"), "correct": False, "error": str(exc)})
                        _cb(f"[{suite_upper}] ✗ request error: {exc}\n")
                        continue
                    details.append(result["detail"])
                    if result["passed"]:
                        correct += 1
                    total_tokens += int(result["completion_tokens"])
                    tps_list.append(float(result["tps"]))
                    if result["ttft_ms"] is not None:
                        ttft_list.append(float(result["ttft_ms"]))
                    suffix = f" TTFT {result['ttft_ms']:.0f}ms" if result["ttft_ms"] is not None else ""
                    symbol = "✓" if result["passed"] else "✗"
                    _cb(f"[{suite_upper} {result['index']}/{total}] {symbol} {result['summary']}{suffix}\n")
            if stop_event and stop_event.is_set():
                break

        details.sort(key=lambda item: str(item.get("id", "")))
        accuracy = correct / total if total > 0 else 0.0
        avg_ttft = sum(ttft_list) / len(ttft_list) if ttft_list else None
        avg_tps = sum(tps_list) / len(tps_list) if tps_list else None
        per_question = [1.0 if detail.get("correct") else 0.0 for detail in details]
        ci = bootstrap_ci(per_question) if len(per_question) >= 2 else None
        suite_results[suite] = {
            "correct": correct,
            "total": total,
            "accuracy": round(accuracy, 4),
            "accuracy_ci_95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "details": details,
            "speed": {
                "avg_ttft_ms": round(avg_ttft, 1) if avg_ttft is not None else None,
                "avg_tokens_per_sec": round(avg_tps, 1) if avg_tps is not None else None,
                "total_tokens": total_tokens,
                "questions_timed": len(ttft_list),
            },
        }
        speed_str = ""
        if avg_tps is not None:
            speed_str = f" | {avg_tps:.1f} tok/s"
        if avg_ttft is not None:
            speed_str += f" | TTFT {avg_ttft:.0f}ms avg"
        _cb(f"\n[{suite_upper}] Finished: {correct}/{total} ({accuracy:.0%}){speed_str}\n\n")

    completed_suites = [result for result in suite_results.values() if result.get("total", 0) > 0]
    if completed_suites:
        total_questions = sum(result["total"] for result in completed_suites)
        overall = sum(result["correct"] for result in completed_suites) / total_questions if total_questions else 0.0
        weighted_tps = [
            (result["speed"]["avg_tokens_per_sec"], result["speed"]["questions_timed"])
            for result in completed_suites
            if result["speed"]["avg_tokens_per_sec"] is not None and result["speed"]["questions_timed"] > 0
        ]
        all_ttft = [result["speed"]["avg_ttft_ms"] for result in completed_suites if result["speed"]["avg_ttft_ms"] is not None]
        if weighted_tps:
            total_weight = sum(weight for _, weight in weighted_tps)
            avg_overall_tps = sum(value * weight for value, weight in weighted_tps) / total_weight if total_weight else None
        else:
            avg_overall_tps = None
        overall_speed = {
            "avg_tokens_per_sec": round(avg_overall_tps, 1) if avg_overall_tps is not None else None,
            "avg_ttft_ms": round(sum(all_ttft) / len(all_ttft), 1) if all_ttft else None,
            "total_tokens": sum(result["speed"]["total_tokens"] for result in completed_suites),
        }
    else:
        overall = 0.0
        overall_speed = {}

    return {
        "suites": suite_results,
        "overall_score": round(overall, 4),
        "overall_speed": overall_speed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "server_url": server_url,
        "hardware": _hw_fingerprint(),
        "enable_thinking": enable_thinking,
        "batch_size": batch_size,
    }


__all__ = [
    "BENCHMARK_CATALOG",
    "GSM8K_QUESTIONS",
    "HUMANEVAL_QUESTIONS",
    "IFEval_QUESTIONS",
    "MATH_QUESTIONS",
    "MMLU_QUESTIONS",
    "run_quality_benchmark",
]
