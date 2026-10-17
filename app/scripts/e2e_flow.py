"""E2E flow on the web export (python playwright): register → onboarding → pantry by hand → tray → swap → cook →
finish → undo, with a light and a dark screenshot of each screen (390×844).
Run against `npm run serve:web` backed by a real API with the catalog imported:
    WEB_URL=http://127.0.0.1:8080 python scripts/e2e_flow.py docs/screenshots
"""
import sys, time, re, os
from playwright.sync_api import sync_playwright, expect
OUT=sys.argv[1] if len(sys.argv)>1 else 'docs/screenshots'
os.makedirs(OUT, exist_ok=True)
BASE=os.environ.get('WEB_URL', 'http://127.0.0.1:8080')
EMAIL=f'nam+{int(time.time())}@example.com'
PW='matkhau-12345'
errors=[]
def run():
  with sync_playwright() as p:
    b=p.chromium.launch()
    global PG
    ctx=b.new_context(viewport={'width':390,'height':844}, device_scale_factor=2, color_scheme='light', locale='vi-VN', timezone_id='Asia/Ho_Chi_Minh')
    pg=ctx.new_page()
    import atexit
    def fail_shot():
        try: pg.screenshot(path=OUT+'/zz-fail.png')
        except Exception: pass
    import builtins; builtins._fail=fail_shot
    pg.set_default_timeout(15000)
    pg.on('pageerror', lambda e: errors.append(str(e)[:300]))
    pg.on('response', lambda r: r.status>=400 and errors.append(f'HTTP {r.status} {r.request.method} {r.url[-70:]}'))
    def shot(name):
        pg.wait_for_timeout(700)
        pg.screenshot(path=f'{OUT}/{name}-light.png')
        pg.emulate_media(color_scheme='dark'); pg.wait_for_timeout(500)
        pg.screenshot(path=f'{OUT}/{name}-dark.png')
        pg.emulate_media(color_scheme='light'); pg.wait_for_timeout(300)
        print('shot', name, flush=True)
    tid=pg.get_by_test_id
    pg.goto(BASE+'/dang-nhap'); tid('screen-login').wait_for(); shot('01-dang-nhap')
    pg.goto(BASE+'/quen-mat-khau'); tid('screen-forgot').wait_for(); shot('03-quen-mat-khau')
    pg.goto(BASE+'/dang-ky'); tid('screen-register').wait_for()
    tid('register-email').fill(EMAIL); tid('register-password').fill(PW); tid('register-password2').fill(PW)
    shot('02-dang-ky')
    tid('register-submit').click()
    tid('screen-consent').wait_for(); shot('04-dong-y')
    tid('consent-health_profile').click(); tid('consent-personalization').click()
    tid('consent-continue').click()
    tid('screen-onboarding-body').wait_for()
    pg.get_by_role('radio', name='Nữ').click()
    tid('body-birth-year').fill('1995'); tid('body-height').fill('158'); tid('body-weight').fill('52')
    shot('05-ho-so-co-the')
    tid('step-next').click()
    pg.get_by_role('radio', name=re.compile('^Nhẹ')).click(); pg.get_by_role('radio', name='Giữ cân').click()
    shot('06-ho-so-van-dong')
    tid('step-next').click()
    tid('energy-suggestion').wait_for(); shot('07-muc-tieu-nang-luong')
    tid('energy-use').click()
    tid('screen-onboarding-allergen').wait_for()
    tid('allergen-none').click(); shot('08-di-ung-che-do-an')
    tid('step-next').click()
    tid('screen-onboarding-favorites').wait_for()
    pg.get_by_role('checkbox', name='Rau muống xào tỏi').click()
    pg.get_by_role('checkbox', name='Thịt rang cháy cạnh').click()
    pg.get_by_role('checkbox', name='Canh rau ngót thịt băm').click()
    shot('09-mon-hay-an')
    tid('step-done').click()
    tid('screen-home').wait_for(); shot('10-trang-chu-trong')
    # pantry by hand
    pg.goto(BASE+'/kho'); tid('screen-pantry').wait_for()
    lots=[('trứng gà','count',10),('rau muống','grams',800),('thịt ba chỉ','grams',600),('thịt băm','grams',400),
          ('rau ngót','grams',400),('hành lá','grams',150),('bắp cải','grams',900),('cà chua','grams',400),('hành tím','grams',100),('tỏi','grams',100)]
    for i,(name,mode,qty) in enumerate(lots):
        tid('pantry-add').click()
        tid('add-lot-search').fill(name)
        tid(f'ing-{name}').first.click()
        if mode=='grams':
            r=pg.get_by_role('radio', name='Theo gam')
            if r.count(): r.click()
            tid('qty-grams').fill(str(qty))
        else:
            for _ in range(qty-1): tid('qty-count-plus').click()
        if i==0: shot('11-kho-them-do')
        tid('add-lot-submit').click()
        tid('sheet-add-lot').wait_for(state='detached')
        pg.wait_for_timeout(300)
    pg.get_by_text('10 lô, đồ cần dùng trước ở trên').wait_for()
    shot('12-kho')
    # tray
    pg.goto(BASE+'/mam'); tid('screen-tray').wait_for()
    tid('make-plan').wait_for(); shot('13-mam-ghep')
    tid('make-plan').click()
    tid('plan-view').wait_for(); shot('14-mam-com-hom-nay')
    # dish menu → swap; a slot may have no alternative (422 no_alternative), then try the next slot
    swapped=False
    for i,slot in enumerate(['rau','man','canh']):
        dish=tid(f'tray-dish-{slot}')
        if not dish.count(): continue
        before=dish.get_attribute('aria-label')
        dish.click(); tid('sheet-dish').wait_for()
        if i==0: shot('15-mon-trong-mam')
        tid('dish-swap').click()
        if i==0: shot('16-doi-mon-ly-do')
        tid('swap-khong_hop_gu').click()
        try:
            tid('sheet-dish').wait_for(state='detached', timeout=20000)
            print('SWAP', before, '->', tid(f'tray-dish-{slot}').get_attribute('aria-label')); swapped=True; break
        except Exception:
            print('SWAP no alternative for', slot); shot(f'16b-doi-mon-khong-con-mon-{slot}')
            pg.get_by_label('Đóng').last.click(); tid('sheet-dish').wait_for(state='detached')
    assert swapped, 'no slot could be swapped'
    shot('17-mam-sau-doi')
    # Thiếu gì
    tid('tray-dish-canh').click() if tid('tray-dish-canh').count() else tid('tray-dish-man').click()
    tid('dish-missing').click(); pg.wait_for_timeout(1500); shot('18-thieu-gi')
    pg.get_by_role('button', name='Xem công thức').count()
    pg.get_by_label('Đóng').last.click()
    # recipe detail
    tid('tray-dish-man').click(); pg.get_by_role('button', name='Xem công thức').click()
    tid('screen-recipe').wait_for(); shot('19-cong-thuc')
    pg.go_back(); tid('plan-view').wait_for()
    # cook
    tid('start-cooking').click()
    tid('screen-cooking').wait_for(); shot('20-nau-ca-mam')
    tid('cook-step-done').click(); pg.wait_for_timeout(300)
    tid('cook-finish').click()
    tid('screen-finish').wait_for()
    pg.get_by_role('radio', name='Hợp gu').first.click()
    shot('21-nau-xong-cham')
    tid('finish-submit').click()
    tid('screen-finished').wait_for(timeout=20000); shot('22-da-tru-kho')
    tid('undo').click(); shot('23-hoan-tac-xac-nhan')
    tid('undo-confirm').click()
    pg.wait_for_url('**/mam'); tid('plan-view').last.wait_for(); pg.wait_for_timeout(800); shot('24-mam-sau-hoan-tac')
    # other screens
    pg.goto(BASE+'/kho'); tid('screen-pantry').wait_for(); pg.wait_for_timeout(500); shot('25-kho-sau-hoan-tac')
    pg.goto(BASE+'/di-cho'); tid('screen-shopping').wait_for(); shot('26-di-cho')
    # cook the tray again and keep it, so the journal has a day with data
    pg.goto(BASE+'/mam'); tid('start-cooking').click(); tid('screen-cooking').wait_for()
    tid('cook-finish').click(); tid('finish-submit').click(); tid('screen-finished').wait_for(timeout=20000)
    pg.goto(BASE+'/nhat-ky'); tid('screen-journal').wait_for(); pg.wait_for_timeout(800); shot('27-nhat-ky')
    pg.goto(BASE+'/'); tid('screen-home').wait_for(); pg.wait_for_timeout(800); shot('28-trang-chu')
    pg.goto(BASE+'/cai-dat'); tid('screen-settings').wait_for(); shot('29-cai-dat')
    tid('settings-consent').click(); pg.wait_for_timeout(800); shot('30-cai-dat-dong-y')
    pg.goto(BASE+'/quet?mode=fridge'); tid('screen-scan').wait_for(); shot('31-quet')
    pg.goto(BASE+'/khao-sat'); tid('screen-survey-start').wait_for(); shot('32-khao-sat')
    tid('survey-consent').click(); tid('survey-start').click()
    tid('screen-survey-closed').wait_for(); shot('33-khao-sat-chua-mo')
    b.close()
try:
    run()
except Exception as e:
    print('FAILED', str(e)[:800]); getattr(__import__('builtins'),'_fail',lambda:None)()
finally:
    print('ERRORS', len(errors)); [print(' ', e) for e in errors[:30]]
    print('EMAIL', EMAIL)
