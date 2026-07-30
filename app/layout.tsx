import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Concilia — Conciliador Bancário",
  description:
    "Interface local para conciliar os lançamentos do ERP com o extrato bancário.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
