using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

public class AppContext : DbContext
{
    public DbSet<Account> Accounts { get; set; }
    public DbSet<Invoice> Invoices { get; set; }
}

[Table("accounts")]
public class Account
{
    public int Id { get; set; }
    public string Email { get; set; }
}

public class Invoice
{
    public int Id { get; set; }
    public int AccountId { get; set; }
    public Account Account { get; set; }
    public string? Note { get; set; }
}
