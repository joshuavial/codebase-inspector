ALTER TABLE public.invoices
    ADD CONSTRAINT invoices_account_fk
    FOREIGN KEY (account_id) REFERENCES accounts(id);
