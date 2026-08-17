"""
builder.py
AI Builder: turns a natural-language project request into a real,
multi-file project written to disk.

Safety model
------------
- Only ever writes inside <projects_root>/<project_name>_<timestamp>/...
- Every file path returned by the AI is validated with
  security.resolve_safe_path() before anything touches disk.
- NEVER executes any AI-generated command, script, or code. Syntax
  checking uses ast.parse(), which parses source into a syntax tree
  without running it - it never executes the generated code.
- All progress is reported back through a callback so the terminal UI
  can show what's happening file by file.

Generation model
-----------------
Earlier versions asked the AI to generate ALL files in a single
response using ===FILE:...===/===ENDFILE=== blocks. That silently lost
files on any project with enough files/content to approach the
response's max_tokens limit: the response got cut off mid-file, the
block-matching regex only matched *complete* blocks, and every file
after the cutoff point just vanished from `contents` with no error -
it looked like the AI "chose" to skip them, when really they were
never fully received.

This version requests ONE file at a time. Each file gets its own chat
completion (so it has the model's full token budget to itself, not a
shared pool with 16 other files), its own retry-on-failure loop (up to
MAX_ATTEMPTS attempts), and is validated + written to disk immediately
after a valid non-empty response comes back - so a failure on file 12
of 17 can never take files 1-11 down with it, and nothing is ever
silently dropped: every planned file ends up either written or
explicitly reported as failed/missing.
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .client import AIClient, ChatMessage, AIClientError
from .security import sanitize_name, resolve_safe_path, SecurityError

ProgressFn = Callable[[str], None]

MAX_ATTEMPTS = 3

PLAN_SYSTEM_PROMPT = """You are a senior software architect. Given a project request, \
respond with ONLY a JSON object (no markdown fences, no commentary) describing the \
project structure. Schema:

{
  "project_name": "short_snake_case_name",
  "description": "one paragraph description",
  "files": [
    {"path": "relative/path/to/file.py", "purpose": "short description of what this file does"}
  ]
}

Rules:
- "path" must be a relative path (no leading slash, no drive letters, no '..').
- Include all files needed to run the project (main entry point, modules, requirements.txt, README.md).
- Keep the file list focused and reasonable (typically 4-20 files).
- Output ONLY the JSON object.
"""

FILE_SYSTEM_PROMPT = """You are a senior software engineer. You will be given a project \
plan and asked for the FULL content of exactly ONE file from that plan.

Output ONLY the raw file content:
- No markdown code fences (no triple backticks).
- No commentary, explanation, or notes before or after the content.
- No "===FILE===" markers or similar wrappers.
- Just the file's complete, working, well-commented content, ready to save to disk exactly as-is.

