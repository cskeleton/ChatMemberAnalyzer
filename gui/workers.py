from PySide6.QtCore import QThread, Signal
import traceback

class StatisticsWorker(QThread):
    """
    Worker thread for fetching user statistics (Page 2)
    """
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, json_path, start_date=None, end_date=None):
        super().__init__()
        self.json_path = json_path
        self.start_date = start_date
        self.end_date = end_date

    def run(self):
        try:
            # Lazy import to avoid circular dep or heavy load at startup
            from count_messages import get_user_statistics
            
            result = get_user_statistics(
                self.json_path, 
                self.start_date, 
                self.end_date
            )
            
            if result.get('success'):
                self.finished.emit(result)
            else:
                self.error.emit(result.get('error', 'Unknown error'))
                
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()

class AnalysisWorker(QThread):
    """
    Worker thread for running the main analysis (Page 3)
    """
    progress = Signal(str)  # Log message
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, config):
        """
        config: dict containing all necessary parameters
        """
        super().__init__()
        self.config = config

    def run(self):
        try:
            from analyze_chat import ChatAnalyzer
            
            # Callback to emit progress signal
            def progress_callback(msg):
                self.progress.emit(msg)
            
            analyzer = ChatAnalyzer(
                api_url=self.config['api_url'],
                api_key=self.config['api_key'],
                model_name=self.config['model_name'],
                cache_dir=self.config.get('cache_dir', 'ChenfenTemp'),
                max_workers=self.config.get('max_workers', 5),
                api_timeout=self.config.get('api_timeout', 180),
                verbose=True,
                progress_callback=progress_callback
            )
            
            # Monkey patch log method for safety, though constructor should handle it now
            analyzer.log = progress_callback
            
            result = analyzer.run_analysis(
                json_path=self.config['json_path'],
                output_dir=self.config['output_dir'],
                users_to_analyze=self.config['users'],
                time_start=self.config.get('start_ts', 0),
                time_end=self.config.get('end_ts', 0),
                max_slices=self.config.get('max_slices', 30),
                template_path=self.config.get('template_path'),
                prompt_template_path=self.config.get('prompt_template_path')
            )
            
            if result.get('success'):
                self.finished.emit(result)
            else:
                self.error.emit(result.get('error', 'Analysis failed'))
                
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()
