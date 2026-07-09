"""
=============================================================================
app/services/reimbursement_pdf.py — 企业级报销单 PDF 渲染
=============================================================================
生成结构化、细颗粒度的中文报销单 PDF：
  - 公司抬头 + 单据标题
  - 基本信息（申请人/部门/单号/日期/出差目的地与天数）
  - 费用汇总（总额 / 需票金额 / 补贴金额）
  - 按【费用大类】分组：每类小计 + 逐条明细（单价×数量、发票号/凭证形式）
  - 审批流转记录 + 签字区
支持自动分页。
=============================================================================
"""
from __future__ import annotations

import os
import tempfile
from datetime import date


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]

STATUS_CN = {
    "draft": "草稿", "pending": "待审批", "approved": "已通过",
    "rejected": "已驳回", "returned": "已退回", "paid": "已付款", "cancelled": "已撤销",
}
ACTION_CN = {"approve": "通过", "reject": "驳回", "return": "退回",
             "pending": "待审批", "cancelled": "已撤销"}


def _register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    body = "Helvetica"
    for fp in _FONT_CANDIDATES:
        if os.path.exists(fp):
            try:
                fn = os.path.splitext(os.path.basename(fp))[0].replace(" ", "").replace("-", "")
                pdfmetrics.registerFont(TTFont(fn, fp))
                return fn
            except Exception:
                continue
    return body


