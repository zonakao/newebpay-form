"""藍新金流申請表產生伺服器  —  python3 server.py"""
import base64, io, os
from datetime import datetime
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from reportlab.pdfgen import canvas as rlcanvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import PIL.Image, urllib.request, json

# ── Google Drive 上傳
_DRIVE_FOLDER_ID = '1l3dUlU_QIi0xWAC1GlzHl9e5GukUivia'
_drive_service = None
def _get_drive():
    global _drive_service
    if _drive_service:
        return _drive_service
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        # 優先用環境變數（Render 部署），fallback 用本地檔案
        creds_json = os.environ.get('GDRIVE_CREDENTIALS_JSON')
        if creds_json:
            import json as _json
            info = _json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/drive'])
        else:
            creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gdrive_credentials.json')
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=['https://www.googleapis.com/auth/drive'])
        _drive_service = build('drive', 'v3', credentials=creds)
    except Exception:
        pass
    return _drive_service

def upload_to_drive(pdf_bytes, filename):
    svc = _get_drive()
    if not svc:
        return
    try:
        from googleapiclient.http import MediaIoBaseUpload
        buf = io.BytesIO(pdf_bytes)
        meta = {'name': filename, 'parents': [_DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(buf, mimetype='application/pdf')
        svc.files().create(body=meta, media_body=media).execute()
    except Exception:
        pass

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ── 中文字體（macOS 優先，Linux 用 Noto Sans CJK）
_font_loaded = False
for _p in ['/System/Library/Fonts/PingFang.ttc',
           '/System/Library/Fonts/STHeiti Medium.ttc',
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
           os.path.join(os.path.dirname(__file__), 'NotoSansCJK-Regular.ttc')]:
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont('CJK',  _p, subfontIndex=0))
            pdfmetrics.registerFont(TTFont('CJKb', _p, subfontIndex=0))
            _font_loaded = True
            break
        except Exception:
            pass
if not _font_loaded:
    _font_path = os.path.join(os.path.dirname(__file__), 'NotoSansCJK.otf')
    pdfmetrics.registerFont(TTFont('CJK',  _font_path, subfontIndex=0))
    pdfmetrics.registerFont(TTFont('CJKb', _font_path, subfontIndex=0))

F, FB = 'CJK', 'CJKb'

# ════════════════════════════════════════════════════════════════════════
# Canvas helpers
# ════════════════════════════════════════════════════════════════════════
def p(x): return x * mm          # mm → pt

W, H = A4   # 595.28 × 841.89

# Form border (10 mm margins)
FL = p(10); FR = p(200); FT = p(287); FB_ = p(10)

def _txt(c, s, x, y, size=7, bold=False, align='left', color=(0,0,0)):
    c.setFont(FB if bold else F, size)
    c.setFillColorRGB(*color)
    if align == 'center':
        c.drawCentredString(p(x), p(y), str(s))
    elif align == 'right':
        c.drawRightString(p(x), p(y), str(s))
    else:
        c.drawString(p(x), p(y), str(s))

def hline(c, x1, y, x2, w=0.4):
    c.setLineWidth(w); c.setStrokeColorRGB(0,0,0)
    c.line(p(x1), p(y), p(x2), p(y))

def vline(c, x, y1, y2, w=0.4):
    c.setLineWidth(w); c.setStrokeColorRGB(0,0,0)
    c.line(p(x), p(y1), p(x), p(y2))

def rect(c, x, y, w2, h2, fill=None, stroke=True):
    if fill:
        c.setFillColorRGB(*fill)
        c.rect(p(x), p(y), p(w2), p(h2), fill=1, stroke=0)
    if stroke:
        c.setStrokeColorRGB(0,0,0); c.setLineWidth(0.4)
        c.rect(p(x), p(y), p(w2), p(h2), fill=0, stroke=1)

def cell(c, x, y, w2, h2, label='', val='', lsize=6.5, vsize=8,
         bold_val=False, fill=None, align='left', valign='bottom'):
    rect(c, x, y, w2, h2, fill=fill)
    ty = y + (h2 * 0.45 if valign == 'mid' else h2 * 0.28)
    if label:
        _txt(c, label, x + 1, ty + (h2*0.38 if val else 0), size=lsize,
             color=(.33,.33,.33))
    if val:
        _txt(c, val, x + 1, ty, size=vsize, bold=bold_val, align=align)

def section_hdr(c, x, y, w2, h2, txt, fill=(.93,.93,.93)):
    rect(c, x, y, w2, h2, fill=fill)
    _txt(c, txt, x + w2/2, y + h2*0.32, size=7.5, bold=True, align='center')

# Load static company stamp
_STATIC_STAMP = None
_stamp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '發票章.png')
if os.path.exists(_stamp_path):
    with open(_stamp_path, 'rb') as _f:
        _STATIC_STAMP = _f.read()

