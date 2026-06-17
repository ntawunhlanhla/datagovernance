FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -qO- http://localhost/healthz/ || exit 1
