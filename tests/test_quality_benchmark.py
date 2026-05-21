# SPDX-License-Identifier: Apache-2.0
"""Tests for quality_runner — grading functions, suite runner, and edge cases."""

from __future__ import annotations

import json
import random
from unittest.mock import MagicMock, patch

from vllm_mlx.dashboard.quality_runner import (
    GSM8K_QUESTIONS,
    HUMANEVAL_QUESTIONS,
    MATH_QUESTIONS,
    MMLU_QUESTIONS,
    IFEval_QUESTIONS,
    _build_mmlu_messages,
    _extract_code,
    _math_answer_match,
    _sentences,
    _strip_thinking,
    bootstrap_ci,
    grade_gsm8k,
    grade_humaneval,
    grade_ifeval,
    grade_math,
    grade_mmlu,
    run_quality_benchmark,
)

# ── _strip_thinking ──────────────────────────────────────────────────────────

class TestStripThinking:
    def test_no_think_block(self):
        assert _strip_thinking("Hello world") == "Hello world"

    def test_basic_think_block(self):
        # Text before the think block is preserved
        assert _strip_thinking("Let me think...<think>I should reason</think>Answer: 42") == "Let me think...Answer: 42"

    def test_nothing_after_think(self):
        # Fallback: if stripping leaves nothing, return raw text
        assert _strip_thinking("<think>reasoning</think>") == "<think>reasoning</think>"

    def test_incomplete_think_block_no_close(self):
        assert _strip_thinking("Hello<think> no close") == "Hello<think> no close"

    def test_empty_think(self):
        assert _strip_thinking("<think></think>42") == "42"

    def test_multiple_think_blocks(self):
        assert _strip_thinking("<think>a</think>X<think>b</think>Y") == "XY"

    def test_nested_tags_not_confused(self):
        assert _strip_thinking("not <think> inner </think> end") == "not  end"


# ── _sentences ──────────────────────────────────────────────────────────────

class TestSentences:
    def test_three_sentences(self):
        assert len(_sentences("First. Second? Third!")) == 3

    def test_single_sentence(self):
        assert len(_sentences("Just one.")) == 1

    def test_trailing_punctuation(self):
        assert len(_sentences("Go! Run! Stop!")) == 3

    def test_semicolons_not_split(self):
        assert len(_sentences("First; still first. Second.")) == 2

    def test_empty_text(self):
        assert _sentences("") == []

    def test_no_punctuation(self):
        assert _sentences("hello") == []


# ── grade_gsm8k ─────────────────────────────────────────────────────────────

class TestGradeGsm8k:
    def test_canonical_format(self):
        assert grade_gsm8k("Step by step... #### 18", "18") is True

    def test_canonical_format_float(self):
        assert grade_gsm8k("Some reasoning #### 3.5", "3.5") is True

    def test_last_number_fallback(self):
        assert grade_gsm8k("So the answer is 42", "42") is True

    def test_last_number_after_text(self):
        assert grade_gsm8k("After calculation, we get 25 dollars", "25") is True

    def test_incorrect_answer(self):
        assert grade_gsm8k("#### 10", "18") is False

    def test_no_numbers(self):
        assert grade_gsm8k("I don't know", "18") is False

    def test_thinking_removed(self):
        assert grade_gsm8k("<think>Let me compute</think>#### 18", "18") is True

    def test_trailing_period(self):
        assert grade_gsm8k("#### 18.", "18") is True

    def test_negative_number(self):
        assert grade_gsm8k("The answer is #### -5", "-5") is True


# ── grade_mmlu ──────────────────────────────────────────────────────────────

class TestGradeMmlu:
    def test_exact_letter(self):
        assert grade_mmlu("The answer is B", "B") is True

    def test_lowercase_input(self):
        assert grade_mmlu("I think it's c", "C") is True

    def test_letter_only(self):
        assert grade_mmlu("A", "A") is True

    def test_no_letter(self):
        assert grade_mmlu("I don't know the answer", "B") is False

    def test_letter_in_word(self):
        assert grade_mmlu("Consider the options", "C") is False

    def test_after_thinking(self):
        assert grade_mmlu("<think>hmm</think>B", "B") is True

    def test_d_with_answer(self):
        assert grade_mmlu("The correct choice is D", "D") is True

    def test_first_200_chars_only(self):
        # Only 200 chars checked — letter after 200 not found
        long = "x" * 200 + "B"
        assert grade_mmlu(long, "B") is False

    def test_letter_within_first_200(self):
        assert grade_mmlu("The answer is B and then " + "x" * 180, "B") is True


