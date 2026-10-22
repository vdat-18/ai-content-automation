import { createContext, useContext } from "react";

export type Language = "en" | "vi";

export type I18nValue = {
  language: Language;
  locale: string;
  setLanguage: (language: Language) => void;
  t: (source: string, variables?: Record<string, string | number>) => string;
  formatDate: (value: string | number | Date, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatCurrency: (value: number, currency?: string) => string;
};

export const I18nContext = createContext<I18nValue | null>(null);

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider is required.");
  return value;
}
