"""Điểm nạp callback cho LiteLLM (config.yaml tham chiếu file cùng thư mục).

Code thật nằm ở libs/ben_litellm_plugins, được mount và thêm vào PYTHONPATH.
"""

from ben_litellm_plugins.callbacks import usage_logger

__all__ = ["usage_logger"]
