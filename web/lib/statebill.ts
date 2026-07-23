import type { StateBill } from "@/lib/db";

// "TX HB 1234" style label. Shared by StateBillRow and the detail page so the
// label reads identically in both, exactly like billLabel.
export function stateBillLabel(sb: Pick<StateBill, "state" | "bill_number">): string {
  return `${sb.state} ${sb.bill_number}`;
}

// LegiScan progress codes -> display. The collector stores the raw numeric code
// (schema: status is "display-mapped in 5b-c"); this is that mapping.
export const STATUS_LABELS: Record<string, string> = {
  "1": "Introduced",
  "2": "Engrossed",
  "3": "Enrolled",
  "4": "Passed",
  "5": "Vetoed",
  "6": "Failed",
};

export function stateBillStatus(code: string | null): string | null {
  if (!code) return null;
  return STATUS_LABELS[code] ?? code; // unmapped -> show the raw code, don't hide it
}
