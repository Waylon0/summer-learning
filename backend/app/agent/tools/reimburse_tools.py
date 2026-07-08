"""
=============================================================================
app/agent/tools/reimburse_tools.py — Agent 工具集
=============================================================================
Agent 的"工具箱"，每个函数代表一项能力：

  1. ocr_recognize_invoice     — 识别发票上的文字信息（DeepSeek Vision）
  2. compliance_check          — 检查报销金额是否在公司标准内
  3. budget_check              — 查询部门预算，判断是否超标
  4. generate_reimbursement_pdf — 用 reportlab 生成真实 PDF 报销单
  5. send_approval_email       — 发送审批邮件
  6. save_reimbursement_to_db  — 报销单持久化到数据库
  7. query_reimbursement_status — 从数据库查询报销进度

所有涉及 I/O 的函数均为 async，由 LangGraph 异步节点直接 await。
=============================================================================
"""
import base64
import json
import os
import uuid
from decimal import Decimal
from io import BytesIO
from loguru import logger
from app.core.config import get_settings
from app.core.database import engine

settings = get_settings()

# =============================================================================
# OCR 提示词
# =============================================================================
_INVOICE_OCR_PROMPT = """你是一个专业的中国增值税发票识别助手。请从发票内容中提取以下字段，只返回 JSON。

发票字段说明:
  {
    # --- 发票头部 ---
    "invoice_code": "发票代码（12位数字，发票左上角）",
    "invoice_number": "发票号码（8位数字，发票右上角）",
    "invoice_date": "开票日期（YYYY-MM-DD格式）",
    "invoice_type": "发票类型: 增值税普通发票/增值税专用发票/增值税电子普通发票/其他",

    # --- 购买方 ---
    "buyer_name": "购买方名称（抬头）",
    "buyer_tax_id": "购买方纳税人识别号（18位）",

    # --- 销售方 ---
    "seller_name": "销售方名称",
    "seller_tax_id": "销售方纳税人识别号",

    # --- 金额（三者关系: total_with_tax = amount + tax_amount）---
    "amount": 合计金额(不含税数字),
    "tax_amount": 税额(数字),
    "total_with_tax": 价税合计(大写下方的小写数字),

    # --- 货物或应税劳务清单 ---
    "items": [
      {
        "name": "货物或应税劳务名称",
        "specification": "规格型号（可能为空）",
        "unit": "单位（个/台/套/张/次/项等）",
        "quantity": 数量(数字),
        "unit_price": 单价(数字),
        "amount": 金额(数字 = 数量×单价),
        "tax_rate": "税率（如 13%, 6%, 3%）"
      }
    ],

    # --- 其他 ---
    "remarks": "备注栏内容（可能为空）",
    "payee": "收款人（发票底部）",
    "reviewer": "复核人（发票底部）",
    "drawer": "开票人（发票底部）"
  }

如果某个字段无法识别，字符串字段设为 ""，数字字段设为 0。
只返回 JSON，不要输出任何其他内容。"""



# =============================================================================
# 工具 1：OCR 发票识别
# =============================================================================
async def ocr_recognize_invoice(file_path: str) -> dict:
    """
    识别上传的票据文件（图片/PDF）中的发票信息。

    图片文件：通过 DeepSeek Vision 多模态识别
    PDF 文件：先用 pypdf 提取文本，再用 DeepSeek 结构化
    无文件时：返回空结构
    """
    if not file_path:
        logger.info("OCR skipped: no file path provided")
        return _empty_invoice_result("")

    ext = os.path.splitext(file_path)[1].lower()
    logger.info(f"OCR processing: {file_path} (type={ext})")

    from app.services.ocr_svc import get_file_content
    try:
        content = await get_file_content(file_path)
    except Exception as e:
        logger.warning(f"MinIO download failed for {file_path}: {e}")
        return _empty_invoice_result(file_path)

    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return _ocr_image(content, file_path)
    elif ext == ".pdf":
        return _ocr_pdf(content, file_path)
    else:
        logger.warning(f"Unsupported file type: {ext}")
        return _empty_invoice_result(file_path)


