"""
=============================================================================
app/agent/__init__.py — Agent 包初始化
=============================================================================
使用懒加载模式避免循环导入问题。

循环导入问题：
  app.agent.graph 导入 app.agent.tools
  app.agent.tools 导入 app.core.database
  如果 app.agent.__init__.py 在导入时直接 import graph，
  会触发一系列连锁导入，可能导致死锁。

解决方案：
  用函数包装导入语句，只在需要时才真正执行 import。
=============================================================================
"""


def get_reimburse_graph():
    """
    懒加载获取报销审批工作流图。

    不使用顶层 import，而是把 import 放在函数内部。
    这样只有在调用 get_reimburse_graph() 时才真正导入 graph 模块。
    """
    from app.agent.graph import reimburse_graph
    return reimburse_graph


__all__ = ["get_reimburse_graph"]
