FROM postgres:16-alpine

ARG PGVECTOR_VERSION=v0.8.0

RUN apk add --no-cache --virtual .build-deps \
        build-base \
        clang19 \
        llvm19 \
        git \
        postgresql16-dev \
    && cd /tmp \
    && git clone --branch ${PGVECTOR_VERSION} --depth 1 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make OPTFLAGS="" \
    && make install \
    && cd / \
    && rm -rf /tmp/pgvector \
    && apk del .build-deps
