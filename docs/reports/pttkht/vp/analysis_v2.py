"""Additional native analysis and design views, executed inside gen_tastoria.py."""
package('pCLV2','Phân tích trách nhiệm theo use case')
# A compact collaboration view per goal; these are conceptual BCE classes, not claims about Python classes.
views=[
 ('CL09','UC09–10 Hồ sơ và đồng ý','Màn hình hồ sơ','Điều phối hồ sơ', [('Hồ sơ',['mụcTiêu:Năng lượng']),('Đồng ý',['mụcĐích:Chuỗi','hiệuLực:Boolean']),('Dị ứng',['nhóm:Định danh'])]),
 ('CL13','UC13 Xác nhận kết quả quét','Màn hình kết quả quét','Xác nhận nhập kho',[('Lần quét',['trạngThái:Trạng thái']),('Kết quả nguyên liệu',['lượng:Khoảng gam']),('Lô nguyên liệu',['ngàyNhập:Thời điểm'])]),
 ('CL15','UC15 Đề xuất mâm cơm','Màn hình chọn mâm','Điều phối ghép mâm',[('Hồ sơ ràng buộc',['sốNgười:Số nguyên']),('Tồn kho',['lượngCòn:Khoảng gam']),('Mâm đề xuất',['điểmXếpHạng:Số thực'])]),
 ('CL20','UC20 Hoàn tất nấu','Màn hình hoàn tất','Xử lý hoàn tất',[('Phiên nấu',['trạngThái:Trạng thái']),('Giao dịch kho',['lượngTrừ:Khoảng gam']),('Mâm cơm',['trạngThái:Trạng thái'])]),
 ('CL30','UC30 Triển khai mô hình','Lệnh triển khai','Điều phối triển khai',[('Phiên bản mô hình',['mãBăm:Chuỗi']),('Kết quả kiểm định',['đạt:Boolean']),('Bản triển khai',['đangHoạtĐộng:Boolean'])])]
for code,title,boundary,control,entities in views:
 cls(code+'b',boundary,st='boundary');cls(code+'c',control,st='control')
 for i,(name,attrs) in enumerate(entities):cls(code+'e'+str(i),name,attrs,st='entity')
 s.dep(code+'bc',code+'b',code+'c',stereo='use')
 for i in range(3):s.dep(code+'ce'+str(i),code+'c',code+'e'+str(i),stereo='use')
 diagram(code,'CLASS',code+' '+title)
 s.show(code+'b',40,230);s.show(code+'c',470,230)
 for i in range(3):s.show(code+'e'+str(i),1000,30+i*230)
 s.conn(code+'bc')
 for i in range(3):s.conn(code+'ce'+str(i),[s.R(code+'c',(i+1)/4),s.L(code+'e'+str(i))])
 finish()
 for key in [code+'b',code+'c']+[code+'e'+str(i) for i in range(3)]:
  s.emit('SCALL',code,key,'setDisplayAsRobustnessAnalysisIcon','b:false')

package('pDSV2','Thiết kế module quét và ghép mâm')
for code,title,modules in [
 ('DS02','UC13 Thiết kế xác nhận quét',[
 ('scan.router',['confirm():ScanConfirmResult']),('scan.service',['confirm():ScanConfirmResult']),
 ('pantry.service',['apply_scan():ScanApplyResult']),('Scan',['status:scan_status_t'])]),
 ('DS03','UC15 Thiết kế tạo mâm',[
 ('meal.router',['create_plan():JSONResponse']),('meal.service',['create_plan():Created']),
 ('meal.composer',['compose():List[Tray]']),('meal.schedule',['solve():Schedule'])])]:
 for i,(name,members) in enumerate(modules):
  cls(code+str(i),name,attrs=members if i==3 and code=='DS02' else [],ops=[] if i==3 and code=='DS02' else members,st='ORM entity' if i==3 and code=='DS02' else 'module')
 for i,j in [(0,1),(1,2),(1,3)]:s.dep(code+str(i)+str(j),code+str(i),code+str(j),stereo='use')
 diagram(code,'CLASS',code+' '+title)
 for i,(x,y) in enumerate([(30,30),(30,280),(650,280),(30,550)]):s.show(code+str(i),x,y)
 for i,j in [(0,1),(1,2),(1,3)]:s.conn(code+str(i)+str(j))
 finish()

package('pSQV2','Xác nhận quét và nhất quán kho')
q=Seq(s);q.diag('SQ03','SEQ','SQ03 Xác nhận quét – ghi kho một lần')
q.setup('cq',[('cqA','boundary','App',80,120,None),('cqR','control','scan.router',380,180,None),('cqS','control','scan.service',750,180,None),('cqD','entity','PostgreSQL',1150,180,None)],30,980)
for i,(a,b,label,kind) in enumerate([
 ('cqA','cqR','POST /scans/{id}/confirm','call'),('cqR','cqS','confirm(session, user, id, body)','call'),
 ('cqS','cqD','khóa lần quét; kiểm tra sở hữu','call'),('cqD','cqS','done + các mục chưa xóa','return'),
 ('cqS','cqD','kiểm tra lượng; ghi lô qua pantry','call'),('cqS','cqD','scan.status = confirmed','call'),
 ('cqS','cqR','ScanConfirmResult','return'),('cqR','cqD','COMMIT qua UnitOfWork','call'),('cqR','cqA','200 + các mã lô','return')]):q.msg('cqm'+str(i),a,b,label,150+i*85,kind)
q.act('cqR',150,850);q.act('cqS',235,660);q.draw();finish()
