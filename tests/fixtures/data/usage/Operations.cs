public class Operations
{
    public object List(AppContext context)
    {
        return context.Invoices.Where(row => row.Id > 0).ToList();
    }

    public void Add(AppContext context, Account account)
    {
        context.Accounts.Add(account);
    }
}
