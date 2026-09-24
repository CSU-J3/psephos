import type { Metadata } from "next";
import "./globals.css";
import { LegiScanAttribution } from "@/components/LegiScanAttribution";

export const metadata: Metadata = {
  title: "psephos",
  description:
    "A monitor for the erosion of voting rights across four channels of federal pressure.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        {children}
        {/* Site-wide, so every "LegiScan ·" citation on the home page (WhereThisStands)
            is covered without editing each Fact. Full width with centred small print,
            because the pages under it do not share a container: /state-bills is
            max-w-4xl, /campaign 5xl, home a 2200px board. */}
        <footer className="border-t border-neutral-900 px-6 py-6">
          <LegiScanAttribution className="mx-auto max-w-4xl text-center" />
        </footer>
      </body>
    </html>
  );
}
