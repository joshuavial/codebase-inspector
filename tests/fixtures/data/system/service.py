def list_accounts(db):
    return db.execute("SELECT id, email FROM accounts")
