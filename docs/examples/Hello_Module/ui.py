from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class HelloModulePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Hello Module"))
        layout.addWidget(
            QLabel("This is my first Z's Multi Tool module!")
        )
