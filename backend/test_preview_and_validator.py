# backend/test_preview_and_validator.py
"""Tests for automated interactivity validator, JSON/code fallback extraction, and live preview engine."""

import os
import shutil
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from agent import _extract_fallback_file_write, _unescape_if_json_string
from llm import extract_json_action, is_chat_model
from main import _prepare_preview_html, detect_workspace_preview
from validator import validate_html, validate_python, validate_workspace_file


class TestValidatorAndPreview(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="preview_val_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_catches_div_value_bug(self):
        html = """<!DOCTYPE html><html><body>
        <div id="display">0</div>
        <button onclick="press('7')">7</button>
        <script>
          const display = document.getElementById('display');
          function press(n) { display.value = n; }
        </script></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("not an <input>" in e.lower() for e in res["errors"]))

    def test_catches_js_syntax_error(self):
        html = """<!DOCTYPE html><html><body>
        <button id="btn">Go</button>
        <script>function broken( { console.log(1); }</script></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("syntaxerror" in e.lower() for e in res["errors"]))

    def test_catches_missing_dom_id(self):
        html = """<!DOCTYPE html><html><body>
        <div id="output"></div>
        <script>document.getElementById('nonexistent').textContent = 'hi';</script>
        </body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("#nonexistent" in e for e in res["errors"]))

    def test_catches_undefined_and_scoped_onclick(self):
        html = """<!DOCTYPE html><html><body>
        <button onclick="missingFn()">A</button>
        <button onclick="trappedFn()">B</button>
        <script>
          document.addEventListener('DOMContentLoaded', () => {
            function trappedFn() { console.log('trapped'); }
          });
        </script></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("missingFn" in e for e in res["errors"]))
        self.assertTrue(any("trappedFn" in e for e in res["errors"]))

    def test_catches_head_script_before_dom(self):
        html = """<!DOCTYPE html><html><head>
        <script>const box = document.getElementById('box'); box.textContent = 'ok';</script>
        </head><body><div id="box"></div></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("before <body>" in e for e in res["errors"]))

    def test_catches_buttons_without_script(self):
        html = """<!DOCTYPE html><html><body><button>Click me</button></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("no javascript" in e.lower() for e in res["errors"]))

    def test_valid_interactive_html_passes(self):
        html = """<!DOCTYPE html><html><body>
        <div id="display">0</div>
        <button onclick="addOne()">+1</button>
        <script>
          let count = 0;
          const display = document.getElementById('display');
          function addOne() { count += 1; display.textContent = String(count); }
        </script></body></html>"""
        res = validate_html(html, "index.html")
        self.assertTrue(res["valid"], f"Expected valid HTML, got errors: {res['errors']}")

    def test_python_validator(self):
        self.assertTrue(validate_python("print('ok')\n", "hello.py")["valid"])
        self.assertFalse(validate_python("def bad(:\n  pass\n", "bad.py")["valid"])

    def test_extract_json_action_with_nested_css_braces(self):
        text = (
            'Here is the call:\n'
            '{"name": "write_file", "arguments": {"path": "index.html", '
            '"content": "<!DOCTYPE html><style>body { color: #fff; }</style><html></html>"}}'
        )
        action = extract_json_action(text)
        self.assertIsNotNone(action)
        self.assertEqual(action["name"], "write_file")
        self.assertEqual(action["arguments"]["path"], "index.html")
        self.assertIn("body { color: #fff; }", action["arguments"]["content"])

    def test_fallback_code_extraction(self):
        resp = "Here is your app:\n```html\n<!DOCTYPE html><html><body><h1>Hi</h1></body></html>\n```"
        tc = _extract_fallback_file_write("Build a calculator into index.html", resp)
        self.assertIsNotNone(tc)
        self.assertEqual(tc["name"], "write_file")
        self.assertEqual(tc["arguments"]["path"], "index.html")

    def test_chat_model_filter(self):
        self.assertTrue(is_chat_model("qwen2.5:7b-instruct-q4_K_M"))
        self.assertTrue(is_chat_model("qwen2.5-coder:3b"))
        self.assertFalse(is_chat_model("nomic-embed-text:latest"))

    def test_preview_detection_all_project_types(self):
        # Empty
        self.assertEqual(detect_workspace_preview(self.temp_dir)["type"], "empty")

        # Python project
        py_p = os.path.join(self.temp_dir, "hello.py")
        with open(py_p, "w", encoding="utf-8") as f:
            f.write("print('hello')\n")
        info_py = detect_workspace_preview(self.temp_dir)
        self.assertEqual(info_py["type"], "python")
        self.assertEqual(info_py["entry"], "hello.py")
        self.assertEqual(info_py["command"], "python hello.py")

        # Nested HTML takes priority over python
        os.makedirs(os.path.join(self.temp_dir, "app"), exist_ok=True)
        with open(os.path.join(self.temp_dir, "app", "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><body>Nested</body></html>")
        info_nested = detect_workspace_preview(self.temp_dir)
        self.assertEqual(info_nested["type"], "web")
        self.assertEqual(info_nested["entry"], "app/index.html")

        # Root index.html takes highest priority
        with open(os.path.join(self.temp_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><body>Root</body></html>")
        info_root = detect_workspace_preview(self.temp_dir)
        self.assertEqual(info_root["entry"], "index.html")

    def test_prepare_preview_html_rewrites_root_assets_and_injects_bridge(self):
        with open(os.path.join(self.temp_dir, "styles.css"), "w", encoding="utf-8") as f:
            f.write("body { margin: 0; }")
        with open(os.path.join(self.temp_dir, "app.js"), "w", encoding="utf-8") as f:
            f.write("console.log('hi');")

        raw = '<!DOCTYPE html><html><head><link rel="stylesheet" href="/styles.css"></head><body><script src="/app.js"></script></body></html>'
        out = _prepare_preview_html(raw, "index.html", self.temp_dir)
        self.assertIn('href="/preview/styles.css"', out)
        self.assertIn('src="/preview/app.js"', out)
        self.assertIn('<base href="/preview/">', out)
        self.assertIn('data-multiagent-bridge="true"', out)

    def test_extract_json_action_with_unescaped_regex_backslashes(self):
        # Simulates 3B model writing JS regex /\d/ and /\+|\-|\*|\/|\./ inside JSON without double-escaping
        raw_text = (
            '{"name": "write_file", "arguments": {"path": "index.html", '
            '"content": "<!DOCTYPE html><html><body><script>if (/\\d/.test(k) || /\\+|\\-|\\*|\\/|\\./.test(k)) {}</script></body></html>"}}'
        ).replace("\\\\d", "\\d").replace("\\\\+", "\\+").replace("\\\\-", "\\-").replace("\\\\*", "\\*").replace("\\\\/", "\\/").replace("\\\\.", "\\.")
        action = extract_json_action(raw_text)
        self.assertIsNotNone(action)
        self.assertEqual(action["name"], "write_file")
        content = action["arguments"]["content"]
        self.assertIn(r"/\+|\-|\*|\/|\./", content)
        res = validate_html(content, "index.html")
        self.assertTrue(res["valid"], f"Expected valid JS regex after extraction, got: {res['errors']}")

    def test_catches_chained_dom_textcontent_state_bug(self):
        html = """<!DOCTYPE html><html><body>
        <div id="display"></div>
        <button onclick="add('1')">1</button>
        <script>
          let display = document.getElementById('display').textContent = '0';
          function add(n) { display += n; }
        </script></body></html>"""
        res = validate_html(html, "index.html")
        self.assertFalse(res["valid"])
        self.assertTrue(any("dom state bug" in e.lower() for e in res["errors"]))

    def test_unescape_double_escaped_html(self):
        escaped = '<!DOCTYPE html>\\n<html lang=\\"en\\">\\n<body>Hi</body>\\n</html>'
        restored = _unescape_if_json_string(escaped)
        self.assertIn('\n<html lang="en">\n', restored)


if __name__ == "__main__":
    unittest.main()