# ── _extract_code ───────────────────────────────────────────────────────────

class TestExtractCode:
    def test_python_fenced(self):
        code = 'Some text\n```python\nprint("hello")\n```\nmore'
        assert _extract_code(code) == 'print("hello")\n'

    def test_any_fenced(self):
        code = '```\ndef foo():\n    pass\n```'
        assert "def foo():" in _extract_code(code)

    def test_no_code_block(self):
        code = "just a plain response"
        assert _extract_code(code) == "just a plain response"

    def test_empty_code_block(self):
        code = "```python\n```"
        assert _extract_code(code) == ""


# ── grade_math ──────────────────────────────────────────────────────────────

class TestGradeMath:
    def test_boxed_answer(self):
        assert grade_math("The answer is \\boxed{42}.", "42") is True

    def test_boxed_expression(self):
        assert grade_math("Result: \\boxed{25π}.", "25π") is True

    def test_operator_spacing_variance(self):
        assert grade_math("\\boxed{e-2}", "e - 2") is True

    def test_inequality_spacing(self):
        assert grade_math("\\boxed{x<1 or x>3}", "x < 1 or x > 3") is True

    def test_fraction(self):
        assert grade_math("The probability is \\boxed{5/16}.", "5/16") is True

    def test_text_fallback(self):
        assert grade_math("The answer is 42.", "42") is True

    def test_equal_sign_fallback(self):
        assert grade_math("Solving gives = 42", "42") is True

    def test_wrong_answer(self):
        assert grade_math("\\boxed{10}", "42") is False

    def test_comma_separated(self):
        assert grade_math("\\boxed{2, 3}", "2,3") is True

    def test_empty_or_gibberish(self):
        assert grade_math("I have no idea", "42") is False

    def test_thinking_excluded(self):
        assert grade_math("<think>compute</think>\\boxed{42}", "42") is True


# ── _math_answer_match ──────────────────────────────────────────────────────

class TestMathAnswerMatch:
    def test_exact_string(self):
        assert _math_answer_match("42", "42") is True

    def test_different_case(self):
        assert _math_answer_match("PI", "pi") is True

    def test_operator_normalization(self):
        assert _math_answer_match("e - 2", "e-2") is True

    def test_comma_list_varying_spaces(self):
        assert _math_answer_match("2,3", "2, 3") is True
        assert _math_answer_match("7, 13", "7,13") is True

    def test_inequality_normalization(self):
        assert _math_answer_match("x<1 or x>3", "x < 1 or x > 3") is True

    def test_empty_strings(self):
        assert _math_answer_match("", "") is True

    def test_totally_different(self):
        assert _math_answer_match("hello", "world") is False

    def test_numeric_equivalent(self):
        assert _math_answer_match("3.0", "3") is True


# ── grade_humaneval ─────────────────────────────────────────────────────────

