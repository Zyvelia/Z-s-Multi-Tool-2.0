# core/tool_registry.py

TOOLS = []


def register_tool(tool: dict):
    """
    Expected schema:
    {
        "name": str,
        "category": str,
        "desc": str,
        "open": callable
    }
    """
    TOOLS.append(tool)


def get_tools():
    return TOOLS


def clear_tools():
    TOOLS.clear()