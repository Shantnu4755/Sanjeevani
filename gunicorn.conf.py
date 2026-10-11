bind = "0.0.0.0:8000"
workers = 1  # one process keeps RAM near 60-80 MB
worker_class = "gthread"
threads = 4
timeout = 30
graceful_timeout = 20
accesslog = "-"
errorlog = "-"