class TestGradeHumanEval:
    def test_passing_code(self):
        code = 'def has_close_elements(numbers, threshold):\n    for i, x in enumerate(numbers):\n        for y in numbers[i+1:]:\n            if abs(x - y) < threshold:\n                return True\n    return False'
        passed, err = grade_humaneval(
            code,
            HUMANEVAL_QUESTIONS[0]["prompt"],
            HUMANEVAL_QUESTIONS[0]["entry_point"],
            HUMANEVAL_QUESTIONS[0]["test_code"],
        )
        assert passed is True
        assert err == ""

    def test_failing_code(self):
        code = "def has_close_elements(numbers, threshold):\n    return False"
        passed, err = grade_humaneval(
            code,
            HUMANEVAL_QUESTIONS[0]["prompt"],
            HUMANEVAL_QUESTIONS[0]["entry_point"],
            HUMANEVAL_QUESTIONS[0]["test_code"],
        )
        assert passed is False
        assert err != ""

    def test_compilation_error(self):
        code = "this is not valid python >>>"
        passed, err = grade_humaneval(
            code,
            HUMANEVAL_QUESTIONS[0]["prompt"],
            HUMANEVAL_QUESTIONS[0]["entry_point"],
            HUMANEVAL_QUESTIONS[0]["test_code"],
        )
        assert passed is False

    def test_function_body_only(self):
        body = "    for i, x in enumerate(numbers):\n        for y in numbers[i+1:]:\n            if abs(x - y) < threshold:\n                return True\n    return False"
        passed, err = grade_humaneval(
            body,
            HUMANEVAL_QUESTIONS[0]["prompt"],
            HUMANEVAL_QUESTIONS[0]["entry_point"],
            HUMANEVAL_QUESTIONS[0]["test_code"],
        )
        assert passed is True


# ── grade_ifeval ────────────────────────────────────────────────────────────