def _ocr_image(image_bytes: bytes, file_path: str) -> dict:
    """用 DeepSeek Vision 识别图片中的发票信息"""
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "webp") else "image/png"

        from langchain_openai import ChatOpenAI
        vision_llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0,
            request_timeout=30,
            max_retries=1,
        )
        msg = vision_llm.invoke([{
            "role": "user",
            "content": [
                {"type": "text", "text": _INVOICE_OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }])
        return _parse_llm_invoice(msg.content, file_path)
    except Exception as e:
        logger.warning(f"Vision OCR failed: {e}")
        return _empty_invoice_result(file_path)


def _ocr_pdf(pdf_bytes: bytes, file_path: str) -> dict:
    """用 pypdf 提取 PDF 文本，再用 DeepSeek 结构化"""
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages[:3]:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return _empty_invoice_result(file_path)

    if not text.strip():
        logger.warning("PDF has no extractable text")
        return _empty_invoice_result(file_path)

    logger.info(f"PDF text extracted: {len(text)} chars")
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0,
            request_timeout=15,
            max_retries=1,
        )
        msg = llm.invoke(f"{_INVOICE_OCR_PROMPT}\n\n发票文本内容:\n{text[:4000]}")
        return _parse_llm_invoice(msg.content, file_path)
    except Exception as e:
        logger.warning(f"LLM invoice structuring failed: {e}")
        return _empty_invoice_result(file_path)


def _parse_llm_invoice(raw: str, file_path: str) -> dict:
    """解析 LLM 返回的 JSON 字符串为结构化发票数据"""
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        data = json.loads(content)
        items = data.get("items", [])
        if isinstance(items, list):
            for it in items:
                it.setdefault("name", "")
                it.setdefault("specification", "")
                it.setdefault("unit", "")
                it.setdefault("quantity", 0)
                it.setdefault("unit_price", 0)
                it.setdefault("amount", 0)
                it.setdefault("tax_rate", "")

        result = {
            # 头部
            "invoice_code": str(data.get("invoice_code", "")),
            "invoice_number": str(data.get("invoice_number", "")),
            "invoice_date": str(data.get("invoice_date", "")),
            "invoice_type": str(data.get("invoice_type", "")),
            # 双方
            "buyer_name": str(data.get("buyer_name", "")),
            "buyer_tax_id": str(data.get("buyer_tax_id", "")),
            "seller_name": str(data.get("seller_name", "")),
            "seller_tax_id": str(data.get("seller_tax_id", "")),
            # 金额
            "amount": float(data.get("amount") or data.get("total_with_tax") or 0),
            "tax_amount": float(data.get("tax_amount") or 0),
            "total_with_tax": float(data.get("total_with_tax") or data.get("amount") or 0),
            # 明细
            "items": items,
            # 其他
            "remarks": str(data.get("remarks", "")),
            "payee": str(data.get("payee", "")),
            "reviewer": str(data.get("reviewer", "")),
            "drawer": str(data.get("drawer", "")),
            "file_path": file_path,
        }
        logger.info(
            f"OCR result: amount={result['amount']} seller={result['seller_name']} "
            f"items={len(result['items'])} tax=¥{result['tax_amount']}"
        )
        return result
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse LLM invoice JSON: {e}")
        return _empty_invoice_result(file_path)


def _empty_invoice_result(file_path: str) -> dict:
    return {
        "invoice_code": "", "invoice_number": "", "invoice_date": "", "invoice_type": "",
        "buyer_name": "", "buyer_tax_id": "",
        "seller_name": "", "seller_tax_id": "",
        "amount": 0, "tax_amount": 0, "total_with_tax": 0,
        "items": [],
        "remarks": "", "payee": "", "reviewer": "", "drawer": "",
        "file_path": file_path,
    }


# =============================================================================
# 工具 2：合规审查
# =============================================================================
async def compliance_check(expense_type: str, total_amount: float, department: str) -> dict:
    """
    检查报销金额是否符合公司费用标准。在每笔报销保存到数据库之前必须调用。

    调用时机：OCR 识别完成 + 金额汇总后，预算检查之前。
    检查内容：根据费用类型（travel/entertainment/office/other），对比数据库 expense_policy 表
    或 fallback 到硬编码的默认限额，判断是否超标。

    参数:
        expense_type : travel / entertainment / office / other
        total_amount : 报销总金额（所有发票汇总后）
        department   : 申请部门名称

    返回:
        compliant  : bool    是否合规
        limit      : float   对应的费用上限
        message    : str     合规/超标描述
        如果超标，调用方需要标记 need_special_approval=True
    """
    _FALLBACK_LIMITS = {
        "travel":        {"max_per_trip": 10000, "daily_limit": 500},
        "entertainment": {"max_per_event": 3000, "per_person_limit": 200},
        "office":        {"max_per_item": 5000},
        "other":         {"max_per_request": 2000},
    }

    policy = None
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM expense_policy WHERE expense_type = :etype"),
                {"etype": expense_type},
            )
            row = result.fetchone()
        if row:
            policy = {
                "max_per_request": float(row.max_per_request) if row.max_per_request else None,
                "max_per_trip": float(row.max_per_trip) if row.max_per_trip else None,
                "max_per_item": float(row.max_per_item) if row.max_per_item else None,
                "max_per_event": float(row.max_per_event) if row.max_per_event else None,
            }
    except Exception as e:
        logger.warning(f"Failed to load expense policy from DB: {e}")

    if policy:
        max_val = float(
            policy.get("max_per_request") or policy.get("max_per_trip")
            or policy.get("max_per_item") or policy.get("max_per_event") or 2000
        )
        source = "database"
    else:
        fallback = _FALLBACK_LIMITS.get(expense_type, {"max_per_request": 2000})
        max_val = float(
            fallback.get("max_per_request") or fallback.get("max_per_trip")
            or fallback.get("max_per_item") or 2000
        )
        source = "fallback"

    compliant = total_amount <= max_val
    type_names = {"travel": "差旅", "entertainment": "招待", "office": "办公", "other": "其他"}
    type_cn = type_names.get(expense_type, expense_type)

    return {
        "compliant": compliant,
        "expense_type": expense_type,
        "limit": max_val,
        "limit_source": source,
        "message": (
            f"✅ {type_cn}费 {total_amount} 元在标准 {max_val} 元以内，合规。"
            if compliant else
            f"⚠️ {type_cn}费 {total_amount} 元超过标准 {max_val} 元，需要特殊说明。"
        ),
    }


