# The instance's settings file, copied from terraform/precogly-user-data.sh.tftpl:
# Caddy terminates TLS there, and this tells Django to trust its header.
from .production import *  # noqa: F403

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
