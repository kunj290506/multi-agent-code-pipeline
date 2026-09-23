import asyncio
import os
import sys
import subprocess

workspace = os.path.abspath("scratch/broken_app")

async def test_integration():
    integration_issues = []
    port = 8123
    server_cmd = [sys.executable, "-m", "http.server", str(port)]
    server_proc = subprocess.Popen(server_cmd, cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    try:
        await asyncio.sleep(0.5)
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.on("pageerror", lambda err: integration_issues.append(f"Uncaught JS Exception: {err}"))
            page.on("console", lambda msg: integration_issues.append(f"Console Error: {msg.text}") if msg.type == "error" else None)
            page.on("requestfailed", lambda req: integration_issues.append(f"Failed to load resource: {req.url} ({req.failure})"))
            try:
                response = await page.goto(f"http://localhost:{port}/index.html", wait_until="networkidle", timeout=5000)
                # simulate a click
                await page.click("button", timeout=1000)
                await asyncio.sleep(0.5)
            except Exception as e:
                pass
            await browser.close()
    finally:
        server_proc.terminate()
        
    print("Integration issues found:", integration_issues)

if __name__ == "__main__":
    os.makedirs(workspace, exist_ok=True)
    with open(os.path.join(workspace, "index.html"), "w") as f:
        f.write('''<!DOCTYPE html>
<html>
<body>
    <button onclick="nonExistentFunction()">Click me</button>
</body>
</html>''')
    asyncio.run(test_integration())
