from django.db import models

class Account(models.Model):
    email = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "customer_accounts"

class Invoice(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    total = models.DecimalField(max_digits=10, decimal_places=2, null=True)
