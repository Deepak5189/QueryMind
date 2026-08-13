import "./globals.css";

export const metadata = {
  title: "QueryMind — Ask your ledger",
  description: "Natural-language analytics over the QueryMind payments dataset.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
