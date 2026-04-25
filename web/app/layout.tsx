import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Dev Loop Analyzer",
  description: "PR 히스토리에서 회귀 패턴을 감지하고 AI 코딩 어시스턴트 규칙을 자동 제안합니다",
  openGraph: {
    title: "AI Dev Loop Analyzer",
    description: "PR 히스토리에서 회귀 패턴을 감지하고 AI 코딩 어시스턴트 규칙을 자동 제안합니다",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
