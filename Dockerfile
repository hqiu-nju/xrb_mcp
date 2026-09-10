FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY . /app
ARG INSTALL_EMBEDDINGS=false
RUN if [ "$INSTALL_EMBEDDINGS" = "true" ]; then pip install '.[embeddings]'; else pip install .; fi
RUN useradd --create-home --uid 10001 xrb && mkdir -p /app/data && chown -R xrb:xrb /app/data
USER xrb
CMD ["xrb-mcp"]
