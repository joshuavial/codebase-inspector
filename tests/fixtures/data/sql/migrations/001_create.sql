-- core tables
CREATE TABLE "accounts" (
    id BIGINT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    state TEXT DEFAULT 'active'
);

CREATE TABLE public.invoices (
    id INTEGER NOT NULL,
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    total NUMERIC(10, 2),
    CONSTRAINT invoices_pk PRIMARY KEY (id),
    UNIQUE (account_id, id)
);
