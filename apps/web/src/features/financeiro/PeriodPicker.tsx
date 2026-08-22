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
  /**
   * ⚠️ O rótulo do select nasce FIXO em "Este ano" — ele não olha o `value` recebido. Hoje isso
   * não mente porque os QUATRO call sites montam com `resolvePeriod("this_year")` (verificado
   * em 21/08/2026: DrePage:32, LucratividadePage:17, ConferenciaPage:53, ContasSaldosPage:531),
   * e nenhum deles mexe no período por fora deste componente. Um call site novo que monte com
   * outro período faria o rótulo mentir já no primeiro quadro — se isso acontecer, o conserto é
   * receber o atalho como prop, não adivinhar o atalho a partir do intervalo.
   */
  const [shortcut, setShortcut] = useState<PeriodShortcut>("this_year");

  /**
   * Os dois campos de "Personalizado" são DERIVADOS do prop — não há cópia local deles (#180).
   *
   * ⚠️ Eram `useState(value.start)`/`useState(value.end)`. `useState` lê o argumento só na
   * MONTAGEM, e este componente NÃO desmonta: ele fica na barra da DRE/Lucratividade/Conferência/
   * Contas & Saldos a tela inteira. Trocar para "Este mês" e depois abrir "Personalizado" aplicava
   * de volta o intervalo da MONTAGEM ("Este ano") — e como o pai refaz a consulta ao backend a
   * cada `period` novo, a tela voltava para o ano quando o dono tinha pedido o mês.
   *
   * Aqui não existe rascunho a preservar (o padrão `rascunho ?? prop` do #155): cada tecla já
   * chama `onChange`, então o prop É o que o dono acabou de digitar. Ler direto dele deixa o
   * componente sem estado nenhum que possa envelhecer.
   *
   * A alternativa era pôr o intervalo na `key` do picker, remontando-o a cada mudança. Custa
   * caro justamente porque cada tecla muda o intervalo: o `shortcut` voltaria a "Este ano", os
   * campos de data sumiriam da tela e o foco iria junto — o campo fecharia debaixo do dedo. O
   * precedente de conserto por `key` deste repo (`NewBillModal`, `pagar/PagarPage.tsx`) é
   * legítimo lá porque aquilo é um MODAL, que nasce e morre por abertura; este não é.
   */
  const customStart = value.start;
  const customEnd = value.end;

  function selectShortcut(next: PeriodShortcut) {
    setShortcut(next);
    // "Personalizado" não aplica intervalo nenhum: só abre os campos já preenchidos com o
    // período EM VIGOR, para o dono ajustá-lo. Chamar `onChange` aqui com os mesmos valores
    // dispararia uma consulta redundante ao backend — o pai depende da IDENTIDADE do objeto.
    if (next === "custom") return;
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
            onChange={(e) => onChange({ start: e.target.value, end: customEnd })}
            aria-label="Início do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <span className="text-sm text-neutral-400">até</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => onChange({ start: customStart, end: e.target.value })}
            aria-label="Fim do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </>
      )}
    </div>
  );
}
