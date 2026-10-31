"""Native VP models via the newer DesignV2 generator and pttkht.uml Open API plugin."""
from pathlib import Path
from spec_lib import Spec, FONT, FP
from gen_beh import Act, Seq, B
ROOT=Path(__file__).resolve().parent
s=Spec();s.no_relax=True;s.emit('NEWPROJECT');s.emit('FONTSIZE',FONT);s.emit('CPTCENTER',1);s.emit('EXTDIR',3,2)

def package(k,n):s.pkg(k,n);s.usepkg(k)
def diagram(k,typ,title):s.diag(k,typ,title)
def cls(k,n,attrs=(),ops=(),st=None):s.cls(k,n,attrs,ops,stereo=st)
def finish():
 # A native VP note below the content leaves clear space for the CE watermark.
 if s.geo:
  bottom=max(y+h for x,y,w,h in s.geo.values())
  key='foot'+s.cur_diag;s.note(key,'Tastoria | '+s.cur_diag)
  s.show(key,20,bottom+65,300,40,final=True)
 s.flush()

def uc_view(code,title,actor,items):
 package('p'+code,title);s.actor('a'+code,actor)
 for key,name in items:s.uc(key,name,eps=['Đổi món', 'Thay nguyên liệu'] if key=='uc15' else None)
 diagram(code,'UC',code+' '+title);s.system('sys'+code,'Tastoria',230,20,650,len(items)*180+55)
 s.show_actor('a'+code,50,len(items)*90-10)
 for i,(key,name) in enumerate(items):
  s.show_uc(key,340,65+i*180,parent='sys'+code,w=370)
  rel='r'+code+str(i);s.link(rel,'a'+code,key);s.conn(rel,[s.R('a'+code),s.L(key)])
 finish()
uc_view('UC00','Use case tổng quát – người nấu','Người dùng',[
 ('uc10','UC10 Cập nhật hồ sơ và dị ứng'),('uc12','UC12 Quét nguyên liệu'),('uc14','UC14 Quản lý kho theo lô'),('uc15','UC15 Nhận mâm cơm hôm nay'),('uc19','UC19 Lập lịch và bắt đầu nấu'),('uc20','UC20 Xác nhận nấu xong'),('uc22','UC22 Xem nhật ký'),('uc05','UC05 Quản lý đồng ý')])
uc_view('UC01','Use case công khai và tài khoản','Khách',[
 ('uc01','UC01 Đăng ký tài khoản'),('uc02','UC02 Đăng nhập'),('uc04','UC04 Đặt lại mật khẩu'),('uc23','UC23 Tham gia khảo sát gu')])
package('pUC02','Phân rã use case');s.uc('uc13','UC13 Xác nhận kết quả quét');s.uc('uc16','UC16 Đổi một món');s.uc('uc17','UC17 Chọn thay thế nguyên liệu')
# Existing UC15 is intentionally reused: one model element, multiple diagram views.
s.extd('ext16','uc16','uc15','Đổi món','Người dùng yêu cầu đổi món');s.extd('ext17','uc17','uc15','Thay nguyên liệu','Người dùng chọn thay thế hợp lệ')
diagram('UC02','UC','UC02 Quét và mở rộng gợi ý mâm');s.system('sys02','Tastoria',20,20,1080,540)
for k,x,y in [('uc12',80,80),('uc13',650,80),('uc15',80,320),('uc16',650,250),('uc17',650,420)]:s.show_uc(k,x,y,w=320,parent='sys02')
s.conn('ext16',[s.L('uc16'),s.R('uc15',.3)]);s.conn('ext17',[s.L('uc17'),s.R('uc15',.75)]);finish()

uc_view('UC03','Các chức năng bổ sung của người dùng','Người dùng',[
 ('uc03','UC03 Đăng xuất'),('uc06','UC06 Tải dữ liệu cá nhân'),('uc07','UC07 Xóa tài khoản'),('uc08','UC08 Yêu cầu về xử lý dữ liệu'),('uc09','UC09 Thiết lập hồ sơ'),('uc11','UC11 Đặt mục tiêu năng lượng'),('uc18','UC18 Quản lý danh sách đi chợ'),('uc21','UC21 Hoàn tác trừ kho')])
