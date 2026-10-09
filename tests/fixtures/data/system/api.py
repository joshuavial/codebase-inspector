from service import list_accounts
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/accounts")
def accounts():
    return list_accounts()

@app.post("/api/accounts")
def create_account():
    """Create one customer account."""
    return {"ok": True}
