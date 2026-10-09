CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT);
CREATE TABLE invoices (
  id INTEGER PRIMARY KEY,
  account_id INTEGER REFERENCES accounts(id),
  note TEXT
);
