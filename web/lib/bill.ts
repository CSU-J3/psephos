import type { Bill } from "@/lib/db";

// House/Senate bill-type prefixes for display: "S. 1383", "H.R. 22". Shared by
// BillRow (home) and the bill detail page so the label reads identically.
export const TYPE_LABEL: Record<string, string> = {
  hr: "H.R.",
  s: "S.",
  hjres: "H.J.Res.",
  sjres: "S.J.Res.",
};

export function billLabel(bill: Pick<Bill, "bill_type" | "number">): string {
  const t = TYPE_LABEL[bill.bill_type] ?? bill.bill_type.toUpperCase();
  return `${t} ${bill.number}`;
}