Write complete, working content - not placeholders or "TODO: implement this".
If the file is requirements.txt, output only the requirement lines (or a single
"# no external dependencies" comment if genuinely none are needed).
If the file is README.md or any other plain-text/markdown file, output the actual
document content - it is a real file like any other and must not be skipped.
Never include shell commands meant to be executed automatically.
Never output an empty response - every file must have real, non-empty content.
"""


class BuildError(Exception):
    pass


@dataclass
class PlannedFile:
    path: str
    purpose: str = ""


@dataclass
class ProjectPlan:
    project_name: str
    description: str
    files: List[PlannedFile]


@dataclass
class FileResult:
    """Outcome for a single planned file after the generate/write loop."""
    path: str
    status: str  # "written" | "failed"
    error: str = ""
    attempts: int = 0


@dataclass
class SyntaxCheckResult:
    path: str
    ok: bool
    error: str = ""


class AIProjectBuilder:
    def __init__(self, client: AIClient, projects_root: str):
        self.client = client
        self.projects_root = projects_root
        os.makedirs(self.projects_root, exist_ok=True)

    def set_projects_root(self, projects_root: str) -> None:
        """Change where future /build output gets written. Creates the
        folder immediately if it doesn't exist yet, so a bad/typo'd path
        fails fast (at the point the user sets it) instead of later,
        mid-build."""
        projects_root = os.path.abspath(projects_root)
        os.makedirs(projects_root, exist_ok=True)
        self.projects_root = projects_root

    # -- plan ------------------------------------------------------------------

    def request_plan(self, user_prompt: str, progress: ProgressFn) -> ProjectPlan:
        progress("Requesting project plan from AI...")
        messages = [
            ChatMessage("system", PLAN_SYSTEM_PROMPT),
            ChatMessage("user", user_prompt),
        ]
        try:
            raw = self.client.simple_chat(messages, max_tokens=1500)
        except AIClientError as e:
            raise BuildError(f"Planning request failed: {e}") from e

        data = self._parse_json_relaxed(raw)
        if data is None:
            raise BuildError("AI did not return valid JSON for the project plan.")

        project_name = sanitize_name(data.get("project_name") or "ai_project")
        description = str(data.get("description") or "").strip()
        raw_files = data.get("files") or []
        if not isinstance(raw_files, list) or not raw_files:
            raise BuildError("AI plan did not include any files.")

        files: List[PlannedFile] = []
        seen_paths = set()
        for f in raw_files:
            path = str(f.get("path", "")).strip()
            purpose = str(f.get("purpose", "")).strip()
            if path and path not in seen_paths:
                files.append(PlannedFile(path=path, purpose=purpose))
                seen_paths.add(path)

        if not files:
            raise BuildError("AI plan contained no usable file paths.")

        progress(f"Plan received: '{project_name}' with {len(files)} file(s).")
        return ProjectPlan(project_name=project_name, description=description, files=files)

    # -- single-file generation --------------------------------------------------

    def _generate_one_file(self, plan: ProjectPlan, planned: PlannedFile, user_prompt: str) -> str:
        """
        Requests content for exactly one file. Raises BuildError (with a
        clear, user-facing reason) on any API failure or an empty
        response. The caller is responsible for retrying.
        """
        plan_summary = json.dumps(
            {
                "project_name": plan.project_name,
                "description": plan.description,
                "files": [{"path": f.path, "purpose": f.purpose} for f in plan.files],
            },
            indent=2,
        )
        messages = [
            ChatMessage("system", FILE_SYSTEM_PROMPT),
            ChatMessage(
                "user",
                f"Original request:\n{user_prompt}\n\n"
                f"Full project plan (for context only - you are generating ONLY the "
                f"one file requested below):\n{plan_summary}\n\n"
                f"Now output the FULL content of exactly this one file:\n"
                f"Path: {planned.path}\n"
                f"Purpose: {planned.purpose or '(see project plan above)'}\n",
            ),
        ]
        try:
            raw = self.client.simple_chat(messages, max_tokens=4000)
        except AIClientError as e:
            raise BuildError(str(e)) from e

        content = self._strip_wrapping(raw)
        if not content.strip():
            raise BuildError("API returned an empty response")
        return content

    @staticmethod
    def _strip_wrapping(text: str) -> str:
        """Best-effort cleanup in case the model wraps the file in a
        markdown code fence, or reverts to the old ===FILE===/===ENDFILE===
        wrapper out of habit, despite being told not to. Keeps generation
        robust against small prompt-following slips without losing or
        mangling real content."""
        text = text.strip("\n")
        text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        text = re.sub(r"^===FILE:.*?===\s*\n", "", text)
        text = re.sub(r"\n?===ENDFILE===\s*$", "", text)
        return text

    # -- write a single file to disk ---------------------------------------------

    def _write_one_file(self, project_root: str, planned: PlannedFile, content: str) -> None:
        """Raises SecurityError (via resolve_safe_path) if the planned
        path is unsafe - caller treats that as non-retryable."""
        target = resolve_safe_path(project_root, planned.path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)

    # -- syntax checking -----------------------------------------------------------

    @staticmethod
    def _check_syntax(path: str, content: str) -> SyntaxCheckResult:
        """Parses (never executes) the generated source to catch invalid
        Python before the build is reported as successful."""
        try:
            ast.parse(content, filename=path)
            return SyntaxCheckResult(path=path, ok=True)
        except SyntaxError as e:
            loc = f"line {e.lineno}, col {e.offset}" if e.lineno else "unknown location"
            return SyntaxCheckResult(path=path, ok=False, error=f"{e.msg} ({loc})")
        except Exception as e:  # noqa: BLE001
            return SyntaxCheckResult(path=path, ok=False, error=str(e))

    # -- orchestration -----------------------------------------------------------

    def build(self, user_prompt: str, progress: ProgressFn) -> str:
        """
        Full pipeline: plan -> generate each file one at a time (with
        retries) -> write each file to disk as soon as it's ready ->
        verify every planned file actually exists -> syntax-check every
        .py file -> report.

        Returns the absolute path to the created project directory.

        Raises BuildError only for failures that happen before any files
        exist yet: no API key, planning failure, or the project directory
        itself can't be created. Per-file failures do NOT raise - every
        planned file is always attempted regardless of earlier failures,
        and the outcome is captured in the final build report instead.
        """
        if not self.client.has_key():
            raise BuildError("No API key set. Connect first before using /build.")

        plan = self.request_plan(user_prompt, progress)

        project_dir_name = f"{plan.project_name}_{int(time.time())}"
        project_root = os.path.abspath(os.path.join(self.projects_root, project_dir_name))
        projects_root_abs = os.path.abspath(self.projects_root)

        # project_root must itself remain inside self.projects_root
        if os.path.commonpath([projects_root_abs, project_root]) != projects_root_abs:
            raise BuildError("Refusing to create project outside the configured output folder.")

        os.makedirs(project_root, exist_ok=True)
        progress(f"Created project directory: {project_root}")

        total = len(plan.files)
        index_width = max(2, len(str(total)))
        results: List[FileResult] = []
        contents_written: Dict[str, str] = {}

        for idx, planned in enumerate(plan.files, start=1):
            tag = f"[{idx:0{index_width}d}/{total}] {planned.path}"
            last_error = ""
            written = False

            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    content = self._generate_one_file(plan, planned, user_prompt)
                    self._write_one_file(project_root, planned, content)
                    contents_written[planned.path] = content
                    progress(f"{tag} \u2713")
                    results.append(FileResult(path=planned.path, status="written", attempts=attempt))
                    written = True
                    break
                except SecurityError as e:
                    # Not retryable - the path itself is the problem, not a
                    # transient generation failure. Every other planned
                    # file still gets attempted normally.
                    last_error = f"Unsafe path rejected: {e}"
                    progress(f"{tag} \u2717 (blocked: {e})")
                    break
                except BuildError as e:
                    last_error = str(e)
                    if attempt < MAX_ATTEMPTS:
                        progress(f"{tag} retry {attempt}/{MAX_ATTEMPTS - 1} after error: {e}")
                    else:
                        progress(f"{tag} \u2717 FAILED after {MAX_ATTEMPTS} attempts: {e}")

            if not written:
                results.append(FileResult(
                    path=planned.path,
                    status="failed",
                    error=last_error or "Unknown error",
                    attempts=MAX_ATTEMPTS,
                ))

        # -- verify: compare planned files against what's actually on disk ------
        missing: List[str] = []
        for planned in plan.files:
            target = os.path.join(project_root, planned.path.replace("/", os.sep))
            if not os.path.isfile(target):
                missing.append(planned.path)

        # -- syntax-check every generated .py file -------------------------------
        syntax_results: List[SyntaxCheckResult] = []
        for planned in plan.files:
            if not planned.path.lower().endswith(".py"):
                continue
            content = contents_written.get(planned.path)
            if content is None:
                continue  # already accounted for under failed/missing
            syntax_results.append(self._check_syntax(planned.path, content))

        report = self._build_report(plan, results, missing, syntax_results, project_root)
        for line in report.splitlines():
            progress(line)

        return project_root

    # -- final report ----------------------------------------------------------

    def _build_report(
        self,
        plan: ProjectPlan,
        results: List[FileResult],
        missing: List[str],
        syntax_results: List[SyntaxCheckResult],
        project_root: str,
    ) -> str:
        planned_count = len(plan.files)
        written = [r for r in results if r.status == "written"]
        failed = [r for r in results if r.status == "failed"]

        syntax_checked = len(syntax_results)
        syntax_passed = sum(1 for s in syntax_results if s.ok)
        syntax_failed = [s for s in syntax_results if not s.ok]

        success = not failed and not missing and not syntax_failed

        lines = ["BUILD COMPLETE" if success else "BUILD FINISHED WITH ERRORS", ""]
        lines.append(f"Planned:    {planned_count}")
        lines.append(f"Generated:  {len(written)}")
        lines.append(f"Written:    {len(written)}")
        lines.append(f"Failed:     {len(failed)}")
        lines.append(f"Missing:    {len(missing)}")

        if failed:
            lines.append("")
            lines.append("Failed:")
            for r in failed:
                lines.append(f"\u2717 {r.path}")
                lines.append(f"  {r.error}")

        if missing:
            lines.append("")
            lines.append("Missing (planned but not found on disk after build):")
            for path in missing:
                lines.append(f"\u2717 {path}")

        if syntax_checked:
            lines.append("")
            lines.append("Syntax Check:")
            lines.append(f"{syntax_checked} Python file(s) checked")
            lines.append(f"{syntax_passed} passed")
            lines.append(f"{len(syntax_failed)} failed")
            for s in syntax_failed:
                lines.append(f"\u2717 {s.path}: {s.error}")

        lines.append("")
        lines.append("Project:")
        lines.append(project_root)

        if not success:
            lines.append("")
            lines.append("The project is incomplete and was NOT marked as successful.")

        return "\n".join(lines)

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _parse_json_relaxed(raw: str) -> Optional[dict]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
            return None
