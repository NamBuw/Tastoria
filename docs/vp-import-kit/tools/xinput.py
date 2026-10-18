import sys,time
from Xlib import X, display, XK
from Xlib.ext import xtest
d=display.Display(':77')
def click(x,y,btn=1,n=1):
    xtest.fake_input(d,X.MotionNotify,x=x,y=y); d.sync(); time.sleep(0.15)
    for _ in range(n):
        xtest.fake_input(d,X.ButtonPress,btn); d.sync(); time.sleep(0.05)
        xtest.fake_input(d,X.ButtonRelease,btn); d.sync(); time.sleep(0.08)
def key(name,mods=()):
    codes=[d.keysym_to_keycode(XK.string_to_keysym({'ctrl':'Control_L','shift':'Shift_L','alt':'Alt_L'}.get(m,m))) for m in mods]
    for c in codes: xtest.fake_input(d,X.KeyPress,c)
    k=d.keysym_to_keycode(XK.string_to_keysym(name))
    xtest.fake_input(d,X.KeyPress,k); xtest.fake_input(d,X.KeyRelease,k)
    for c in reversed(codes): xtest.fake_input(d,X.KeyRelease,c)
    d.sync(); time.sleep(0.05)
SPECIAL={'/':'slash','.':'period','-':'minus','_':'underscore',' ':'space',':':'colon'}
def typ(s):
    for ch in s:
        if ch in SPECIAL: nm=SPECIAL[ch]
        else: nm=ch
        ks=XK.string_to_keysym(nm)
        kc=d.keysym_to_keycode(ks)
        shift = ch.isupper() or ch in '_:'
        if shift: xtest.fake_input(d,X.KeyPress,d.keysym_to_keycode(XK.string_to_keysym('Shift_L')))
        xtest.fake_input(d,X.KeyPress,kc); xtest.fake_input(d,X.KeyRelease,kc)
        if shift: xtest.fake_input(d,X.KeyRelease,d.keysym_to_keycode(XK.string_to_keysym('Shift_L')))
        d.sync(); time.sleep(0.02)
a=sys.argv[1:]
while a:
    c=a.pop(0)
    if c=='click': click(int(a.pop(0)),int(a.pop(0)))
    elif c=='dclick': click(int(a.pop(0)),int(a.pop(0)),n=2)
    elif c=='rclick': click(int(a.pop(0)),int(a.pop(0)),btn=3)
    elif c=='key': k=a.pop(0).split('+'); key(k[-1],k[:-1])
    elif c=='type': typ(a.pop(0))
    elif c=='sleep': time.sleep(float(a.pop(0)))