def render_reimbursement_pdf(data: dict) -> str:
    """根据结构化报销单数据渲染 PDF，返回临时文件路径。"""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    font = _register_font()
    reimb_id = data.get("id", "unknown")
    path = tempfile.mktemp(suffix=f"_reimb_{reimb_id}.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    margin = 15 * mm
    today = date.today().isoformat()

    state = {"y": H - margin}

    def new_page():
        c.showPage()
        state["y"] = H - margin

    def ensure(space_mm):
        if state["y"] - space_mm * mm < margin + 10 * mm:
            new_page()

    def text(x, s, size=10, f=None, color=(0, 0, 0)):
        c.setFont(f or font, size)
        c.setFillColorRGB(*color)
        c.drawString(x, state["y"], s)

    def money(v):
        return f"¥{float(v or 0):,.2f}"

    # ---- 抬头 ----
    c.setFont(font, 20)
    c.drawCentredString(W / 2, state["y"] - 6 * mm, "中国石油华东分公司")
    c.setFont(font, 14)
    c.drawCentredString(W / 2, state["y"] - 14 * mm, "费 用 报 销 单")
    state["y"] -= 22 * mm
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1)
    c.line(margin, state["y"], W - margin, state["y"])
    state["y"] -= 8 * mm

    # ---- 基本信息（两列）----
    left_x = margin
    right_x = W / 2 + 5 * mm
    rows = [
        (f"报销单号：{reimb_id}", f"日期：{today}"),
        (f"申请人：{data.get('user_name','')}", f"部门：{data.get('department','')}"),
        (f"标题：{data.get('title','') or '—'}", f"状态：{STATUS_CN.get(data.get('status',''), data.get('status',''))}"),
    ]
    if data.get("trip_destination") or data.get("trip_days"):
        trip = data.get("trip_destination", "") or "—"
        span = ""
        if data.get("trip_start_date"):
            span = f"{data.get('trip_start_date','')} ~ {data.get('trip_end_date','')}"
        days = data.get("trip_days")
        rows.append((f"出差目的地：{trip}", f"出差日期：{span}（{days}天）" if days else f"出差日期：{span}"))
    for l, r in rows:
        text(left_x, l, 10)
        text(right_x, r, 10)
        state["y"] -= 7 * mm

    # ---- 费用汇总 ----
    state["y"] -= 2 * mm
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.4)
    c.line(margin, state["y"], W - margin, state["y"])
    state["y"] -= 7 * mm
    text(left_x, f"报销总额：{money(data.get('total_amount'))}", 11, color=(0.75, 0.15, 0.15))
    text(right_x, f"其中 需票：{money(data.get('invoice_amount'))}   补贴：{money(data.get('subsidy_amount'))}", 10)
    state["y"] -= 9 * mm

    # ---- 分类明细 ----
    col = {
        "seq": left_x,
        "name": left_x + 12 * mm,
        "detail": left_x + 48 * mm,
        "qty": left_x + 110 * mm,
        "amount": left_x + 138 * mm,
        "evid": left_x + 162 * mm,
    }
    table_right = W - margin

    def draw_header():
        c.setFillColorRGB(0.93, 0.93, 0.93)
        c.rect(left_x, state["y"] - 6 * mm, table_right - left_x, 6 * mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font, 8.5)
        c.drawString(col["seq"] + 1 * mm, state["y"] - 4.3 * mm, "#")
        c.drawString(col["name"] + 1 * mm, state["y"] - 4.3 * mm, "项目")
        c.drawString(col["detail"] + 1 * mm, state["y"] - 4.3 * mm, "说明")
        c.drawString(col["qty"] + 1 * mm, state["y"] - 4.3 * mm, "单价×数量")
        c.drawString(col["amount"] + 1 * mm, state["y"] - 4.3 * mm, "金额")
        c.drawString(col["evid"] + 1 * mm, state["y"] - 4.3 * mm, "凭证")
        state["y"] -= 6 * mm

    categories = data.get("categories", [])
    if not categories:
        text(left_x, "（无费用明细）", 10, color=(0.5, 0.5, 0.5))
        state["y"] -= 8 * mm

    for cat in categories:
        ensure(20)
        # 大类标题 + 小计
        text(left_x, f"【{cat.get('category_label','')}】", 11, color=(0.1, 0.3, 0.6))
        c.setFont(font, 10)
        c.drawRightString(table_right, state["y"], f"小计：{money(cat.get('subtotal'))}")
        state["y"] -= 7 * mm
        draw_header()

        for it in cat.get("items", []):
            ensure(14)
            c.setFont(font, 8.5)
            c.setFillColorRGB(0, 0, 0)
            # 单价×数量
            if it.get("unit_price"):
                qd = f"{money(it['unit_price'])}×{it.get('quantity','')}{it.get('unit','')}"
            else:
                qd = f"{it.get('quantity','')}{it.get('unit','')}".strip() or "—"
            desc = it.get("description", "")
            if it.get("from_location") and it.get("to_location"):
                desc = f"{desc} {it['from_location']}→{it['to_location']}".strip()
            if it.get("occur_date"):
                desc = f"{desc} ({it['occur_date']})".strip()
            evid = "补贴免票" if it.get("is_subsidy") else ("已附票" if it.get("has_invoice") else ("需补票" if it.get("needs_invoice") else "免票"))
            c.drawString(col["seq"] + 1 * mm, state["y"] - 4 * mm, str(it.get("seq", "")))
            c.drawString(col["name"] + 1 * mm, state["y"] - 4 * mm, str(it.get("subtype_label", ""))[:10])
            c.drawString(col["detail"] + 1 * mm, state["y"] - 4 * mm, str(desc)[:26])
            c.drawString(col["qty"] + 1 * mm, state["y"] - 4 * mm, qd[:16])
            c.drawString(col["amount"] + 1 * mm, state["y"] - 4 * mm, money(it.get("amount")))
            c.drawString(col["evid"] + 1 * mm, state["y"] - 4 * mm, evid)
            # 底线
            c.setStrokeColorRGB(0.85, 0.85, 0.85)
            c.setLineWidth(0.3)
            c.line(left_x, state["y"] - 5.5 * mm, table_right, state["y"] - 5.5 * mm)
            state["y"] -= 5.5 * mm

            # 发票明细（缩进小字）
            for inv in it.get("invoices", []):
                ensure(6)
                c.setFont(font, 7.5)
                c.setFillColorRGB(0.45, 0.45, 0.45)
                info = f"    发票: {inv.get('invoice_number','') or inv.get('invoice_code','')}"
                if inv.get("seller_name"):
                    info += f" | {inv['seller_name'][:14]}"
                if inv.get("invoice_date"):
                    info += f" | {inv['invoice_date']}"
                info += f" | {money(inv.get('amount'))}"
                c.drawString(col["detail"] + 1 * mm, state["y"] - 3.5 * mm, info[:60])
                state["y"] -= 4.5 * mm
        state["y"] -= 4 * mm

    # ---- 审批记录 ----
    ensure(30)
    state["y"] -= 2 * mm
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.4)
    c.line(margin, state["y"], W - margin, state["y"])
    state["y"] -= 7 * mm
    text(left_x, "审批流转：", 10)
    state["y"] -= 6 * mm
    approvals = data.get("approvals", [])
    if approvals:
        c.setFont(font, 9)
        for ap in approvals:
            ensure(6)
            line = f"  {ap.get('step','')}. {ap.get('approver','')} — {ACTION_CN.get(ap.get('action',''), ap.get('action',''))}"
            if ap.get("comment"):
                line += f"（{str(ap['comment'])[:24]}）"
            c.setFillColorRGB(0, 0, 0)
            c.drawString(left_x, state["y"], line)
            state["y"] -= 5.5 * mm
    else:
        text(left_x + 2 * mm, "暂无审批记录", 9, color=(0.5, 0.5, 0.5))
        state["y"] -= 5.5 * mm

    # ---- 签字区 ----
    ensure(20)
    state["y"] -= 6 * mm
    c.setFont(font, 9)
    for label, x in [("申请人：", left_x), ("部门经理：", left_x + 55 * mm), ("财务审核：", left_x + 110 * mm)]:
        c.drawString(x, state["y"], label)
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.setLineWidth(0.4)
        c.line(x + 18 * mm, state["y"] - 1 * mm, x + 45 * mm, state["y"] - 1 * mm)

    # ---- 页脚 ----
    c.setFont(font, 7.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(margin, margin - 2 * mm, f"系统生成 · {today}")
    c.drawRightString(W - margin, margin - 2 * mm, f"编号: {reimb_id}")

    c.save()
    return path
