FROM pgvector/pgvector:pg16
COPY database/init-reader.sh /docker-entrypoint-initdb.d/10-reader.sh
RUN chmod 644 /docker-entrypoint-initdb.d/10-reader.sh
