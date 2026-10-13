import "./globals.css";

export const metadata = {
  title: "APEX-IN | Nifty & Sensex F&O Paper Trading Command",
  description: "Next-generation institutional paper trading bot for Indian derivatives with complete statutory charge tracking.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  );
}
