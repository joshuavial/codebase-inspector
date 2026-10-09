class Account {}
class Invoice {}

export function prismaReads(prisma: any) {
  return prisma.invoice.findMany();
}

export function prismaWrites(prisma: any) {
  return prisma.account.create({ data: { email: "x" } });
}

export function typeorm(dataSource: any) {
  const repo = dataSource.getRepository(Invoice);
  repo.find();
  repo.save({ id: 1 });
}

export async function supabaseReads(supabase: any) {
  return supabase.from("accounts").select("id, email").eq("id", 1);
}

export async function supabaseWrites(supabase: any) {
  return supabase
    .from("invoices")
    .update({ note: "paid" })
    .eq("id", 1);
}
