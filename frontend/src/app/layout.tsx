import type { Metadata, Viewport } from "next";
import { Fraunces, Manrope } from "next/font/google";
import "./globals.css";

const heading = Fraunces({
  variable: "--font-heading",
  subsets: ["latin"],
  axes: ["opsz", "SOFT"],
  display: "swap",
});

const body = Manrope({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Mesa",
  description: "Finanças pessoais e carteira de investimentos, 100% local",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Mesa",
    // Renders the status bar over the page so the header can own the top inset.
    statusBarStyle: "default",
  },
};

export const viewport: Viewport = {
  // viewport-fit=cover is what makes env(safe-area-inset-*) resolve on iPhone.
  viewportFit: "cover",
  width: "device-width",
  initialScale: 1,
  themeColor: "#faf8f4",
};

const RootLayout = ({
  children,
}: Readonly<{ children: React.ReactNode }>) => {
  return (
    <html lang="pt-BR">
      <body className={`${heading.variable} ${body.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
};

export default RootLayout;