# Each operational actor is a role outside the application boundary; no invented admin UI.
for code,title,actor,items in [
 ('UC04','Biên soạn dữ liệu','Người biên soạn', [('uc25','UC25 Nhập kho công thức'),('uc26','UC26 Quản lý cặp thay thế')]),
 ('UC05','Vận hành mô hình và khảo sát','Người vận hành mô hình',[('uc24','UC24 Quản lý đợt khảo sát'),('uc28','UC28 Xuất dữ liệu huấn luyện'),('uc29','UC29 Kiểm định phiên bản mô hình'),('uc30','UC30 Triển khai và quay lui')]),
 ('UC06','Quản trị quyền dữ liệu','Quản trị viên',[('uc27','UC27 Xử lý yêu cầu dữ liệu')]),
 ('UC07','Gán nhãn dữ liệu','Người gán nhãn',[('uc31','UC31 Gán nhãn ảnh góp')]),
 ('UC08','Tác vụ theo lịch','Bộ lập lịch',[('uc32','UC32 Xóa ảnh quét quá hạn'),('uc33','UC33 Sao lưu dữ liệu'),('uc34','UC34 Dọn job và khóa hết hạn')])]:uc_view(code,title,actor,items)

# Package views share canonical UC elements. Read metadata, never copy old diagram geometry.
import yaml
meta=yaml.safe_load((ROOT.parents[2]/'Tastoria/docs/sad/model.yaml').read_text())
# Resolve explicit repository path; report lives inside PTTKHT/Tastoria.
for pk in meta['packages']:
 items=[u for u in meta['use_cases'] if u['pkg']==pk['id']]
 code='PK'+pk['id'][2:].zfill(2);package('view'+code,pk['name'])
 roles=sorted({u['primary'] for u in items}|{a for u in items for a in u.get('secondary',[])})
 actor_names={a['id']:a['name'] for a in meta['actors']}
 for aid in roles:s.actor(code+aid,actor_names[aid])
 diagram(code,'UC',code+' '+pk['name']);s.system('sys'+code,'Tastoria / '+pk['name'],260,20,740,len(items)*160+90)
 for i,aid in enumerate(roles):s.show_actor(code+aid,30,90+i*max(180,len(items)*150//len(roles)))
 for i,u in enumerate(items):
  key=u['id'].lower();s.show_uc(key,350,65+i*160,w=500,parent='sys'+code)
  for j,aid in enumerate([u['primary']]+u.get('secondary',[])):
   r=code+u['id']+aid;s.link(r,code+aid,key);s.conn(r,[s.R(code+aid),s.L(key)])
 finish()

package('pDM','Mô hình miền – phân tích')
for k,n,a in [('nguoi','Người dùng',['mãNgườiDùng:Định danh']),('lo','Lô nguyên liệu',['ngàyNhập:Ngày','lượngMin:Gam','lượngMax:Gam']),('nl','Nguyên liệu',['tên:Tên nguyên liệu']),('gd','Giao dịch kho',['thayĐổiMin:Gam','thayĐổiMax:Gam','lýDo:Loại giao dịch']),('mam','Mâm cơm',['sốNgười:Số nguyên','trạngThái:Trạng thái mâm']),('mm','Món trong mâm',['hệSốKhẩuPhần:Số thực']),('mon','Công thức món',['tên:Tên món','khẩuPhầnGốc:Số nguyên']),('tp','Thành phần công thức',['lượng:Gam']),('phien','Phiên nấu',['giờDọn:Thời điểm','trạngThái:Trạng thái phiên'])]:cls(k,n,a)
rels=[('d1','nguoi','lo','1','0..*',None),('d2','nl','lo','1','0..*',None),('d3','lo','gd','1','0..*',None),('d4','nguoi','mam','1','0..*',None),('d5','mam','mm','1','2..3','composite'),('d6','mon','mm','1','0..*',None),('d7','mon','tp','1','1..*','composite'),('d8','nl','tp','1','0..*',None),('d9','mam','phien','1','0..*',None)]
for k,a,b,ma,mb,agg in rels:s.assoc(k,a,b,ma=ma,mb=mb,agg_a=agg)
diagram('DM01','CLASS','DM01 Miền kho nguyên liệu')
for k,x,y in [('nguoi',30,30),('nl',650,30),('lo',340,280),('gd',340,550)]:s.show(k,x,y)
for k in ['d1','d2','d3']:s.conn(k)
finish();diagram('DM02','CLASS','DM02 Miền mâm cơm và phiên nấu')
for k,x,y in [('nguoi',30,30),('mam',30,260),('mm',470,260),('mon',900,260),('phien',30,540),('tp',900,540),('nl',470,540)]:s.show(k,x,y)
for k in ['d4','d5','d6','d7','d8','d9']:s.conn(k)
finish()

package('pAR','Thiết kế kiến trúc')
for k,n,st in [('ui','Expo Android / Web','presentation'),('api','FastAPI routers','controller'),('svc','Nghiệp vụ theo module','service'),('orm','SQLAlchemy + Unit of Work','persistence'),('db','PostgreSQL + pgvector','database'),('queue','Valkey / RQ','queue'),('worker','Worker / ONNX Runtime','worker'),('files','Tệp riêng + nginx','storage')]:cls(k,n,st=st)
for k,a,b in [('ar1','ui','api'),('ar2','api','svc'),('ar3','svc','orm'),('ar4','orm','db'),('ar5','svc','queue'),('ar6','worker','queue'),('ar7','worker','db'),('ar8','worker','files')]:s.dep(k,a,b,stereo='use')
diagram('AR01','CLASS','AR01 Các tầng và phụ thuộc triển khai')
for k,x,y in [('ui',30,30),('api',30,230),('svc',30,430),('orm',30,630),('db',30,830),('queue',650,430),('worker',650,630),('files',650,830)]:s.show(k,x,y)
for k in ['ar1','ar2','ar3','ar4','ar5','ar6','ar8']:s.conn(k)
s.conn('ar7',[s.L('worker'),FP((500,s.cy('worker'))),FP((500,s.cy('db'))),s.R('db')]);finish()

# Relational schema view: native UML classes stereotyped table, not falsely labelled a Chen ERD.
package('pDB','Cấu trúc bảng và khóa ngoại')
tables={
 'users':['id:uuid {PK}','email:text {UQ}'],
 'ingredients':['id:uuid {PK}','name_vi:text'],
 'pantry_lots':['id:uuid {PK}','user_id:uuid {FK}','ingredient_id:uuid {FK}','initial_g_min:numeric','initial_g_max:numeric','status:lot_status_t'],
 'pantry_transactions':['id:bigint {PK}','lot_id:uuid {FK}','delta_g_min:numeric','delta_g_max:numeric','reverses_id:bigint {FK UQ nullable}'],
 'recipes':['id:uuid {PK}','name_vi:text'],
 'recipe_ingredients':['recipe_id:uuid {PK FK}','ingredient_id:uuid {PK FK}','grams:numeric'],
 'meal_plans':['id:uuid {PK}','user_id:uuid {FK}','status:meal_plan_status_t'],
 'meal_plan_items':['id:uuid {PK}','meal_plan_id:uuid {FK}','recipe_id:uuid {FK}','servings_scale:numeric'],
 'cook_sessions':['id:uuid {PK}','meal_plan_id:uuid {FK}','status:cook_status_t','completed_at:timestamptz'],
 'scans':['id:uuid {PK}','user_id:uuid {FK}','status:scan_status_t'],
 'scan_images':['id:uuid {PK}','scan_id:uuid {FK}','storage_key:text'],
 'scan_items':['id:uuid {PK}','scan_id:uuid {FK}','ingredient_id:uuid {FK}']}
for t,a in tables.items():cls('t'+t,t,a,st='table')
fks=[('users','pantry_lots'),('ingredients','pantry_lots'),('pantry_lots','pantry_transactions'),('recipes','recipe_ingredients'),('ingredients','recipe_ingredients'),('users','meal_plans'),('meal_plans','meal_plan_items'),('recipes','meal_plan_items'),('meal_plans','cook_sessions'),('users','scans'),('scans','scan_images'),('scans','scan_items'),('ingredients','scan_items')]
for a,b in fks:s.assoc('fk'+a+b,'t'+a,'t'+b,ma='1',mb='0..*')
for code,title,pos,pairs in [
 ('DB01','Kho và lịch sử giao dịch',{'users':(30,30),'ingredients':(800,30),'pantry_lots':(420,290),'pantry_transactions':(420,650)},fks[:3]),
 ('DB02','Công thức, mâm và phiên nấu',{'users':(30,30),'meal_plans':(30,260),'cook_sessions':(30,560),'meal_plan_items':(490,260),'recipes':(970,260),'recipe_ingredients':(970,560),'ingredients':(490,560)},fks[3:9]),
 ('DB03','Quét ảnh và kết quả',{'users':(30,30),'scans':(30,260),'scan_images':(30,550),'scan_items':(650,260),'ingredients':(650,30)},fks[9:])]:
 diagram(code,'CLASS',code+' '+title)
 for t,(x,y) in pos.items():s.show('t'+t,x,y)
 for a,b in pairs:s.conn('fk'+a+b)
 finish()

package('pAD','Hoạt động nghiệp vụ')
def activity(code,title,steps):
 a=Act(s);a.diag(code,'ACT',code+' '+title);c=a.lanes(code+'sw',[(code+'u','Người dùng',460),(code+'h','Tastoria',600)],20,len(steps)*105+150)
 prev=code+'start';a.node(prev,'InitialNode',c[code+'u'],90,lane=code+'u')
 for i,(lane,name) in enumerate(steps):
  k=code+'n'+str(i);ln=code+lane;a.node(k,'ActivityAction',c[ln],190+i*105,name,lane=ln)
  a.f(code+'f'+str(i),prev,k,'v' if a.geo[prev][0]+a.geo[prev][2]/2==c[ln] else 'vh');prev=k
 end=code+'end';a.node(end,'ActivityFinalNode',c[code+steps[-1][0]],190+len(steps)*105,lane=code+steps[-1][0]);a.f(code+'last',prev,end);finish()
activity('AD01','Quét và xác nhận nguyên liệu', [('u','Chọn ảnh và chế độ quét'),('h','Kiểm tra ảnh, tạo yêu cầu quét'),('h','Nhận diện và tạo kết quả đề xuất'),('u','Sửa tên, số lượng và cách ghép lô'),('u','Xác nhận danh sách nguyên liệu'),('h','Ghi kho và xác nhận quét cùng giao dịch'),('h','Trả về kho đã cập nhật')])
activity('AD02','Nhận và sử dụng mâm cơm', [('u','Chọn số người, thời gian và dị ứng'),('h','Lọc món theo ràng buộc bắt buộc'),('h','Ghép mâm và kiểm tra tổng lượng kho'),('h','Tính lịch nấu, xếp hạng mâm hợp lệ'),('u','Xem lý do gợi ý và chấp nhận mâm'),('h','Tạo phiên nấu và lịch các bước'),('u','Nấu theo lịch, xác nhận hoàn thành'),('h','Trừ kho và ghi nhận kết quả')])

package('pEX','Luồng ngoại lệ')
a=Act(s);a.diag('AD03','ACT','AD03 Hoàn tác – quyết định nghiệp vụ')
a.node('exi','InitialNode',360,50)
a.node('ex1','ActivityAction',360,135,'Yêu cầu hoàn tác phiên đã hoàn tất')
a.node('ex2','ActivityAction',360,235,'Kiểm tra sở hữu và khóa phiên')
a.node('exd','DecisionNode',360,340)
a.node('exok','ActivityAction',360,465,'Ghi giao dịch đảo, cập nhật mâm và phiên')
a.node('exno','ActivityAction',940,340,'Từ chối: đã hết thời hạn')
a.node('exend1','ActivityFinalNode',360,575);a.node('exend2','ActivityFinalNode',940,465)
a.f('exf1','exi','ex1');a.f('exf2','ex1','ex2');a.f('exf3','ex2','exd')
a.f('exf4','exd','exok',guard='[trong 10 phút]',at=(380,380))
a.f('exf5','exd','exno','h',guard='[quá 10 phút]',at=(540,305))
a.f('exf6','exok','exend1');a.f('exf7','exno','exend2');finish()

package('pDS','Phân bổ trách nhiệm thiết kế')
for k,n,attrs,ops,st in [
 ('dsrouter','cooking.router',[],['complete_session():JSONResponse'],'module'),
 ('dsservice','cooking.service',[],['complete_session():CookCompletion','undo_session():CookSessionOut'],'module'),
 ('dspantry','pantry.service',[],['deduct():DeductionResult'],'module'),
 ('dsuow','UnitOfWork',['session:Session'],['after_commit(fn:Callable)'],'class'),
 ('dsentity','CookSession',['id:UUID','status:cook_status_t'],[],'ORM entity')]:cls(k,n,attrs,ops,st)
for k,a1,b1 in [('ds1','dsrouter','dsservice'),('ds2','dsrouter','dsuow'),('ds3','dsservice','dspantry'),('ds4','dsservice','dsentity')]:s.dep(k,a1,b1,stereo='use')
diagram('DS01','CLASS','DS01 Thiết kế chức năng hoàn tất nấu')
for k,x,y in [('dsrouter',30,30),('dsservice',30,300),('dspantry',650,300),('dsuow',650,30),('dsentity',30,580)]:s.show(k,x,y)
for k in ['ds1','ds2','ds3','ds4']:s.conn(k)
finish()

package('pSQ','Tương tác thiết kế')
q=Seq(s);q.diag('SQ01','SEQ','SQ01 Hoàn tất nấu – chống ghi lặp')
q.setup('sq', [('sqA','boundary','App',100,150,None),('sqR','control','cooking.router',440,200,None),('sqS','control','cooking.service',800,220,None),('sqD','entity','PostgreSQL',1200,180,None)],30,1000)
for i,(a,b,label,kind) in enumerate([
 ('sqA','sqR','POST complete + Idempotency-Key','call'),('sqR','sqD','begin: khóa và tra khóa yêu cầu','call'),('sqD','sqR','chưa có phản hồi đã lưu','return'),('sqR','sqS','complete_session(...)','call'),('sqS','sqD','khóa phiên, kiểm tra chủ sở hữu','call'),('sqD','sqS','phiên đang nấu','return'),('sqS','sqD','ghi giao dịch kho; cập nhật phiên, mâm','call'),('sqS','sqR','CookCompletion','return'),('sqR','sqD','lưu phản hồi lũy đẳng; COMMIT','call'),('sqR','sqA','200 + lượng trừ và hạn hoàn tác','return')]):q.msg('sqm'+str(i),a,b,label,140+i*75,kind)
q.act('sqR',140,850);q.act('sqS',365,665);q.draw();finish()

# Native sequence alt fragment rather than drawing dashed boxes as pictures.
q=Seq(s);q.diag('SQ02','SEQ','SQ02 Hoàn tác trong thời hạn')
q.setup('uq',[('uqA','boundary','App',100,150,None),('uqS','control','cooking.service',500,220,None),('uqD','entity','PostgreSQL',1000,180,None)],30,890)
for i,(a,b,label,y,kind) in enumerate([
 ('uqA','uqS','POST /cook-sessions/{id}/undo',130,'call'),('uqS','uqD','khóa phiên; đọc completed_at',210,'call'),('uqD','uqS','trạng thái và thời điểm máy chủ',270,'return'),('uqS','uqD','ghi giao dịch đảo; phiên reverted',400,'call'),('uqS','uqD','mâm accepted; COMMIT',480,'call'),('uqS','uqA','200 phiên đã hoàn tác',550,'return'),('uqS','uqA','409 undo_window_expired',720,'return')]):q.msg('uqm'+str(i),a,b,label,y,kind)
q.frag('uqalt','alt',30,320,1130,800,['uqA','uqS','uqD'],[('completed và còn trong 10 phút',320),('completed và đã quá 10 phút',630)])
q.act('uqS',130,760);q.draw();finish()
exec((ROOT/'analysis_v2.py').read_text())
s.emit('ELEMFONT',FONT)
for d in sorted({l.split('\t')[1] for l in s.lines if l.startswith('DIAG\t')}):s.emit('FIT',d)
s.emit('REPOINT');s.emit('SANITIZE','Tastoria – Phân tích và thiết kế','Nhóm Tastoria');s.emit('SAVEAS',str(ROOT/'Tastoria.vpp'));s.write(str(ROOT/'spec_tastoria.tsv'))
print('Wrote',len(s.lines),'commands')