class TestGradeIfeval:
    def test_unknown_constraint_fails_closed(self):
        assert grade_ifeval("anything", {"type": "nonexistent"}) is False

    def test_paragraph_count(self):
        text = "Para one sentence one. Sentence two.\n\nPara two sentence one. Sentence two."
        assert grade_ifeval(text, {"type": "paragraph_count", "value": 2, "min_sentences_per": 2}) is True

    def test_paragraph_count_too_few(self):
        text = "Only one paragraph. With two sentences.\n\n"
        assert grade_ifeval(text, {"type": "paragraph_count", "value": 2, "min_sentences_per": 1}) is False

    def test_json_array(self):
        assert grade_ifeval('["a", "b", "c"]', {"type": "json_array", "min_items": 3}) is True

    def test_json_array_invalid(self):
        assert grade_ifeval("not json", {"type": "json_array", "min_items": 1}) is False

    def test_endswith(self):
        assert grade_ifeval("Hello world.", {"type": "endswith", "value": "world."}) is True

    def test_word_count_in_range(self):
        text = "one two three four five six seven eight nine ten"
        assert grade_ifeval(text, {"type": "word_count", "min": 5, "max": 15}) is True

    def test_word_count_too_short(self):
        assert grade_ifeval("hi", {"type": "word_count", "min": 5, "max": 10}) is False

    def test_bullet_count(self):
        text = "- one\n- two\n- three"
        assert grade_ifeval(text, {"type": "bullet_count", "value": 3, "prefix": "-"}) is True

    def test_contains_words(self):
        assert grade_ifeval("serendipity is unexpected", {"type": "contains_words", "value": ["serendipity", "unexpected"]}) is True

    def test_json_object(self):
        assert grade_ifeval('{"name": "Alice", "age": 30, "city": "NYC"}', {"type": "json_object", "keys": ["name", "age", "city"]}) is True

    def test_no_letter(self):
        assert grade_ifeval("I can talk", {"type": "no_letter", "value": "e"}) is True

    def test_no_letter_violation(self):
        assert grade_ifeval("hello", {"type": "no_letter", "value": "e"}) is False

    def test_exact_word_count(self):
        assert grade_ifeval("one two three four five six seven eight nine ten", {"type": "exact_word_count", "value": 10}) is True

    def test_numbered_list(self):
        text = "1. first\n2. second\n3. third"
        assert grade_ifeval(text, {"type": "numbered_list", "min_items": 3}) is True

    def test_numbered_list_exact(self):
        text = "1. step one\n2. step two\n3. step three\n4. step four\n5. step five"
        assert grade_ifeval(text, {"type": "numbered_list_exact", "value": 5}) is True

    def test_forbidden_word(self):
        assert grade_ifeval("This has no bad words", {"type": "forbidden_word", "value": "connection"}) is True

    def test_forbidden_word_violation(self):
        assert grade_ifeval("connection is bad", {"type": "forbidden_word", "value": "connection"}) is False

    def test_contains_strings(self):
        assert grade_ifeval("year 2024 was a breakthrough", {"type": "contains_strings", "value": ["2024", "breakthrough"]}) is True

    def test_code_block(self):
        text = '```python\ndef hello():\n    return "world"\n```'
        assert grade_ifeval(text, {"type": "code_block", "language": "python"}) is True

    def test_starts_with_sequence(self):
        text = "First, step one.\nSecond, step two.\nThird, step three."
        assert grade_ifeval(text, {"type": "starts_with_sequence", "value": ["First,", "Second,", "Third,"]}) is True

    def test_haiku(self):
        assert grade_ifeval("An old silent pond\nA frog jumps into the pond\nSplash! Silence again", {"type": "haiku"}) is True

    def test_starts_and_ends(self):
        assert grade_ifeval("Yes, but this is true, No, because", {"type": "starts_and_ends", "start": "Yes, but", "end": "No, because"}) is True

    # Newly implemented constraint types
    def test_min_chars(self):
        assert grade_ifeval("What? Really? Yes!", {"type": "min_chars", "char": "?", "count": 2}) is True
        assert grade_ifeval("No questions here", {"type": "min_chars", "char": "?", "count": 1}) is False

    def test_contains_punctuation(self):
        assert grade_ifeval("Hello: world; done,", {"type": "contains_punctuation", "value": [":", ";", ","]}) is True
        assert grade_ifeval("missing colon", {"type": "contains_punctuation", "value": [":", ";"]}) is False

    def test_line_count(self):
        assert grade_ifeval("a\nb\nc\nd", {"type": "line_count", "value": 4}) is True
        assert grade_ifeval("a\nb", {"type": "line_count", "value": 4}) is False

    def test_min_emojis(self):
        assert grade_ifeval("Happy 😊 Party 🎉 Fun 🎊", {"type": "min_emojis", "value": 3}) is True
        assert grade_ifeval("No emojis here", {"type": "min_emojis", "value": 1}) is False

    def test_sentence_count_exact(self):
        assert grade_ifeval("First. Second. Third.", {"type": "sentence_count_exact", "value": 3}) is True
        assert grade_ifeval("First. Second.", {"type": "sentence_count_exact", "value": 3}) is False

    def test_contains_word_and_max_chars(self):
        assert grade_ifeval("the algorithm works", {"type": "contains_word_and_max_chars", "word": "algorithm", "max_chars": 80}) is True
        assert grade_ifeval("no match", {"type": "contains_word_and_max_chars", "word": "algorithm", "max_chars": 80}) is False
        assert grade_ifeval("the algorithm " + "x" * 80, {"type": "contains_word_and_max_chars", "word": "algorithm", "max_chars": 80}) is False

    def test_exact_word_count_with_word(self):
        assert grade_ifeval("moon is bright tonight yes it is", {"type": "exact_word_count_with_word", "word_count": 7, "required_word": "moon", "occurrences": 1}) is True
        assert grade_ifeval("no moon here", {"type": "exact_word_count_with_word", "word_count": 15, "required_word": "moon", "occurrences": 1}) is False

    def test_comma_list(self):
        assert grade_ifeval("a, b, c, d, e", {"type": "comma_list", "min_items": 4}) is True
        assert grade_ifeval("a, b", {"type": "comma_list", "min_items": 4}) is False

    def test_word_count_min(self):
        assert grade_ifeval("neural networks use neural layers for neural processing", {"type": "word_count_min", "word": "neural", "min": 3}) is True
        assert grade_ifeval("only one neural", {"type": "word_count_min", "word": "neural", "min": 3}) is False

    def test_every_sentence_contains(self):
        assert grade_ifeval("The cat sat. The cat ran. The cat slept.", {"type": "every_sentence_contains", "value": "cat"}) is True
        assert grade_ifeval("The dog sat. The cat ran.", {"type": "every_sentence_contains", "value": "cat"}) is False

    def test_min_word_length(self):
        assert grade_ifeval("all words long here", {"type": "min_word_length", "value": 3}) is True
        assert grade_ifeval("a short word here", {"type": "min_word_length", "value": 3}) is False

    def test_line_word_count(self):
        assert grade_ifeval("one two three four five\nsix seven eight nine ten\none two three four five", {"type": "line_word_count", "lines": 3, "words_per_line": 5}) is True
        assert grade_ifeval("short\nline", {"type": "line_word_count", "lines": 3, "words_per_line": 5}) is False

    def test_sentences_start_different(self):
        assert grade_ifeval("Apples are red. Bananas are yellow. Cherries are sweet.", {"type": "sentences_start_different"}) is True
        assert grade_ifeval("Apples are red. Apples are sweet. Apples are tasty.", {"type": "sentences_start_different"}) is False

    def test_three_sentences_second_question(self):
        assert grade_ifeval("First sentence. Is this a question? Third sentence.", {"type": "three_sentences_second_question"}) is True
        assert grade_ifeval("First. Second. Third.", {"type": "three_sentences_second_question"}) is False
        assert grade_ifeval("First. Second? Third. Fourth.", {"type": "three_sentences_second_question"}) is False

    def test_word_count_and_position(self):
        assert grade_ifeval("the cat is on the mat now", {"type": "word_count_and_position", "total_words": 7, "word_at_position": {3: "is"}}) is True
        assert grade_ifeval("wrong count", {"type": "word_count_and_position", "total_words": 7, "word_at_position": {3: "is"}}) is False

    def test_json_structure(self):
        assert grade_ifeval('{"results": ["a", "b"]}', {"type": "json_structure", "path": "results", "expected_type": "array"}) is True
        assert grade_ifeval('{"results": {}}', {"type": "json_structure", "path": "results", "expected_type": "array"}) is False

    def test_alliteration(self):
        assert grade_ifeval("Peter Piper picked peppers", {"type": "alliteration", "count": 3}) is True
        assert grade_ifeval("no repeating letters here", {"type": "alliteration", "count": 3}) is False

    def test_dialogue(self):
        text = "Alice: Hello\nBob: Hi\nAlice: How are you?\nBob: I am fine.\nAlice: Good.\nBob: Yes."
        assert grade_ifeval(text, {"type": "dialogue", "speakers": 2, "lines_each": 3, "format": "Name: line"}) is True
        assert grade_ifeval("Alice: Hello\nBob: Hi", {"type": "dialogue", "speakers": 2, "lines_each": 3, "format": "Name: line"}) is False