# =============================================================================
# 工具 3：预算池控制
# =============================================================================
async def budget_check(department: str, amount: float) -> dict:
    """
    查询部门年度预算余额，判断当前报销金额是否会导致预算超支。

    调用时机：合规检查通过后，报销单入库之前。
    数据来源：数据库 department_budget 表，读取年度预算和已使用金额。
    计算方式：报销后余额 = 剩余预算 - 当前报销金额，小于 0 则标记超标。

    参数:
        department : 部门名称
        amount     : 本次报销金额

    返回:
        remaining              : float   报销前剩余预算
        after_reimbursement    : float   报销后剩余预算（负数即超支）
        exceeded               : bool    是否超支
        need_special_approval  : bool    是否需要特殊审批（超支则为 True）
        annual_budget          : float   年度总预算
    """
    from sqlalchemy import text
    bud = None
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT department, annual_budget, used_amount "
                    "FROM department_budget WHERE department = :dept"
                ),
                {"dept": department},
            )
            row = result.fetchone()
            if row:
                bud = {
                    "department": row.department,
                    "annual_budget": float(row.annual_budget),
                    "used": float(row.used_amount),
                    "remaining": float(row.annual_budget - row.used_amount),
                }
    except Exception as e:
        logger.warning(f"DB query failed for department={department}: {e}")

    if bud is None:
        bud = {"department": department, "annual_budget": 100000, "used": 50000, "remaining": 50000}

    after = bud["remaining"] - amount
    exceeded = after < 0
    logger.info(
        f"Budget check: {department} "
        f"remaining={bud['remaining']} after={after} exceeded={exceeded}"
    )
    return {
        "department": department,
        "annual_budget": bud["annual_budget"],
        "used": bud["used"],
        "remaining": bud["remaining"],
        "after_reimbursement": after,
        "exceeded": exceeded,
        "need_special_approval": exceeded,
    }


# =============================================================================
# 工具 4：生成报销单 PDF（中文字体 + 表格 + 签字区）
# =============================================================================
def generate_reimbursement_pdf(reimb_data: dict) -> str:
    """
    生成标准化的中文报销单 PDF 文件，包含公司抬头、报销明细表、金额汇总和签字区。

    调用时机：合规检查 + 预算检查 + 数据库保存全部完成后，发送邮件之前。
    输出格式：A4 大小，中文黑体/微软雅黑字体，含表格、金额汇总行和审批签字区。

    参数:
        reimb_data : 报销数据字典，需包含 id, department, expense_type, total_amount, invoices 等

    返回:
        生成的 PDF 文件的绝对路径（临时目录），用于后续邮件附件
    """
    import os as _os
    import tempfile
    from datetime import date
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics.barcode import code128

    # ---- 注册中文字体（跨平台）----
    _font_candidates = [
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Windows
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    _font_exists = _os.path.exists

    title_font = "Helvetica"
    body_font = "Helvetica"
    for fp in _font_candidates:
        if _font_exists(fp):
            try:
                fn = _os.path.splitext(_os.path.basename(fp))[0].replace(" ", "").replace("-", "")
                pdfmetrics.registerFont(TTFont(fn, fp))
                if title_font == "Helvetica":
                    title_font = fn
                body_font = fn
                break
            except Exception:
                continue

    reimb_id = reimb_data.get("id", "unknown")
    path = tempfile.mktemp(suffix=f"_reimb_{reimb_id}.pdf")

    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    margin = 20 * mm
    today = date.today().isoformat()

    # ---- 边框 ----
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(1.5)
    c.rect(margin, margin, W - 2 * margin, H - 2 * margin)
    c.setLineWidth(0.5)
    c.rect(margin + 3, margin + 3, W - 2 * margin - 6, H - 2 * margin - 6)

    # ---- 公司抬头 ----
    c.setFont(title_font, 22)
    c.drawCentredString(W / 2, H - margin - 18 * mm, "中国石油华东分公司")
    c.setFont(body_font, 14)
    c.drawCentredString(W / 2, H - margin - 26 * mm, "费 用 报 销 单")

    # ---- 分隔线 ----
    y_top = H - margin - 32 * mm
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1)
    c.line(margin + 5 * mm, y_top, W - margin - 5 * mm, y_top)

    # ---- 基本信息表格 ----
    c.setFont(body_font, 10)
    col1_x = margin + 8 * mm
    col2_x = margin + 35 * mm
    col3_x = margin + 95 * mm
    col4_x = margin + 122 * mm
    row_h = 9 * mm
    y = y_top - row_h

    def draw_row(label1, val1, label2=None, val2=None):
        nonlocal y
        c.setFont(body_font, 10)
        c.drawString(col1_x, y + 2 * mm, label1)
        val_str = str(val1) if val1 is not None else ""
        c.drawString(col2_x, y + 2 * mm, val_str)
        if label2 and val2 is not None:
            c.drawString(col3_x, y + 2 * mm, label2)
            c.drawString(col4_x, y + 2 * mm, str(val2))
        # 行线
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setLineWidth(0.3)
        c.line(col1_x, y, W - margin - 5 * mm, y)
        y -= row_h

    expense_type_map = {"travel": "差旅费", "entertainment": "招待费", "office": "办公用品", "other": "其他"}
    total = float(reimb_data.get("total_amount", 0))

    draw_row("报销单号：", reimb_id, "日期：", today)
    draw_row("部    门：", reimb_data.get("department", ""),
             "费用类型：", expense_type_map.get(reimb_data.get("expense_type", ""), ""))
    draw_row("金    额：", f"¥{total:,.2f}",
             "发票张数：", str(len(reimb_data.get("invoices", [])) or 1))

    # ---- 发票明细表格 ----
    y -= 6 * mm
    c.setFont(body_font, 11)
    c.drawString(col1_x, y + 2 * mm, "发票明细：")
    y -= 5 * mm

    # 表头
    tbl_left = col1_x
    tbl_cols = [tbl_left, tbl_left + 24 * mm, tbl_left + 48 * mm, tbl_left + 66 * mm, tbl_left + 84 * mm, tbl_left + 106 * mm]
    tbl_widths = [24 * mm, 24 * mm, 18 * mm, 18 * mm, 22 * mm, 30 * mm]
    headers = ["发票代码", "发票号码", "开票日期", "金额(不含税)", "税额", "销售方"]
    tbl_row_h = 7 * mm

    c.setFont(body_font, 9)
    c.setFillColorRGB(0.9, 0.9, 0.9)
    c.rect(tbl_left, y - tbl_row_h, sum(tbl_widths), tbl_row_h, fill=1, stroke=1)
    c.setFillColorRGB(0, 0, 0)
    for i, (hdr, cx) in enumerate(zip(headers, tbl_cols)):
        c.drawString(cx + 1 * mm, y - tbl_row_h + 2 * mm, hdr)
    y -= tbl_row_h

    # 表体
    invoices = reimb_data.get("invoices", [])
    if not invoices:
        invoices = [{}]
    for inv in invoices[:5]:  # 最多显示 5 行
        c.setFillColorRGB(1, 1, 1)
        c.rect(tbl_left, y - tbl_row_h, sum(tbl_widths), tbl_row_h, fill=1, stroke=1)
        c.setFillColorRGB(0, 0, 0)
        vals = [
            str(inv.get("invoice_code", ""))[:12],
            str(inv.get("invoice_number", ""))[:8],
            str(inv.get("invoice_date", ""))[:10],
            f"¥{float(inv.get('amount', 0) or 0):,.2f}",
            f"¥{float(inv.get('tax_amount', 0) or 0):,.2f}",
            str(inv.get("seller_name", ""))[:10],
        ]
        for v, cx in zip(vals, tbl_cols):
            c.drawString(cx + 1 * mm, y - tbl_row_h + 2 * mm, v)
        y -= tbl_row_h

    # ---- 审批签字区 ----
    y -= 10 * mm
    c.setFont(body_font, 10)
    c.drawString(col1_x, y + 2 * mm, "审批记录：")
    y -= 7 * mm

    sign_labels = [
        ("申请人签名：", col1_x),
        ("部门经理：", col1_x + 55 * mm),
        ("财务审核：", col1_x + 105 * mm),
    ]
    c.setFont(body_font, 9)
    for label, sx in sign_labels:
        c.drawString(sx, y + 2 * mm, label)
        c.line(sx + 16 * mm, y + 1 * mm, sx + 40 * mm, y + 1 * mm)  # 签名横线

    y -= 12 * mm
    c.drawString(col1_x, y + 2 * mm, "日    期：")
    c.line(col1_x + 18 * mm, y + 1 * mm, col1_x + 42 * mm, y + 1 * mm)
    c.drawString(col1_x + 55 * mm, y + 2 * mm, "日    期：")
    c.line(col1_x + 73 * mm, y + 1 * mm, col1_x + 97 * mm, y + 1 * mm)
    c.drawString(col1_x + 105 * mm, y + 2 * mm, "日    期：")
    c.line(col1_x + 123 * mm, y + 1 * mm, col1_x + 147 * mm, y + 1 * mm)

    c.setFont(body_font, 8)
    c.drawString(margin + 8 * mm, margin + 6 * mm, f"系统生成 · {today}")
    c.drawRightString(W - margin - 8 * mm, margin + 6 * mm, f"编号: {reimb_id}")

    c.save()
    logger.info(f"PDF created: {path}")
    return path


