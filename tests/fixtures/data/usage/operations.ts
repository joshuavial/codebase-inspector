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
