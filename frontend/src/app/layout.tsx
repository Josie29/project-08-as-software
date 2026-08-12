import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Patient Imaging Portal",
  description: "Secure access to your ultrasound images, cine clips, reports, and appointments.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
