import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Both faces live in ./fonts (latin subset, variable weight, OFL): the build
// must not depend on reaching Google Fonts from the Pi.

// Display face: contemporary grotesque with real character in the numerals,
// which is what the money figures are set in.
const heading = localFont({
  src: "./fonts/bricolage-grotesque-latin-wght-normal.woff2",
  variable: "--font-heading",
  weight: "200 800",
  display: "swap",
});

// Everything else, including all data. Wide apertures and a true tabular set,
// so a column of figures stays aligned between refreshes.
const body = localFont({
  src: "./fonts/plus-jakarta-sans-latin-wght-normal.woff2",
  variable: "--font-body",
  weight: "200 800",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Assay",
  description: "Finanças pessoais e carteira de investimentos",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Assay",
    // Renders the status bar over the page so the header can own the top inset.
    statusBarStyle: "default",
  },
};

export const viewport: Viewport = {
  // viewport-fit=cover is what makes env(safe-area-inset-*) resolve on iPhone.
  viewportFit: "cover",
  width: "device-width",
  initialScale: 1,
  // Matches --bg-primary, so the iOS status bar blends into the page.
  themeColor: "#f6f7f9",
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
