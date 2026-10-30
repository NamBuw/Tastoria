"""Browser checks against exported app. Mock auth/API: never creates a real account."""
import json
import os
import time
import urllib.request
from playwright.sync_api import sync_playwright

BASE = os.environ.get('WEB_URL', 'http://127.0.0.1:8137')
for attempt in range(30):
    try:
        urllib.request.urlopen(BASE, timeout=2)
        break
    except OSError:
        time.sleep(1)
else:
    raise RuntimeError('Preview server did not start')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    for width in (320, 390, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(BASE + '/')
        page.get_by_role('heading', name='Taste and write your story.').wait_for()
        assert page.url == BASE + '/'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.get_by_role('link', name='Đăng nhập', exact=True).get_attribute('href') == '/dang-nhap'
        page.get_by_role('button', name='Đậu phụ', exact=True).click()
        assert page.locator('#recipe-name').inner_text() == 'Đậu phụ sốt nấm'
    page.get_by_role('link', name='Đăng nhập', exact=True).click()
    page.get_by_test_id('screen-login').wait_for()
    page.get_by_role('link', name='← Về trang giới thiệu Tastoria').click()
    page.get_by_role('heading', name='Taste and write your story.').wait_for()
    page.get_by_role('link', name='Đăng ký', exact=False).first.click()
    page.get_by_test_id('screen-register').wait_for()
    page.goto(BASE + '/bep')
    page.get_by_test_id('screen-login').wait_for()
    # A separate browser context simulates an existing account, using no server data.
    ctx = browser.new_context(viewport={'width': 390, 'height': 844})
    ctx.add_init_script("sessionStorage.setItem('tastoria.refresh', 'fixture-only')")
    def api(route):
        url = route.request.url
        status = 200
        if '/auth/refresh' in url:
            body = {'access_token': 'fixture', 'refresh_token': 'fixture', 'user': {'id': 'fixture', 'email': 'fixture@example.com'}}
        elif '/me/profile' in url:
            body = {'updated_at': '2026-10-30', 'allergen_codes': [], 'favorite_recipe_ids': [], 'diet_code': None}
        elif '/meal-plans/latest' in url:
            body, status = {}, 404
        else:
            body = {'items': []}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body))
    ctx.route('**/api/**', api)
    signed = ctx.new_page()
    signed.on('pageerror', lambda e: errors.append(str(e)))
    signed.goto(BASE + '/dang-nhap')
    signed.get_by_test_id('screen-home').wait_for()
    assert signed.url.endswith('/bep')
    signed.reload()
    signed.get_by_test_id('screen-home').wait_for()
    for scheme in ('light', 'dark'):
        signed.emulate_media(color_scheme=scheme)
        assert signed.get_by_text('Taste and write your story').is_visible()
        assert signed.evaluate('document.documentElement.scrollWidth <= innerWidth')
    signed.get_by_test_id('home-scan-fridge').click()
    signed.wait_for_url('**/quet?mode=fridge')
    assert not errors, errors
    browser.close()
print('PASS: public root, optional auth, protected app, refresh, scan navigation, responsive layout.')