# ── bootstrap_ci ────────────────────────────────────────────────────────────

class TestBootstrapCi:
    def test_none_for_single_value(self):
        assert bootstrap_ci([1.0]) is None

    def test_none_for_empty(self):
        assert bootstrap_ci([]) is None

    def test_ci_bounds_are_reasonable(self):
        values = [1.0] * 25
        ci = bootstrap_ci(values)
        assert ci is not None
        lower, upper = ci
        assert lower <= 1.0 <= upper
        assert 0.9 <= lower <= 1.0

    def test_ci_with_variance(self):
        random.seed(42)
        values = [1.0] * 15 + [0.0] * 10
        ci = bootstrap_ci(values)
        assert ci is not None
        lower, upper = ci
        assert lower < 1.0
        assert upper > 0.0


# ── _build_mmlu_messages ────────────────────────────────────────────────────

class TestBuildMmluMessages:
    def test_five_shot_structure(self):
        msgs = _build_mmlu_messages("Test?", "A. 1\nB. 2", "System prompt")
        assert len(msgs) == 12  # 1 system + 5 examples * 2 + 1 final user
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "System prompt"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"
        assert msgs[11]["role"] == "user"
        assert msgs[11]["content"].endswith("Answer:")

    def test_choices_formatted(self):
        msgs = _build_mmlu_messages("Q?", "A. 1\nB. 2", "S")
        last = msgs[-1]["content"]
        assert "Q?" in last
        assert "A. 1" in last
        assert "Answer:" in last


# ── run_quality_benchmark (full pipeline, mocked HTTP) ──────────────────────

def _mock_stream_response(chunks: list[str], usage_tokens: int = 50):
    """Build a mock requests response that streams SSE-formatted data."""
    lines = []
    for chunk in chunks:
        data = json.dumps({"choices": [{"delta": {"content": chunk}}]})
        lines.append(f"data: {data}")
    # Final chunk with usage
    final = json.dumps({
        "choices": [{"delta": {"content": ""}}],
        "usage": {"completion_tokens": usage_tokens},
    })
    lines.append(f"data: {final}")
    lines.append("data: [DONE]")
    mock_resp = MagicMock()
    mock_resp.iter_lines.return_value = lines
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


