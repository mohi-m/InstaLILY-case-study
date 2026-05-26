import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "PartSelect Assistant",
  description: "Find Refrigerator and Dishwasher parts",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
