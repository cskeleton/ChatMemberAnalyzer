import sys
from PySide6.QtWidgets import QApplication
from gui.wizard import MainWizard

def main():
    app = QApplication(sys.argv)
    
    # Optional: Set a style
    app.setStyle("Fusion")
    
    window = MainWizard()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