# =============================================================================
# 工具 4b：生成增值税发票 PDF（模拟票据，用于测试/演示/补开）
# =============================================================================
def _amount_to_chinese(amount: float) -> str:
    """把金额数字转成中文大写（如 1234.56 → 壹仟贰佰叁拾肆元伍角陆分）。"""
    if amount < 0:
        return "负" + _amount_to_chinese(-amount)
    digits = "零壹贰叁肆伍陆柒捌玖"
    int_units = ["", "拾", "佰", "仟"]
    big_units = ["", "万", "亿", "兆"]

    # 分离整数与小数（角、分）
    amount = round(amount + 1e-9, 2)
    int_part = int(amount)
    frac = int(round((amount - int_part) * 100))
    jiao, fen = frac // 10, frac % 10

    def _four(n: int) -> str:
        s = ""
        started = False
        for i in range(3, -1, -1):
            d = (n // (10 ** i)) % 10
            if d == 0:
                if started and i > 0:
                    s += "零"
            else:
                s += digits[d] + int_units[i]
                started = True
        return s.rstrip("零")

    if int_part == 0:
        int_str = ""
    else:
        groups = []
        n = int_part
        gi = 0
        while n > 0:
            grp = n % 10000
            if grp > 0:
                groups.append(_four(grp) + big_units[gi])
            else:
                groups.append("")
            n //= 10000
            gi += 1
        int_str = "".join(reversed([g for g in groups if g != ""]))
        # 处理组间缺位补零（简化：合并多余零）
        int_str = int_str + "元"

    if jiao == 0 and fen == 0:
        frac_str = "整" if int_str else "零元整"
    else:
        frac_str = ""
        if jiao > 0:
            frac_str += digits[jiao] + "角"
        elif fen > 0 and int_part > 0:
            frac_str += "零"
        if fen > 0:
            frac_str += digits[fen] + "分"

    result = (int_str or "") + frac_str
    return result or "零元整"


def generate_invoice_pdf(invoice_data: dict) -> str:
    """
    生成一张模拟的中国增值税普通发票 PDF（用于测试/演示/补录票据）。

    与 generate_reimbursement_pdf（报销单）不同：本函数产出的是「发票」样式，
    含发票代码/号码、购买方/销售方信息栏、货物明细表、价税合计大写、开票信息等。

    参数:
        invoice_data : 发票数据字典，可包含:
          invoice_code, invoice_number, invoice_date, invoice_type,
          buyer_name, buyer_tax_id, seller_name, seller_tax_id,
          amount(不含税), tax_amount(税额), total_with_tax(价税合计),
          items(明细行列表), remarks, payee, reviewer, drawer

    返回:
        生成的发票 PDF 文件绝对路径（临时目录）。
    """
    import os as _os
    import tempfile
    import random
    from datetime import date
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # ---- 注册中文字体（跨平台）----
    _font_candidates = [
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
    title_font = "Helvetica"
    body_font = "Helvetica"
    for fp in _font_candidates:
        if _os.path.exists(fp):
            try:
                fn = _os.path.splitext(_os.path.basename(fp))[0].replace(" ", "").replace("-", "")
                pdfmetrics.registerFont(TTFont(fn, fp))
                if title_font == "Helvetica":
                    title_font = fn
                body_font = fn
                break
            except Exception:
                continue

    # ---- 补全缺省字段 ----
    inv_type = invoice_data.get("invoice_type") or "增值税普通发票"
    inv_code = str(invoice_data.get("invoice_code") or "".join(random.choice("0123456789") for _ in range(12)))
    inv_number = str(invoice_data.get("invoice_number") or "".join(random.choice("0123456789") for _ in range(8)))
    inv_date = invoice_data.get("invoice_date") or date.today().isoformat()

    buyer_name = invoice_data.get("buyer_name") or "中国石油华东分公司"
    buyer_tax_id = invoice_data.get("buyer_tax_id") or "91310000710913000J"
    seller_name = invoice_data.get("seller_name") or "某某供应商有限公司"
    seller_tax_id = invoice_data.get("seller_tax_id") or ""

    items = invoice_data.get("items") or []
    amount = invoice_data.get("amount")
    tax_amount = invoice_data.get("tax_amount")
    total_with_tax = invoice_data.get("total_with_tax")

    # 金额推断：优先用 items 汇总，其次用传入值
    if items:
        amount = sum(float(it.get("amount", 0) or 0) for it in items)
    amount = float(amount or 0)
    tax_amount = float(tax_amount or 0)
    if total_with_tax is None:
        total_with_tax = amount + tax_amount
    total_with_tax = float(total_with_tax)
    # 若只给了价税合计，反推不含税（默认无税率时不含税=价税合计）
    if amount == 0 and total_with_tax > 0:
        amount = total_with_tax - tax_amount

    path = tempfile.mktemp(suffix=f"_invoice_{inv_number}.pdf")

    # 发票通常是横向票样，这里用 A4 横向布局的上半部分
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    margin = 15 * mm

    # ---- 外框（发票联红框风格）----
    c.setStrokeColorRGB(0.75, 0.15, 0.15)
    c.setLineWidth(1.2)
    box_top = H - margin
    box_bottom = H - margin - 120 * mm
    c.rect(margin, box_bottom, W - 2 * margin, box_top - box_bottom)

    # ---- 标题 ----
    c.setFillColorRGB(0.75, 0.15, 0.15)
    c.setFont(title_font, 20)
    c.drawCentredString(W / 2, box_top - 12 * mm, "中国石油华东分公司")
    c.setFont(title_font, 15)
    c.drawCentredString(W / 2, box_top - 20 * mm, inv_type)
    c.setFillColorRGB(0, 0, 0)

    # ---- 右上：发票代码/号码/日期 ----
    c.setFont(body_font, 9)
    right_x = W - margin - 55 * mm
    c.drawString(right_x, box_top - 10 * mm, f"发票代码: {inv_code}")
    c.drawString(right_x, box_top - 15 * mm, f"发票号码: {inv_number}")
    c.drawString(right_x, box_top - 20 * mm, f"开票日期: {inv_date}")

    # ---- 分隔线 ----
    y = box_top - 26 * mm
    c.setStrokeColorRGB(0.75, 0.15, 0.15)
    c.setLineWidth(0.6)
    c.line(margin + 2 * mm, y, W - margin - 2 * mm, y)

    # ---- 购买方信息栏 ----
    def _info_block(y0, title, name, tax_id):
        c.setFont(body_font, 9)
        c.drawString(margin + 4 * mm, y0 - 5 * mm, f"{title}")
        c.drawString(margin + 22 * mm, y0 - 5 * mm, f"名  称: {name}")
        c.drawString(margin + 22 * mm, y0 - 11 * mm, f"纳税人识别号: {tax_id}")
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.setLineWidth(0.3)
        c.line(margin + 2 * mm, y0 - 14 * mm, W - margin - 2 * mm, y0 - 14 * mm)

    _info_block(y, "购买方", buyer_name, buyer_tax_id)
    y -= 16 * mm
    _info_block(y, "销售方", seller_name, seller_tax_id)
    y -= 16 * mm

    # ---- 货物明细表 ----
    tbl_left = margin + 4 * mm
    headers = ["货物或应税劳务名称", "规格型号", "单位", "数量", "单价", "金额", "税率", "税额"]
    col_w = [42 * mm, 20 * mm, 12 * mm, 14 * mm, 20 * mm, 24 * mm, 12 * mm, 22 * mm]
    col_x = [tbl_left]
    for w in col_w[:-1]:
        col_x.append(col_x[-1] + w)
    row_h = 7 * mm

    c.setFont(body_font, 8)
    c.setFillColorRGB(0.95, 0.92, 0.92)
    c.rect(tbl_left, y - row_h, sum(col_w), row_h, fill=1, stroke=1)
    c.setFillColorRGB(0, 0, 0)
    for hdr, cx in zip(headers, col_x):
        c.drawString(cx + 1 * mm, y - row_h + 2 * mm, hdr)
    y -= row_h

    if not items:
        items = [{
            "name": invoice_data.get("description") or "服务费",
            "specification": "", "unit": "项", "quantity": 1,
            "unit_price": amount, "amount": amount, "tax_rate": "",
        }]
    for it in items[:6]:
        c.rect(tbl_left, y - row_h, sum(col_w), row_h, fill=0, stroke=1)
        vals = [
            str(it.get("name", ""))[:20],
            str(it.get("specification", ""))[:8],
            str(it.get("unit", ""))[:4],
            str(it.get("quantity", "") or ""),
            f"{float(it.get('unit_price', 0) or 0):,.2f}" if it.get("unit_price") else "",
            f"{float(it.get('amount', 0) or 0):,.2f}",
            str(it.get("tax_rate", "")),
            f"{float(it.get('tax_amount', 0) or 0):,.2f}" if it.get("tax_amount") else "",
        ]
        for v, cx in zip(vals, col_x):
            c.drawString(cx + 1 * mm, y - row_h + 2 * mm, v)
        y -= row_h

    # ---- 合计行 ----
    c.rect(tbl_left, y - row_h, sum(col_w), row_h, fill=0, stroke=1)
    c.setFont(body_font, 8)
    c.drawString(col_x[0] + 1 * mm, y - row_h + 2 * mm, "合  计")
    c.drawString(col_x[5] + 1 * mm, y - row_h + 2 * mm, f"¥{amount:,.2f}")
    c.drawString(col_x[7] + 1 * mm, y - row_h + 2 * mm, f"¥{tax_amount:,.2f}")
    y -= row_h

    # ---- 价税合计（大写 + 小写）----
    y -= 2 * mm
    c.setFont(body_font, 9)
    cn_amount = _amount_to_chinese(total_with_tax)
    c.drawString(tbl_left, y - 5 * mm, f"价税合计（大写）:  {cn_amount}")
    c.drawRightString(W - margin - 4 * mm, y - 5 * mm, f"（小写）¥{total_with_tax:,.2f}")
    y -= 10 * mm
    c.setStrokeColorRGB(0.75, 0.15, 0.15)
    c.setLineWidth(0.6)
    c.line(margin + 2 * mm, y, W - margin - 2 * mm, y)

    # ---- 备注 + 开票信息 ----
    y -= 6 * mm
    c.setFont(body_font, 8)
    remarks = invoice_data.get("remarks") or ""
    c.drawString(tbl_left, y, f"备注: {remarks}")
    y -= 8 * mm
    payee = invoice_data.get("payee") or ""
    reviewer = invoice_data.get("reviewer") or ""
    drawer = invoice_data.get("drawer") or ""
    c.drawString(tbl_left, y, f"收款人: {payee}")
    c.drawString(tbl_left + 45 * mm, y, f"复核: {reviewer}")
    c.drawString(tbl_left + 85 * mm, y, f"开票人: {drawer}")

    # ---- 底部提示 ----
    c.setFont(body_font, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, box_bottom + 3 * mm, "本发票为系统生成的模拟票据，仅供测试与演示使用，不具备法律效力。")

    c.save()
    logger.info(f"Invoice PDF created: {path} (number={inv_number}, total={total_with_tax})")

    # 回写解析后的实际值，方便调用方（如 API）获取生成的发票号/金额
    if isinstance(invoice_data, dict):
        invoice_data["invoice_code"] = inv_code
        invoice_data["invoice_number"] = inv_number
        invoice_data["invoice_date"] = inv_date
        invoice_data["amount"] = amount
        invoice_data["tax_amount"] = tax_amount
        invoice_data["total_with_tax"] = total_with_tax

    return path


# =============================================================================
# 工具 5：发送审批邮件（同步，Celery 任务提交后立即返回）
# =============================================================================
async def send_approval_email(to_email: str, reimb_id: str, total_amount: float, pdf_path: str = "") -> dict:
    """
    发送审批通知邮件给审批人，附带生成的 PDF 报销单作为附件。

    调用时机：PDF 生成完成后，作为报销流程的最后一步。
    发送方式：优先通过 Celery 异步任务队列发送，不可用时降级为同步 SMTP 直连。
    邮件内容：包含报销单号、金额、申请人信息，PDF 作为附件。

    参数:
        to_email     : 审批人邮箱地址
        reimb_id     : 报销单号
        total_amount : 报销金额
        pdf_path     : PDF 报销单文件路径

    返回:
        sent : bool    是否发送成功
    """
    logger.info(f"Email to={to_email} reimb={reimb_id} amount={total_amount} pdf={pdf_path}")

    sent = False
    # 优先用 Celery 异步
    try:
        from tasks.email_task import send_approval_email_task
        send_approval_email_task.delay(to_email, reimb_id, total_amount, pdf_path)
        sent = True
        logger.info("Email queued via Celery")
    except Exception as e:
        logger.warning(f"Celery unavailable ({e}), trying direct send...")
        try:
            from app.services.email_svc import send_email
            subject = f"【报销审批】报销单 {reimb_id} 待审批 - ¥{total_amount:,.2f}"
            body = f"<h2>报销审批通知</h2><p>报销单编号: <b>{reimb_id}</b></p><p>报销金额: <b>¥{total_amount:,.2f}</b></p><p>请登录系统进行审批。</p>"
            await send_email(
                to_email, subject, body,
                pdf_path if pdf_path else None,
                f"报销单_{reimb_id}.pdf",
            )
            sent = True
            logger.info(f"Email sent directly to {to_email}")
        except Exception as e2:
            logger.error(f"Direct email also failed: {e2}")

    return {
        "sent": sent, "to": to_email, "reimb_id": reimb_id,
        "message": (
            f"报销单 {reimb_id} (金额 ¥{total_amount:,.2f}) 已提交审批，邮件已发送。"
            if sent else
            f"报销单 {reimb_id} 已提交，但邮件发送失败。"
        ),
    }


# =============================================================================
# 工具 6：报销单持久化到数据库
# =============================================================================
async def save_reimbursement_to_db(
    department: str, expense_type: str, total_amount: float,
    invoices: list[dict], need_special_approval: bool,
    budget_remaining_after: float, description: str = "",
    user_id: str = "demo_user", user_name: str = "演示用户",
) -> dict:
    """
    将报销申请持久化到数据库。一次调用同时写入三张表并更新预算。

    调用时机：合规检查 + 预算检查全部通过后，PDF 生成之前。
    写入内容：
      1. reimbursements 表 — 报销单主记录
      2. invoices 表 — 每张发票的明细记录
      3. approval_records 表 — 初始待审批记录
      4. 更新 department_budget 表 — 增加已使用金额

    参数:
        department             : 申请部门
        expense_type           : travel / entertainment / office / other
        total_amount           : 报销总金额
        invoices               : 发票列表 [{invoice_code, invoice_number, amount, ...}]
        need_special_approval  : 是否需要特殊审批（超标标记）
        budget_remaining_after : 报销后剩余预算
        user_id                : 员工工号（默认 demo_user）
        user_name              : 员工姓名（默认 演示用户）

    返回:
        id                     : 生成的报销单号（12位）
        status                 : pending（初始状态）
    """
    from sqlalchemy import text

    reimb_id = uuid.uuid4().hex[:12]
    # SQLite 不支持 Decimal 类型绑参，统一转 float
    total_val = float(total_amount)
    budget_after = float(budget_remaining_after) if budget_remaining_after else None

    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO reimbursements
                (id, user_id, user_name, department, expense_type, total_amount,
                 description, invoice_count, need_special_approval,
                 budget_remaining_after, status)
                VALUES (:id, :uid, :uname, :dept, :etype, :amount,
                        :desc, :icount, :special, :remaining, 'pending')
            """), {
                "id": reimb_id, "uid": user_id, "uname": user_name,
                "dept": department, "etype": expense_type, "amount": total_val,
                "desc": description or "", "icount": len(invoices),
                "special": need_special_approval, "remaining": budget_after,
            })

            for inv in invoices:
                inv_amount = float(inv.get("amount", 0) or 0)
                await conn.execute(text("""
                    INSERT INTO invoices
                    (id, reimbursement_id, invoice_code, invoice_number, amount,
                     invoice_date, invoice_type,
                     seller_name, seller_tax_id, buyer_name, buyer_tax_id,
                     tax_amount, total_with_tax, file_path)
                    VALUES (:id, :rid, :code, :num, :amount,
                            :date, :itype,
                            :seller, :stax, :buyer, :btax,
                            :tax, :total, :fpath)
                """), {
                    "id": uuid.uuid4().hex[:12], "rid": reimb_id,
                    "code": inv.get("invoice_code") or "",
                    "num": inv.get("invoice_number") or "",
                    "amount": inv_amount,
                    "date": inv.get("invoice_date") or None,
                    "itype": inv.get("invoice_type") or "",
                    "seller": inv.get("seller_name") or "",
                    "stax": inv.get("seller_tax_id") or "",
                    "buyer": inv.get("buyer_name") or "",
                    "btax": inv.get("buyer_tax_id") or "",
                    "tax": float(inv.get("tax_amount", 0) or 0),
                    "total": float(inv.get("total_with_tax", inv_amount) or inv_amount),
                    "fpath": inv.get("file_path") or "",
                })

            await conn.execute(text("""
                INSERT INTO approval_records
                (id, reimbursement_id, approver, step, action, comment)
                VALUES (:id, :rid, '部门经理', 1, 'pending', '报销单已提交，等待审批')
            """), {"id": uuid.uuid4().hex[:12], "rid": reimb_id})

            await conn.execute(text("""
                UPDATE department_budget
                SET used_amount = used_amount + :amount
                WHERE department = :dept
            """), {"amount": total_val, "dept": department})

        logger.info(
            f"报销单已入库: id={reimb_id} dept={department} "
            f"amount={total_amount} special={need_special_approval}"
        )
        return {"reimb_id": reimb_id, "status": "pending"}

    except Exception as e:
        logger.error(f"数据库写入失败: {e}")
        raise


# =============================================================================
# 工具 7：查询报销进度 / 多维度搜索报销单
# =============================================================================
async def query_reimbursement_status(
    reimb_id: str = "",
    date_from: str = "",
    date_to: str = "",
    department: str = "",
    expense_type: str = "",
    keyword: str = "",
    amount_min: float = None,
    amount_max: float = None,
    amount_exact: float = None,
    status: str = "",
    limit: int = 20,
) -> dict:
    """多维度查询报销单。

    支持:
      - 按报销单号精确查询
      - 按金额范围/精确金额查询
      - 按关键词搜索描述
      - 按部门、类型、状态筛选
      - 按日期范围筛选
    """
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            # 按 ID 精确查询
            if reimb_id:
                r = await conn.execute(
                    text("SELECT id, user_id, status, total_amount, department, expense_type, description, created_at "
                         "FROM reimbursements WHERE id = :rid"),
                    {"rid": reimb_id},
                )
                reimb = r.fetchone()
                if reimb:
                    ar = await conn.execute(
                        text("SELECT step, approver, action, comment, acted_at "
                             "FROM approval_records WHERE reimbursement_id = :rid ORDER BY step"),
                        {"rid": reimb_id},
                    )
                    approvals = ar.fetchall()
                    return {
                        "reimb_id": reimb.id,
                        "user_id": reimb.user_id,
                        "status": reimb.status,
                        "department": reimb.department,
                        "expense_type": reimb.expense_type,
                        "total_amount": float(reimb.total_amount),
                        "description": reimb.description,
                        "created_at": str(reimb.created_at),
                        "steps": [
                            {"step": a.step, "approver": a.approver,
                             "action": a.action, "acted_at": str(a.acted_at)}
                            for a in approvals
                        ] or [
                            {"step": 1, "approver": "部门经理", "action": "待审批"},
                            {"step": 2, "approver": "财务总监", "action": "等待中"},
                        ],
                    }
                return {"reimb_id": reimb_id, "status": "not_found", "steps": []}

            # 多维度搜索
            conditions = []
            params = {}
            if status:
                conditions.append("r.status = :status")
                params["status"] = status
            if department:
                conditions.append("r.department = :dept")
                params["dept"] = department
            if expense_type:
                conditions.append("r.expense_type = :etype")
                params["etype"] = expense_type
            if keyword:
                conditions.append("r.description LIKE :kw")
                params["kw"] = f"%{keyword}%"
            if amount_exact is not None:
                conditions.append("r.total_amount = :amt_exact")
                params["amt_exact"] = float(amount_exact)
            else:
                if amount_min is not None:
                    conditions.append("r.total_amount >= :amt_min")
                    params["amt_min"] = float(amount_min)
                if amount_max is not None:
                    conditions.append("r.total_amount <= :amt_max")
                    params["amt_max"] = float(amount_max)
            if date_from:
                conditions.append("r.created_at >= :dfrom")
                params["dfrom"] = date_from
            if date_to:
                conditions.append("r.created_at <= :dto")
                params["dto"] = date_to

            params["limit"] = min(limit, 100)
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            sql = f"""
                SELECT id, status, total_amount, department, expense_type, description, created_at, user_name
                FROM reimbursements r
                {where_clause}
                ORDER BY r.created_at DESC
                LIMIT :limit
            """
            rows = (await conn.execute(text(sql), params)).fetchall()
            return {
                "count": len(rows),
                "results": [
                    {
                        "reimb_id": row.id,
                        "status": row.status,
                        "department": row.department,
                        "expense_type": row.expense_type,
                        "total_amount": float(row.total_amount),
                        "description": row.description or "",
                        "user_name": row.user_name,
                        "created_at": str(row.created_at),
                    }
                    for row in rows
                ],
            }
    except Exception as e:
        logger.warning(f"DB query failed for status check: {e}")

    return {"reimb_id": reimb_id or "N/A", "status": "unknown", "steps": [], "results": []}


# =============================================================================
# 工具 8：查询报销列表（支持泛化查询 — 我的报销、全部、按状态筛选）
# =============================================================================
async def query_reimbursement_list(
    status: str = "", limit: int = 50, user_id: str = ""
) -> list[dict]:
    """
    查询报销单列表（支持无 reimb_id 的泛化查询）。

    支持场景：
      - "查询我的报销" / "列出所有报销" → 返回全部列表
      - "待审批的有哪些" → 按 status 筛选
      - "最近有哪些报销记录" → 返回最近 limit 条

    Returns:
        报销单摘要列表，每项含 id, user_name, department, expense_type,
        total_amount, invoice_count, status, created_at
    """
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            where_clauses = []
            params = {"limit": min(limit, 200)}  # 硬上限 200 条

            if status:
                where_clauses.append("r.status = :status")
                params["status"] = status
            if user_id:
                where_clauses.append("r.user_id = :uid")
                params["uid"] = user_id

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            query = f"""
                SELECT r.id, r.user_name, r.department, r.expense_type,
                       r.total_amount, r.invoice_count, r.status, r.created_at,
                       r.need_special_approval, r.description
                FROM reimbursements r
                {where_sql}
                ORDER BY r.created_at DESC
                LIMIT :limit
            """
            result = await conn.execute(text(query), params)
            rows = result.fetchall()

            return [
                {
                    "id": row.id,
                    "user_name": row.user_name,
                    "department": row.department,
                    "expense_type": row.expense_type,
                    "total_amount": float(row.total_amount),
                    "invoice_count": row.invoice_count,
                    "status": row.status,
                    "created_at": str(row.created_at) if row.created_at else "",
                    "need_special_approval": bool(row.need_special_approval),
                    "description": row.description or "",
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning(f"DB query failed for reimbursement list: {e}")

    return []


# =============================================================================
# 工具 8：获取当前登录用户信息
# =============================================================================
def get_current_user_info(
    user_id: str = "", user_name: str = "", department: str = "", role: str = "",
) -> dict:
    """
    获取当前 JWT 会话中的用户信息。

    Agent 在以下场景自动调用:
      - 用户说"我要报销"但未指定部门 → 自动使用用户所属部门
      - 需要确认用户身份时

    Returns:
        {"user_id": "...", "user_name": "...", "department": "...", "role": "..."}
    """
    if not user_name:
        return {"user_id": "", "user_name": "未知用户", "department": "", "role": "", "hint": "请先登录"}
    return {
        "user_id": user_id,
        "user_name": user_name,
        "department": department,
        "role": role,
        "hint": f"当用户未指定部门时，默认使用部门: {department}",
    }


# =============================================================================
# 工具集合：供外部引用
# =============================================================================
ALL_TOOLS = [
    ocr_recognize_invoice,
    compliance_check,
    budget_check,
    generate_reimbursement_pdf,
    generate_invoice_pdf,
    send_approval_email,
    save_reimbursement_to_db,
    query_reimbursement_status,
    get_current_user_info,
]
