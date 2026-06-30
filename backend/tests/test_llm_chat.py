"""
=============================================================================
tests/test_llm_chat.py — 命令行对话测试脚本
=============================================================================
无需启动后端，直接用 Agent 和工作流与 LLM 对话。

使用方式：
  cd backend
  uv run python tests/test_llm_chat.py
=============================================================================
"""
import sys
import os

# 确保能从 backend/ 目录正确导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage
from app.agent.graph import reimburse_graph


def chat(user_input: str):
    """发送一条消息给 Agent，打印回复"""
    # 构造工作流初始状态（与 API 接口保持一致）
    initial_state = {
        "messages": [HumanMessage(content=user_input)],
        "intent": "",
        "session_id": "terminal_test",
        "department": "",
        "expense_type": "",
        "total_amount": 0.0,
        "invoices": [],
        "compliance_result": {},
        "budget_result": {},
        "need_special_approval": False,
        "pdf_path": "",
        "status": "",
    }

    # 执行工作流
    result = reimburse_graph.invoke(initial_state)

    # 打印所有节点产生的消息
    for msg in result["messages"]:
        if hasattr(msg, "content") and msg.content:
            print(msg.content)
    print("─" * 50)


if __name__ == "__main__":
    print("💰 ReimburseAgent — 对话测试")
    print("输入 'quit' 退出\n")

    # 固定测试输入
    test_inputs = [
        "你好，请问你可以做什么？",
        "差旅费报销标准是多少？",
        "我要报销办公费3000元，部门技术部",
    ]

    for inp in test_inputs:
        print(f"👤 用户: {inp}")
        chat(inp)
