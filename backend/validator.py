# backend/validator.py
"""Automated static & syntax validator for generated HTML, JS, CSS, and Python workspace files.

Catches common LLM interactivity bugs (e.g. setting .value on a <div>, missing DOM IDs,
undefined onclick handlers, script-before-DOM bugs, JS/Python syntax errors, truncated HTML,
and missing local assets) so the agent can self-heal before completing a turn.
"""

import html.parser
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

NON_VALUE_TAGS = {
    "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "td", "th", "tr", "li", "ul", "ol", "label", "section",
    "article", "header", "footer", "main", "aside", "nav",
    "pre", "code", "strong", "em", "b", "i", "small", "a",
    "blockquote", "figure", "figcaption", "table", "tbody", "thead",
}

VALUE_TAGS = {"input", "textarea", "select", "option", "button", "progress", "meter", "output"}

INLINE_EVENT_ATTRS = {
    "onclick", "ondblclick", "onchange", "oninput", "onsubmit",
    "onkeydown", "onkeyup", "onkeypress", "onmousedown", "onmouseup",
    "onmouseover", "mouseout", "onmouseenter", "onmouseleave",
    "onfocus", "onblur", "onload", "onreset", "onwheel", "oncontextmenu",
}

JS_BUILTINS = {
    "alert", "confirm", "prompt", "console", "window", "document", "location",
    "history", "navigator", "localStorage", "sessionStorage", "Math", "Date",
    "JSON", "Array", "Object", "String", "Number", "Boolean", "parseInt",
    "parseFloat", "isNaN", "isFinite", "setTimeout", "clearTimeout",
    "setInterval", "clearInterval", "fetch", "eval", "this", "event", "return",
    "void", "new", "delete", "typeof", "true", "false", "null", "undefined",
    "if", "else", "for", "while", "switch", "try", "catch",
}


