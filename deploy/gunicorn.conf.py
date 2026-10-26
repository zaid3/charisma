bind = '0.0.0.0:8787'
workers = 2
worker_class = 'gthread'
threads = 4
timeout = 30
graceful_timeout = 20
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
limit_request_line = 4094
limit_request_fields = 40
limit_request_field_size = 4094
accesslog = None
errorlog = '-'
loglevel = 'warning'
capture_output = False
forwarded_allow_ips = ''

# Container supervision manages the process; no writable home/control socket.
control_socket_disable = True
worker_tmp_dir = '/tmp'
