FROM postgres:16

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-server-dev-all \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Build pgvector from official tarball
RUN cd /tmp && \
    curl -L https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.2.tar.gz -o pgvector.tar.gz && \
    tar -xzf pgvector.tar.gz && \
    cd pgvector-0.8.2 && \
    make && make install && \
    rm -rf /tmp/pgvector*

