class ToolStatus:

    def __init__(self):

        self.status = {}

    def set(
        self,
        tool,
        text
    ):

        self.status[tool] = text

    def get(
        self,
        tool
    ):

        return self.status.get(tool, "")