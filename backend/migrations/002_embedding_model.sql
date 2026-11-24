-- Record which embedding model produced each vector, so switching models re-embeds the corpus.
ALTER TABLE policy_chunks ADD COLUMN embedding_model text NOT NULL DEFAULT '';
