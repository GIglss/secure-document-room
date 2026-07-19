import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Secure Document Room",
  description: "Secure document room with sovereign local AI — review, download, and question documents inside an ephemeral sandbox",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">{children}</body>
    </html>
  );
}
