import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import "./globals.css";
import { Background } from "./background";

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
    <html lang="pt-BR" suppressHydrationWarning>
      <body className="min-h-screen bg-slate-50 text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <Background />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