# ════════════════════════════════════════════════════════════════════════
# Build PDF
# ════════════════════════════════════════════════════════════════════════
def build_pdf(data, sig_bytes, stamp_bytes):
    buf = io.BytesIO()
    c = rlcanvas.Canvas(buf, pagesize=A4)
    c.setTitle('藍新金流合作推廣商商店商業條件申請表')

    date_str = data.get('fillDate','')
    try:
        d = datetime.strptime(date_str,'%Y-%m-%d')
        yr, mo, dy = str(d.year), str(d.month), str(d.day)
    except Exception:
        yr = mo = dy = ''

    mt   = data.get('memberType','企業')
    atype= data.get('applyType','新會員新增商店')
    cr   = data.get('creditRate','2.8')
    pd_  = data.get('payoutDays','10')
    desc = data.get('productDesc','')

    # ── Page outer border
    c.setLineWidth(0.8); c.setStrokeColorRGB(0,0,0)
    c.rect(p(10), p(10), p(190), p(277), fill=0, stroke=1)

    # ════════════ HEADER ════════════════════════════════════════════════
    # header box top=287, height=18mm → bottom at 269
    HT, HH = 287, 18
    rect(c, 10, HT-HH, 190, HH)

    _txt(c, '藍新科技股份有限公司', 105, HT-5.5, size=10.5, bold=True, align='center')
    _txt(c, '藍新金流服務平台', 105, HT-10, size=9, align='center')
    _txt(c, '合作推廣商商店商業條件申請表', 105, HT-15, size=9, bold=True, align='center')

    # 填寫日期 (right side of header area, outside main table)
    _txt(c, '填寫日期：', 140, HT-HH+3.5, size=7, color=(.33,.33,.33))
    _txt(c, yr, 162, HT-HH+3.5, size=7.5, bold=True)
    _txt(c, '年', 170, HT-HH+3.5, size=7, color=(.33,.33,.33))
    _txt(c, mo, 177, HT-HH+3.5, size=7.5, bold=True)
    _txt(c, '月', 183, HT-HH+3.5, size=7, color=(.33,.33,.33))
    _txt(c, dy, 189, HT-HH+3.5, size=7.5, bold=True)
    _txt(c, '日', 196, HT-HH+3.5, size=7, color=(.33,.33,.33))

    # ════════════ ROW: 推廣商 ══════════════════════════════════════════
    R = HT - HH  # current y (bottom of previous row)
    RH = 7       # row height mm

    R -= RH
    # cols: [推廣商會員編號 label 27mm | value 78mm | 推廣商名稱 label 22mm | value 63mm]
    x0=10; x1=37; x2=115; x3=137; x4=200
    hline(c, 10, R, 200)
    vline(c, x1, R, R+RH); vline(c, x2, R, R+RH); vline(c, x3, R, R+RH)
    _txt(c, '推廣商會員編號', x0+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('promoterId',''), x1+1, R+2, size=7.5, bold=True)
    _txt(c, '推廣商名稱', x2+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('promoterName',''), x3+1, R+2, size=7.5, bold=True)

    # ════════════ ROW: 申請人 ══════════════════════════════════════════
    R -= RH
    hline(c, 10, R, 200)
    # cols: [姓名 label 22 | value 48 | 電話 label 18 | value 40 | 郵件 label 22 | value]
    ax = [10, 32, 80, 98, 138, 160, 200]
    for x in ax[1:-1]: vline(c, x, R, R+RH)
    _txt(c, '申請人姓名', ax[0]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('applicantName',''), ax[1]+1, R+2, size=7.5, bold=True)
    _txt(c, '申請人電話', ax[2]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('applicantPhone',''), ax[3]+1, R+2, size=7.5, bold=True)
    _txt(c, '申請人電子郵件', ax[4]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('applicantEmail',''), ax[5]+1, R+2, size=7.5, bold=True)

    # ════════════ SECTION: 推廣用戶資料 ══════════════════════════════
    R -= 5.5
    hline(c, 10, R, 200)
    rect(c, 10, R, 190, 5.5, fill=(.92,.92,.92))
    _txt(c, '推廣用戶資料', 105, R+1.5, size=7.5, bold=True, align='center')

    # ════════════ ROW: 會員類型 + 申請項目 ══════════════════════════
    RH2 = 6.5
    R -= RH2
    hline(c, 10, R, 200)
    # 會員類型: [label 18 | 個人 10 | V 7 | 企業 10 | 申請項目 label 18 | 新增 32 | 加開 36 | 異動]
    tx=[10,28,38,45,55,73,105,141,200]
    for x in tx[1:-1]: vline(c, x, R, R+RH2)
    _txt(c, '會員類型', tx[0]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, '個人', tx[1]+1, R+2, size=7)
    _txt(c, 'Ｖ' if mt=='個人' else ' ', tx[2]+1, R+2, size=8, bold=True)
    _txt(c, '企業', tx[3]+1, R+2, size=7)
    _txt(c, '申請項目', tx[4]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, 'Ｖ' if atype=='新會員新增商店' else ' ', tx[5]+0.5, R+2, size=8, bold=True)
    _txt(c, '新會員新增商店', tx[5]+3.5, R+2, size=6.5)
    _txt(c, 'Ｖ' if atype=='既有會員加開商店' else ' ', tx[6]+0.5, R+2, size=8, bold=True)
    _txt(c, '既有會員加開商店', tx[6]+3.5, R+2, size=6.5)
    _txt(c, 'Ｖ' if atype=='異動商業條件' else ' ', tx[7]+0.5, R+2, size=8, bold=True)
    _txt(c, '異動商業條件', tx[7]+3.5, R+2, size=6.5)

    # ════════════ ROW: 會員編號 ══════════════════════════════════════
    R -= RH2
    hline(c, 10, R, 200)
    vline(c, 28, R, R+RH2); vline(c, 100, R, R+RH2); vline(c, 118, R, R+RH2)
    _txt(c, '會員編號', 11, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('memberId',''), 29, R+2, size=7.5, bold=True)
    _txt(c, '會員名稱', 101, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('memberName',''), 119, R+2, size=7.5, bold=True)

    # ════════════ ROW: 商店代號 ══════════════════════════════════════
    R -= RH2
    hline(c, 10, R, 200)
    vline(c, 28, R, R+RH2); vline(c, 100, R, R+RH2); vline(c, 118, R, R+RH2)
    _txt(c, '商店代號', 11, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('storeId',''), 29, R+2, size=7.5, bold=True)
    _txt(c, '商店名稱', 101, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, data.get('storeName',''), 119, R+2, size=7.5, bold=True)

    # ════════════ ROW: 商店類型 ══════════════════════════════════════
    R -= RH2
    hline(c, 10, R, 200)
    sx=[10,28,35,60,87,107,125,200]
    for x in sx[1:-1]: vline(c, x, R+0.3, R+RH2)
    _txt(c, '商店類型', sx[0]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, 'Ｖ', sx[1]+0.5, R+2, size=8, bold=True)
    _txt(c, '網路商店', sx[2]+1, R+2, size=7)
    _txt(c, '實體商店(無刷卡機)', sx[3]+1, R+2, size=7)
    _txt(c, 'ezAIO卡機商店', sx[4]+1, R+2, size=7)
    _txt(c, '販售商品說明', sx[5]+1, R+2, size=6.5, color=(.33,.33,.33))
    _txt(c, desc, sx[6]+1, R+2, size=7.5, bold=True)

    # ════════════ RATE TABLE ════════════════════════════════════════
    # Columns x positions (mm from left):
    # [支付方式|期別|sys_val|sys_%|sys_unit|T+_txt|days|天|app_val|app_%|app_unit|T+|days|天|同意事項]
    # widths: 26, 8, 12, 6, 4, 5, 5, 4, 12, 6, 4, 5, 5, 4, 84  → sum=190 ✓
    # widths: [支付方式|期別|sys_val|sys_%|sys_unit|T+|days|天|app_val|app_%|app_unit|aT+|adays|a天|同意事項]
    RX = [10]
    for w in [26, 7, 18, 8, 5, 5, 5, 4, 18, 8, 5, 5, 5, 4, 62]:
        RX.append(RX[-1]+w)
    # RX[0..15]

    # Rate table header row (single row, 6 sections)
    RH_HDR = 5
    R -= RH_HDR
    RT_TOP = R + RH_HDR  # top of rate table
    hline(c, 10, R, 200)
    hline(c, 10, R+RH_HDR, 200)
    rect(c, 10, R, 190, RH_HDR, fill=(.88,.88,.88), stroke=False)
    # Cover artifacts from 商店類型 vlines inside this header
    c.setFillColorRGB(.88,.88,.88)
    c.rect(p(59.5), p(R), p(1.0), p(RH_HDR), fill=1, stroke=0)  # x=60 (系統預設值)
    c.rect(p(106.5), p(R), p(1.0), p(RH_HDR), fill=1, stroke=0) # x=107 (申請設定條件)
    c.setFillColorRGB(0,0,0)
    # Only 5 dividers creating 6 main sections (no sub-column dividers)
    vline(c, 10, R, R+RH_HDR)
    vline(c, 200, R, R+RH_HDR)
    for rx in [RX[2], RX[4], RX[8], RX[10], RX[14]]: vline(c, rx, R, R+RH_HDR)
    _txt(c, '支付方式',      (RX[0]+RX[2])/2,     R+1.5, size=7, bold=True, align='center')
    _txt(c, '系統預設值',    (RX[2]+RX[4])/2,     R+1.5, size=7, bold=True, align='center')
    _txt(c, '撥款天期',      (RX[4]+RX[8])/2,     R+1.5, size=6.5, bold=True, align='center')
    _txt(c, '申請設定條件',  (RX[8]+RX[10])/2,    R+1.5, size=7, bold=True, align='center')
    _txt(c, '撥款天期',      (RX[10]+RX[14])/2,   R+1.5, size=6.5, bold=True, align='center')
    _txt(c, '同意事項（請勾選「我同意」）', (RX[14]+200)/2, R+1.5, size=6.5, bold=True, align='center')

    # ── Rate rows data ──────────────────────────────────────────────
    RH_R = 3.8   # height per rate row

    def draw_rate_row(row_y, label, period, sv, smod, sunit, tplus, days, tunit,
                      av='', amod='', aunit='', atplus='', adays='', atunit='',
                      label_span=1, first_of_span=True, agree_text=''):
        # For mid-span rows, only draw hline from col1 onward (not crossing label cell)
        if first_of_span:
            hline(c, 10, row_y, 200)
        else:
            hline(c, RX[1], row_y, 200)
        # Main section dividers always drawn; sub-col dividers only when ATM-style sub-units exist
        main_vlines = [RX[1], RX[2], RX[4], RX[8], RX[9], RX[10], RX[14]]
        sub_vlines = [RX[5], RX[11]] if sunit or aunit else []
        for rx in main_vlines + sub_vlines: vline(c, rx, row_y-RH_R, row_y)
        cy = row_y - 2.5
        if first_of_span and label:
            # Center label vertically in span.
            # row_y = bottom of first span row; each additional row extends downward by RH_R.
            # span top = row_y+RH_R, span bottom = row_y-(label_span-1)*RH_R
            # mathematical center = row_y + RH_R*(1 - label_span/2)
            label_lines = label.split('\n') if '\n' in label else [label]
            n = len(label_lines)
            ls = 3.6  # line spacing mm
            if label_span == 1:
                span_center = cy
            else:
                span_center = row_y + RH_R * (1 - label_span / 2)
            atm_down = 1.0 if (label_span > 1 and sunit) else 0
            for li, ll in enumerate(label_lines):
                offset = ((n - 1) / 2 - li) * ls
                text_y = span_center + offset - (0 if label_span == 1 else 1.1) - atm_down
                _txt(c, ll, RX[0]+1, text_y, size=6.5)
        if period: _txt(c, period, (RX[1]+RX[2])/2-2, cy, size=6.5)
        if sv:     _txt(c, str(sv), RX[2]+0.5, cy, size=5 if len(str(sv))>7 else (6 if len(str(sv))>5 else 7))
        if smod:
            if str(smod).startswith('單筆'):
                smod_x = RX[3]-10.5
            elif str(smod).startswith('元/次'):
                smod_x = RX[3]-13.5
            else:
                smod_x = RX[3]+0.5
            _txt(c, smod, smod_x, cy, size=5 if len(str(smod))>5 else 6.5)
        if sunit:  _txt(c, sunit, RX[4]+0.3, cy, size=6)
        if tplus:
            tplus_x = RX[5]+0.3-13 if str(tplus) == '非3D' else RX[5]+0.3
            _txt(c, tplus, tplus_x, cy, size=4.5 if len(str(tplus))>4 else 6.5)
        if days:   _txt(c, str(days), RX[6]+1, cy, size=7)
        if tunit:
            tunit_x = RX[7]+0.5-13 if str(tunit) == '強制3D' else RX[7]+0.5
            _txt(c, tunit, tunit_x, cy, size=6.5)
        if av:     _txt(c, str(av), RX[8]+1, cy, size=7, bold=True)
        if amod:
            amod_x = RX[9]-10.5 if str(amod).startswith('單筆') else RX[9]+0.5
            _txt(c, amod, amod_x, cy, size=5 if len(str(amod))>5 else 6.5)
        if aunit:  _txt(c, aunit, RX[10]+0.3, cy, size=6)
        if atplus:
            atplus_x = RX[11]+0.3-13 if str(atplus) == '非3D' else RX[11]+0.3
            _txt(c, atplus, atplus_x, cy, size=4.5 if len(str(atplus))>4 else 6.5)
        if adays:  _txt(c, str(adays), RX[12]+1, cy, size=7, bold=True)
        if atunit:
            atunit_x = RX[13]+0.5-13 if str(atunit) == '強制3D' else RX[13]+0.5
            _txt(c, atunit, atunit_x, cy, size=6.5)
        return row_y - RH_R

    # Agreement text (placed at start, spans all rows → drawn after all rows)
    AGREE_TOP = R  # top of first data row (will be set below)

    rows_def = [
        # (label, period, sv, smod, sunit, T+, days, tunit,  av,   amod,  aunit, aT, adays, atunit, span, first_span)
        ('信用卡一次付清','', 2.8,'%','','T+',10,'天',  cr, '%','','T+', pd_,'天', 1, True),
        ('信用卡\n分期',  '3期', 3,'%','','','','',   '','%','','','','',  6, True),
        ('',             '6期', 3.5,'%','','','','',  '','%','','','','',  6, False),
        ('',             '12期',7,'%','','','','',   '','%','','','','',  6, False),
        ('',             '18期',9,'%','','T+',10,'天','','%','','','','',  6, False),
        ('',             '24期',12,'%','','','','',  '','%','','','','',  6, False),
        ('',             '30期',15,'%','','','','',  '','%','','','','',  6, False),
        ('國外卡',       '', 3.5,'%','','','','',     '','%','','','','',  1, True),
        ('銀聯卡',       '', 2.8,'%','','','','',     '','%','','','','',  1, True),
        ('DCC',          '', 2.8,'%','','','','',     '','%','','','','',  1, True),
        ('AFTEE一般支付','', 2.6,'%','','T+',10,'天','','%','','T+','','天', 1, True),
        ('AFTEE\n分期',  '3期', 3.6,'%','','','','',  '','%','','','','',  8, True),
        ('',             '6期', 4.7,'%','','','','',  '','%','','','','',  8, False),
        ('',             '9期', 5.7,'%','','','','',  '','%','','','','',  8, False),
        ('',             '12期',7.3,'%','','','','',  '','%','','','','',  8, False),
        ('',             '15期',8.3,'%','','','','',  '','%','','','','',  8, False),
        ('',             '18期',9.4,'%','','','','',  '','%','','','','',  8, False),
        ('',             '21期', 11,'%','','','','',  '','%','','','','',  8, False),
        ('',             '24期',12.6,'%','','','','', '','%','','','','',  8, False),
        # WebATM (2 sub-rows)
        ('WebATM',       '', 1,'%上限','元','T+',7,'天','','%上限','元','T+','','天', 2, True),
        ('',             '', '','單筆固定','元','','','',  '','單筆固定','元','','','', 2, False),
        # ATM轉帳 (2 sub-rows)
        ('ATM轉帳',      '', 1,'%上限','元','T+',7,'天','','%上限','元','T+','','天', 2, True),
        ('',             '', '','單筆固定','元','','','',  '','單筆固定','元','','','', 2, False),
        # 智慧ATM 2.0 (3 sub-rows)
        ('智慧\nATM 2.0','', 1,'%最低','元','T+',7,'天','','%最低','元','T+','','天', 3, True),
        ('',             '', '','單筆上限','元','','','',    '','單筆上限','元','','','', 3, False),
        ('',             '', '','單筆固定','元','','','',  '','單筆固定','元','','','', 3, False),
        # others
        ('條碼繳費',     '', 20,'元/筆','','T+',10,'天','','元/筆','','T+','','天', 1, True),
        ('超商代碼繳費', '', 28,'元/筆','','T+',10,'天','','元/筆','','T+','','天', 1, True),
        ('大宗寄倉取貨付款','',1,'%','元','T+',10,'天','','%','元','T+','','天', 1, True),
        ('大宗寄倉物流費用','',55,'元','','','','',      '','元','','','','', 1, True),
        ('支付寶',       '', 3.2,'%','','T+',10,'天',    '','%','','T+','','天', 1, True),
        ('玉山wallet',   '', 2.8,'%','','T+',10,'天',    '','%','','T+','','天', 1, True),
        ('台灣Pay(玉山)','',1.5,'%','','T+',7,'天',    '','%','','T+','','天', 1, True),
        ('AIO-Line Pay','','3(不含稅)','%','','依支付機構而定','','','','%','','依支付機構而定','','', 1, True),
        ('AIO-LINE Pay Money','','3(不含稅)','%','','','','',  '','%','','','','', 1, True),
        ('信用卡收款額度', '', '個人20、企業60','萬元','','','','',  '','萬元','','','','', 1, True),
        ('提領手續費',   '', 10,'元/次·每月免費','','5','次','',  '','元/次','','每月免費','','次', 1, True),
        ('3D機制',       '', '3D','','','非3D','','強制3D','3D','','','非3D','','強制3D', 1, True),
        ('單筆交易金額上限','','','無設定','','','','','','無設定','設定','','','元', 1, True),
    ]

    AGREE_TOP = R  # will be current R before first data row
    agree_start_y = None

    for i, rd in enumerate(rows_def):
        (label,period,sv,smod,sunit,tplus,days,tunit,
         av,amod,aunit,atplus,adays,atunit,span,first) = rd
        if agree_start_y is None:
            agree_start_y = R
        R = draw_rate_row(R, label, period, sv, smod, sunit, tplus, days, tunit,
                          av, amod, aunit, atplus, adays, atunit, span, first)

    RATE_BOTTOM = R   # bottom of last rate row
    hline(c, 10, RATE_BOTTOM, 200)

    # ── Agreement text (drawn in the 同意事項 column spanning all data rows)
    agree_h = agree_start_y - RATE_BOTTOM
    # Draw agree column background
    c.saveState()
    c.setFillColorRGB(.98,.98,.95)
    c.rect(p(RX[14]), p(RATE_BOTTOM), p(200-RX[14]), p(agree_h), fill=1, stroke=0)
    c.restoreState()
    # Re-draw borders
    vline(c, RX[14], RATE_BOTTOM, agree_start_y)
    vline(c, 200, RATE_BOTTOM, agree_start_y)

    agree_y = agree_start_y - 2
    agree_lines1 = [
        'Ｖ 本申請人（即代表推廣商）同意下列事項：',
        '●推廣商代為勾選同意即代表本案會員已再次',
        '  審閱、瞭解及同意藍新科技股份有限公司揭',
        '  露之「藍新金流服務平台服務條款」與相關',
        '  管理規範 ( 請參考：https://www.newebpay.',
        '  com/website/Page/content/new_service_',
        '  policy )，如未來會員因使用本平台服務產',
        '  生任何爭議，推廣商願共同處理並負相關法',
        '  律責任。',
        '',
        '●收款商店接受信用卡付款時，需配合本平台',
        '  依商品銷售類別要求啟用信用卡3D驗證機',
        '  制，如收款商店不使用信用卡3D驗證機制，',
        '  應自行承擔付款方因使用信用卡付款而衍生',
        '  之所有爭議款項。',
    ]
    for line in agree_lines1:
        if agree_y < RATE_BOTTOM + 1: break
        _txt(c, line, RX[14]+1, agree_y, size=5.8)
        agree_y -= 3.2

    # ════════════ NOTES + SIGNATURE ════════════════════════════════
    # 重要提醒與簽章 header
    NOTES_TOP = RATE_BOTTOM
    NH = 5
    NOTES_TOP -= NH
    hline(c, 10, NOTES_TOP, 200)
    rect(c, 10, NOTES_TOP, 190, NH, fill=(.92,.92,.92))
    _txt(c, '重要提醒與簽章', 105, NOTES_TOP+1.5, size=7.5, bold=True, align='center')

    # Notes area: left ~55% for text, right ~45% for signature
    # Left: notes 1-5 stacked
    # Right: 申請人親簽處 top half, 蓋章處 bottom half
    NOTES_Y = NOTES_TOP  # current y bottom of header

    # We need enough room for signature: 30mm
    SIG_H = 30
    NOTE_AREA_H = NOTES_Y - p(10)/mm  # remaining mm to bottom margin

    # Notes text
    notes = [
        ('1.', '實際設定生效日以本公司實際流程作業完成日為準。'),
        ('2.', '本申請表送件需申請人親簽及蓋公司大小章（或發票章），\n'
               '如未勾選下方同意事項或未配合簽章者恕不受理。'),
        ('3.', '本申請表所蒐集之個人資料，將依個人資料保護法及相關\n'
               '法令之規定，只就其特定目的，做為承辦所提供服務之用，\n'
               '不會任意對其他第三者揭露。'),
        ('4.', '本申請表填妥後，請利用拍照或掃描方式將申請表影像檔\n'
               '回傳予負責商務同仁，或回傳至專用信箱：\n'
               'cs@newebpay.com，亦可傳真至 02-2786-3306'),
        ('5.', '本公司保留最終准駁權利。'),
    ]

    ny = NOTES_Y - 4
    for num, text in notes:
        _txt(c, num, 11, ny, size=7, bold=(num=='2.'))
        for i, line in enumerate(text.split('\n')):
            _txt(c, line, 15, ny - i*3.8, size=7, bold=(num=='2.' and i==0))
        lines_count = len(text.split('\n'))
        ny -= lines_count * 3.8 + 2
        if ny < p(10)/mm + SIG_H + 2:
            break

    # Vertical divider between notes and signature area
    SIG_X = 105  # signature area starts here
    SIG_Y_TOP = NOTES_Y
    SIG_Y_BOT = p(10) / mm + 0.5  # 10mm from bottom
    vline(c, SIG_X, SIG_Y_BOT, SIG_Y_TOP, w=0.4)
    hline(c, SIG_X, SIG_Y_BOT + SIG_H, 200)  # divider between two sig boxes

    def draw_img_in_box(img_bytes, x_mm, y_mm, max_w_mm, max_h_mm, transparent=False):
        """Draw PIL image centered in box using canvas.drawImage."""
        try:
            pil = PIL.Image.open(io.BytesIO(img_bytes)).convert('RGBA')
            if not transparent:
                bg = PIL.Image.new('RGBA', pil.size, (255,255,255,255))
                bg.paste(pil, mask=pil.split()[3])
                pil = bg.convert('RGB')
            sb = io.BytesIO()
            pil.save(sb, 'PNG')
            sb.seek(0)
            pw, ph = pil.size
            avail_w, avail_h = p(max_w_mm), p(max_h_mm)
            scale = min(avail_w/pw, avail_h/ph)
            iw, ih = pw*scale, ph*scale
            ox = p(x_mm) + (avail_w - iw)/2
            oy = p(y_mm) + (avail_h - ih)/2
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(sb), ox, oy, width=iw, height=ih,
                        mask='auto' if transparent else None)
        except Exception:
            pass

    # 申請人親簽處 (top sig box: from SIG_Y_BOT+SIG_H to SIG_Y_TOP)
    sig_box_top = SIG_Y_TOP; sig_box_bot = SIG_Y_BOT + SIG_H
    _txt(c, '申請人親簽處：', SIG_X+2, sig_box_top-3.5, size=6.5, color=(.33,.33,.33))
    if sig_bytes:
        draw_img_in_box(sig_bytes, SIG_X+2, sig_box_bot+1,
                        200-SIG_X-4, sig_box_top-sig_box_bot-5, transparent=True)

    # 蓋章處 (bottom sig box: from SIG_Y_BOT to SIG_Y_BOT+SIG_H)
    _txt(c, '蓋章處：', SIG_X+2, sig_box_bot-3.5, size=6.5, color=(.33,.33,.33))
    _stamp = stamp_bytes or _STATIC_STAMP
    if _stamp:
        draw_img_in_box(_stamp, SIG_X+2, SIG_Y_BOT+1,
                        200-SIG_X-4, SIG_H-5, transparent=False)

    c.save()
    buf.seek(0)
    return buf.read()


# ── Routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        payload = request.get_json()
        data = payload.get('data', {})
        sig_bytes   = base64.b64decode(payload['sigImage'].split(',')[-1])   if payload.get('sigImage')   else None
        stamp_bytes = base64.b64decode(payload['stampImage'].split(',')[-1]) if payload.get('stampImage') else None
        pdf_bytes = build_pdf(data, sig_bytes, stamp_bytes)
        member = data.get('memberName') or data.get('memberId') or '申請'
        date   = data.get('fillDate','').replace('-','')
        filename = f'藍新申請表_{member}_{date}.pdf'
        upload_to_drive(pdf_bytes, filename)
        buf = io.BytesIO(pdf_bytes)
        return send_file(buf, as_attachment=True,
                         download_name=filename,
                         mimetype='application/pdf')
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/send-slack', methods=['POST'])
def send_slack():
    payload = request.get_json()
    webhook = payload.get('webhook')
    body    = payload.get('body')
    if not webhook or not body:
        return jsonify({'error': 'missing params'}), 400
    try:
        req = urllib.request.Request(webhook,
              data=json.dumps(body).encode(),
              headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=8) as resp:
            return jsonify({'ok': True, 'status': resp.status})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8899))
    host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
    print(f'✅  http://{host}:{port}')
    app.run(host=host, port=port, debug=False)