class TestRunQualityBenchmark:
    @patch("requests.get")
    @patch("requests.post")
    def test_basic_run(self, mock_post, mock_get):
        mock_get.return_value.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.status_code = 200

        mock_post.return_value = _mock_stream_response(
            ["The answer is B", "Let me explain why B is correct"]
        )
        mock_post.return_value.raise_for_status = lambda: None

        result = run_quality_benchmark(
            suites=["mmlu"],
            server_url="http://localhost:8000",
            num_questions=3,
        )

        assert result["model"] == "test-model"
        assert "suites" in result
        assert "mmlu" in result["suites"]
        assert 0 <= result["suites"]["mmlu"]["accuracy"] <= 1.0
        assert result["suites"]["mmlu"]["total"] == 3
        assert result["suites"]["mmlu"]["speed"]["avg_ttft_ms"] is not None
        assert "hardware" in result
        assert result["hardware"]["chip_gen"] in ("M5", "Intel", "Unknown")

    @patch("requests.get")
    @patch("requests.post")
    def test_all_suites(self, mock_post, mock_get):
        mock_get.return_value.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.status_code = 200

        mock_post.return_value = _mock_stream_response(["42"])
        mock_post.return_value.raise_for_status = lambda: None

        result = run_quality_benchmark(
            suites=["gsm8k", "mmlu", "humaneval", "math", "ifeval"],
            server_url="http://localhost:8000",
            num_questions=2,
        )

        for suite in ("gsm8k", "mmlu", "humaneval", "math", "ifeval"):
            assert suite in result["suites"], f"Missing suite: {suite}"
            assert result["suites"][suite]["total"] == 2

    @patch("requests.get")
    @patch("requests.post")
    def test_humaneval_handles_timeout(self, mock_post, mock_get):
        mock_get.return_value.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.status_code = 200

        mock_post.side_effect = Exception("Connection timeout")

        result = run_quality_benchmark(
            suites=["humaneval"],
            server_url="http://localhost:8000",
            num_questions=1,
        )
        # Should not crash — request errors should be captured per-question
        assert result["suites"]["humaneval"]["total"] == 1
        assert result["suites"]["humaneval"]["accuracy"] == 0.0

    @patch("requests.get")
    def test_server_unreachable(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")

        result = run_quality_benchmark(
            suites=["gsm8k"],
            server_url="http://localhost:9999",
        )
        # Should not crash — _get_model_name returns "unknown"
        assert result["model"] == "unknown"

    @patch("requests.get")
    @patch("requests.post")
    def test_stop_event(self, mock_post, mock_get):
        import threading
        mock_get.return_value.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.status_code = 200
        mock_post.return_value = _mock_stream_response(["some response"])
        mock_post.return_value.raise_for_status = lambda: None

        stop = threading.Event()
        stop.set()

        result = run_quality_benchmark(
            suites=["gsm8k"],
            server_url="http://localhost:8000",
            stop_event=stop,
        )
        # Should stop immediately without running
        assert "gsm8k" not in result["suites"] or result["suites"]["gsm8k"]["total"] == 0


# ── Data integrity ─────────────────────────────────────────────────────────

class TestQuestionDataIntegrity:
    def test_math_questions_have_problem_key(self):
        for q in MATH_QUESTIONS:
            assert "problem" in q, f'{q["id"]} missing "problem" key'

    def test_math_questions_have_answer(self):
        for q in MATH_QUESTIONS:
            assert "answer" in q, f'{q["id"]} missing "answer" key'

    def test_ifeval_questions_have_instruction(self):
        for q in IFEval_QUESTIONS:
            assert "instruction" in q, f'{q["id"]} missing "instruction" key'
            assert "constraint" in q, f'{q["id"]} missing "constraint"'
            ctype = q["constraint"]["type"]
            assert ctype != "simple_sentences", f"{q['id']} has ungradable simple_sentences"
            assert ctype != "rhymes_with", f"{q['id']} has ungradable rhymes_with"
            # Check no duplicate keys in constraint
            keys = list(q["constraint"].keys())
            assert len(keys) == len(set(keys)), f'{q["id"]} has duplicate constraint keys: {keys}'

    def test_no_duplicate_ifeval_types(self):
        for q in IFEval_QUESTIONS:
            constraint = q["constraint"]
            keys = list(constraint.keys())
            assert len(keys) == len(set(keys)), f'{q["id"]} duplicate keys: {keys}'

    def test_mmlu_questions_have_choices(self):
        for q in MMLU_QUESTIONS:
            assert "choices" in q, f'{q["id"]} missing "choices"'
            assert len(q["choices"]) == 4, f'{q["id"]} must have 4 choices'

    def test_gsm8k_questions_have_answer(self):
        for q in GSM8K_QUESTIONS:
            assert "answer" in q
            float(q["answer"])  # must be parseable as number

    def test_humaneval_questions_have_required_keys(self):
        for q in HUMANEVAL_QUESTIONS:
            assert "prompt" in q
            assert "entry_point" in q
            assert "test_code" in q

    def test_all_ifeval_types_have_handlers(self):
        from vllm_mlx.dashboard.quality_runner import grade_ifeval
        # Every IFEval question's constraint type must have a handler
        empty_cases = {
            "paragraph_count": {"type": "paragraph_count", "value": 1},
            "json_array": {"type": "json_array", "min_items": 0},
            "endswith": {"type": "endswith", "value": ""},
            "word_count": {"type": "word_count", "min": 0, "max": 9999},
            "bullet_count": {"type": "bullet_count", "value": 0},
            "contains_words": {"type": "contains_words", "value": []},
            "json_object": {"type": "json_object", "keys": []},
            "no_letter": {"type": "no_letter", "value": "x"},
            "exact_word_count": {"type": "exact_word_count", "value": 0},
            "numbered_list": {"type": "numbered_list", "min_items": 0},
            "numbered_list_exact": {"type": "numbered_list_exact", "value": 1},
            "forbidden_word": {"type": "forbidden_word", "value": "xyznonexistent"},
            "contains_strings": {"type": "contains_strings", "value": []},
            "code_block": {"type": "code_block"},
            "starts_with_sequence": {"type": "starts_with_sequence", "value": ["x"]},
            "haiku": {"type": "haiku"},
            "starts_and_ends": {"type": "starts_and_ends", "start": "a", "end": "b"},
            "min_chars": {"type": "min_chars", "char": "?", "count": 1},
            "contains_punctuation": {"type": "contains_punctuation", "value": []},
            "line_count": {"type": "line_count", "value": 1},
            "min_emojis": {"type": "min_emojis", "value": 0},
            "sentence_count_exact": {"type": "sentence_count_exact", "value": 1},
            "contains_word_and_max_chars": {"type": "contains_word_and_max_chars", "word": "x", "max_chars": 9999},
            "exact_word_count_with_word": {"type": "exact_word_count_with_word", "word_count": 1, "required_word": "x", "occurrences": 1},
            "comma_list": {"type": "comma_list", "min_items": 1},
            "word_count_min": {"type": "word_count_min", "word": "x", "min": 0},
            "every_sentence_contains": {"type": "every_sentence_contains", "value": "x"},
            "min_word_length": {"type": "min_word_length", "value": 1},
            "line_word_count": {"type": "line_word_count", "lines": 1, "words_per_line": 1},
            "sentences_start_different": {"type": "sentences_start_different"},
            "three_sentences_second_question": {"type": "three_sentences_second_question"},
            "word_count_and_position": {"type": "word_count_and_position", "total_words": 1, "word_at_position": {1: "x"}},
            "json_structure": {"type": "json_structure", "path": "x", "expected_type": "string"},
            "alliteration": {"type": "alliteration", "count": 1},
            "dialogue": {"type": "dialogue", "speakers": 1, "lines_each": 1, "format": "Name: line"},
        }
        for ctype in empty_cases:
            # Should NOT raise NotImplementedError or KeyError
            grade_ifeval("some text", empty_cases[ctype])
