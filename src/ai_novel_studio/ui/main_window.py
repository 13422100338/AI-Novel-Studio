from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Novel Studio")
        self.setMinimumSize(960, 640)
        self.resize(1440, 900)
        self.setCentralWidget(QLabel("AI Novel Studio V3"))
