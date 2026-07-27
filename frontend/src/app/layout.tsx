import type { Metadata } from "next";
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
  title: "Mesa de aportes",
  description:
    "Aportes ad-hoc com comitê autônomo de investimentos — 5 reuniões encadeadas + fechamento",
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
