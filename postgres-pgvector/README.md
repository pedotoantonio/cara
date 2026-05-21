# cara-postgres-pgvector

Custom postgres image: `postgres:16-alpine` + pgvector v0.8.0.

Same Alpine base, same UID 70, so the existing `/opt/cara/data/postgres` volume works without permission changes.

## Build & deploy

```sh
cd /opt/cara/postgres-pgvector
docker build -t cara-postgres-pgvector:16-0.8.0 .
```

Then in `/opt/cara/docker-compose.yml`, replace:
```yaml
  postgres:
    image: postgres:16-alpine
```
with:
```yaml
  postgres:
    image: cara-postgres-pgvector:16-0.8.0
```

Restart:
```sh
docker compose -f /opt/cara/docker-compose.yml --profile app up -d postgres
```

## Enable extension

```sh
docker exec -it cara-postgres psql -U cara cara -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## Migration plan (separate work)

`facts.embedding` is currently `JSONB`. Migrate via:
```sql
ALTER TABLE facts ADD COLUMN embedding_v vector(384);
UPDATE facts SET embedding_v = embedding::text::vector;
ALTER TABLE facts DROP COLUMN embedding;
ALTER TABLE facts RENAME COLUMN embedding_v TO embedding;
CREATE INDEX ON facts USING hnsw (embedding vector_cosine_ops);
```

Backend code at `cara/models/fact.py` must be updated to use `pgvector.sqlalchemy.Vector(384)` instead of `JSONB`. Same change for any other table storing embeddings.

Note: with only 2 rows in `facts` today, the migration is trivial. The real work is wiring an *ingestion pipeline* (notes / messages / conversations → embedded → indexed).