class _HTMLStructureParser(html.parser.HTMLParser):
    """Lightweight HTML parser capturing element IDs, tags, scripts, links, and inline handlers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.id_to_tag: Dict[str, str] = {}
        self.tags_seen: Set[str] = set()
        self.inline_handlers: List[Tuple[str, str, int]] = []  # (attr, code, line)
        self.inline_scripts: List[Tuple[str, bool, int, str]] = []  # (code, in_head, line, type)
        self.external_scripts: List[Tuple[str, int]] = []  # (src, line)
        self.stylesheets: List[Tuple[str, int]] = []  # (href, line)
        self.has_interactive_controls: bool = False
        self._in_head: bool = False
        self._in_script: bool = False
        self._script_is_head: bool = False
        self._script_line: int = 1
        self._script_type: str = ""
        self._script_has_src: bool = False
        self._script_buf: List[str] = []
        self._in_style: bool = False
        self.unclosed_script: bool = False
        self.unclosed_style: bool = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        self.tags_seen.add(t)
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        line = self.getpos()[0]

        if t == "head":
            self._in_head = True
        elif t == "body":
            self._in_head = False

        if t in ("button", "input", "select", "textarea", "form", "canvas"):
            self.has_interactive_controls = True

        elem_id = attr_map.get("id", "").strip()
        if elem_id:
            self.id_to_tag[elem_id] = t

        for attr_name, attr_val in attr_map.items():
            if attr_name in INLINE_EVENT_ATTRS and attr_val.strip():
                self.inline_handlers.append((attr_name, attr_val.strip(), line))
                self.has_interactive_controls = True

        if t == "link":
            rel = attr_map.get("rel", "").lower()
            href = attr_map.get("href", "").strip()
            if "stylesheet" in rel and href:
                self.stylesheets.append((href, line))

        if t == "script":
            src = attr_map.get("src", "").strip()
            script_type = attr_map.get("type", "").strip().lower()
            if src:
                self.external_scripts.append((src, line))
                self._script_has_src = True
            else:
                self._script_has_src = False
            self._in_script = True
            self._script_is_head = self._in_head and ("defer" not in attr_map)
            self._script_line = line
            self._script_type = script_type
            self._script_buf = []

        if t == "style":
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "head":
            self._in_head = False
        elif t == "script":
            if self._in_script and not self._script_has_src:
                code = "".join(self._script_buf)
                self.inline_scripts.append((code, self._script_is_head, self._script_line, self._script_type))
            self._in_script = False
            self._script_buf = []
        elif t == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buf.append(data)

    def finalize(self) -> None:
        if self._in_script:
            self.unclosed_script = True
            if not self._script_has_src:
                code = "".join(self._script_buf)
                self.inline_scripts.append((code, self._script_is_head, self._script_line, self._script_type))
        if self._in_style:
            self.unclosed_style = True


def _check_js_syntax(js_code: str, is_module: bool = False) -> Optional[str]:
    """Validate JavaScript syntax using `node --check`. Returns error string or None."""
    node_bin = shutil.which("node")
    if not node_bin:
        return None
    if not js_code.strip():
        return None

    suffix = ".mjs" if is_module else ".js"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", delete=False) as tf:
            tf.write(js_code)
            tmp_path = tf.name

        proc = subprocess.run(
            [node_bin, "--check", tmp_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "JavaScript syntax error").strip()
            # Clean up temp filename in output for readability
            err = err.replace(tmp_path, "<script>")
            lines = [ln for ln in err.splitlines() if ln.strip()][:6]
            return " | ".join(lines)
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return None


def _strip_js_comments_and_strings_for_top_level(js_code: str) -> str:
    """Best-effort strip of single-line and multi-line comments for regex analysis."""
    code = re.sub(r"/\*[\s\S]*?\*/", " ", js_code)
    code = re.sub(r"(?<!:)//[^\n]*", "", code)
    return code


def _extract_defined_js_functions(js_code: str) -> Tuple[Set[str], Set[str]]:
    """
    Returns (all_defined_names, global_defined_names).
    Helps catch functions that are undefined OR trapped inside DOMContentLoaded / IIFE
    when called from inline HTML onclick="...".
    """
    clean = _strip_js_comments_and_strings_for_top_level(js_code)

    fn_patterns = [
        r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
        r"\bwindow\.([A-Za-z_$][\w$]*)\s*=",
        r"\bglobalThis\.([A-Za-z_$][\w$]*)\s*=",
    ]

    all_defs: Set[str] = set()
    for pat in fn_patterns:
        for m in re.finditer(pat, clean):
            all_defs.add(m.group(1))

    # Track brace depth to find truly top-level definitions (depth == 0) + explicit window.X
    global_defs: Set[str] = set()
    for m in re.finditer(r"\b(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*=", clean):
        global_defs.add(m.group(1))

    depth = 0
    in_str: Optional[str] = None
    escaped = False
    i = 0
    n = len(clean)
    top_level_chars: List[str] = []

    while i < n:
        ch = clean[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            top_level_chars.append(" " if depth > 0 else ch)
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_str = ch
            top_level_chars.append(" " if depth > 0 else ch)
        elif ch == "{":
            if depth == 0:
                top_level_chars.append("{")
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                top_level_chars.append("}")
        else:
            top_level_chars.append(ch if depth == 0 else " ")
        i += 1

    top_code = "".join(top_level_chars)
    for pat in fn_patterns[:2]:
        for m in re.finditer(pat, top_code):
            global_defs.add(m.group(1))

    return all_defs, global_defs


def validate_html(
    content: str,
    file_path: str,
    workspace_root: Optional[str] = None,
    check_missing_assets: bool = True,
    strict_assets: bool = False,
) -> Dict[str, Any]:
    """
    Validate an HTML document for syntax, DOM mismatches, broken handlers, and interactivity bugs.
    Returns {"valid": bool, "errors": List[str], "warnings": List[str]}.
    """
    errors: List[str] = []
    warnings: List[str] = []

    stripped = content.strip()
    if not stripped:
        return {"valid": False, "errors": [f"'{file_path}' is empty."], "warnings": []}

    # Detect JSON-double-escaped HTML written on a single line (e.g. <!DOCTYPE html>\n<html lang=\"en\">)
    if "\\n" in content and '\\"' in content and content.count("\n") <= 2:
        return {
            "valid": False,
            "errors": [
                f"Formatting bug in '{file_path}': file contains literal escaped '\\n' and '\\\"' characters instead of real newlines and quotes. Rewrite cleanly with write_file."
            ],
            "warnings": [],
        }

    parser = _HTMLStructureParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:
        errors.append(f"HTML parse error in '{file_path}': {exc}")
    parser.finalize()

    # 1. Truncation / unclosed critical tags
    if parser.unclosed_script:
        errors.append(f"Unclosed <script> tag in '{file_path}'. The file appears truncated.")
    if parser.unclosed_style:
        errors.append(f"Unclosed <style> tag in '{file_path}'. The file appears truncated.")
    if "<html" in content.lower() and "</html>" not in content.lower():
        errors.append(f"Missing closing </html> tag in '{file_path}'. Output may have been truncated.")

    # Collect local external scripts content too so cross-file checks work accurately
    combined_js_parts: List[str] = []
    base_dir = os.path.dirname(os.path.join(workspace_root, file_path)) if workspace_root else ""

    for src, line in parser.external_scripts:
        if src.startswith(("http://", "https://", "//")):
            # Check for known breaking CDN usage patterns (e.g. marked() vs marked.parse())
            if "marked" in src.lower():
                warnings.append(
                    f"External CDN script '{src}' (line {line}): consider implementing a self-contained "
                    "markdown parser in vanilla JS so the app works reliably offline without CDN version mismatches."
                )
        else:
            if workspace_root:
                rel_src = src.lstrip("/")
                cand1 = os.path.join(base_dir, src) if not src.startswith("/") else os.path.join(workspace_root, rel_src)
                cand2 = os.path.join(workspace_root, rel_src)
                found_js = cand1 if os.path.isfile(cand1) else (cand2 if os.path.isfile(cand2) else None)
                if found_js:
                    try:
                        with open(found_js, "r", encoding="utf-8", errors="replace") as fh:
                            combined_js_parts.append(fh.read())
                    except Exception:
                        pass
                elif check_missing_assets:
                    msg = f"Referenced local script '{src}' (line {line}) does not exist in workspace."
                    if strict_assets:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

    for href, line in parser.stylesheets:
        if not href.startswith(("http://", "https://", "//", "data:")):
            if workspace_root and check_missing_assets:
                rel_href = href.lstrip("/")
                cand1 = os.path.join(base_dir, href) if not href.startswith("/") else os.path.join(workspace_root, rel_href)
                cand2 = os.path.join(workspace_root, rel_href)
                if not (os.path.isfile(cand1) or os.path.isfile(cand2)):
                    msg = f"Referenced local stylesheet '{href}' (line {line}) does not exist in workspace."
                    if strict_assets:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

    # 2. Inline script syntax & head-script DOM checks
    all_module_scripts = True
    for script_code, in_head, line, script_type in parser.inline_scripts:
        if script_type and script_type not in ("text/javascript", "application/javascript", "module"):
            continue
        if not script_code.strip():
            continue

        is_mod = script_type == "module"
        if not is_mod:
            all_module_scripts = False
        syntax_err = _check_js_syntax(script_code, is_module=is_mod)
        if syntax_err:
            errors.append(f"JavaScript SyntaxError in '{file_path}' (script near line {line}): {syntax_err}")

        # Check script in <head> running top-level DOM queries without DOMContentLoaded
        if in_head and not is_mod:
            has_dom_ready = bool(re.search(r"DOMContentLoaded|window\.onload|addEventListener\s*\(\s*['\"]load['\"]", script_code))
            has_top_dom_query = bool(re.search(r"\bdocument\.(?:getElementById|querySelector|querySelectorAll)\s*\(", script_code))
            # Only flag if the query appears at top level (not purely inside functions)
            if has_top_dom_query and not has_dom_ready:
                # Check if there is a top-level const/let/var = document.getElementById(...)
                if re.search(r"^\s*(?:const|let|var)\s+\w+\s*=\s*document\.(?:getElementById|querySelector)", script_code, re.MULTILINE):
                    errors.append(
                        f"DOM timing bug in '{file_path}': <script> inside <head> (line {line}) queries DOM elements "
                        "before <body> is parsed (returns null!). Move <script> to the end of <body> or wrap in DOMContentLoaded."
                    )

        combined_js_parts.append(script_code)

    combined_js = "\n\n".join(combined_js_parts)

    # 3. No JS at all when page has interactive controls
    if parser.has_interactive_controls and not combined_js.strip() and not parser.external_scripts:
        errors.append(
            f"Interactivity bug in '{file_path}': page has buttons/inputs but no JavaScript logic! "
            "Add complete working JavaScript inside <script> at the bottom of <body>."
        )

    if combined_js.strip():
        clean_js = _strip_js_comments_and_strings_for_top_level(combined_js)

        # Collect dynamically generated IDs in JS (e.g. id="cell-0" or .id = 'foo')
        dynamic_ids: Set[str] = set()
        for m in re.finditer(r"""\bid\s*=\s*['"]([A-Za-z0-9_-]+)['"]""", combined_js):
            dynamic_ids.add(m.group(1))
        for m in re.finditer(r"""\.id\s*=\s*['"]([A-Za-z0-9_-]+)['"]""", combined_js):
            dynamic_ids.add(m.group(1))

        all_known_ids = set(parser.id_to_tag.keys()) | dynamic_ids

        # 4. DOM .value mismatch on non-input elements (THE classic calculator display.value bug!)
        # Map JS variable name -> (element_id, tag_name)
        var_to_elem: Dict[str, Tuple[str, str]] = {}
        assign_patterns = [
            r"""\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.getElementById\(\s*['"]([^'"]+)['"]\s*\)""",
            r"""\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.querySelector\(\s*['"]#([A-Za-z0-9_-]+)['"]\s*\)""",
        ]
        for pat in assign_patterns:
            for m in re.finditer(pat, clean_js):
                var_name, elem_id = m.group(1), m.group(2)
                if elem_id in parser.id_to_tag:
                    var_to_elem[var_name] = (elem_id, parser.id_to_tag[elem_id])

        # Check chained DOM property assignment bug:
        # e.g. `let display = document.getElementById('display').textContent = '0';`
        # That stores the string '0' in `display` instead of the DOM element, so screen never updates!
        for m in re.finditer(
            r"""\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.(?:getElementById|querySelector)\([^)]+\)\.(?:textContent|innerText|innerHTML|value)\s*=""",
            clean_js,
        ):
            bad_var = m.group(1)
            errors.append(
                f"DOM state bug in '{file_path}': '{bad_var}' is assigned the result of '.textContent = ...' (a string), "
                f"NOT the DOM element! Store the element ('const {bad_var}El = document.getElementById(...)') and update "
                f"'{bad_var}El.textContent = ...' inside your event handlers so the UI visibly updates."
            )

        # Check direct document.getElementById('X').value
        for m in re.finditer(
            r"""document\.(?:getElementById\(\s*['"]([^'"]+)['"]\s*\)|querySelector\(\s*['"]#([A-Za-z0-9_-]+)['"]\s*\))\.value\b""",
            clean_js,
        ):
            elem_id = m.group(1) or m.group(2)
            tag = parser.id_to_tag.get(elem_id)
            if tag and tag in NON_VALUE_TAGS:
                errors.append(
                    f"DOM interactivity bug in '{file_path}': element #{elem_id} is a <{tag}>, NOT an <input>/<textarea>/<select>. "
                    f"Using '.value' on <{tag}> does NOTHING visually! Use '.textContent' (or change <{tag} id=\"{elem_id}\"> to <input readonly>)."
                )

        # Check variable.value for variables bound to non-value tags
        reported_vars: Set[str] = set()
        for var_name, (elem_id, tag) in var_to_elem.items():
            if tag in NON_VALUE_TAGS and var_name not in reported_vars:
                if re.search(rf"\b{re.escape(var_name)}\.value\b", clean_js):
                    reported_vars.add(var_name)
                    errors.append(
                        f"DOM interactivity bug in '{file_path}': '{var_name}' references <{tag} id=\"{elem_id}\">, "
                        f"which is NOT an <input>/<textarea>/<select>. Reading/setting '{var_name}.value' does NOTHING! "
                        f"Use '{var_name}.textContent' instead (or change the HTML element to an <input>)."
                    )

        # Check variable.textContent / innerHTML on <input> elements (writing to input.textContent does nothing!)
        for var_name, (elem_id, tag) in var_to_elem.items():
            if tag == "input":
                if re.search(rf"\b{re.escape(var_name)}\.(?:textContent|innerText|innerHTML)\s*=", clean_js):
                    errors.append(
                        f"DOM interactivity bug in '{file_path}': '{var_name}' references <input id=\"{elem_id}\">. "
                        f"Setting '{var_name}.textContent' does nothing on an <input>! Use '{var_name}.value = ...'."
                    )

        # 5. Missing DOM ID references
        missing_ids: Set[str] = set()
        for m in re.finditer(r"""document\.getElementById\(\s*['"]([^'"]+)['"]\s*\)""", clean_js):
            ref_id = m.group(1)
            if ref_id not in all_known_ids and "${" not in ref_id:
                missing_ids.add(ref_id)
        for m in re.finditer(r"""document\.querySelector\(\s*['"]#([A-Za-z0-9_-]+)['"]\s*\)""", clean_js):
            ref_id = m.group(1)
            if ref_id not in all_known_ids:
                missing_ids.add(ref_id)

        for mid in sorted(missing_ids):
            errors.append(
                f"Missing DOM element in '{file_path}': JS queries id='#{mid}', but no element with id=\"{mid}\" exists in the HTML!"
            )

        # 6. Inline HTML event handlers calling undefined or non-global functions
        all_defs, global_defs = _extract_defined_js_functions(combined_js)
        # If every inline script is type="module", only explicit window.X / globalThis.X are global
        if parser.inline_scripts and all_module_scripts and not parser.external_scripts:
            global_defs = {
                m.group(1)
                for m in re.finditer(r"\b(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*=", clean_js)
            }
        missing_fns: Set[str] = set()
        scoped_fns: Set[str] = set()

        for attr, code, line in parser.inline_handlers:
            # Find function calls like myFunc( or foo.bar(
            for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", code):
                fn_name = m.group(1)
                if fn_name in JS_BUILTINS:
                    continue
                if fn_name not in all_defs:
                    missing_fns.add(f"{fn_name}() in {attr} (line {line})")
                elif fn_name not in global_defs:
                    scoped_fns.add(f"{fn_name}() in {attr} (line {line})")

        for mf in sorted(missing_fns):
            errors.append(
                f"Broken event handler in '{file_path}': inline handler calls {mf}, which is not defined in <script>!"
            )
        for sf in sorted(scoped_fns):
            errors.append(
                f"Scope bug in '{file_path}': inline handler calls {sf}, which is defined inside a nested scope/DOMContentLoaded "
                "and NOT reachable from global inline onclick! Define it at top level or use addEventListener."
            )

        # 7. Check for marked() v4 vs marked.parse() v5+ pitfall if CDN marked is used
        if any("marked" in src.lower() for src, _ in parser.external_scripts):
            if re.search(r"(?<![.\w])marked\s*\(", clean_js):
                errors.append(
                    f"Library API bug in '{file_path}': 'marked(text)' throws TypeError in modern marked.js CDN versions! "
                    "Use 'marked.parse(text)' OR better yet write a self-contained vanilla JS markdown parser with zero external CDN dependencies."
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def validate_js(content: str, file_path: str) -> Dict[str, Any]:
    """Validate standalone JS file syntax using node --check."""
    is_mod = file_path.lower().endswith(".mjs") or bool(re.search(r"^\s*(?:import|export)\s+", content, re.MULTILINE))
    err = _check_js_syntax(content, is_module=is_mod)
    if err:
        return {"valid": False, "errors": [f"JavaScript SyntaxError in '{file_path}': {err}"], "warnings": []}
    return {"valid": True, "errors": [], "warnings": []}


def validate_python(content: str, file_path: str) -> Dict[str, Any]:
    """Validate Python file syntax using built-in compile()."""
    try:
        compile(content, file_path, "exec")
        return {"valid": True, "errors": [], "warnings": []}
    except SyntaxError as exc:
        return {
            "valid": False,
            "errors": [f"Python SyntaxError in '{file_path}' at line {exc.lineno}: {exc.msg}"],
            "warnings": [],
        }


def validate_workspace_file(
    workspace_root: str,
    rel_path: str,
    check_missing_assets: bool = True,
    strict_assets: bool = False,
) -> Dict[str, Any]:
    """Dispatch validation based on file extension."""
    full_path = os.path.join(workspace_root, rel_path)
    if not os.path.isfile(full_path):
        return {"valid": True, "errors": [], "warnings": []}

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return {"valid": True, "errors": [], "warnings": []}

    ext = os.path.splitext(rel_path)[1].lower()
    if ext in (".html", ".htm"):
        return validate_html(
            content,
            rel_path,
            workspace_root=workspace_root,
            check_missing_assets=check_missing_assets,
            strict_assets=strict_assets,
        )
    if ext in (".js", ".mjs"):
        return validate_js(content, rel_path)
    if ext == ".py":
        return validate_python(content, rel_path)
    return {"valid": True, "errors": [], "warnings": []}
