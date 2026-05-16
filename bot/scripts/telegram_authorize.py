from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from http.cookiejar import Cookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import urllib3
from playwright.async_api import async_playwright

from hh_applicant_tool.main import BaseNamespace, HHApplicantTool


HH_ANDROID_SCHEME = "hhandroid"

SEL_LOGIN_INPUT = 'input[data-qa="login-input-username"]'
SEL_CODE_CONTAINER = 'div[data-qa="account-login-code-input"]'
SEL_PIN_CODE_INPUT = 'input[data-qa="magritte-pincode-input-field"]'
SEL_CAPTCHA_IMAGE = 'img[data-qa="account-captcha-picture"]'
SEL_CAPTCHA_INPUT = 'input[data-qa="account-captcha-input"]'


def emit(event: str) -> None:
    print(event, flush=True)


def read_required_line(event: str) -> str:
    value = sys.stdin.readline().strip()
    if not value:
        raise RuntimeError(f"{event}: empty input")
    return value


def create_tool(config_dir: str, profile_id: str) -> HHApplicantTool:
    os.environ["HH_PROFILE_ID"] = profile_id
    tool = HHApplicantTool()
    args = tool._parser.parse_args(
        ["--config-dir", config_dir, "--profile-id", profile_id],
        namespace=BaseNamespace(),
    )
    tool._assign_args(args)
    tool.config_path.mkdir(parents=True, exist_ok=True)
    return tool


def set_session_cookies(tool: HHApplicantTool, cookies: list[dict]) -> None:
    for c in cookies:
        cookie = Cookie(
            version=0,
            name=c["name"],
            value=c["value"],
            port=None,
            port_specified=False,
            domain=c["domain"],
            domain_specified=True,
            domain_initial_dot=c["domain"].startswith("."),
            path=c["path"],
            path_specified=True,
            secure=c["secure"],
            expires=int(c.get("expires") or 0),
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": str(c.get("httpOnly", False))},
            rfc2109=False,
        )
        tool.session.cookies.set_cookie(cookie)


async def handle_captcha_if_present(page, captcha_file: Path) -> None:
    try:
        captcha = await page.wait_for_selector(
            SEL_CAPTCHA_IMAGE,
            timeout=5000,
            state="visible",
        )
    except Exception:
        return

    captcha_file.parent.mkdir(parents=True, exist_ok=True)
    await captcha.screenshot(path=str(captcha_file))
    emit("CAPTCHA_REQUIRED")
    captcha_text = read_required_line("CAPTCHA")
    await page.fill(SEL_CAPTCHA_INPUT, captcha_text)
    await page.press(SEL_CAPTCHA_INPUT, "Enter")


async def authorize(args: argparse.Namespace) -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    tool = create_tool(args.config_dir, args.profile_id)
    api_client = tool.api_client

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(**pw.devices["Galaxy A55"])
            page = await context.new_page()
            code_future: asyncio.Future[str | None] = asyncio.Future()

            def handle_request(request) -> None:
                url = request.url
                if url.startswith(f"{HH_ANDROID_SCHEME}://") and not code_future.done():
                    sp = urlsplit(url)
                    code_future.set_result(parse_qs(sp.query).get("code", [None])[0])

            page.on("request", handle_request)
            await page.goto(
                api_client.oauth_client.authorize_url,
                timeout=30000,
                wait_until="load",
            )
            await page.wait_for_selector(SEL_LOGIN_INPUT, timeout=30000)
            await page.fill(SEL_LOGIN_INPUT, args.phone)
            await page.press(SEL_LOGIN_INPUT, "Enter")

            await handle_captcha_if_present(page, Path(args.captcha_file))
            await page.wait_for_selector(SEL_CODE_CONTAINER, timeout=30000)
            emit("SMS_SENT")

            sms_code = read_required_line("SMS")
            await page.fill(SEL_PIN_CODE_INPUT, sms_code)
            await page.press(SEL_PIN_CODE_INPUT, "Enter")

            auth_code = await asyncio.wait_for(code_future, timeout=60)
            if not auth_code:
                raise RuntimeError("OAuth code was not received")

            token = await asyncio.to_thread(
                api_client.oauth_client.authenticate,
                auth_code,
            )
            api_client.handle_access_token(token)
            tool.storage.settings.set_value("auth.username", args.phone)
            tool.storage.settings.set_value("auth.last_login", datetime.now())
            set_session_cookies(tool, await context.cookies())
            tool.save_token()
            tool.save_cookies()
            emit("AUTH_SUCCESS")
        finally:
            await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--captcha-file", required=True)
    args = parser.parse_args()

    try:
        asyncio.run(authorize(args))
    except Exception as exc:
        emit(f"AUTH_ERROR {exc.__class__.__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
