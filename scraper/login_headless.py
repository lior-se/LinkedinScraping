import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def login(email: str, password: str, *, headless: bool=False, state_file: str="login_state.json") -> bool:
    """
    Automatic login to LinkedIn.
    :param email: LinkedIn email address. Default is LINKEDIN_EMAIL env var.
    :param password: LinkedIn password. Default is LINKEDIN_PASSWORD env var.
    :param headless: With or without headless mode. Default is False.
    :param state_file: User session state file. Default is login_state.json.
    :return: True if successful, False otherwise.
    """
    load_dotenv()
    email = email or os.getenv("LINKEDIN_EMAIL", "")
    password = password or os.getenv("LINKEDIN_PASSWORD", "")
    if not email or not password:
        print("Missing credentials.")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            locale="en-US"
        )
        page = context.new_page()

        try:
            page.goto("https://www.linkedin.com/login", timeout=30000)
            page.wait_for_selector("#username", timeout=20000)
            page.fill("#username", email)
            page.fill("#password, #session_password", password)
            page.click('button[data-litms-control-urn="login-submit"], button[type="submit"]')
            page.wait_for_timeout(2000)
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30_000)
            if "/login" in page.url:
                print("Still on login")
                return False

            context.storage_state(path=state_file)
            print(f"Saved session to {state_file}")
            return True

        except PWTimeout:
            print("Timeout during login.")
            return False
        finally:
            context.close()
            browser.close()

def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=os.getenv("LINKEDIN_EMAIL", ""))
    ap.add_argument("--password", default=os.getenv("LINKEDIN_PASSWORD", ""))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--state", default="login_state.json")
    args = ap.parse_args()
    ok = login(args.email, args.password, headless=args.headless, state_file=args.state)
    raise SystemExit(0 if ok else 1)

# CLI passthrough
if __name__ == "__main__":
    _cli()
