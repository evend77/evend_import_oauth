import sys

class LogWrapper:
    def __init__(self, filepath):
        self.file = open(filepath, 'a', encoding='utf-8')
    def write(self, message):
        self.file.write(message)
        self.file.flush()  # flush immédiat
    def flush(self):
        self.file.flush()
