import { useState } from "react";
import { PERIOD_SHORTCUT_LABEL, resolvePeriod, type PeriodRange, type PeriodShortcut } from "./periodRange";

const SHORTCUTS: PeriodShortcut[] = [
  "this_month",
  "last_month",
  "this_quarter",
  "this_year",
  "last_12_months",
  "all",
  "custom",
];

/** Dropdown de período (Este mês/Mês anterior/Este trimestre/Este ano/Últimos 12 meses/Tudo/
 * Personalizado) compartilhado pela DRE em matriz e pela Lucratividade por Contrato. */
export default function PeriodPicker({
  value,
  onChange,
}: {
  value: PeriodRange;
  onChange: (range: PeriodRange) => void;
}) {
  const [shortcut, setShortcut] = useState<PeriodShortcut>("this_year");
  const [customStart, setCustomStart] = useState(value.start);
  const [customEnd, setCustomEnd] = useState(value.end);

  function selectShortcut(next: PeriodShortcut) {
    setShortcut(next);
    if (next === "custom") {
      onChange({ start: customStart, end: customEnd });
      return;
    }
    onChange(resolvePeriod(next));
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={shortcut}
        onChange={(e) => selectShortcut(e.target.value as PeriodShortcut)}
        aria-label="Período"
        className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        {SHORTCUTS.map((s) => (
          <option key={s} value={s}>
            {PERIOD_SHORTCUT_LABEL[s]}
          </option>
        ))}
      </select>
      {shortcut === "custom" && (
        <>
          <input
            type="date"
            value={customStart}
            onChange={(e) => {
              setCustomStart(e.target.value);
              onChange({ start: e.target.value, end: customEnd });
            }}
            aria-label="Início do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <span className="text-sm text-neutral-400">até</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => {
              setCustomEnd(e.target.value);
              onChange({ start: customStart, end: e.target.value });
            }}
            aria-label="Fim do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </>
      )}
    </div>
  );
}
