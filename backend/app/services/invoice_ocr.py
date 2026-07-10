"""
=============================================================================
app/services/invoice_ocr.py — 票据归一化与增值税发票二维码取证（P0）
=============================================================================
目标：显著提升票据识别成功率，且【不引入必装重依赖、不影响现有环境】。

P0 能力：
  1. normalize_to_images(content, ext) — 把上传件统一成图像:
       - 图片(png/jpg/webp/bmp) → 原样返回；
       - PDF → 用 PyMuPDF 逐页渲染成高清 PNG（治好"扫描件/图片型 PDF 抽不到文本"）。
     未安装 PyMuPDF 时 PDF 返回空列表，调用方自动退回 pypdf 文本抽取（无回归）。
  2. decode_vat_qr(image_bytes) — 解码中国增值税发票二维码，直接拿到
       发票代码/号码/开票日期/金额 等"高置信真值"（比任何 OCR 都准、几乎免费）。

依赖策略：pymupdf / opencv / pillow 全部为【可选】依赖（extra = "ocr"），
用 importlib 探测、按需惰性导入；任一缺失都优雅降级，绝不导致启动或识别流程报错。
启用：uv sync --extra ocr
=============================================================================
"""
from __future__ import annotations

import importlib.util
from loguru import logger

# 归一化直接透传的图片类型
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def capabilities() -> dict:
    """返回当前环境的 OCR 增强能力（用于日志/诊断）。"""
    return {
        "pdf_render": _has("fitz"),   # PyMuPDF
        "qr_decode": _has("cv2"),     # opencv
        "image_tools": _has("PIL"),   # Pillow
    }


# =============================================================================
# 1. 归一化为图像
# =============================================================================
def normalize_to_images(content: bytes, ext: str, *, dpi: int = 200, max_pages: int = 5) -> list[bytes]:
    """把上传文件统一转成 PNG 图像字节列表。

    - 图片：返回 [原始字节]（保持格式，交由视觉模型识别）；
    - PDF ：渲染每一页为 PNG（需 PyMuPDF），返回多页；未装 PyMuPDF 则返回 []。
    - 其他/失败：返回 []。
    """
    ext = (ext or "").lower()
    if ext in IMAGE_EXTS:
        return [content]
    if ext == ".pdf":
        return _render_pdf(content, dpi=dpi, max_pages=max_pages)
    return []


def _render_pdf(pdf_bytes: bytes, *, dpi: int, max_pages: int) -> list[bytes]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.info("PyMuPDF 未安装，PDF 无法渲染成图 → 退回文本抽取（如需扫描件识别请 uv sync --extra ocr）")
        return []
    imgs: list[bytes] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(dpi=dpi)
                imgs.append(pix.tobytes("png"))
        finally:
            doc.close()
        logger.info(f"PDF 已渲染为 {len(imgs)} 页 PNG（dpi={dpi}）")
    except Exception as e:
        logger.warning(f"PDF 渲染失败: {e}")
        return []
    return imgs


# =============================================================================
# 2. 增值税发票二维码解码
# =============================================================================
def decode_qr_texts(image_bytes: bytes) -> list[str]:
    """从图像中解码全部二维码文本（需 opencv；缺失或失败返回 []）。"""
    try:
        import numpy as np
        import cv2
    except Exception:
        return []
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []
        det = cv2.QRCodeDetector()
        texts: list[str] = []
        # 优先多码检测（一张图可能有多个码）
        try:
            ok, decoded, _pts, _ = det.detectAndDecodeMulti(img)
            if ok and decoded:
                texts.extend([t for t in decoded if t])
        except Exception:
            pass
        # 兜底单码检测
        if not texts:
            try:
                t, _pts, _ = det.detectAndDecode(img)
                if t:
                    texts.append(t)
            except Exception:
                pass
        return texts
    except Exception as e:
        logger.warning(f"二维码解码失败: {e}")
        return []


def parse_vat_qr_payload(text: str) -> dict:
    """解析中国增值税发票二维码文本 → 结构化字段（纯函数，便于单测）。

    常见（逗号分隔）格式：
      01,<发票种类>,<发票代码>,<发票号码>,<金额(不含税)>,<开票日期YYYYMMDD>,<校验码后6位>,...
      例：01,10,3700174320,12345678,1000.00,20200105,123456,
    对全电发票(数电票)：发票代码可能为空、发票号码为 20 位，本函数同样兼容。
    非该格式（如 URL/普通二维码）返回 {}。
    """
    if not text:
        return {}
    t = text.strip()
    parts = t.split(",")
    if len(parts) < 5:
        return {}
    # 仅处理以纯数字前缀（如 "01"）开头的增值税发票二维码，过滤 URL 等无关码
    if not parts[0].strip().isdigit():
        return {}

    def g(i: int) -> str:
        return parts[i].strip() if i < len(parts) and parts[i] is not None else ""

    code, number, amount, date, check = g(2), g(3), g(4), g(5), g(6)
    out: dict = {}
    if code and code.isdigit():
        out["invoice_code"] = code
    if number and number.isdigit():
        out["invoice_number"] = number
    if amount:
        try:
            out["amount"] = float(amount)
        except ValueError:
            pass
    if len(date) == 8 and date.isdigit():
        out["invoice_date"] = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    if check:
        out["check_code"] = check
    out["qr_raw"] = t
    return out


def decode_vat_qr(image_bytes: bytes) -> dict:
    """解码并解析一张图里的增值税发票二维码；取到有效"代码或号码"即返回。"""
    for text in decode_qr_texts(image_bytes):
        parsed = parse_vat_qr_payload(text)
        if parsed.get("invoice_number") or parsed.get("invoice_code"):
            return parsed
    return {}
