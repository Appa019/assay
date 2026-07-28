import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

// Display face: contemporary grotesque with real character in the numerals,
// which is what the money figures are set in.
const heading = Bricolage_Grotesque({
  variable: "--font-heading",
  subsets: ["latin"],
  display: "swap",
});

// Everything else, including all data. Wide apertures and a true tabular set,
// so a column of figures stays aligned between refreshes.
const body = Plus_Jakarta_Sans({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Mesa",
  description: "Finanças pessoais e carteira de investimentos",
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
  themeColor: "#f8f9fb",
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
