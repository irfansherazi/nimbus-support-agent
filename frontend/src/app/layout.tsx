import type { Metadata, Viewport } from "next";
import { Schibsted_Grotesk } from "next/font/google";
import "./globals.css";

const schibsted = Schibsted_Grotesk({ variable: "--font-schibsted", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nimbus Support",
  description: "Customer support agent for Nimbus — chat or talk, with a live view of every step it takes.",
};

export const viewport: Viewport = { themeColor: "#edeff4" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${schibsted.variable} antialiased`}>{children}</body>
    </html>
  );
}
