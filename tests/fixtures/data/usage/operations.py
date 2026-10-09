class Account:
    pass

class Invoice:
    pass

def report(session):
    rows = session.query(Invoice).all()
    account = Account.objects.get(id=1)
    sql = """SELECT invoices.id
             FROM invoices
             JOIN accounts ON accounts.id = invoices.account_id"""
    return rows, account, sql

def change(session):
    Account.objects.create(email="a@example.test")
    session.add(Invoice())
    sql = "UPDATE invoices SET note = 'paid' WHERE id = 1"
    return sql

# session.query(NotATable).all()
# DELETE FROM accounts
def unrelated():
    helper.find("accounts")
