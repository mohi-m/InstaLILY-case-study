import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "PartSelect Assistant",
  description: "Find genuine OEM Refrigerator and Dishwasher parts",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@300..700&family=Roboto:ital,wght@0,100..900;1,100..900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="ps-header">
          <div className="ps-header__bar">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="ps-logo"
              src="/ps-header-logo-here-to-help.svg"
              alt="PartSelect — Here to help"
            />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
