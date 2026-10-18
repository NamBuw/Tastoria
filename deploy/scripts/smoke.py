"""Browser smoke test of the deployed stack (python playwright):
register -> consent + onboarding -> pantry lots by hand -> tray of the day. Screenshot of the tray: deploy/smoke.png.
    ~/miniconda3/bin/python deploy/scripts/smoke.py [http://127.0.0.1:6880] [deploy/smoke.png]
Creates one throwaway account (smoke+<time>@example.com). Exit 1 on any failure or unexpected 5xx.
Selectors follow app/scripts/e2e_flow.py.
"""
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6880").rstrip("/")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "smoke.png")
EMAIL = f"smoke+{int(time.time())}@example.com"
PW = "smoke-matkhau-12345"
LOTS = [("trứng gà", "count", 10), ("rau muống", "grams", 800), ("thịt ba chỉ", "grams", 600),
        ("thịt băm", "grams", 400), ("rau ngót", "grams", 400), ("hành lá", "grams", 150),
        ("bắp cải", "grams", 900), ("cà chua", "grams", 400), ("hành tím", "grams", 100), ("tỏi", "grams", 100)]


def main() -> int:
    server_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="light",
                            locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh")
        pg = ctx.new_page()
        pg.set_default_timeout(20000)
        pg.on("pageerror", lambda e: page_errors.append(str(e)[:300]))
        pg.on("response", lambda r: r.status >= 500 and server_errors.append(f"{r.status} {r.request.method} {r.url}"))
        tid = pg.get_by_test_id
        step = "start"
        try:
            step = "register"
            pg.goto(BASE + "/dang-ky")
            tid("screen-register").wait_for()
            tid("register-email").fill(EMAIL)
            tid("register-password").fill(PW)
            tid("register-password2").fill(PW)
            tid("register-submit").click()
            step = "consent"
            tid("screen-consent").wait_for()
            tid("consent-health_profile").click()
            tid("consent-personalization").click()
            tid("consent-continue").click()
            step = "onboarding"
            tid("screen-onboarding-body").wait_for()
            pg.get_by_role("radio", name="Nữ").click()
            tid("body-birth-year").fill("1995")
            tid("body-height").fill("158")
            tid("body-weight").fill("52")
            tid("step-next").click()
            pg.get_by_role("radio", name=re.compile("^Nhẹ")).click()
            pg.get_by_role("radio", name="Giữ cân").click()
            tid("step-next").click()
            tid("energy-suggestion").wait_for()
            tid("energy-use").click()
            tid("screen-onboarding-allergen").wait_for()
            tid("allergen-none").click()
            tid("step-next").click()
            tid("screen-onboarding-favorites").wait_for()
            for name in ("Rau muống xào tỏi", "Thịt rang cháy cạnh", "Canh rau ngót thịt băm"):
                pg.get_by_role("checkbox", name=name).click()
            tid("step-done").click()
            tid("screen-home").wait_for()
            step = "pantry"
            pg.goto(BASE + "/kho")
            tid("screen-pantry").wait_for()
            for name, mode, qty in LOTS:
                tid("pantry-add").click()
                tid("add-lot-search").fill(name)
                tid(f"ing-{name}").first.click()
                if mode == "grams":
                    r = pg.get_by_role("radio", name="Theo gam")
                    if r.count():
                        r.click()
                    tid("qty-grams").fill(str(qty))
                else:
                    for _ in range(qty - 1):
                        tid("qty-count-plus").click()
                tid("add-lot-submit").click()
                tid("sheet-add-lot").wait_for(state="detached")
                pg.wait_for_timeout(300)
            pg.get_by_text(f"{len(LOTS)} lô, đồ cần dùng trước ở trên").wait_for()
            step = "tray"
            pg.goto(BASE + "/mam")
            tid("screen-tray").wait_for()
            tid("make-plan").click()
            tid("plan-view").wait_for(timeout=30000)
            dishes = [s for s in ("man", "rau", "canh") if tid(f"tray-dish-{s}").count()]
            labels = [tid(f"tray-dish-{s}").get_attribute("aria-label") for s in dishes]
            pg.wait_for_timeout(800)
            pg.screenshot(path=OUT)
            print("TRAY", labels)
            ok = bool(dishes) and not server_errors
        except Exception as exc:  # report where it stopped, keep a screenshot
            print(f"FAILED at {step}: {str(exc)[:600]}")
            pg.screenshot(path=OUT)
            ok = False
        b.close()
    print("EMAIL", EMAIL)
    print("SERVER_ERRORS", server_errors)
    print("PAGE_ERRORS", page_errors[:10])
    print("SCREENSHOT", os.path.abspath(OUT))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
