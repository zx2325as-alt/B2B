import json
from pathlib import Path
from app.core.config import settings

HISTORY_FILE = Path(settings.DATA_DIR) / "analysis_history.jsonl"

class HistoryService:
    @staticmethod
    def append_log(log_entry):
        """Append log to JSONL file"""
        try:
            # Ensure directory exists
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Failed to save log: {e}")

    @staticmethod
    def load_history(limit=50):
        """Load last N logs"""
        logs = []
        if not HISTORY_FILE.exists():
            return logs
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # If limit is -1, load all
                if limit == -1:
                    target_lines = lines
                else:
                    target_lines = lines[-limit:]
                    
                for line in target_lines:
                    try:
                        logs.append(json.loads(line))
                    except: pass
        except Exception as e:
            print(f"Failed to load history: {e}")
        return logs

    @staticmethod
    def clear_history():
        """Clear history file"""
        try:
            open(HISTORY_FILE, "w").close()
        except: pass

    @staticmethod
    def update_log_entry(log_id, updates):
        """
        Generic update for a log entry.
        :param log_id: ID of the log to update
        :param updates: Dictionary of fields to update (e.g. {"text": "...", "analysis": ...})
        """
        all_logs = HistoryService.load_history(limit=-1)
        updated = False
        
        for log in all_logs:
            if log.get("id") == log_id:
                for k, v in updates.items():
                    log[k] = v
                updated = True
                break
        
        if updated:
            try:
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    for log in all_logs:
                        f.write(json.dumps(log, ensure_ascii=False) + "\n")
                return True
            except Exception as e:
                print(f"Failed to update log: {e}")
        return False

    @staticmethod
    def update_log_text(log_id, new_text, new_rating=None):
        """Legacy wrapper for update_log_entry"""
        updates = {"text": new_text}
        if new_rating is not None:
            updates["rating"] = new_rating
        return HistoryService.update_log_entry(log_id, updates)
