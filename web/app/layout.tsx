import type { Metadata } from "next";
import "./globals.css";

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
      </body>
    </html>
  );
}
