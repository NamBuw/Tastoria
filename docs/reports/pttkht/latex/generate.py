"""Convert the edited Markdown sources to independently buildable LaTeX documents."""
from pathlib import Path
import re,shutil,subprocess,html
import markdown
from bs4 import BeautifulSoup,NavigableString
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'latex'
STEMS=['Bao-cao-Tastoria','Phu-luc-A-Use-Cases','Phu-luc-B-Co-so-du-lieu','Ma-tran-truy-vet']
SYMBOLS={'→':r'\ensuremath{\rightarrow}','←':r'\ensuremath{\leftarrow}','↔':r'\ensuremath{\leftrightarrow}','≤':r'\ensuremath{\leq}','≥':r'\ensuremath{\geq}','≠':r'\ensuremath{\neq}','×':r'\ensuremath{\times}','−':'-','–':'--','—':'---','…':r'\ldots{}','«':r'\guillemotleft{}','»':r'\guillemotright{}','“':'``','”':"''",'‘':'`','’':"'",'≥':r'\ensuremath{\geq}','∈':r'\ensuremath{\in}','∞':r'\ensuremath{\infty}','≈':r'\ensuremath{\approx}','∅':r'\ensuremath{\emptyset}','✓':'[OK]','Δ':r'\ensuremath{\Delta}','°':r'\ensuremath{^\circ}','₂':r'\textsubscript{2}','₉':r'\textsubscript{9}'}
SYMBOLS.update({'β':r'\ensuremath{\beta}','δ':r'\ensuremath{\delta}','Σ':r'\ensuremath{\Sigma}','²':r'\textsuperscript{2}','§':r'\S{}'})
ESC={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','$':r'\$','&':r'\&','#':r'\#','%':r'\%','_':r'\_','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
def esc(s):
 s=re.sub(r'([A-Za-z0-9]{22,})',lambda m:'§BREAK§'.join(m[0][i:i+12] for i in range(0,len(m[0]),12)),s)
 out=''.join(SYMBOLS.get(c,ESC.get(c,c))+(r'\allowbreak{}' if c in '/_-|' else '') for c in s)
 return out.replace(r'\S{}BREAK\S{}',r'\allowbreak{}')
def inline(el):
 if isinstance(el,NavigableString):return esc(str(el))
 inner=''.join(inline(x) for x in el.children)
 if el.name in ['strong','b']:return r'\textbf{'+inner+'}'
 if el.name in ['em','i']:return r'\emph{'+inner+'}'
 if el.name=='code':
  # Break identifiers at separators, preserving their exact visible characters.
  inner=inner.replace(r'\_',r'\_\allowbreak{}').replace('/',r'/\allowbreak{}').replace('.',r'.\allowbreak{}')
  return r'{\small\texttt{'+inner+'}}'
 if el.name=='a' and el.get('href','').startswith('http'):return r'\href{'+el['href'].replace('%',r'\%')+'}{'+inner+'}'
 if el.name=='br':return r'\newline{}'
 return inner

def asset(im):
 src=ROOT/im['src'];is_ui='/ui/' in im['src'];key=re.match(r'[A-Z]+\d+',src.stem)
 name=key[0] if not is_ui and key else 'ui-'+re.sub('[^a-zA-Z0-9-]','-',src.stem)
 if not is_ui:
  target=OUT/'assets'/(name+'.pdf');svg=ROOT/'fig/svg'/(src.stem+'.svg')
  if not target.exists() or target.stat().st_mtime<svg.stat().st_mtime:subprocess.run(['rsvg-convert','-f','pdf','-o',str(target),str(svg)],check=True)
 else:
  target=OUT/'assets'/(name+'.png');shutil.copy2(src,target)
 w,h=Image.open(src).size
 return 'assets/'+target.name,w/h,is_ui

def stripnum(t):return re.sub(r'^\d+(?:\.[\da-z]+)*\.\s*','',t)

def convert(stem):
 md=(ROOT/(stem+'.md')).read_text();md=re.sub(r'!\[([^]]*)\]\(([^)]+)\)',lambda m:f'![{m[1]}](<{m[2]}>)',md)
 soup=BeautifulSoup(markdown.markdown(md,extensions=['tables','fenced_code']),'html.parser')
 main=stem==STEMS[0];dest=OUT/stem;dest.mkdir(exist_ok=True)
 figures=0;tables=0;last='Thông tin tổng hợp';chunks=[];current=[];cover=[];in_cover=main
 def render(el):
  nonlocal figures,tables,last
  if not getattr(el,'name',None):return ''
  name=el.name
  if name in ['h1','h2','h3','h4']:
   title=el.get_text(' ',strip=True);last=title
   if name=='h1':
    if main and not re.match(r'^\d+\.',title):return r'\chapter*{'+esc(title)+'}\n'+r'\addcontentsline{toc}{chapter}{'+esc(title)+'}\n'
    return r'\chapter{'+esc(stripnum(title) if main else title)+'}\n'
   command={'h2':'section','h3':'subsection','h4':'subsubsection'}[name]
   return '\\'+command+'{'+esc(stripnum(title))+'}\n'
  if name=='table':
   tables+=1;rows=el.find_all('tr');n=max(len(row.find_all(['th','td'])) for row in rows)
   width=(16-(n-1)*.3)/n
   widths=[1.2,1.0,1.1,6.0,5.5] if stem=='Ma-tran-truy-vet' else [width]*n
   specs='@{}'+'@{\\hspace{3mm}}'.join('L{'+f'{v:.3f}'+'cm}' for v in widths)+'@{}'
   header=' & '.join(r'\textbf{'+inline(c)+'}' for c in rows[0].find_all(['th','td']))+r' \\'
   lines=[r'{\footnotesize\setlength{\tabcolsep}{0pt}',r'\begin{longtable}{'+specs+'}',r'\caption{'+esc(stripnum(last))+r'}\\',r'\toprule',header,r'\midrule\endfirsthead',r'\multicolumn{'+str(n)+r'}{l}{\small\itshape Bảng \thetable{} (tiếp theo)}\\',r'\toprule',header,r'\midrule\endhead',r'\bottomrule\endfoot']
   for row in rows[1:]:lines.append(' & '.join(inline(c) for c in row.find_all(['th','td']))+r' \\ \addlinespace[3pt]')
   return '\n'.join(lines)+ '\n'+r'\end{longtable}}'+'\n'
  if el.find('img'):
   result=[]
   for im in el.find_all('img'):
    figures+=1;path,ratio,ui=asset(im);caption=esc(im.get('alt',''));wide=ratio>1.25 and not ui
    if wide:result.append(r'\clearpage\begin{landscape}')
    result.append(r'\begin{figure}[H]\centering')
    result.append(r'\includegraphics[width='+('0.96\\linewidth' if not ui else '0.85\\linewidth')+',height='+('0.75\\textheight' if not wide else '0.78\\textwidth')+r',keepaspectratio]{'+path+'}')
    result.append(r'\caption{'+caption+r'}\label{fig:'+stem+':'+str(figures)+'}')
    result.append(r'\end{figure}')
    if wide:result.append(r'\end{landscape}\clearpage')
   return '\n'.join(result)+'\n'
  if name in ['ul','ol']:
   env='itemize' if name=='ul' else 'enumerate';lines=['\\begin{'+env+'}']
   for li in el.find_all('li',recursive=False):
    body=''.join(render(c) if getattr(c,'name',None) in ['ul','ol'] else inline(c) for c in li.children)
    lines.append((r'\item \raggedright ' if li.find('code') and li.get_text()==li.code.get_text() else r'\item ')+body)
   lines.append('\\end{'+env+'}');return '\n'.join(lines)+'\n'
  if name=='pre':
   # SQL uses ASCII except comments; regular escaped text supports Vietnamese safely.
   return r'\begin{quote}\scriptsize\ttfamily\raggedright'+'\n'+r'\newline{}'.join(esc(line).replace(' ',r'\ ') for line in el.get_text().splitlines())+'\n'+r'\end{quote}'+'\n'
  return inline(el)+'\n\n'
 for el in soup.children:
  if main and getattr(el,'name',None)=='h1' and el.get_text()!='BÁO CÁO BÀI TẬP NHÓM':in_cover=False
  if in_cover:cover.append(el);continue
  if getattr(el,'name',None)=='h1' and current:chunks.append(current);current=[]
  current.append(render(el))
 if current:chunks.append(current)
 includes=[]
 for i,chunk in enumerate(chunks):
  filename=f'chapter-{i:02d}.tex';(dest/filename).write_text(''.join(chunk));includes.append(r'\input{'+stem+'/'+filename+'}')
 if main:
  front=r'''\begin{titlepage}
\centering
{\Large\bfseries BÁO CÁO BÀI TẬP NHÓM\par}\vspace{1cm}
{\LARGE\bfseries TASTORIA\par}\vspace{0.4cm}
{\large\bfseries HỖ TRỢ LÊN MÂM CƠM VIỆT\par TỪ NGUYÊN LIỆU SẴN CÓ\par}\vspace{0.5cm}
\textit{Taste and write your story}\par\vspace{0.8cm}
Học phần: [Điền tên học phần]\par
Giảng viên: [Điền họ tên]\par
Lớp / nhóm: [Điền thông tin]\par
Ngày đối chiếu: 31/10/2026\par\vspace{0.8cm}
{\small\setlength{\tabcolsep}{4pt}\renewcommand{\arraystretch}{1.5}
\begin{tabularx}{\textwidth}{|L{0.8cm}|L{2.4cm}|X|X|L{1.8cm}|}\hline
\textbf{STT}&\textbf{Họ và tên}&\textbf{Phần việc chung}&\textbf{Phần việc cá nhân}&\textbf{Ước tính đóng góp}\\\hline
1&[Điền]&[Điền theo thực tế]&[Điền theo thực tế]&[Điền]\\\hline
2&[Điền]&[Điền theo thực tế]&[Điền theo thực tế]&[Điền]\\\hline
3&[Điền]&[Điền theo thực tế]&[Điền theo thực tế]&[Điền]\\\hline
\ldots&[Thêm/bớt dòng]&&&\\\hline
&\textbf{Tổng}&&&\textbf{100\%}\\\hline
\end{tabularx}}\par\vspace{0.5cm}
\begin{minipage}{\textwidth}\small
\textbf{Ghi chú:} Nhóm thống nhất phần việc và tỷ lệ theo đóng góp thực tế. Bảng phân công chỉ đặt tại trang đầu; nội dung báo cáo tổ chức theo các pha phát triển hệ thống.
\end{minipage}
\vfill
{Tháng 10 năm 2026}
\end{titlepage}
'''

  if not (dest/'cover.tex').exists():(dest/'cover.tex').write_text(front)
  start=r'\input{'+stem+'/cover.tex}\n'
 else:start=r'\begin{titlepage}\centering\vspace*{3cm}{\LARGE\bfseries '+esc(soup.find('h1').get_text())+r'\par}\vspace{1cm}{\Large TASTORIA}\vfill Bản biên tập ngày 31/10/2026\end{titlepage}'+'\n'
 tex=r'\documentclass[12pt,a4paper,oneside]{report}'+'\n'+r'\input{preamble}'+'\n'+r'\begin{document}'+'\n'+start+r'\pagenumbering{roman}\tableofcontents\listoffigures\listoftables\clearpage\pagenumbering{arabic}'+'\n'+'\n'.join(includes)+'\n'+r'\end{document}'+'\n'
 (OUT/(stem+'.tex')).write_text(tex)
 print(stem,len(chunks),'parts',figures,'figures',tables,'tables')
for stem in STEMS:convert(stem)
