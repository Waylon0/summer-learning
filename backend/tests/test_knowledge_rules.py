"""
=============================================================================
tests/test_knowledge_rules.py — 知识库文档标识/校验纯函数回归测试
=============================================================================
与 tests/test_rules.py 同风格：仅依赖标准库与项目内纯规则模块
（app/services/knowledge_rules.py），无需数据库/向量库/LLM 即可运行，守护
知识库管理模块（阶段二·方案 A）的安全校验：doc_key 白名单、防路径遍历、
启用/停用文件名互转。

注：knowledge_rules 属 app.services 包，但该包 __init__ 会引入 SQLAlchemy；
为保持“无重依赖可直跑”，这里用文件路径直接加载该纯模块。

运行方式:
  cd backend
  python -m pytest tests/test_knowledge_rules.py     # 有 pytest 时
  python tests/test_knowledge_rules.py               # 无 pytest 时直接跑
=============================================================================
"""
import os
import sys
import importlib.util

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

# 直接按文件路径加载纯模块，绕过 app.services.__init__（其引入 SQLAlchemy）
_spec = importlib.util.spec_from_file_location(
    "knowledge_rules_under_test",
    os.path.join(_BACKEND, "app", "services", "knowledge_rules.py"),
)
kr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kr)


# ---------------------------------------------------------------- doc_key 合法性
def test_valid_doc_keys():
    for k in ("expense_policy", "faq", "invoice_format", "abc123", "a", "_" * 64):
        assert kr.is_valid_doc_key(k) is True, k


def test_invalid_doc_keys_block_traversal():
    # 路径遍历/分隔符/点号/空白/超长/空 一律拒绝
    for k in ("../etc", "/etc/passwd", "a/b", "a\\b", "has space",
              "", "a" * 65, ".hidden", "trail.", "..", "a.b", "键中文"):
        assert kr.is_valid_doc_key(k) is False, k


# ---------------------------------------------------------------- 文件名互转
def test_filename_builders():
    assert kr.enabled_filename("expense_policy") == "expense_policy.md"
    assert kr.disabled_filename("expense_policy") == "expense_policy.md.disabled"
    assert kr.ENABLED_SUFFIX == ".md"
    assert kr.DISABLED_SUFFIX == ".md.disabled"


# ---------------------------------------------------------------- 反解 doc_key
def test_doc_key_from_filename():
    assert kr.doc_key_from_filename("expense_policy.md") == "expense_policy"
    assert kr.doc_key_from_filename("expense_policy.md.disabled") == "expense_policy"
    assert kr.doc_key_from_filename("faq.md") == "faq"
    # 非法/无后缀/含非法字符 → None
    assert kr.doc_key_from_filename("nosuffix") is None
    assert kr.doc_key_from_filename("bad key.md") is None
    assert kr.doc_key_from_filename("a/b.md") is None
    assert kr.doc_key_from_filename("") is None
    assert kr.doc_key_from_filename("README.txt") is None


# ---------------------------------------------------------------- 停用态识别
def test_is_disabled_filename():
    assert kr.is_disabled_filename("faq.md.disabled") is True
    assert kr.is_disabled_filename("faq.md") is False
    assert kr.is_disabled_filename("disabled") is False
    assert kr.is_disabled_filename("") is False


# ---------------------------------------------------------------- 往返一致性
def test_roundtrip():
    for key in ("expense_policy", "faq", "a1_b2"):
        assert kr.doc_key_from_filename(kr.enabled_filename(key)) == key
        assert kr.doc_key_from_filename(kr.disabled_filename(key)) == key
        assert kr.is_disabled_filename(kr.disabled_filename(key)) is True
        assert kr.is_disabled_filename(kr.enabled_filename(key)) is False


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} knowledge rule tests passed.")


if __name__ == "__main__":
    _run_all()
