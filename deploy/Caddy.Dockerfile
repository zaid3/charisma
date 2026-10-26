FROM caddy:2.11.7-alpine
# The upstream binary has a low-port file capability. Our ports are unprivileged,
# so copy to a fresh inode without that xattr before dropping all capabilities.
RUN cp /usr/bin/caddy /tmp/caddy-unprivileged \
    && chmod 0755 /tmp/caddy-unprivileged \
    && mv /tmp/caddy-unprivileged /usr/bin/caddy
USER 10001:10001
